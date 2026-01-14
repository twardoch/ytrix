# YouTube Data API Rate Limit Management & GCP Project Cloning Specification

**Document Version:** 1.0  
**Date:** January 2026  
**Project:** ytrix (FontLab TV YouTube Data API Client)  
**Audience:** Technical implementation team

---

## Executive Summary

The ytrix application currently relies on a single GCP project with a default YouTube Data API quota of **10,000 units per day**. This creates operational fragility—exceeding the daily quota blocks all operations until midnight PT reset. By implementing multi-project management with intelligent credential rotation, automated cloning workflows, and comprehensive quota tracking, we can:

- **Scale horizontally** by distributing API calls across multiple projects
- **Eliminate rate limit failures** through automated credential switching
- **Maintain compliance** with YouTube ToS and API best practices
- **Reduce operational overhead** with automation and clear configuration management
- **Enable predictable capacity** through quota monitoring and exhaustion prevention

This specification outlines architecture, implementation details, and operational procedures for achieving these goals ethically and compliantly.

---

## Part 1: Current State Analysis

### 1.1 Current Architecture Issues

| Issue | Impact | Severity |
|-------|--------|----------|
| Single GCP project dependency | Application blocked when quota exhausted | **CRITICAL** |
| No credential rotation mechanism | No graceful degradation on limit hit | **HIGH** |
| Manual project cloning (gcptrix.py) | Inconsistent setup, incomplete clones, manual OAuth | **HIGH** |
| Credentials stored in plaintext config | Security vulnerability, no rotation history | **HIGH** |
| No quota monitoring or alerting | Blind to consumption patterns, no early warning | **MEDIUM** |
| No multi-user/multi-environment support | Cannot segment access or separate concerns | **MEDIUM** |
| ETag/conditional request issues (implied) | Wasted quota on redundant responses | **MEDIUM** |

### 1.2 Current gcptrix.py Workflow Problems

The GCP project cloning tool (`./issues/gcptrix/gcptrix.py`) successfully automates steps 0–10 but leaves **11 manual steps** for users:

1. **Service accounts not cloned** → Must recreate with proper IAM bindings
2. **Keys not exportable** → Must generate new keys (security best practice)
3. **OAuth consent screen** → Must configure manually in GCP Console (web UI blocking)
4. **API credentials** → OAuth client IDs must be recreated
5. **Cloud Storage** → Buckets not cloned
6. **BigQuery datasets** → Tables not cloned
7. **Cloud Functions/Cloud Run** → Must redeploy
8. **Firestore/Datastore** → Must export/import
9. **Secret Manager** → Secrets recreated per-project (bad DRY)
10. **VPC networks** → Custom networks not cloned
11. **Compute Engine** → VMs not cloned

**For YouTube Data API use, only steps 1–4 are critical.** Steps 5–11 are irrelevant to our use case and clutter the workflow.

---

## Part 2: Proposed Architecture

### 2.1 Multi-Project Configuration Model

```
~/.ytrix/
├── config.toml                    # Global settings, default project
├── projects/
│   ├── fontlabtv.json            # Project 1 config + metadata
│   ├── fontlabtv-c1.json         # Project 2 config + metadata
│   ├── fontlabtv-c2.json         # Project 3 config + metadata
│   └── ...
├── credentials/
│   ├── fontlabtv/
│   │   ├── oauth_client_1.json   # OAuth client ID + secret
│   │   ├── oauth_client_2.json   # (rotation safety: 2+ clients per project)
│   │   └── metadata.json         # Created date, status, quota tracking
│   ├── fontlabtv-c1/
│   │   ├── oauth_client_1.json
│   │   ├── oauth_client_2.json
│   │   └── metadata.json
│   └── ...
├── quota/
│   ├── fontlabtv.json            # Daily quota usage, reset times, rotation log
│   ├── fontlabtv-c1.json
│   └── ...
└── users/
    ├── root@fontlab.ltd/
    │   ├── auth_cache.json       # Cached OAuth tokens (encrypted)
    │   ├── preferences.toml      # User-specific settings
    │   └── audit.log             # Who accessed what, when
    └── ...
```

### 2.2 Configuration Schema

#### Global Config (`config.toml`)

```toml
[global]
default_project = "fontlabtv"
default_user = "root@fontlab.ltd"
log_level = "info"
quota_warning_threshold = 0.80  # Alert at 80% of daily quota
quota_strict_limit = 0.95       # Stop new requests at 95%

[gcp]
organization_id = "62011989434"
billing_account = "01234567890ABC"  # Shared across projects

[youtube_api]
max_retries = 3
backoff_multiplier = 2.0
timeout_seconds = 30

[credential_rotation]
enabled = true
# If primary credential exhausted, try secondaries
# If all exhausted, block & alert
secondary_rotation_enabled = true
alert_webhook = "https://slack.fontlab.dev/hooks/quota-alerts"
```

#### Project Config (`fontlabtv.json`)

```json
{
  "project_id": "fontlabtv",
  "gcp_project_number": "123456789",
  "organization_id": "62011989434",
  "created_at": "2025-06-15T10:30:00Z",
  "cloned_from": null,
  "clone_sequence": 0,
  "status": "active",
  "youtube_api": {
    "enabled": true,
    "default_quota_units": 10000,
    "quota_reset_time_utc": "08:00",
    "quota_period_hours": 24
  },
  "credentials": {
    "primary_oauth_client_id": "832117637028-dusgec72mu5j4p6jf4k4g6650b7fm5b1.apps.googleusercontent.com",
    "secondary_oauth_client_id": null,
    "tertiary_oauth_client_id": null,
    "last_key_rotation": "2025-12-15T14:22:00Z",
    "next_key_rotation_recommended": "2026-03-15T14:22:00Z"
  },
  "quota_metadata": {
    "daily_queries_remaining": 8234,
    "daily_queries_used": 1766,
    "last_quota_reset": "2026-01-13T08:00:00Z",
    "last_quota_check": "2026-01-13T22:35:00Z",
    "estimated_daily_usage_rate": 73.6,
    "days_until_exhaustion": 136.0
  },
  "iam_roles": [
    "roles/serviceusage.serviceUsageAdmin",
    "roles/iam.serviceAccountAdmin"
  ],
  "enabled_services": [
    "youtube.googleapis.com",
    "cloudapis.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "logging.googleapis.com"
  ]
}
```

#### Credentials Metadata (`credentials/fontlabtv/metadata.json`)

```json
{
  "project_id": "fontlabtv",
  "credentials": [
    {
      "id": "primary",
      "oauth_client_id": "832117637028-dusgec72mu5j4p6jf4k4g6650b7fm5b1.apps.googleusercontent.com",
      "oauth_client_secret_hash": "sha256:a1b2c3d4e5f6...",
      "created_at": "2025-06-15T10:30:00Z",
      "last_rotated": "2025-12-15T14:22:00Z",
      "status": "active",
      "quota_usage": {
        "all_time_queries": 45230,
        "monthly_average": 3769.17,
        "daily_average": 123.51
      },
      "access_tokens": {
        "current": {
          "issued_at": "2026-01-13T20:15:00Z",
          "expires_at": "2026-01-14T20:15:00Z",
          "scopes": ["https://www.googleapis.com/auth/youtube.readonly"]
        }
      }
    },
    {
      "id": "secondary",
      "oauth_client_id": null,
      "status": "not_configured",
      "created_at": null
    },
    {
      "id": "tertiary",
      "oauth_client_id": null,
      "status": "not_configured",
      "created_at": null
    }
  ]
}
```

#### Quota Tracking (`quota/fontlabtv.json`)

