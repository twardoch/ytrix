# Part 5: GCP Setup Automation

## Current Pain Points

The existing `gcptrix.py` handles steps 0-10 but leaves 11 manual steps. For YouTube API use, only 4 are critical:

1. **OAuth consent screen** - Must be configured manually (API limitation)
2. **OAuth client credentials** - Must be created manually
3. **Service account keys** - Cannot be exported (security)
4. **Config update** - User must edit config.toml

## Improved Workflow: "Guided Automation"

Instead of failing silently at manual steps, provide rich interactive guidance.

### 5.1 Enhanced Project Creation

```python
# gcptrix.py additions

def create_project_interactive(
    base_name: str,
    billing_account: str | None = None,
    dry_run: bool = False,
) -> ProjectSetupResult:
    """Create new GCP project with interactive guidance.

    Returns:
        ProjectSetupResult with status, project_id, and next_steps
    """
    console = Console()

    # Generate unique project ID
    project_id = f"{base_name}-{int(time.time()) % 100000}"

    with console.status("[bold blue]Creating GCP project..."):
        # Step 1: Create project
        create_project(project_id, parent=None, dry_run=dry_run)

        # Step 2: Enable YouTube API
        enable_service(project_id, "youtube.googleapis.com", dry_run=dry_run)

    console.print(f"[green]✓ Created project: {project_id}[/green]")

    # Step 3: Guided OAuth setup
    return guide_oauth_setup(project_id, console)
```

### 5.2 Interactive OAuth Guide

```python
def guide_oauth_setup(project_id: str, console: Console) -> ProjectSetupResult:
    """Guide user through OAuth setup with deep links and verification."""

    console.print("\n[bold]OAuth Setup Required[/bold]")
    console.print("─" * 50)

    # Step 1: Consent screen
    consent_url = f"https://console.cloud.google.com/apis/credentials/consent?project={project_id}"

    console.print("\n[bold cyan]Step 1: Configure OAuth Consent Screen[/bold cyan]")
    console.print(f"Open: [link={consent_url}]{consent_url}[/link]")
    console.print("""
    Settings:
    • User Type: External
    • App name: ytrix
    • User support email: <your email>
    • Developer contact: <your email>
    • Scopes: Add 'youtube' scope
    • Test users: Add your email
    """)

    if Confirm.ask("Have you completed the consent screen configuration?"):
        console.print("[green]✓ Consent screen configured[/green]")
    else:
        console.print("[yellow]Skipped. Complete before using ytrix.[/yellow]")

    # Step 2: Create credentials
    creds_url = f"https://console.cloud.google.com/apis/credentials?project={project_id}"

    console.print("\n[bold cyan]Step 2: Create OAuth Credentials[/bold cyan]")
    console.print(f"Open: [link={creds_url}]{creds_url}[/link]")
    console.print("""
    Steps:
    1. Click "Create Credentials" → "OAuth client ID"
    2. Application type: "Desktop app"
    3. Name: "ytrix"
    4. Click "Create"
    5. Copy the Client ID and Client Secret
    """)

    client_id = Prompt.ask("Enter Client ID (or press Enter to skip)")
    client_secret = ""
    if client_id:
        client_secret = Prompt.ask("Enter Client Secret", password=True)

    # Step 3: Update config
    if client_id and client_secret:
        return _update_config_with_project(project_id, client_id, client_secret, console)

    return ProjectSetupResult(
        success=True,
        project_id=project_id,
        needs_manual_config=True,
        config_snippet=_generate_config_snippet(project_id)
    )
```

### 5.3 File Watcher Pattern (Advanced)

For users who prefer browser-based credential download:

```python
import watchdog.observers
import watchdog.events

class CredentialFileHandler(watchdog.events.FileSystemEventHandler):
    """Watch for downloaded credential files."""

    def __init__(self, project_id: str, callback):
        self.project_id = project_id
        self.callback = callback

    def on_created(self, event):
        if event.src_path.endswith('.json'):
            filename = Path(event.src_path).name
            if filename.startswith('client_secret_'):
                self.callback(event.src_path)


def watch_for_credentials(project_id: str, timeout: int = 300) -> str | None:
    """Watch Downloads folder for credential file.

    Returns:
        Path to credential file, or None if timeout
    """
    downloads_dir = Path.home() / "Downloads"
    found_path = None

    def on_found(path):
        nonlocal found_path
        found_path = path

    observer = watchdog.observers.Observer()
    handler = CredentialFileHandler(project_id, on_found)
    observer.schedule(handler, str(downloads_dir), recursive=False)
    observer.start()

    console.print("[dim]Watching Downloads folder for credential file...[/dim]")
    console.print("[dim]Download the JSON from GCP Console[/dim]")

    start = time.time()
    while time.time() - start < timeout and found_path is None:
        time.sleep(1)

    observer.stop()
    observer.join()

    return found_path
```

