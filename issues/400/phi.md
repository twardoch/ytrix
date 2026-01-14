I'll create a comprehensive specification to improve your YouTube Data API integration with a focus on ethical rate limit management, authentication, and reporting.

## Step-by-Step Thought Process

1. **Analyze Current Challenges**: The main issues are rate limit exhaustion, authentication management, credential rotation, and GCP project cloning
2. **Research Best Practices**: Based on the search results, focus on quota management, credential security, and monitoring
3. **Design Architecture**: Create a multi-layered approach with quota pooling, intelligent request distribution, and comprehensive monitoring
4. **Implementation Strategy**: Build incrementally with existing code preservation

### Key Points to Consider

- YouTube Data API has a default quota of 10,000 units per day [0]
- GCP-managed service account keys rotate automatically weekly [3]
- API keys should be rotated every 90 days or less [3][5]
- Implement proper authentication and authorization mechanisms
- Use monitoring and alerting for quota usage

## Detailed Actionable Specification

### 1. Quota Management System

```typescript
// src/quota/QuotaManager.ts
interface QuotaConfig {
  projectId: string;
  dailyLimit: number;
  currentUsage: number;
  lastReset: Date;
  priority: number; // 1-10, higher = more important
}

interface QuotaCost {
  search: number;        // 100 units
  list: number;         // 1 unit
  insert: number;       // 50 units
  update: number;       // 50 units
  delete: number;       // 50 units
}

class QuotaManager {
  private static readonly QUOTA_COSTS: QuotaCost = {
    search: 100,
    list: 1,
    insert: 50,
    update: 50,
    delete: 50
  };

  private static readonly DEFAULT_DAILY_QUOTA = 10000;
  private static readonly SAFETY_BUFFER = 0.1; // Keep 10% buffer
  
  private projects: Map<string, QuotaConfig> = new Map();
  private requestQueue: PriorityQueue<APIRequest> = new PriorityQueue();
  
  constructor(private storage: QuotaStorage) {
    this.loadProjects();
    this.startQuotaResetScheduler();
  }

  async canMakeRequest(projectId: string, operation: keyof QuotaCost): Promise<boolean> {
    const project = this.projects.get(projectId);
    if (!project) return false;
    
    const cost = QuotaManager.QUOTA_COSTS[operation];
    const availableQuota = project.dailyLimit - project.currentUsage;
    const safetyThreshold = project.dailyLimit * QuotaManager.SAFETY_BUFFER;
    
    return availableQuota - cost > safetyThreshold;
  }

  async executeRequest<T>(
    request: APIRequest,
    operation: keyof QuotaCost
  ): Promise<T> {
    const optimalProject = await this.selectOptimalProject(operation);
    
    if (!optimalProject) {
      // Queue the request for later execution
      this.requestQueue.enqueue(request, request.priority);
      throw new QuotaExhaustedError('All projects exhausted. Request queued.');
    }

    try {
      const result = await this.performRequest(request, optimalProject);
      await this.updateQuotaUsage(optimalProject, operation);
      return result;
    } catch (error) {
      if (this.isQuotaError(error)) {
        await this.handleQuotaError(optimalProject, request);
      }
      throw error;
    }
  }

  private async selectOptimalProject(operation: keyof QuotaCost): Promise<string | null> {
    const cost = QuotaManager.QUOTA_COSTS[operation];
    const availableProjects = Array.from(this.projects.entries())
      .filter(([_, config]) => {
        const available = config.dailyLimit - config.currentUsage;
        return available >= cost * 1.2; // 20% buffer
      })
      .sort((a, b) => {
        // Sort by available quota percentage
        const aPercent = (a[1].dailyLimit - a[1].currentUsage) / a[1].dailyLimit;
        const bPercent = (b[1].dailyLimit - b[1].currentUsage) / b[1].dailyLimit;
        return bPercent - aPercent;
      });

    return availableProjects.length > 0 ? availableProjects[0][0] : null;
  }

  private startQuotaResetScheduler(): void {
    // Reset quotas daily at midnight PST (YouTube API reset time)
    cron.schedule('0 0 * * *', async () => {
      for (const [projectId, config] of this.projects) {
        config.currentUsage = 0;
        config.lastReset = new Date();
        await this.storage.updateProject(projectId, config);
      }
      
      // Process queued requests
      await this.processQueuedRequests();
    }, {
      timezone: 'America/Los_Angeles'
    });
  }
}
```

### 2. Authentication & Credential Management