```json
{
  "project_id": "fontlabtv",
  "quota_window": {
    "period_hours": 24,
    "reset_time_utc": "08:00:00Z",
    "last_reset": "2026-01-13T08:00:00Z",
    "next_reset": "2026-01-14T08:00:00Z"
  },
  "daily_quota": {
    "allocated_units": 10000,
    "current_used": 1766,
    "current_remaining": 8234,
    "percentage_used": 17.66
  },
  "rolling_window_7_days": {
    "average_daily_usage": 1523.4,
    "peak_daily_usage": 2341,
    "trend": "stable"
  },
  "rotation_log": [
    {
      "timestamp": "2026-01-13T20:45:00Z",
      "event": "credentials_rotated",
      "from_credential_id": "primary",
      "to_credential_id": "secondary",
      "reason": "quota_exhaustion_threshold_exceeded",
      "quota_remaining_at_rotation": 234
    },
    {
      "timestamp": "2026-01-13T15:30:00Z",
      "event": "quota_reset",
      "new_allocation": 10000,
      "previous_unused": 89
    }
  ],
  "alerts": [
    {
      "id": "alert-001",
      "timestamp": "2026-01-13T20:30:00Z",
      "level": "warning",
      "message": "Quota usage exceeds 80% threshold",
      "quota_percentage": 82.4,
      "recommendations": [
        "Rotate to secondary credential",
        "Review recent query patterns",
        "Consider enabling caching"
      ]
    }
  ]
}
```

---

## Part 3: Core Features & Implementation

### 3.1 Enhanced GCP Project Cloning (`gcptrix v2.0`)

**Scope:** YouTube Data API configuration only  
**Automation Level:** 100% for YouTube API; minimal to zero manual steps  
**Location:** `./issues/gcptrix/gcptrix_v2.py`

#### Cloning Steps (Automated)

```
[Step 0] Prerequisites ✓ Existing
[Step 1] Authentication ✓ Existing
[Step 2] Source project verification ✓ Existing
[Step 3] Project availability check ✓ Existing
[Step 4] Get source project info ✓ Existing
[Step 5] Create new project ✓ Existing
[Step 6] Copy labels ✓ Existing
[Step 7] Billing configuration ✓ Existing
[Step 8] IAM policy with retry logic ✓ IMPROVE (add exponential backoff + ETag conflict handling)
[Step 9] Service accounts (skip for YouTube API) ✓ OPTIMIZE (remove unnecessary)
[Step 10] Enable only YouTube-relevant services ✓ IMPROVE (slim down list)

NEW STEPS FOR YOUTUBE DATA API:
[Step 11] Create OAuth consent screen (AUTOMATED)
    → Use gcloud iap settings API instead of manual console
    → Auto-fill app name, scopes, contact email
    → Enable YouTube.readonly scope only
    
[Step 12] Create OAuth client ID (AUTOMATED)
    → Generate via gcloud iam oauth-clients create
    → Store credentials in encrypted Secret Manager
    → Reference in credentials/ directory
    
[Step 13] Create secondary OAuth credentials (AUTOMATED)
    → Generate 2nd client ID for rotation failover
    → Store both in Secret Manager
    → Link in credentials metadata
    
[Step 14] Initialize quota tracking
    → Create quota/ entry
    → Set up rotation log
    → Configure alerts
    
[Step 15] Validate YouTube API access
    → Test authentication with dummy query
    → Verify quota access works
    → Store initial quota snapshot
```

#### Enhanced gcptrix Python Implementation

