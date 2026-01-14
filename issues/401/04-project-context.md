# Part 4: Project Context Management (ToS-Compliant)

## Terminology Change

| Old Term | New Term | Rationale |
|----------|----------|-----------|
| Rotation | Context switching | Emphasizes purpose selection, not evasion |
| Quota pooling | Environment isolation | Legitimate separation of concerns |
| Credential cycling | Identity selection | Choose appropriate credentials for task |

## Configuration Schema Update

Update `config.py` to enforce purpose-based grouping:

```python
class ProjectConfig(BaseModel):
    """Configuration for a single GCP project."""

    name: str = Field(..., description="Unique identifier for the project")
    client_id: str
    client_secret: str
    quota_group: str = Field(
        "default",
        description="Logical group (e.g., 'personal', 'work', 'client-acme'). "
                    "Automatic context switching only occurs within same group."
    )
    environment: str = Field(
        "production",
        description="Environment type: development, staging, production"
    )
    priority: int = Field(
        0,
        description="Selection priority within group (higher = preferred)"
    )
```

### Example Configuration

```toml
# ~/.ytrix/config.toml

channel_id = "UCxxxxxx"

# Personal use - development
[[projects]]
name = "ytrix-dev"
client_id = "xxx.apps.googleusercontent.com"
client_secret = "xxx"
quota_group = "personal"
environment = "development"
priority = 1

# Personal use - production
[[projects]]
name = "ytrix-prod"
client_id = "yyy.apps.googleusercontent.com"
client_secret = "yyy"
quota_group = "personal"
environment = "production"
priority = 10  # Preferred for personal use

# Client work - separate quota group
[[projects]]
name = "client-acme-prod"
client_id = "zzz.apps.googleusercontent.com"
client_secret = "zzz"
quota_group = "client-acme"
environment = "production"
priority = 10
```

## Context Selection Logic

Replace `rotate_on_quota_exceeded()` with ToS-compliant logic:

```python
class ProjectManager:
    """Manages project contexts with ToS-compliant selection."""

    def select_context(
        self,
        quota_group: str | None = None,
        environment: str | None = None,
        force_project: str | None = None,
    ) -> ProjectConfig:
        """Select appropriate project context.

        Args:
            quota_group: Filter by quota group (e.g., "personal", "client-acme")
            environment: Filter by environment (e.g., "production")
            force_project: Directly select a specific project by name

        Returns:
            Selected project configuration

        Raises:
            ValueError: If no matching project available
        """
        if force_project:
            return self.config.get_project(force_project)

        candidates = self._get_candidates(quota_group, environment)
        if not candidates:
            raise ValueError(f"No available projects for group={quota_group}, env={environment}")

        # Sort by priority (highest first), then by remaining quota
        candidates.sort(key=lambda p: (
            -p.priority,
            -self._get_remaining_quota(p.name)
        ))

        return candidates[0]

    def handle_quota_exhausted(self, current_project: str) -> bool:
        """Handle quota exhaustion with ToS-compliant failover.

        IMPORTANT: This does NOT automatically cycle to increase quota.
        It only fails over within the same quota_group for resilience.

        Returns:
            True if failover succeeded within same group
            False if no failover available (user must wait for reset)
        """
        current = self.config.get_project(current_project)
        same_group = [
            p for p in self._get_candidates(current.quota_group)
            if p.name != current_project
            and not self._states[p.name].is_exhausted
        ]

        if not same_group:
            logger.warning(
                "All projects in group '{}' exhausted. "
                "Quota resets at midnight PT. Consider requesting quota increase.",
                current.quota_group
            )
            return False

        # Failover to another project in same group
        # This is for RESILIENCE, not quota multiplication
        next_project = same_group[0]
        logger.info(
            "Failing over to '{}' within group '{}'. "
            "Note: All projects share the same daily quota purpose.",
            next_project.name, current.quota_group
        )
        self.select_project(next_project.name)
        return True
```

## CLI Changes

### Add `--quota-group` Flag

```bash
# Use specific quota group
ytrix --quota-group personal plist2mlist PLxxx

# Use specific project (overrides group)
ytrix --project ytrix-dev plist2mlist PLxxx
```

### Update `projects` Command Output

```bash
$ ytrix projects

Projects by Quota Group:
═══════════════════════════════════════════════════════════════

Group: personal
  * ytrix-prod     [ACTIVE]  3,500/10,000 units  (production)
    ytrix-dev                8,200/10,000 units  (development)

Group: client-acme
    client-acme-prod          0/10,000 units  (production)

═══════════════════════════════════════════════════════════════
Quota resets in 5h 23m (midnight Pacific Time)

Note: Automatic failover only occurs within the same quota group.
For higher quota, request an increase: https://support.google.com/youtube/contact/yt_api_form
```

## User Education

### Startup Warning (First Run)

```python
def show_tos_reminder():
    """Display ToS reminder on first run or after update."""
    console.print(Panel(
        "[yellow]Important: YouTube API Terms of Service[/yellow]\n\n"
        "Using multiple GCP projects to circumvent quota limits is prohibited.\n"
        "ytrix supports multiple projects for legitimate purposes:\n"
        "• Environment isolation (dev/staging/prod)\n"
        "• Multi-tenant separation (different clients)\n"
        "• Resilience (failover, not throughput multiplication)\n\n"
        "For higher quota needs, request an increase:\n"
        "https://support.google.com/youtube/contact/yt_api_form",
        title="ToS Reminder",
        border_style="yellow"
    ))
```

### Documentation Update

Add to README:

```markdown
## Multi-Project Configuration

ytrix supports multiple GCP projects for legitimate purposes:

1. **Environment Isolation**: Separate dev/staging/production
2. **Multi-Tenancy**: Different projects for different clients
3. **Resilience**: Failover if one project has issues

**Important**: Using multiple projects solely to multiply quota violates
Google's Terms of Service and can result in account suspension.

If you need more than 10,000 units/day, request a quota increase:
https://support.google.com/youtube/contact/yt_api_form
```

## Implementation Checklist

- [ ] Add `quota_group` and `environment` fields to ProjectConfig
- [ ] Update config.py schema and validation
- [ ] Replace `rotate_on_quota_exceeded()` with `handle_quota_exhausted()`
- [ ] Add `--quota-group` CLI flag
- [ ] Update `projects` command to show groups
- [ ] Add ToS reminder on first run
- [ ] Update README with multi-project guidance
- [ ] Add validation to prevent obvious quota circumvention patterns