```typescript
// src/auth/CredentialManager.ts
interface Credential {
  id: string;
  type: 'oauth2' | 'api_key' | 'service_account';
  projectId: string;
  createdAt: Date;
  lastRotated: Date;
  expiresAt?: Date;
  metadata: Record<string, any>;
}

class CredentialManager {
  private static readonly ROTATION_INTERVALS = {
    api_key: 90 * 24 * 60 * 60 * 1000,      // 90 days
    service_account: 365 * 24 * 60 * 60 * 1000, // 1 year
    oauth2: 30 * 24 * 60 * 60 * 1000        // 30 days for refresh
  };

  private credentials: Map<string, Credential> = new Map();
  private vault: SecretVault;
  
  constructor(private gcpClient: GCPClient) {
    this.vault = new SecretVault();
    this.initializeRotationScheduler();
  }

  async rotateCredential(credentialId: string): Promise<Credential> {
    const credential = this.credentials.get(credentialId);
    if (!credential) throw new Error('Credential not found');

    console.log(`Starting rotation for credential ${credentialId}`);
    
    switch (credential.type) {
      case 'api_key':
        return await this.rotateAPIKey(credential);
      case 'service_account':
        return await this.rotateServiceAccount(credential);
      case 'oauth2':
        return await this.refreshOAuth2Token(credential);
    }
  }

  private async rotateAPIKey(credential: Credential): Promise<Credential> {
    // Create new API key
    const newKey = await this.gcpClient.createAPIKey(credential.projectId, {
      restrictions: {
        apiTargets: [{ service: 'youtube.googleapis.com' }],
        browserKeyRestrictions: {
          allowedReferrers: process.env.ALLOWED_REFERRERS?.split(',') || []
        }
      }
    });

    // Store new key securely
    await this.vault.store(`api_key_${credential.projectId}`, newKey.key);
    
    // Schedule old key deletion after grace period
    setTimeout(async () => {
      await this.gcpClient.deleteAPIKey(credential.metadata.keyId);
    }, 24 * 60 * 60 * 1000); // 24 hour grace period

    // Update credential record
    const updated: Credential = {
      ...credential,
      lastRotated: new Date(),
      metadata: { ...credential.metadata, keyId: newKey.id }
    };
    
    this.credentials.set(credential.id, updated);
    await this.notifyRotation(credential, 'success');
    
    return updated;
  }

  private async rotateServiceAccount(credential: Credential): Promise<Credential> {
    // Use GCP-managed keys when possible
    const serviceAccount = credential.metadata.email;
    
    // List existing keys
    const keys = await this.gcpClient.listServiceAccountKeys(serviceAccount);
    const userManagedKeys = keys.filter(k => k.keyType === 'USER_MANAGED');
    
    if (userManagedKeys.length > 0) {
      console.warn(`Found ${userManagedKeys.length} user-managed keys. Migrating to GCP-managed.`);
      
      // Create new GCP-managed credential
      const newCredential = await this.gcpClient.createServiceAccountCredential(
        serviceAccount,
        { keyType: 'SYSTEM_MANAGED' }
      );
      
      // Delete old user-managed keys after validation
      for (const key of userManagedKeys) {
        await this.gcpClient.deleteServiceAccountKey(key.name);
      }
    }

    const updated: Credential = {
      ...credential,
      lastRotated: new Date()
    };
    
    this.credentials.set(credential.id, updated);
    return updated;
  }

  private initializeRotationScheduler(): void {
    // Check for credentials needing rotation every hour
    cron.schedule('0 * * * *', async () => {
      for (const [id, credential] of this.credentials) {
        const rotationInterval = CredentialManager.ROTATION_INTERVALS[credential.type];
        const timeSinceRotation = Date.now() - credential.lastRotated.getTime();
        
        if (timeSinceRotation >= rotationInterval * 0.9) { // Rotate at 90% of interval
          try {
            await this.rotateCredential(id);
          } catch (error) {
            await this.notifyRotation(credential, 'failed', error);
          }
        }
      }
    });
  }
}
```

### 3. Project Cloning & Management