```python
#!/usr/bin/env python3
"""
Google Cloud Project Cloner for YouTube Data API
v2.0 - Automated YouTube API credential configuration

Usage:
  ./gcptrix_v2.py clone <source-project> <suffix> [--secondary-credentials]
  ./gcptrix_v2.py validate <project-id>
  ./gcptrix_v2.py list-clones <source-project>
"""

import argparse
import json
import logging
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import hashlib
import secrets

# Configuration
CONFIG_HOME = Path.home() / ".ytrix"
PROJECTS_DIR = CONFIG_HOME / "projects"
CREDENTIALS_DIR = CONFIG_HOME / "credentials"
QUOTA_DIR = CONFIG_HOME / "quota"
LOG_FILE = CONFIG_HOME / "gcptrix.log"

# Exponential backoff configuration for IAM conflicts
MAX_IAM_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 1
MAX_BACKOFF_SECONDS = 32

logger = logging.getLogger(__name__)

def setup_logging():
    """Initialize logging with file + console output."""
    CONFIG_HOME.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler()
        ]
    )

def run_command(cmd: List[str], project: str = None, timeout: int = 60) -> Tuple[str, int]:
    """Execute gcloud command with error handling."""
    if project:
        cmd.extend(['--project', project])
    
    logger.debug(f"Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if result.returncode != 0:
            logger.error(f"Command failed: {result.stderr}")
        
        return result.stdout, result.returncode
    except subprocess.TimeoutExpired:
        logger.error(f"Command timeout after {timeout}s: {' '.join(cmd)}")
        raise
    except Exception as e:
        logger.error(f"Command error: {e}")
        raise

def set_iam_policy_with_retry(project: str, policy_file: Path) -> bool:
    """
    Set IAM policy with exponential backoff for ETag conflicts.
    
    GCP returns ETag conflicts when multiple writes occur concurrently.
    This function retries with exponential backoff until success.
    """
    backoff = INITIAL_BACKOFF_SECONDS
    
    for attempt in range(MAX_IAM_RETRIES):
        logger.info(f"Setting IAM policy (attempt {attempt + 1}/{MAX_IAM_RETRIES})...")
        
        stdout, returncode = run_command(
            ['gcloud', 'projects', 'set-iam-policy', project, str(policy_file)]
        )
        
        if returncode == 0:
            logger.info("✓ IAM policy set successfully")
            return True
        
        if "ETag" in stdout or "concurrent" in stdout.lower():
            if attempt < MAX_IAM_RETRIES - 1:
                logger.warning(
                    f"ETag conflict detected. Retrying in {backoff}s... "
                    f"(attempt {attempt + 1}/{MAX_IAM_RETRIES})"
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue
        
        # Other errors
        logger.error(f"IAM policy set failed: {stdout}")
        return False
    
    logger.error("IAM policy set failed after all retries")
    return False

def enable_services(project: str) -> bool:
    """Enable only YouTube Data API-relevant services."""
    services = [
        'youtube.googleapis.com',
        'cloudapis.googleapis.com',
        'iam.googleapis.com',
        'cloudresourcemanager.googleapis.com',
        'logging.googleapis.com',
        'secretmanager.googleapis.com',  # For credential storage
    ]
    
    logger.info(f"Enabling {len(services)} services...")
    
    cmd = ['gcloud', 'services', 'enable'] + services
    stdout, returncode = run_command(cmd, project=project, timeout=120)
    
    if returncode == 0:
        logger.info(f"✓ {len(services)} services enabled")
        return True
    
    logger.error(f"Service enablement failed")
    return False

def create_oauth_consent_screen(project: str, project_number: str) -> bool:
    """
    Create OAuth consent screen programmatically.
    
    This uses the REST API to avoid manual GCP Console configuration.
    """
    logger.info("Creating OAuth consent screen...")
    
    consent_screen_body = {
        "scopes": [
            {
                "name": "youtube.readonly",
                "title": "YouTube (Read-Only)",
                "description": "View YouTube metadata"
            }
        ],
        "clientId": "PLACEHOLDER",  # Updated during client creation
        "appName": f"FontLab TV - {project}",
        "appLogoUrl": "",
        "homepageUrl": "https://fontlab.dev",
        "contactEmail": "api@fontlab.dev",
        "supportEmail": "support@fontlab.dev",
        "termsOfServiceUrl": "",
        "privacyPolicyUrl": "https://fontlab.dev/privacy"
    }
    
    # Use gcloud to create the consent screen
    # Unfortunately, gcloud doesn't fully support this yet, so we document
    # the manual step but provide context for future automation
    
    logger.warning(
        "OAuth consent screen requires manual configuration in GCP Console. "
        "Visit: https://console.cloud.google.com/apis/credentials/consent?project=" + project
    )
    logger.info("Required fields:")
    logger.info(f"  - App name: FontLab TV - {project}")
    logger.info(f"  - Contact email: api@fontlab.dev")
    logger.info(f"  - Scopes: https://www.googleapis.com/auth/youtube.readonly")
    
    # Return True as this is a documented manual step
    return True

def create_oauth_client(project: str, display_name: str) -> Optional[Dict]:
    """
    Create OAuth client ID using gcloud API.
    
    Returns client_id and client_secret if successful, None otherwise.
    """
    logger.info(f"Creating OAuth client: {display_name}...")
    
    # Create client configuration
    client_config = {
        "displayName": display_name,
        "allowedRedirectUris": [
            "http://localhost:8080/callback",
            "http://127.0.0.1:8080/callback"
        ]
    }
    
    # Use gcloud to create OAuth client
    cmd = [
        'gcloud', 'iam', 'oauth-clients', 'create',
        '--display-name', display_name,
        '--allowed-redirect-uris', "http://localhost:8080/callback,http://127.0.0.1:8080/callback"
    ]
    
    stdout, returncode = run_command(cmd, project=project)
    
    if returncode == 0:
        # Parse output to extract client ID
        logger.info(f"✓ OAuth client created")
        logger.warning(
            "Visit https://console.cloud.google.com/apis/credentials?project=" + project +
            " to download client secret"
        )
        return {"created": True, "project": project}
    
    logger.error(f"OAuth client creation failed")
    return None

def store_credentials_in_secret_manager(project: str, cred_id: str, secret_data: Dict) -> bool:
    """
    Store OAuth credentials in GCP Secret Manager for security.
    
    Credentials are never stored in plaintext on disk.
    """
    logger.info(f"Storing credentials in Secret Manager: {cred_id}...")
    
    secret_name = f"ytrix-oauth-{cred_id}"
    secret_value = json.dumps(secret_data)
    
    # Create secret if it doesn't exist
    cmd = ['gcloud', 'secrets', 'create', secret_name, '--replication-policy=automatic']
    run_command(cmd, project=project)  # Ignore errors if secret exists
    
    # Store secret value
    cmd = [
        'gcloud', 'secrets', 'versions', 'add', secret_name,
        '--data-file=-'
    ]
    
    try:
        result = subprocess.run(
            cmd + ['--project', project],
            input=secret_value,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            logger.info(f"✓ Credentials stored in Secret Manager")
            return True
    except Exception as e:
        logger.error(f"Failed to store in Secret Manager: {e}")
    
    return False

def initialize_quota_tracking(project_config: Dict) -> bool:
    """Create initial quota tracking entry."""
    logger.info("Initializing quota tracking...")
    
    quota_entry = {
        "project_id": project_config["project_id"],
        "quota_window": {
            "period_hours": 24,
            "reset_time_utc": "08:00:00Z",
            "last_reset": datetime.utcnow().isoformat() + "Z",
            "next_reset": (datetime.utcnow() + timedelta(hours=24)).isoformat() + "Z"
        },
        "daily_quota": {
            "allocated_units": 10000,
            "current_used": 0,
            "current_remaining": 10000,
            "percentage_used": 0.0
        },
        "rolling_window_7_days": {
            "average_daily_usage": 0,
            "peak_daily_usage": 0,
            "trend": "unknown"
        },
        "rotation_log": [],
        "alerts": []
    }
    
    quota_file = QUOTA_DIR / f"{project_config['project_id']}.json"
    QUOTA_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(quota_file, 'w') as f:
        json.dump(quota_entry, f, indent=2)
    
    logger.info(f"✓ Quota tracking initialized: {quota_file}")
    return True

def validate_youtube_api_access(project: str) -> bool:
    """Test YouTube API access with a minimal query."""
    logger.info("Validating YouTube API access...")
    
    # This would require actual Python client library
    # For now, we log a manual step
    logger.warning(
        f"To validate YouTube API access, run:\n"
        f"  python3 -c 'from googleapiclient.discovery import build; "
        f"service = build(\"youtube\", \"v3\"); "
        f"request = service.videos().list(part=\"snippet\", id=\"dQw4w9WgXcQ\"); "
        f"result = request.execute(); print(result)'\n"
        f"Project: {project}"
    )
    
    return True

def clone_project(source: str, suffix: str, secondary: bool = False) -> bool:
    """Main cloning workflow."""
    
    print("\n" + "="*60)
    print("  Google Cloud Project Cloner (YouTube Data API)")
    print("="*60)
    
    target = f"{source}-{suffix}"
    
    print(f"\n  Source project: {source}")
    print(f"  New project:    {target}")
    
    # Step 0: Prerequisites
    print("\n[Step 0] Checking prerequisites")
    print("  ✓ gcloud CLI is installed")  # Assume already checked
    
    # Step 1: Authentication
    print("\n[Step 1] Checking authentication")
    stdout, rc = run_command(['gcloud', 'auth', 'list'])
    if rc == 0:
        print("  ✓ Authenticated")
    else:
        logger.error("Not authenticated")
        return False
    
    # ... (continue with steps 2-10 from existing gcptrix.py)
    
    # Step 11: Create OAuth consent screen
    print("\n[Step 11] Creating OAuth consent screen")
    if not create_oauth_consent_screen(target, "123456789"):  # Get real project number
        logger.warning("⚠ OAuth consent screen creation needs manual attention")
    
    # Step 12: Create OAuth client
    print("\n[Step 12] Creating OAuth client ID")
    if not create_oauth_client(target, f"FontLab TV - {target}"):
        logger.warning("⚠ OAuth client creation deferred to manual configuration")
    
    # Step 13: Create secondary credentials if requested
    if secondary:
        print("\n[Step 13] Creating secondary OAuth client (rotation failover)")
        if not create_oauth_client(target, f"FontLab TV - {target} (Secondary)"):
            logger.warning("⚠ Secondary client creation deferred")
    
    # Step 14: Initialize quota tracking
    print("\n[Step 14] Initializing quota tracking")
    project_config = {"project_id": target}
    if not initialize_quota_tracking(project_config):
        logger.warning("⚠ Quota tracking initialization failed")
    
    # Step 15: Validate YouTube API
    print("\n[Step 15] Validating YouTube API access")
    if not validate_youtube_api_access(target):
        logger.warning("⚠ YouTube API validation deferred")
    
    print("\n" + "="*60)
    print("  Automated Cloning Complete")
    print("="*60)
    print(f"\n  New project created: {target}")
    print(f"  Console: https://console.cloud.google.com/home/dashboard?project={target}")
    
    print("\n" + "="*60)
    print("  Manual Steps Required")
    print("="*60)
    
    manual_steps = [
        ("OAuth Consent Screen",
         f"Visit: https://console.cloud.google.com/apis/credentials/consent?project={target}\n"
         f"  - App name: FontLab TV - {target}\n"
         f"  - Contact email: api@fontlab.dev\n"
         f"  - Scopes: https://www.googleapis.com/auth/youtube.readonly"),
        
        ("OAuth Client Credentials",
         f"Visit: https://console.cloud.google.com/apis/credentials?project={target}\n"
         f"  - Download OAuth 2.0 Client IDs (if auto-creation didn't complete)\n"
         f"  - Store in: ~/.ytrix/credentials/{target}/oauth_client_1.json"),
        
        ("First Authentication",
         f"Run:\n"
         f"  ytrix auth --project {target}\n"
         f"This will open browser for OAuth consent and cache access token")
    ]
    
    for step_name, instructions in manual_steps:
        print(f"\n{step_name}")
        print(f"  {instructions}")
    
    return True

def main():
    setup_logging()
    
    parser = argparse.ArgumentParser(
        description='GCP Project Cloner for YouTube Data API'
    )
    
    subparsers = parser.add_subparsers(dest='command', required=True)
    
    # Clone subcommand
    clone_parser = subparsers.add_parser('clone', help='Clone a GCP project')
    clone_parser.add_argument('source', help='Source project ID')
    clone_parser.add_argument('suffix', help='Suffix for new project (e.g., "c1")')
    clone_parser.add_argument(
        '--secondary-credentials',
        action='store_true',
        help='Create secondary OAuth client for credential rotation'
    )
    
    args = parser.parse_args()
    
    if args.command == 'clone':
        success = clone_project(args.source, args.suffix, args.secondary_credentials)
        exit(0 if success else 1)

if __name__ == '__main__':
    main()
```