### 5.4 Automatic Config Update

```python
def _update_config_with_project(
    project_id: str,
    client_id: str,
    client_secret: str,
    console: Console
) -> ProjectSetupResult:
    """Add project to config.toml automatically."""

    config_path = get_config_dir() / "config.toml"

    # Read existing config
    if config_path.exists():
        with open(config_path) as f:
            config_content = f.read()
    else:
        config_content = ""

    # Append new project
    new_project = f'''
[[projects]]
name = "{project_id}"
client_id = "{client_id}"
client_secret = "{client_secret}"
quota_group = "default"
environment = "production"
priority = 0
'''

    with open(config_path, 'a') as f:
        f.write(new_project)
    config_path.chmod(0o600)

    console.print(f"[green]✓ Added {project_id} to config.toml[/green]")

    # Prompt for authentication
    if Confirm.ask("Authenticate now?"):
        from ytrix.projects import get_project_manager
        manager = get_project_manager()
        manager.select_project(project_id)
        manager.get_credentials()
        console.print("[green]✓ Authentication complete[/green]")

    return ProjectSetupResult(
        success=True,
        project_id=project_id,
        needs_manual_config=False,
        authenticated=True
    )
```

### 5.5 Clone Project Enhancement

```python
def clone_project_enhanced(
    source_project: str,
    suffix: str,
    dry_run: bool = False,
) -> int:
    """Clone project with improved UX.

    Enhancements over current gcptrix:
    1. Better error messages with suggested fixes
    2. Exponential backoff for IAM conflicts
    3. Interactive OAuth setup after clone
    4. Automatic config.toml update
    """
    console = Console()

    with console.status("[bold blue]Cloning project..."):
        # ... existing clone logic with improved error handling ...
        pass

    # After clone completes, guide OAuth setup
    new_project_id = f"{source_project}-{suffix}"
    return guide_oauth_setup(new_project_id, console)
```

### 5.6 Error Handling Improvements

```python
def handle_clone_error(error: GcloudError, context: dict) -> str:
    """Return user-friendly error message with resolution steps."""

    error_str = str(error).lower()

    if "already exists" in error_str:
        return (
            f"Project ID '{context['project_id']}' already exists.\n"
            f"Try a different suffix: ytrix gcp_clone {context['source']} suffix2"
        )

    if "billing" in error_str:
        return (
            "Billing account required. Link a billing account:\n"
            f"gcloud billing projects link {context['project_id']} --billing-account=ACCOUNT_ID"
        )

    if "permission" in error_str:
        return (
            "Insufficient permissions. Ensure you have:\n"
            "• roles/resourcemanager.projectCreator on the organization\n"
            "• roles/billing.user on the billing account\n\n"
            "Run: gcloud auth login"
        )

    if "quota" in error_str or "rate" in error_str:
        return (
            "GCP API rate limit hit. Wait 60 seconds and retry:\n"
            f"ytrix gcp_clone {context['source']} {context['suffix']}"
        )

    return f"Unknown error: {error}\nSee: gcloud --help"
```

## New CLI Commands

```bash
# Create new project with guided setup
ytrix gcp_init <project-name> [--billing-account ACCOUNT]

# Clone project with guided OAuth
ytrix gcp_clone <source> <suffix> [--guide-oauth]

# Show inventory
ytrix gcp_inventory <project>

# Print OAuth setup guide
ytrix gcp_guide <project>
```

## Implementation Checklist

- [ ] Add `ProjectSetupResult` dataclass
- [ ] Implement `guide_oauth_setup()` with rich prompts
- [ ] Add file watcher for credential download (optional)
- [ ] Implement automatic config.toml update
- [ ] Add `gcp_init` command for fresh project creation
- [ ] Improve error messages with resolution steps
- [ ] Add exponential backoff for IAM operations
- [ ] Update `gcp_clone` to include OAuth guidance