```typescript
// src/gcp/ProjectCloner.ts
interface ProjectCloneConfig {
  sourceProjectId: string;
  targetProjectPrefix: string;
  numberOfClones: number;
  enabledAPIs: string[];
  billingAccount?: string;
}

class ProjectCloner {
  private static readonly MAX_PROJECTS_PER_ACCOUNT = 30;
  private static readonly YOUTUBE_API = 'youtube.googleapis.com';
  
  constructor(
    private gcpClient: GCPClient,
    private quotaManager: QuotaManager
  ) {}

  async cloneProject(config: ProjectCloneConfig): Promise<string[]> {
    const clonedProjects: string[] = [];
    
    for (let i = 0; i < config.numberOfClones; i++) {
      const projectId = `${config.targetProjectPrefix}-${Date.now()}-${i}`;
      
      try {
        // Create new project
        const project = await this.gcpClient.createProject({
          projectId,
          name: `${config.targetProjectPrefix} Clone ${i + 1}`,
          parent: { type: 'organization', id: process.env.GCP_ORG_ID }
        });

        // Link billing account if provided
        if (config.billingAccount) {
          await this.gcpClient.linkBillingAccount(projectId, config.billingAccount);
        }

        // Enable required APIs
        for (const api of config.enabledAPIs) {
          await this.gcpClient.enableAPI(projectId, api);
          await this.delay(1000); // Avoid rate limits
        }

        // Configure YouTube API specific settings
        if (config.enabledAPIs.includes(ProjectCloner.YOUTUBE_API)) {
          await this.configureYouTubeAPI(projectId);
        }

        // Register with quota manager
        await this.quotaManager.registerProject(projectId, {
          dailyLimit: 10000,
          priority: 5
        });

        clonedProjects.push(projectId);
        
        await this.reportProgress(i + 1, config.numberOfClones, projectId);
        
      } catch (error) {
        console.error(`Failed to clone project ${i + 1}:`, error);
        await this.reportError(projectId, error);
      }
    }

    return clonedProjects;
  }

  private async configureYouTubeAPI(projectId: string): Promise<void> {
    // Create OAuth 2.0 credentials
    const oauth2 = await this.gcpClient.createOAuth2Credentials(projectId, {
      redirectUris: [process.env.OAUTH_REDIRECT_URI],
      javascriptOrigins: [process.env.APP_ORIGIN]
    });

    // Create restricted API key as backup
    const apiKey = await this.gcpClient.createAPIKey(projectId, {
      restrictions: {
        apiTargets: [{ service: 'youtube.googleapis.com' }],
        ipRestrictions: {
          allowedIps: process.env.ALLOWED_IPS?.split(',') || []
        }
      }
    });

    // Store credentials securely
    await this.storeCredentials(projectId, { oauth2, apiKey });
  }

  private delay(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}
```

### 4. Monitoring & Reporting System

```typescript
// src/monitoring/ReportingDashboard.ts
interface QuotaMetrics {
  projectId: string;
  quotaUsed: number;
  quotaLimit: number;
  percentageUsed: number;
  estimatedHoursRemaining: number;
  topOperations: OperationMetric[];
}

interface OperationMetric {
  operation: string;
  count: number;
  totalCost: number;
  averageLatency: number;
}

class ReportingDashboard {
  private metrics: Map<string, QuotaMetrics> = new Map();
  private alerts: Alert[] = [];
  
  constructor(
    private quotaManager: QuotaManager,
    private notificationService: NotificationService
  ) {
    this.initializeMetricsCollection();
    this.setupAlertRules();
  }

  async generateReport(): Promise<DashboardReport> {
    const projects = await this.quotaManager.getAllProjects();
    const report: DashboardReport = {
      timestamp: new Date(),
      summary: {
        totalProjects: projects.length,
        activeProjects: 0,
        totalQuotaUsed: 0,
        totalQuotaAvailable: 0,
        healthScore: 100
      },
      projects: [],
      alerts: this.alerts,
      recommendations: []
    };

    for (const project of projects) {
      const metrics = await this.collectProjectMetrics(project);
      report.projects.push(metrics);
      
      if (metrics.quotaUsed > 0) {
        report.summary.activeProjects++;
      }
      
      report.summary.totalQuotaUsed += metrics.quotaUsed;
      report.summary.totalQuotaAvailable += metrics.quotaLimit;
      
      // Calculate health score
      if (metrics.percentageUsed > 90) {
        report.summary.healthScore -= 20;
      } else if (metrics.percentageUsed > 75) {
        report.summary.healthScore -= 10;
      }
    }

    // Generate recommendations
    report.recommendations = this.generateRecommendations(report);
    
    return report;
  }

  private async collectProjectMetrics(project: ProjectConfig): Promise<QuotaMetrics> {
    const usage = await this.quotaManager.getQuotaUsage(project.id);
    const history = await this.quotaManager.getUsageHistory(project.id, 7); // Last 7 days
    
    const averageDaily = history.reduce((sum, day) => sum + day.usage, 0) / history.length;
    const currentRate = usage.current / (Date.now() - usage.resetTime) * (24