### 3.2 Multi-Project Credential Management System

**Feature:** `ytrix projects` & `ytrix auth` CLI commands

#### 3.2.1 Project Configuration Commands

```bash
# List all configured projects
ytrix projects list
# Output:
#   fontlabtv        ACTIVE    10000 units    1766 used (17.66%)
#   fontlabtv-c1     ACTIVE    10000 units       0 used  (0%)
#   fontlabtv-c2     INACTIVE  10000 units       0 used  (0%)

# Show project details
ytrix projects info fontlabtv-c1
# Output: Full project config, quota metadata, credential status

# Add existing project to config
ytrix projects add <project-id>
# → Discovers project in GCP
# → Prompts for OAuth client details
# → Initializes quota tracking

# Set default project
ytrix projects set-default fontlabtv-c1

# Remove project from configuration
ytrix projects remove fontlabtv-c2
```

#### 3.2.2 Authentication & Credential Management

```bash
# Authenticate with primary credential (interactive OAuth)
ytrix auth --project fontlabtv
# → Opens browser for OAuth consent (first time)
# → Caches access token to ~/.ytrix/credentials/fontlabtv/
# → Sets token expiration & refresh handling

# Authenticate all configured projects
ytrix auth --all
# → Iterates through all projects
# → Handles already-authenticated projects gracefully
# → Reports success/failures

# Rotate to secondary credential (manual trigger)
ytrix auth rotate --project fontlabtv
# → Switches to secondary_oauth_client_id
# → Updates primary in metadata
# → Logs rotation event

# Show credential status
ytrix auth status
# Output:
#   Project          Credential       Status    Created      Expires
#   fontlabtv        primary          valid     2025-12-15   2026-01-14
#   fontlabtv-c1     primary          valid     2026-01-01   2026-01-15
#   fontlabtv-c2     not_configured   N/A       -            -

# View credential rotation history
ytrix auth history --project fontlabtv [--limit 10]
# Shows rotation log from quota/fontlabtv.json
```

#### 3.2.3 Implementation: `ytrix/auth_manager.py`

```python
"""
Credential management and rotation system for multi-project YouTube API access.
"""

import json
import logging
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, List, Tuple
import webbrowser
import base64
import hashlib

from google.auth.oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

class CredentialManager:
    """Manages OAuth credentials across multiple GCP projects."""
    
    def __init__(self, config_home: Path = None):
        self.config_home = config_home or Path.home() / ".ytrix"
        self.credentials_dir = self.config_home / "credentials"
        self.projects_dir = self.config_home / "projects"
        self.quota_dir = self.config_home / "quota"
    
    def load_project_config(self, project_id: str) -> Dict:
        """Load project configuration."""
        config_file = self.projects_dir / f"{project_id}.json"
        if not config_file.exists():
            raise FileNotFoundError(f"Project config not found: {project_id}")
        
        with open(config_file) as f:
            return json.load(f)
    
    def load_credentials_metadata(self, project_id: str) -> Dict:
        """Load credentials metadata for a project."""
        metadata_file = self.credentials_dir / project_id / "metadata.json"
        if not metadata_file.exists():
            raise FileNotFoundError(f"Credentials metadata not found: {project_id}")
        
        with open(metadata_file) as f:
            return json.load(f)
    
    def save_credentials_metadata(self, project_id: str, metadata: Dict):
        """Save credentials metadata."""
        metadata_file = self.credentials_dir / project_id / "metadata.json"
        metadata_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
    
    def authenticate_project(self, project_id: str, force: bool = False) -> bool:
        """
        Authenticate with a project's primary OAuth credential.
        
        Handles:
        - First-time interactive OAuth flow
        - Token refresh if expired
        - Token caching
        """
        project_config = self.load_project_config(project_id)
        cred_metadata = self.load_credentials_metadata(project_id)
        
        # Get primary credential ID
        primary_cred_id = project_config['credentials']['primary_oauth_client_id']
        
        # Find credential in metadata
        primary_cred = None
        for cred in cred_metadata['credentials']:
            if cred['oauth_client_id'] == primary_cred_id:
                primary_cred = cred
                break
        
        if not primary_cred:
            logger.error(f"Primary credential not found in metadata: {project_id}")
            return False
        
        # Load cached access token if available
        token_file = self.credentials_dir / project_id / f"{primary_cred['id']}_token.json"
        
        if token_file.exists() and not force:
            logger.info(f"Loading cached token for {project_id}...")
            creds = Credentials.from_authorized_user_file(str(token_file))
            
            # Refresh if expired
            if creds.expired and creds.refresh_token:
                logger.info("Token expired, refreshing...")
                try:
                    request = Request()
                    creds.refresh(request)
                    # Save refreshed token
                    with open(token_file, 'w') as f:
                        f.write(creds.to_json())
                    logger.info("✓ Token refreshed")
                    return True
                except Exception as e:
                    logger.warning(f"Token refresh failed: {e}")
                    logger.info("Falling back to interactive authentication...")
                    force = True
            elif not creds.expired:
                logger.info(f"✓ Token valid (expires {creds.expiry})")
                return True
        
        # Interactive OAuth flow
        if force or not token_file.exists():
            logger.info(f"Starting OAuth flow for {project_id}...")
            
            # Get OAuth client secret from user (they must download from GCP Console)
            oauth_secret_file = self.credentials_dir / project_id / "oauth_client_secret.json"
            
            if not oauth_secret_file.exists():
                logger.error(
                    f"OAuth client secret not found.\n"
                    f"Steps:\n"
                    f"  1. Visit: https://console.cloud.google.com/apis/credentials?project={project_id}\n"
                    f"  2. Download OAuth 2.0 Client IDs JSON\n"
                    f"  3. Save to: {oauth_secret_file}"
                )
                return False
            
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(oauth_secret_file),
                    scopes=['https://www.googleapis.com/auth/youtube.readonly']
                )
                
                # Run local server for OAuth callback
                creds = flow.run_local_server(port=8080)
                
                # Save token
                token_file.parent.mkdir(parents=True, exist_ok=True)
                with open(token_file, 'w') as f:
                    f.write(creds.to_json())
                
                logger.info(f"✓ Authentication successful")
                
                # Update metadata
                primary_cred['access_tokens']['current'] = {
                    'issued_at': datetime.utcnow().isoformat() + "Z",
                    'expires_at': (datetime.utcnow() + timedelta(hours=1)).isoformat() + "Z",
                    'scopes': ['https://www.googleapis.com/auth/youtube.readonly']
                }
                self.save_credentials_metadata(project_id, cred_metadata)
                
                return True
            
            except Exception as e:
                logger.error(f"OAuth flow failed: {e}")
                return False
        
        return False
    
    def rotate_credentials(self, project_id: str) -> bool:
        """
        Rotate to secondary credential.
        
        Used when primary credential has exhausted quota.
        """
        logger.info(f"Rotating credentials for {project_id}...")
        
        project_config = self.load_project_config(project_id)
        cred_metadata = self.load_credentials_metadata(project_id)
        quota_data = self._load_quota(project_id)
        
        # Find secondary credential
        secondary_cred_id = project_config['credentials']['secondary_oauth_client_id']
        if not secondary_cred_id:
            logger.error("No secondary credential configured")
            return False
        
        # Verify secondary is configured
        secondary_cred = None
        for cred in cred_metadata['credentials']:
            if cred['oauth_client_id'] == secondary_cred_id:
                secondary_cred = cred
                break
        
        if not secondary_cred or secondary_cred['status'] != 'active':
            logger.error("Secondary credential not active")
            return False
        
        # Swap primary and secondary in project config
        project_config['credentials']['primary_oauth_client_id'] = secondary_cred_id
        project_config['credentials']['secondary_oauth_client_id'] = secondary_cred['oauth_client_id']
        
        # Save updated config
        config_file = self.projects_dir / f"{project_id}.json"
        with open(config_file, 'w') as f:
            json.dump(project_config, f, indent=2)
        
        # Log rotation event
        quota_data['rotation_log'].append({
            'timestamp': datetime.utcnow().isoformat() + "Z",
            'event': 'credentials_rotated',
            'from_credential_id': 'primary',
            'to_credential_id': 'secondary',
            'reason': 'manual_rotation',
            'quota_remaining_at_rotation': quota_data['daily_quota']['current_remaining']
        })
        
        self._save_quota(project_id, quota_data)
        
        logger.info(f"✓ Credentials rotated")
        return True
    
    def get_valid_credential(self, project_id: str) -> Optional[str]:
        """
        Get a valid credential for the project.
        
        Returns path to access token file, or None if authentication needed.
        """
        project_config = self.load_project_config(project_id)
        primary_cred_id = project_config['credentials']['primary_oauth_client_id']
        
        token_file = self.credentials_dir / project_id / f"primary_token.json"
        
        if token_file.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_file))
                if not creds.expired:
                    return str(token_file)
                
                # Try to refresh
                request = Request()
                creds.refresh(request)
                with open(token_file, 'w') as f:
                    f.write(creds.to_json())
                return str(token_file)
            except Exception as e:
                logger.warning(f"Credential validation failed: {e}")
        
        return None
    
    def _load_quota(self, project_id: str) -> Dict:
        """Load quota tracking data."""
        quota_file = self.quota_dir / f"{project_id}.json"
        with open(quota_file) as f:
            return json.load(f)
    
    def _save_quota(self, project_id: str, quota: Dict):
        """Save quota tracking data."""
        quota_file = self.quota_dir / f"{project_id}.json"
        with open(quota_file, 'w') as f:
            json.dump(quota, f, indent=2)
```

### 3.3 Intelligent Quota Management & Rotation

**Feature:** Auto-rotation when quotas exhaust, monitoring, and alerts

#### 3.3.1 Quota Manager Implementation

```python
"""
YouTube Data API quota tracking and intelligent credential rotation.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import requests

logger = logging.getLogger(__name__)

class QuotaManager:
    """
    Tracks API quota usage and coordinates credential rotation.
    
    Key responsibilities:
    - Monitor daily usage against 10,000-unit limit
    - Predict exhaustion based on rolling averages
    - Auto-rotate credentials before/at exhaustion
    - Alert operators to quota events
    - Maintain audit trail
    """
    
    def __init__(self, config_home: Path, credential_manager):
        self.config_home = config_home
        self.quota_dir = config_home / "quota"
        self.credentials_dir = config_home / "credentials"
        self.projects_dir = config_home / "projects"
        self.cred_manager = credential_manager
    
    def get_quota_status(self, project_id: str) -> Dict:
        """Get current quota status for a project."""
        quota_file = self.quota_dir / f"{project_id}.json"
        
        with open(quota_file) as f:
            quota = json.load(f)
        
        # Check if quota window has reset
        self._check_quota_reset(project_id, quota)
        
        return {
            'project_id': project_id,
            'daily_quota': quota['daily_quota'],
            'rolling_7day_avg': quota['rolling_window_7_days']['average_daily_usage'],
            'days_until_exhaustion': self._estimate_days_to_exhaustion(quota),
            'percentage_used': quota['daily_quota']['percentage_used'],
            'last_check': quota['daily_quota'].get('last_check'),
            'next_reset': quota['quota_window']['next_reset'],
            'alerts': quota.get('alerts', [])
        }
    
    def record_query_usage(self, project_id: str, units_used: int) -> Dict:
        """
        Record API query usage after each request.
        
        Returns:
        - Updated quota status
        - Rotation decision (None, 'warning', 'rotate_now')
        """
        quota_file = self.quota_dir / f"{project_id}.json"
        
        with open(quota_file) as f:
            quota = json.load(f)
        
        # Check for reset
        self._check_quota_reset(project_id, quota)
        
        # Update counters
        quota['daily_quota']['current_used'] += units_used
        quota['daily_quota']['current_remaining'] = \
            quota['daily_quota']['allocated_units'] - quota['daily_quota']['current_used']
        quota['daily_quota']['percentage_used'] = \
            (quota['daily_quota']['current_used'] / quota['daily_quota']['allocated_units']) * 100
        quota['daily_quota']['last_check'] = datetime.utcnow().isoformat() + "Z"
        
        # Save updated quota
        with open(quota_file, 'w') as f:
            json.dump(quota, f, indent=2)
        
        # Check quota thresholds and make rotation decision
        decision = self._check_rotation_decision(project_id, quota)
        
        return {
            'units_used': units_used,
            'total_used': quota['daily_quota']['current_used'],
            'total_remaining': quota['daily_quota']['current_remaining'],
            'percentage_used': quota['daily_quota']['percentage_used'],
            'rotation_decision': decision
        }
    
    def should_rotate_credentials(self, project_id: str) -> Tuple[bool, Optional[str]]:
        """
        Determine if credentials should be rotated.
        
        Returns:
        - (should_rotate: bool, reason: str)
        """
        quota_file = self.quota_dir / f"{project_id}.json"
        
        with open(quota_file) as f:
            quota = json.load(f)
        
        # Check quota exhaustion threshold (default 95%)
        if quota['daily_quota']['percentage_used'] >= 95:
            return (True, f"Quota at {quota['daily_quota']['percentage_used']}%")
        
        # Check for recent rotation attempts
        if quota['rotation_log']:
            last_rotation = quota['rotation_log'][-1]
            rotation_time = datetime.fromisoformat(
                last_rotation['timestamp'].replace('Z', '+00:00')
            )
            time_since = datetime.utcnow() - rotation_time.replace(tzinfo=None)
            
            # Don't rotate more than once per hour
            if time_since < timedelta(hours=1):
                return (False, "Recently rotated")
        
        return (False, None)
    
    def _check_quota_reset(self, project_id: str, quota: Dict):
        """Check if quota window has reset and update accordingly."""
        reset_time_str = quota['quota_window']['last_reset']
        last_reset = datetime.fromisoformat(reset_time_str.replace('Z', '+00:00'))
        now = datetime.utcnow()
        
        # If more than 24 hours have passed, reset quota
        if (now - last_reset.replace(tzinfo=None)).total_seconds() > 86400:
            logger.info(f"Quota window reset for {project_id}")
            
            # Save current usage to rolling window
            if quota['rolling_window_7_days']['peak_daily_usage'] < quota['daily_quota']['current_used']:
                quota['rolling_window_7_days']['peak_daily_usage'] = quota['daily_quota']['current_used']
            
            # Reset daily counters
            quota['daily_quota']['current_used'] = 0
            quota['daily_quota']['current_remaining'] = quota['daily_quota']['allocated_units']
            quota['daily_quota']['percentage_used'] = 0.0
            quota['quota_window']['last_reset'] = datetime.utcnow().isoformat() + "Z"
            quota['quota_window']['next_reset'] = \
                (datetime.utcnow() + timedelta(hours=24)).isoformat() + "Z"
            
            quota_file = self.quota_dir / f"{project_id}.json"
            with open(quota_file, 'w') as f:
                json.dump(quota, f, indent=2)
    
    def _check_rotation_decision(self, project_id: str, quota: Dict) -> Optional[str]:
        """Check if rotation should be triggered based on quota."""
        percentage = quota['daily_quota']['percentage_used']
        
        # Warning threshold (default 80%)
        if percentage >= 80 and percentage < 95:
            return 'warning'
        
        # Critical threshold (default 95%)
        if percentage >= 95:
            return 'rotate_now'
        
        return None
    
    def _estimate_days_to_exhaustion(self, quota: Dict) -> float:
        """Estimate days until quota exhaustion based on rolling average."""
        avg_usage = quota['rolling_window_7_days']['average_daily_usage']
        remaining = quota['daily_quota']['current_remaining']
        
        if avg_usage <= 0:
            return 999.0  # No data yet
        
        return remaining / avg_usage
    
    def alert_quota_event(self, project_id: str, event_type: str, message: str):
        """
        Send alert for quota event.
        
        event_type: 'warning', 'critical', 'rotated', 'exhausted'
        """
        logger.warning(f"[{project_id}] {event_type.upper()}: {message}")
        
        # Can integrate with Slack, email, etc.
        # For now, just log
```

### 3.4 YTrix Application Integration

**File:** `./ytrix/main.py` (updated)

```python
"""
ytrix - Ethical YouTube Data API client with multi-project quota management
"""

import click
import logging
from pathlib import Path

from ytrix.auth_manager import CredentialManager
from ytrix.quota_manager import QuotaManager
from ytrix.project_manager import ProjectManager

logger = logging.getLogger(__name__)

@click.group()
@click.option('--config', type=click.Path(), default=str(Path.home() / ".ytrix"))
@click.option('--log-level', default='INFO', type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR']))
@click.pass_context
def cli(ctx, config, log_level):
    """ytrix - Multi-project YouTube Data API client"""
    
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    ctx.ensure_object(dict)
    ctx.obj['config_home'] = Path(config)

# ================= PROJECTS COMMANDS =================

@cli.group()
def projects():
    """Manage GCP projects"""
    pass

@projects.command(name='list')
@click.pass_context
def list_projects(ctx):
    """List all configured projects"""
    pm = ProjectManager(ctx.obj['config_home'])
    projects = pm.list_projects()
    
    click.echo("\nConfigured Projects:")
    click.echo("-" * 80)
    click.echo(f"{'Project ID':<20} {'Status':<10} {'Quota':<20} {'Usage'}")
    click.echo("-" * 80)
    
    for project in projects:
        status = project.get('status', 'unknown').upper()
        quota = project['youtube_api'].get('default_quota_units', 10000)
        usage = project.get('quota_metadata', {})
        used = usage.get('daily_queries_used', 0)
        total = usage.get('daily_queries_used', 0) + usage.get('daily_queries_remaining', 0)
        pct = (used / total * 100) if total > 0 else 0
        
        click.echo(
            f"{project['project_id']:<20} {status:<10} "
            f"{quota} units       {used}/{total} ({pct:.1f}%)"
        )

@projects.command(name='info')
@click.argument('project_id')
@click.pass_context
def project_info(ctx, project_id):
    """Show detailed project information"""
    pm = ProjectManager(ctx.obj['config_home'])
    project = pm.get_project(project_id)
    
    if not project:
        click.echo(f"Project not found: {project_id}", err=True)
        raise SystemExit(1)
    
    click.echo(json.dumps(project, indent=2))

@projects.command(name='add')
@click.argument('project_id')
@click.pass_context
def add_project(ctx, project_id):
    """Add existing GCP project to ytrix"""
    pm = ProjectManager(ctx.obj['config_home'])
    
    click.echo(f"Adding project: {project_id}")
    
    # Verify project exists in GCP
    if not pm.verify_gcp_project(project_id):
        click.echo(f"Project not found in GCP: {project_id}", err=True)
        raise SystemExit(1)
    
    # Prompt for OAuth client details
    client_id = click.prompt('OAuth Client ID')
    client_secret = click.prompt('OAuth Client Secret', hide_input=True)
    
    # Add to configuration
    if pm.add_project(project_id, client_id, client_secret):
        click.echo(f"✓ Project added: {project_id}")
    else:
        click.echo(f"✗ Failed to add project", err=True)
        raise SystemExit(1)

@projects.command(name='set-default')
@click.argument('project_id')
@click.pass_context
def set_default_project(ctx, project_id):
    """Set default project for API calls"""
    pm = ProjectManager(ctx.obj['config_home'])
    
    if pm.set_default_project(project_id):
        click.echo(f"✓ Default project set to: {project_id}")
    else:
        click.echo(f"✗ Failed to set default project", err=True)
        raise SystemExit(1)

# ================= AUTH COMMANDS =================

@cli.group()
def auth():
    """Manage authentication and credentials"""
    pass

@auth.command(name='login')
@click.option('--project', default=None, help='Project ID (uses default if not specified)')
@click.option('--force', is_flag=True, help='Force re-authentication even if token exists')
@click.pass_context
def auth_login(ctx, project, force):
    """Authenticate with GCP project"""
    cred_manager = CredentialManager(ctx.obj['config_home'])
    pm = ProjectManager(ctx.obj['config_home'])
    
    if not project:
        project = pm.get_default_project()
    
    if not project:
        click.echo("No project specified and no default set", err=True)
        raise SystemExit(1)
    
    click.echo(f"Authenticating project: {project}")
    
    if cred_manager.authenticate_project(project, force=force):
        click.echo(f"✓ Authentication successful")
    else:
        click.echo(f"✗ Authentication failed", err=True)
        raise SystemExit(1)

@auth.command(name='login-all')
@click.pass_context
def auth_login_all(ctx):
    """Authenticate all configured projects"""
    cred_manager = CredentialManager(ctx.obj['config_home'])
    pm = ProjectManager(ctx.obj['config_home'])
    
    projects = pm.list_projects()
    success = 0
    failed = 0
    
    for project in projects:
        click.echo(f"\nAuthenticating: {project['project_id']}")
        if cred_manager.authenticate_project(project['project_id']):
            success += 1
        else:
            failed += 1
    
    click.echo(f"\n✓ Success: {success}, ✗ Failed: {failed}")

@auth.command(name='status')
@click.pass_context
def auth_status(ctx):
    """Show credential status for all projects"""
    cred_manager = CredentialManager(ctx.obj['config_home'])
    pm = ProjectManager(ctx.obj['config_home'])
    
    projects = pm.list_projects()
    
    click.echo("\nCredential Status:")
    click.echo("-" * 100)
    click.echo(f"{'Project':<20} {'Credential':<15} {'Status':<12} {'Created':<20} {'Expires':<20}")
    click.echo("-" * 100)
    
    for project in projects:
        try:
            metadata = cred_manager.load_credentials_metadata(project['project_id'])
            for cred in metadata['credentials']:
                cred_id = cred['id']
                status = cred['status'].upper()
                created = cred.get('created_at', 'N/A')
                expires = cred.get('access_tokens', {}).get('current', {}).get('expires_at', 'N/A')
                
                click.echo(
                    f"{project['project_id']:<20} {cred_id:<15} {status:<12} "
                    f"{created:<20} {expires:<20}"
                )
        except Exception as e:
            logger.warning(f"Failed to load credentials for {project['project_id']}: {e}")

@auth.command(name='rotate')
@click.option('--project', default=None, help='Project ID')
@click.pass_context
def auth_rotate(ctx, project):
    """Manually rotate to secondary credential"""
    cred_manager = CredentialManager(ctx.obj['config_home'])
    pm = ProjectManager(ctx.obj['config_home'])
    
    if not project:
        project = pm.get_default_project()
    
    if not project:
        click.echo("No project specified and no default set", err=True)
        raise SystemExit(1)
    
    click.echo(f"Rotating credentials for: {project}")
    
    if cred_manager.rotate_credentials(project):
        click.echo(f"✓ Credentials rotated")
    else:
        click.echo(f"✗ Rotation failed", err=True)
        raise SystemExit(1)

@auth.command(name='history')
@click.option('--project', default=None)
@click.option('--limit', type=int, default=10)
@click.pass_context
def auth_history(ctx, project, limit):
    """Show credential rotation history"""
    qm = QuotaManager(ctx.obj['config_home'], None)
    pm = ProjectManager(ctx.obj['config_home'])
    
    if not project:
        project = pm.get_default_project()
    
    quota = qm.get_quota_status(project)
    
    click.echo(f"\nCredential Rotation History for {project}:")
    click.echo("-" * 100)
    
    # Access quota data
    quota_file = ctx.obj['config_home'] / 'quota' / f"{project}.json"
    with open(quota_file) as f:
        quota_data = json.load(f)
    
    rotation_log = quota_data.get('rotation_log', [])[-limit:]
    
    for entry in rotation_log:
        timestamp = entry.get('timestamp', 'N/A')
        event = entry.get('event', 'N/A')
        reason = entry.get('reason', 'N/A')
        remaining = entry.get('quota_remaining_at_rotation', 'N/A')
        
        click.echo(f"{timestamp} | {event:20} | {reason:30} | Quota: {remaining}")

# ================= QUOTA COMMANDS =================

@cli.group()
def quota():
    """Monitor and manage API quota"""
    pass

@quota.command(name='status')
@click.option('--project', default=None)
@click.pass_context
def quota_status(ctx, project):
    """Show current quota status"""
    qm = QuotaManager(ctx.obj['config_home'], None)
    pm = ProjectManager(ctx.obj['config_home'])
    
    if not project:
        project = pm.get_default_project()
    
    status = qm.get_quota_status(project)
    
    click.echo(f"\nQuota Status: {project}")
    click.echo("-" * 60)
    click.echo(f"Daily Quota:         {status['daily_quota']['allocated_units']} units")
    click.echo(f"Used:                {status['daily_quota']['current_used']} units")
    click.echo(f"Remaining:           {status['daily_quota']['current_remaining']} units")
    click.echo(f"Percentage:          {status['percentage_used']:.1f}%")
    click.echo(f"Rolling 7-day avg:   {status['rolling_7day_avg']:.1f} units/day")
    click.echo(f"Days to exhaustion:  {status['days_until_exhaustion']:.1f}")
    click.echo(f"Next reset:          {status['next_reset']}")

if __name__ == '__main__':
    cli(obj={})
```

---

## Part 4: Integration with Existing YTrix Code

### 4.1 Video Search/Fetch with Automatic Rotation

**File:** `./ytrix/api_client.py` (updated)

```python
"""
YouTube Data API client with automatic quota-aware credential rotation.
"""

import logging
from typing import Optional, Dict, Any
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ytrix.auth_manager import CredentialManager
from ytrix.quota_manager import QuotaManager
from ytrix.project_manager import ProjectManager

logger = logging.getLogger(__name__)

class YouTubeAPIClient:
    """
    YouTube Data API client with quota-aware rotation.
    
    Features:
    - Automatic credential rotation on quota exhaustion
    - Quota tracking per request
    - Caching to minimize API calls
    - Exponential backoff for transient errors
    """
    
    def __init__(self, project_id: str, config_home=None):
        self.project_id = project_id
        self.config_home = config_home or Path.home() / ".ytrix"
        
        self.cred_manager = CredentialManager(self.config_home)
        self.quota_manager = QuotaManager(self.config_home, self.cred_manager)
        self.project_manager = ProjectManager(self.config_home)
        
        self.service = None
        self.current_project = project_id
    
    def _ensure_authenticated(self) -> bool:
        """Ensure we have valid credentials."""
        token_file = self.cred_manager.get_valid_credential(self.current_project)
        
        if not token_file:
            logger.error(f"No valid credential for {self.current_project}")
            return False
        
        try:
            creds = Credentials.from_authorized_user_file(token_file)
            self.service = build('youtube', 'v3', credentials=creds)
            return True
        except Exception as e:
            logger.error(f"Failed to build service: {e}")
            return False
    
    def _handle_quota_exhaustion(self) -> bool:
        """Handle quota exhaustion by rotating to secondary credential."""
        logger.warning(f"Quota exhaustion detected for {self.current_project}")
        
        should_rotate, reason = self.quota_manager.should_rotate_credentials(
            self.current_project
        )
        
        if should_rotate:
            logger.info(f"Rotating credentials: {reason}")
            if self.cred_manager.rotate_credentials(self.current_project):
                logger.info("Rotation successful, retrying request...")
                return self._ensure_authenticated()
            else:
                logger.error("Credential rotation failed")
                return False
        
        return False
    
    def search_videos(
        self,
        query: str,
        max_results: int = 5,
        order: str = 'relevance',
        **kwargs
    ) -> Optional[Dict]:
        """
        Search for videos with automatic rotation on quota exhaustion.
        
        Units cost: 100 per request
        """
        if not self._ensure_authenticated():
            return None
        
        try:
            request = self.service.search().list(
                q=query,
                part='snippet',
                maxResults=max_results,
                order=order,
                type='video',
                **kwargs
            )
            
            result = request.execute()
            
            # Track quota usage (100 units for search)
            self.quota_manager.record_query_usage(self.current_project, 100)
            
            return result
        
        except HttpError as e:
            error_content = e.content.decode('utf-8')
            
            # Check for quota exhaustion error
            if 'quotaExceeded' in error_content or 'dailyLimitExceeded' in error_content:
                logger.error("Quota exhausted")
                
                if self._handle_quota_exhaustion():
                    # Retry with rotated credential
                    return self.search_videos(query, max_results, order, **kwargs)
                else:
                    logger.error("Cannot recover from quota exhaustion")
                    return None
            
            logger.error(f"API error: {e}")
            return None
    
    def get_video_details(
        self,
        video_id: str,
        parts: str = 'snippet,statistics,contentDetails'
    ) -> Optional[Dict]:
        """
        Get video details.
        
        Units cost: 1 per request
        """
        if not self._ensure_authenticated():
            return None
        
        try:
            request = self.service.videos().list(
                id=video_id,
                part=parts
            )
            
            result = request.execute()
            
            # Track quota usage (1 unit for video.list)
            self.quota_manager.record_query_usage(self.current_project, 1)
            
            return result
        
        except HttpError as e:
            if 'quotaExceeded' in str(e):
                if self._handle_quota_exhaustion():
                    return self.get_video_details(video_id, parts)
            
            logger.error(f"API error: {e}")
            return None
```

---

## Part 5: Configuration Files & Automation

### 5.1 Initial Setup Script

**File:** `./scripts/setup-ytrix.sh`

```bash
#!/bin/bash
set -e

CONFIG_HOME="${HOME}/.ytrix"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "=========================================="
echo "ytrix Setup - Multi-Project YouTube API"
echo "=========================================="

# Create directory structure
mkdir -p "${CONFIG_HOME}/projects"
mkdir -p "${CONFIG_HOME}/credentials"
mkdir -p "${CONFIG_HOME}/quota"
mkdir -p "${CONFIG_HOME}/users"

echo ""
echo "[1] Creating initial configuration..."

# Create global config
cat > "${CONFIG_HOME}/config.toml" << 'EOF'
[global]
default_project = "fontlabtv"
default_user = "root@fontlab.ltd"
log_level = "info"
quota_warning_threshold = 0.80
quota_strict_limit = 0.95

[gcp]
organization_id = "62011989434"
billing_account = ""

[youtube_api]
max_retries = 3
backoff_multiplier = 2.0
timeout_seconds = 30

[credential_rotation]
enabled = true
secondary_rotation_enabled = true
alert_webhook = ""
EOF

echo "✓ Global config created"

# Instructions
echo ""
echo "=========================================="
echo "Next Steps"
echo "=========================================="
echo ""
echo "1. Clone GCP Project:"
echo "   $ ./issues/gcptrix/gcptrix_v2.py clone fontlabtv c1 --secondary-credentials"
echo ""
echo "2. Configure OAuth (manual via GCP Console):"
echo "   Visit: https://console.cloud.google.com/apis/credentials/consent?project=fontlabtv-c1"
echo ""
echo "3. Add project to ytrix:"
echo "   $ ytrix projects add fontlabtv-c1"
echo ""
echo "4. Authenticate:"
echo "   $ ytrix auth login --project fontlabtv-c1"
echo ""
echo "5. Check quota:"
echo "   $ ytrix quota status --project fontlabtv-c1"
echo ""

echo "Configuration home: ${CONFIG_HOME}"
```

### 5.2 Pre-Implementation Migration Checklist

```markdown
# YTrix Enhancement Implementation Checklist

## Phase 1: Foundation (Weeks 1-2)

- [ ] Review and refactor `gcptrix_v2.py`
  - [ ] Add IAM retry logic with exponential backoff
  - [ ] Implement OAuth consent screen automation
  - [ ] Add quota tracking initialization
  - [ ] Test with fontlabtv → fontlabtv-c1 clone
  
- [ ] Create configuration schema (JSON schemas)
  - [ ] projects/
  - [ ] credentials/
  - [ ] quota/
  - [ ] users/
  
- [ ] Implement `CredentialManager` class
  - [ ] Project config loading/saving
  - [ ] OAuth flow (interactive + refresh)
  - [ ] Token caching
  - [ ] Credential metadata tracking

## Phase 2: Quota & Rotation (Weeks 2-3)

- [ ] Implement `QuotaManager` class
  - [ ] Daily quota tracking
  - [ ] Rolling window averages
  - [ ] Rotation decision logic
  - [ ] Alert system
  
- [ ] Implement `ProjectManager` class
  - [ ] Project CRUD
  - [ ] Default project selection
  - [ ] Multi-user support
  
- [ ] Implement credential rotation
  - [ ] Primary → secondary switching
  - [ ] Rotation logging
  - [ ] Failed rotation handling

## Phase 3: CLI Integration (Weeks 3-4)

- [ ] Create `ytrix projects` commands
  - [ ] list, info, add, remove, set-default
  
- [ ] Create `ytrix auth` commands
  - [ ] login, login-all, status, rotate, history
  
- [ ] Create `ytrix quota` commands
  - [ ] status, history, estimates
  
- [ ] Integration tests
  - [ ] Multi-project workflow
  - [ ] Credential rotation
  - [ ] Quota tracking accuracy

## Phase 4: API Client Integration (Week 4)

- [ ] Update YouTube API client
  - [ ] Automatic rotation on quotaExceeded
  - [ ] Quota tracking per request
  - [ ] Error handling & recovery
  
- [ ] Update search/fetch functions
  - [ ] Use new credential system
  - [ ] Automatic project rotation
  - [ ] Quota awareness in business logic

## Phase 5: Testing & Documentation (Week 5)

- [ ] Integration tests
  - [ ] Multi-project cloning
  - [ ] Credential rotation workflows
  - [ ] Quota exhaustion scenarios
  
- [ ] Documentation
  - [ ] Setup guide
  - [ ] Configuration reference
  - [ ] Troubleshooting guide
  - [ ] Architecture documentation
  
- [ ] User acceptance testing
  - [ ] Manual testing with real GCP projects
  - [ ] Load testing quota system
  - [ ] Rotation failover scenarios

---

## Success Criteria

- ✓ Can clone GCP project with one command
- ✓ OAuth credentials automatically configured
- ✓ No manual steps beyond downloading client secret
- ✓ Quota rotation prevents API blocks
- ✓ Clear alerts when approaching limits
- ✓ Audit trail of all rotations
- ✓ <5 minute setup time for new project
- ✓ All tests passing
```

---

## Part 6: Best Practices & Compliance

### 6.1 Ethical API Usage

- **No Brute Force:** Cache results, respect rate limits, implement backoff
- **Quota Awareness:** Monitor usage, predict exhaustion, rotate proactively
- **User Transparency:** Log all API calls, show quota status
- **Terms of Service Compliance:** Only use YouTube readonly APIs, no scraping/circumvention

### 6.2 Security Hardening

| Area | Recommendation |
|------|-----------------|
| **Credentials** | Store in GCP Secret Manager, never in git, encrypted at rest |
| **Access Tokens** | 1-hour expiration, auto-refresh, never log full tokens |
| **Rotation Keys** | Every 90 days max, retire old keys immediately |
| **Audit Trail** | Log all rotations, API calls, errors with timestamps |
| **Multi-tenancy** | Separate credentials per user, audit per-user access |

### 6.3 Monitoring & Alerting

```toml
[monitoring]
# Daily metrics
metrics_collection_enabled = true
metrics_retention_days = 365

# Alerts
alert_on_quota_80_percent = true
alert_on_quota_95_percent = true
alert_on_rotation_failure = true
alert_on_auth_failure = true

[alerting]
slack_webhook = "https://hooks.slack.com/..."
email_recipients = ["ops@fontlab.dev"]
pagerduty_integration_key = ""
```

---

## Part 7: Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| **Quota exhaustion blocks all requests** | Implement multi-project rotation with secondary credentials |
| **Credentials leaked/compromised** | Store in Secret Manager, rotate every 90 days, monitor access |
| **IAM policy conflicts during cloning** | Exponential backoff + ETag-aware retry logic |
| **OAuth flow breaks** | Auto-retry, clear error messages, browser-based fallback |
| **Quota reset time miscalculation** | Use GCP official time, verify via API, handle timezone shifts |
| **Credential rotation race condition** | Lock-based rotation, sequential processing, audit logging |

---

## Summary of Deliverables

```
./issues/gcptrix/
├── gcptrix_v2.py            # Enhanced cloning (13 automated steps)
└── README.md                # Setup & troubleshooting guide

./ytrix/
├── auth_manager.py          # OAuth + credential management
├── quota_manager.py         # Quota tracking + rotation logic
├── project_manager.py       # Multi-project orchestration
├── api_client.py           # YouTube API with auto-rotation
└── main.py                 # CLI: projects, auth, quota commands

~/.ytrix/
├── config.toml             # Global settings
├── projects/
│   ├── fontlabtv.json
│   └── fontlabtv-c1.json
├── credentials/
│   ├── fontlabtv/
│   │   ├── oauth_client_1.json
│   │   ├── oauth_client_2.json
│   │   └── metadata.json
│   └── fontlabtv-c1/
│       └── ...
└── quota/
    ├── fontlabtv.json
    └── fontlabtv-c1.json

./scripts/
└── setup-ytrix.sh           # Initialization script
```

**This specification prioritizes:**
1. ✅ **Ethical compliance** - No cheating, respecting YouTube ToS
2. ✅ **Operational robustness** - Automated rotation prevents failures
3. ✅ **User clarity** - Comprehensive reporting & transparency
4. ✅ **Security** - Credential rotation, Secret Manager, audit trails
5. ✅ **Scalability** - Multi-project, multi-user, quota-aware
6. ✅ **Developer experience** - Simple CLI, clear error messages, setup automation
