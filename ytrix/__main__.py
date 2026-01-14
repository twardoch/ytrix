"""ytrix CLI - YouTube playlist management."""

import contextlib
import json
from collections import defaultdict
from importlib import resources
from pathlib import Path
from typing import Any

import fire
from rich.console import Console
from rich.progress import Progress

from ytrix import __version__, api, cache, extractor, info, quota, yaml_ops
from ytrix.api import BatchAction, BatchOperationHandler, classify_error, display_error
from ytrix.config import Config, get_config_dir, load_config
from ytrix.dedup import MatchType, analyze_batch_deduplication, load_target_playlists_with_videos
from ytrix.journal import (
    Journal,
    TaskStatus,
    clear_journal,
    create_journal,
    get_journal_summary,
    get_pending_tasks,
    load_journal,
    update_task,
)
from ytrix.logging import configure_logging, logger
from ytrix.models import Playlist, extract_playlist_id
from ytrix.projects import get_project_manager
from ytrix.quota import (
    QuotaEstimate,
    can_afford_operation,
    estimate_copy_cost,
    format_quota_warning,
)

console = Console()


class YtrixCLI:
    """YouTube playlist management CLI.

    Examples:
        ytrix plist2mlist "https://youtube.com/playlist?list=PLxxx"
        ytrix --verbose mlists2yaml --details
        ytrix --json-output plist2mlist PLxxx
        ytrix --throttle 500 plists2mlists playlists.txt  # Slower API calls
        ytrix --project backup plist2mlist PLxxx  # Use specific project
    """

    def __init__(
        self,
        verbose: bool = False,
        json_output: bool = False,
        throttle: int = 200,
        project: str | None = None,
        quota_group: str | None = None,
    ) -> None:
        """Initialize CLI with options.

        Args:
            verbose: Enable debug logging
            json_output: Output results as JSON instead of human-readable text
            throttle: Milliseconds between API write calls (default 200, 0 to disable)
            project: Force using a specific project for API calls (multi-project setup)
            quota_group: Restrict context switching to projects in this quota group
        """
        configure_logging(verbose)
        self._json = json_output
        self._verbose = verbose
        self._project = project
        self._quota_group = quota_group
        # Set API throttle delay
        api.set_throttle_delay(throttle)
        logger.debug(
            "ytrix initialized with verbose={}, json={}, throttle={}ms, project={}, quota_group={}",
            verbose,
            json_output,
            throttle,
            project,
            quota_group,
        )
        # Show ToS reminder on first run after update
        self._check_tos_reminder()

    def _output(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Output result as JSON or print nothing (human output already printed)."""
        if self._json:
            print(json.dumps(data, indent=2))
        return data if self._json else None

    def _check_tos_reminder(self) -> None:
        """Show ToS reminder on first run or after version update."""
        if self._json:
            return  # Skip for JSON output mode

        config_dir = get_config_dir()
        version_file = config_dir / ".last_version"

        # Check if this is a new version or first run
        last_version = ""
        if version_file.exists():
            last_version = version_file.read_text().strip()

        if last_version != __version__:
            self._show_tos_reminder()
            version_file.write_text(__version__)

    def _show_tos_reminder(self) -> None:
        """Display ToS compliance reminder for multi-project setups."""
        console.print()
        console.print("[bold yellow]📋 Multi-Project ToS Reminder[/bold yellow]")
        console.print()
        console.print(
            "If you use multiple GCP projects, please ensure compliance with\n"
            "Google's Terms of Service (Section III.D.1.c):"
        )
        console.print()
        console.print(
            "  [dim]• Each project should serve a distinct purpose (e.g., personal vs client)[/dim]"
        )
        console.print("  [dim]• Do NOT use multiple projects to circumvent quota limits[/dim]")
        console.print("  [dim]• Use --quota-group to group projects by purpose[/dim]")
        console.print()
        console.print(
            "[dim]Quota increase requests: "
            "https://support.google.com/youtube/contact/yt_api_form[/dim]"
        )
        console.print()

    def _get_youtube_client(self, config: Config) -> Any:
        """Get YouTube API client, optionally using a specific project.

        If --project was specified, selects that project.
        If --quota-group was specified, selects from that group.
        """
        manager = get_project_manager(config)

        if self._project:
            manager.select_project(self._project)
            return manager.get_client()

        if self._quota_group:
            manager.select_context(quota_group=self._quota_group)
            return manager.get_client()

        return api.get_youtube_client(config)

    def version(self) -> None:
        """Show ytrix version."""
        if self._json:
            self._output({"version": __version__})
        else:
            console.print(f"ytrix {__version__}", highlight=False)

    def help(self) -> None:
        """Show available commands and usage.

        For detailed help on a specific command, use:
            ytrix <command> --help

        Example:
            ytrix help
            ytrix plist2mlist --help
        """
        console.print("[bold]ytrix[/bold] - YouTube playlist management\n")
        console.print("[bold]Core Commands:[/bold]")
        console.print("  plist2mlist    Copy external playlist to my channel")
        console.print("  plists2mlist   Merge multiple playlists from file")
        console.print("  plist2mlists   Split playlist by channel or year")
        console.print("  plists2mlists  Batch copy playlists with journaling")
        console.print()
        console.print("[bold]YAML Operations:[/bold]")
        console.print("  mlists2yaml    Export all my playlists to YAML")
        console.print("  yaml2mlists    Apply YAML edits to my playlists")
        console.print("  mlist2yaml     Export single playlist to YAML")
        console.print("  yaml2mlist     Apply YAML edits to single playlist")
        console.print()
        console.print("[bold]Info & Listing:[/bold]")
        console.print("  ls             List playlists on my channel")
        console.print("  plist2info     Extract playlist info with transcripts")
        console.print("  plists2info    Batch extract playlist info")
        console.print()
        console.print("[bold]Project Management:[/bold]")
        console.print("  projects       Show configured GCP projects")
        console.print("  projects_add   Add new project interactively")
        console.print("  projects_auth  Authenticate a project")
        console.print("  projects_select Select active project")
        console.print("  gcp_init       Create new GCP project from scratch")
        console.print("  gcp_clone      Clone GCP project for quota expansion")
        console.print("  gcp_inventory  Show GCP project resources")
        console.print("  gcp_guide      Show OAuth setup guide for a project")
        console.print()
        console.print("[bold]Utilities:[/bold]")
        console.print("  config         Show/setup configuration")
        console.print("  quota_status   Show API quota usage")
        console.print("  cache_stats    Show cache statistics")
        console.print("  cache_clear    Clear cached data")
        console.print("  journal_status Show batch operation status")
        console.print("  version        Show version")
        console.print()
        console.print("[bold]Global Flags:[/bold]")
        console.print("  --verbose      Enable debug logging")
        console.print("  --json-output  Output as JSON")
        console.print("  --throttle N   Milliseconds between API calls (default: 200)")
        console.print("  --project NAME Use specific GCP project")
        console.print()
        console.print("For detailed help: [cyan]ytrix <command> --help[/cyan]")

    def config(self) -> dict[str, Any] | None:
        """Show configuration status and setup instructions.

        Displays:
            - Config file path
            - Current config (if exists)
            - Setup guide (if not configured)

        Example:
            ytrix config
        """
        config_dir = get_config_dir()
        config_path = config_dir / "config.toml"
        token_path = config_dir / "token.json"

        if self._json:
            result: dict[str, Any] = {
                "config_path": str(config_path),
                "config_exists": config_path.exists(),
                "token_path": str(token_path),
                "token_exists": token_path.exists(),
            }
            if config_path.exists():
                result["config_content"] = config_path.read_text()
            return self._output(result)

        console.print(f"[bold]Config path:[/bold] {config_path}")
        console.print(f"[bold]Token path:[/bold] {token_path}")
        console.print()

        if config_path.exists():
            console.print("[green]Config file exists[/green]")
            console.print()
            # Show content with secrets masked
            content = config_path.read_text()
            for line in content.strip().split("\n"):
                if "secret" in line.lower() and "=" in line:
                    key = line.split("=")[0]
                    console.print(f"  {key}= [dim]<hidden>[/dim]")
                else:
                    console.print(f"  {line}")
            console.print()
            if token_path.exists():
                console.print("[green]OAuth token cached (authorized)[/green]")
            else:
                console.print("[yellow]No OAuth token yet (run a command to authorize)[/yellow]")
        else:
            console.print("[red]Config file not found[/red]")
            console.print()
            console.print("[bold]Setup guide:[/bold]")
            console.print()
            # Read bundled SETUP.txt
            try:
                setup_text = resources.files("ytrix").joinpath("SETUP.txt").read_text()
                print(setup_text)  # Use print() to avoid Rich markup interpretation
            except Exception:
                console.print("  See: https://github.com/fontlabtv/ytrix for setup instructions")
        return None

    def cache_stats(self) -> dict[str, Any] | None:
        """Show cache statistics.

        Displays cache location, size, and entry counts.

        Example:
            ytrix cache_stats
            ytrix --json-output cache_stats
        """
        stats = cache.get_cache_stats()

        if self._json:
            return self._output(stats)

        console.print(f"[bold]Cache path:[/bold] {stats['path']}")
        if "size_mb" in stats:
            console.print(f"[bold]Cache size:[/bold] {stats['size_mb']} MB")
        console.print()

        for table in ["playlists", "videos", "playlist_videos", "channel_playlists"]:
            info = stats.get(table, {})
            console.print(f"  {table}: {info.get('valid', 0)} valid / {info.get('total', 0)} total")

        return None

    def cache_clear(self, expired_only: bool = False) -> dict[str, Any] | None:
        """Clear cached data.

        Args:
            expired_only: Only clear expired entries (default: clear all)

        Example:
            ytrix cache_clear              # Clear all cache
            ytrix cache_clear --expired-only  # Only clear expired entries
        """
        if expired_only:
            deleted = cache.clear_expired()
            msg = f"Cleared {deleted} expired cache entries"
        else:
            deleted = cache.clear_cache()
            msg = f"Cleared {deleted} cache entries"

        if self._json:
            return self._output({"deleted": deleted, "expired_only": expired_only})

        console.print(f"[green]{msg}[/green]")
        return None

    def quota_status(self) -> dict[str, Any] | None:
        """Show API quota usage for current session.

        Displays quota units consumed, remaining capacity, and time until reset.
        Note: Only tracks usage within the current session; YouTube does not
        provide an API to query actual remaining quota.

        Example:
            ytrix quota_status
            ytrix --json-output quota_status
        """
        summary = quota.get_quota_summary()
        reset_time = quota.get_time_until_reset()

        if self._json:
            output: dict[str, Any] = dict(summary)
            output["reset_in"] = reset_time
            return self._output(output)

        used = summary["used"]
        remaining = summary["remaining"]
        limit = summary["limit"]
        pct = summary["usage_percent"]
        ops: dict[str, int] = summary.get("operations", {})  # type: ignore[assignment]

        console.print("[bold]Session Quota Usage[/bold]")
        console.print(f"  Used: {used:,} / {limit:,} units ({pct:.1f}%)")
        console.print(f"  Remaining: {remaining:,} units")
        console.print(f"  Resets in: {reset_time} (midnight PT)")

        if ops:
            console.print()
            console.print("[bold]Operations this session:[/bold]")
            for op, count in sorted(ops.items()):
                unit_cost = quota.QUOTA_COSTS.get(op, 50)
                total_cost = int(count) * unit_cost
                console.print(f"  {op}: {count} x {unit_cost} = {total_cost:,} units")

        warning = quota.get_tracker().check_and_warn()
        if warning:
            console.print()
            console.print(f"[yellow]{warning}[/yellow]")

        return None

    def projects(self) -> dict[str, Any] | None:
        """Show configured projects and quota status.

        Displays all configured GCP projects, their quota usage,
        and which project is currently active.

        Example:
            ytrix projects
            ytrix --json-output projects
        """
        config = load_config()
        manager = get_project_manager(config)

        summary = manager.status_summary()

        if self._json:
            return self._output({"projects": summary})

        console.print("[bold]Configured Projects[/bold]")
        console.print()

        # Group projects by quota_group
        groups: dict[str, list[dict[str, Any]]] = {}
        for proj in summary:
            group = str(proj.get("quota_group", "default"))
            if group not in groups:
                groups[group] = []
            groups[group].append(proj)

        for group_name, projects in sorted(groups.items()):
            console.print(f"[dim]── {group_name} ──[/dim]")
            for proj in projects:
                name = proj["name"]
                current = proj["current"]
                used = proj["quota_used"]
                remaining = proj["quota_remaining"]
                limit = proj["quota_limit"]
                exhausted = proj["is_exhausted"]
                env = proj.get("environment", "prod")

                # Active marker and status
                marker = "[green]→[/green] " if current else "  "
                active_tag = "[ACTIVE] " if current else ""
                status = "[red](exhausted)[/red]" if exhausted else ""
                env_tag = f"[dim][{env}][/dim] " if env != "prod" else ""

                console.print(f"{marker}[bold]{name}[/bold] {active_tag}{env_tag}{status}")

                # Quota bar visualization
                pct = (used / limit * 100) if limit > 0 else 0
                if pct >= 90:
                    bar_color = "red"
                elif pct >= 70:
                    bar_color = "yellow"
                else:
                    bar_color = "green"
                console.print(
                    f"    Quota: [{bar_color}]{used:,}[/{bar_color}] / {limit:,} "
                    f"({remaining:,} remaining)"
                )
            console.print()

        # Footer with time until reset
        reset_time = quota.get_time_until_reset()
        console.print(f"[dim]Quota resets in {reset_time} (midnight PT)[/dim]")
        console.print(
            "[dim]Request increase: https://support.google.com/youtube/contact/yt_api_form[/dim]"
        )

        return None

    def projects_auth(self, name: str | None = None) -> dict[str, Any] | None:
        """Authenticate a project (triggers OAuth flow if needed).

        Args:
            name: Project name to authenticate (default: current project)

        Example:
            ytrix projects_auth           # Auth current project
            ytrix projects_auth backup    # Auth specific project
        """
        config = load_config()
        manager = get_project_manager(config)

        if name:
            manager.select_project(name)

        project = manager.current_project

        if not self._json:
            console.print(f"[blue]Authenticating project '{project.name}'...[/blue]")

        try:
            manager.get_credentials()

            if self._json:
                return self._output(
                    {
                        "project": project.name,
                        "authenticated": True,
                    }
                )

            console.print(f"[green]Project '{project.name}' authenticated successfully[/green]")

        except Exception as e:
            if self._json:
                return self._output(
                    {
                        "project": project.name,
                        "authenticated": False,
                        "error": str(e),
                    }
                )
            console.print(f"[red]Authentication failed: {e}[/red]")

        return None

    def projects_select(self, name: str) -> dict[str, Any] | None:
        """Select a project as the active project.

        Args:
            name: Project name to select

        Example:
            ytrix projects_select backup
        """
        config = load_config()
        manager = get_project_manager(config)

        try:
            manager.select_project(name)

            if self._json:
                return self._output(
                    {
                        "selected": name,
                        "success": True,
                    }
                )

            console.print(f"[green]Selected project '{name}'[/green]")

        except ValueError as e:
            if self._json:
                return self._output(
                    {
                        "selected": name,
                        "success": False,
                        "error": str(e),
                    }
                )
            console.print(f"[red]{e}[/red]")

        return None

    def gcp_clone(
        self,
        source_project: str,
        suffix: str,
        dry_run: bool = False,
        skip_labels: bool = False,
        skip_service_accounts: bool = False,
    ) -> dict[str, Any] | None:
        """Clone a Google Cloud project for YouTube API quota expansion.

        Creates a new GCP project based on the source project, copying IAM policies,
        enabled services, billing configuration, and custom service accounts.

        Requires gcloud CLI installed and authenticated.

        Args:
            source_project: Source GCP project ID to clone
            suffix: Suffix for new project (creates {source}-{suffix})
            dry_run: Show what would be done without making changes
            skip_labels: Skip copying project labels
            skip_service_accounts: Skip cloning service accounts

        Example:
            ytrix gcp_clone my-youtube-project 2 --dry-run
            ytrix gcp_clone ytrix-main backup
        """
        from ytrix import gcptrix

        # Set output modes
        if self._verbose:
            gcptrix.set_verbose(True)

        new_project_id = f"{source_project}-{suffix}"

        if self._json:
            gcptrix.set_quiet(True)

        console.print("[bold]Cloning GCP project[/bold]")
        console.print(f"  Source: {source_project}")
        console.print(f"  Target: {new_project_id}")
        if dry_run:
            console.print("  [yellow]DRY RUN - no changes will be made[/yellow]")

        # Check gcloud CLI
        if not gcptrix.check_gcloud_installed():
            msg = "gcloud CLI not found. Install from https://cloud.google.com/sdk/docs/install"
            if self._json:
                return self._output({"success": False, "error": msg})
            console.print(f"[red]{msg}[/red]")
            return None

        # Check authentication
        try:
            auth_info = gcptrix.check_authentication()
            console.print(f"  Authenticated as: {auth_info['account']}")
        except gcptrix.AuthenticationError as e:
            if self._json:
                return self._output({"success": False, "error": str(e)})
            console.print(f"[red]{e}[/red]")
            console.print("Run 'gcloud auth login' to authenticate")
            return None

        # Check source project access
        if not gcptrix.check_project_permissions(source_project, dry_run):
            msg = f"Cannot access project: {source_project}"
            if self._json:
                return self._output({"success": False, "error": msg})
            console.print(f"[red]{msg}[/red]")
            return None

        # Check if target exists
        if gcptrix.project_exists(new_project_id, dry_run):
            msg = f"Project already exists: {new_project_id}"
            if self._json:
                return self._output({"success": False, "error": msg})
            console.print(f"[red]{msg}[/red]")
            return None

        # Get source project info
        try:
            project_info = gcptrix.get_project_info(source_project, dry_run)
            parent = project_info.get("parent")
        except gcptrix.GcloudError as e:
            if self._json:
                return self._output({"success": False, "error": str(e)})
            console.print(f"[red]Failed to get project info: {e}[/red]")
            return None

        # Create project
        try:
            gcptrix.create_project(new_project_id, parent, dry_run)
            if not dry_run:
                console.print(f"[green]Created project: {new_project_id}[/green]")
        except gcptrix.GcloudError as e:
            if self._json:
                return self._output({"success": False, "error": str(e)})
            console.print(f"[red]Failed to create project: {e}[/red]")
            return None

        # Copy labels
        if not skip_labels:
            try:
                labels = gcptrix.get_project_labels(source_project, dry_run)
                if labels:
                    gcptrix.set_project_labels(new_project_id, labels, dry_run)
                    if not dry_run:
                        console.print(f"  Copied {len(labels)} labels")
            except gcptrix.GcloudError as e:
                console.print(f"[yellow]Warning: Could not copy labels: {e}[/yellow]")

        # Configure billing
        try:
            billing_info = gcptrix.get_billing_info(source_project, dry_run)
            if billing_info.get("billingEnabled"):
                billing_account = billing_info.get("billingAccountName", "").split("/")[-1]
                if billing_account:
                    gcptrix.link_billing(new_project_id, billing_account, dry_run)
                    if not dry_run:
                        console.print(f"  Linked billing account: {billing_account}")
        except gcptrix.GcloudError as e:
            console.print(f"[yellow]Warning: Could not configure billing: {e}[/yellow]")

        # Enable services
        try:
            services = gcptrix.get_enabled_services(source_project, dry_run)
            if services and not dry_run:
                console.print(f"  Enabling {len(services)} services...")
                for svc in services:
                    with contextlib.suppress(gcptrix.GcloudError):
                        gcptrix.enable_service(new_project_id, svc, dry_run)
                console.print("  [green]Services enabled[/green]")
        except gcptrix.GcloudError as e:
            console.print(f"[yellow]Warning: Could not enable services: {e}[/yellow]")

        # Clone service accounts
        if not skip_service_accounts:
            try:
                sas = gcptrix.get_service_accounts(source_project, dry_run)
                default_patterns = ["-compute@", "@cloudservices", "@cloudbuild", "@appspot"]
                custom_sas = [
                    sa
                    for sa in sas
                    if sa.get("email", "").endswith(".iam.gserviceaccount.com")
                    and not any(p in sa.get("email", "") for p in default_patterns)
                ]
                if custom_sas and not dry_run:
                    for sa in custom_sas:
                        email = sa.get("email", "")
                        account_id = email.split("@")[0]
                        display_name = sa.get("displayName", account_id)
                        with contextlib.suppress(gcptrix.GcloudError):
                            gcptrix.create_service_account(
                                new_project_id, account_id, display_name, dry_run
                            )
                    console.print(f"  Created {len(custom_sas)} service accounts")
            except gcptrix.GcloudError as e:
                console.print(f"[yellow]Warning: Could not clone SAs: {e}[/yellow]")

        if self._json:
            return self._output(
                {
                    "success": True,
                    "source_project": source_project,
                    "new_project": new_project_id,
                    "dry_run": dry_run,
                }
            )

        console.print(f"\n[green]Clone complete: {new_project_id}[/green]")
        console.print(
            f"Console: https://console.cloud.google.com/home/dashboard?project={new_project_id}"
        )
        console.print("\n[yellow]Manual steps required:[/yellow]")
        console.print("  - Create OAuth credentials in the new project")
        console.print("  - Add new project to ~/.ytrix/config.toml [[projects]] section")
        console.print("  - Run 'ytrix projects_auth <name>' to authenticate")

        return None

    def gcp_inventory(self, project_id: str) -> dict[str, Any] | None:
        """Show inventory of resources in a GCP project.

        Displays project info, labels, billing, service accounts, and enabled services.
        Useful for understanding what a project contains before cloning.

        Requires gcloud CLI installed and authenticated.

        Args:
            project_id: GCP project ID to inspect

        Example:
            ytrix gcp_inventory my-youtube-project
        """
        from ytrix import gcptrix

        if self._verbose:
            gcptrix.set_verbose(True)

        # Check gcloud CLI
        if not gcptrix.check_gcloud_installed():
            msg = "gcloud CLI not found. Install from https://cloud.google.com/sdk/docs/install"
            if self._json:
                return self._output({"success": False, "error": msg})
            console.print(f"[red]{msg}[/red]")
            return None

        # Check authentication
        try:
            auth_info = gcptrix.check_authentication()
        except gcptrix.AuthenticationError as e:
            if self._json:
                return self._output({"success": False, "error": str(e)})
            console.print(f"[red]{e}[/red]")
            return None

        # Check project access
        if not gcptrix.check_project_permissions(project_id):
            msg = f"Cannot access project: {project_id}"
            if self._json:
                return self._output({"success": False, "error": msg})
            console.print(f"[red]{msg}[/red]")
            return None

        # Gather inventory data
        inventory: dict[str, Any] = {"project_id": project_id}

        try:
            info = gcptrix.get_project_info(project_id)
            inventory["project_number"] = info.get("projectNumber")
            inventory["name"] = info.get("name")
            inventory["parent"] = info.get("parent")
        except gcptrix.GcloudError:
            pass

        try:
            inventory["labels"] = gcptrix.get_project_labels(project_id)
        except gcptrix.GcloudError:
            inventory["labels"] = {}

        try:
            billing = gcptrix.get_billing_info(project_id)
            inventory["billing_enabled"] = billing.get("billingEnabled", False)
            inventory["billing_account"] = billing.get("billingAccountName", "").split("/")[-1]
        except gcptrix.GcloudError:
            inventory["billing_enabled"] = False

        try:
            sas = gcptrix.get_service_accounts(project_id)
            inventory["service_accounts"] = [sa.get("email") for sa in sas]
        except gcptrix.GcloudError:
            inventory["service_accounts"] = []

        try:
            inventory["enabled_services"] = gcptrix.get_enabled_services(project_id)
        except gcptrix.GcloudError:
            inventory["enabled_services"] = []

        if self._json:
            return self._output({"success": True, **inventory})

        # Display inventory
        console.print(f"\n[bold]Project Inventory: {project_id}[/bold]")
        console.print(f"  Authenticated as: {auth_info['account']}")
        console.print()
        console.print("[bold]Project Info[/bold]")
        console.print(f"  ID:     {project_id}")
        console.print(f"  Number: {inventory.get('project_number', 'N/A')}")
        console.print(f"  Name:   {inventory.get('name', 'N/A')}")
        parent = inventory.get("parent")
        if parent:
            console.print(f"  Parent: {parent.get('type')} ({parent.get('id')})")

        console.print()
        console.print("[bold]Labels[/bold]")
        labels = inventory.get("labels", {})
        if labels:
            for k, v in labels.items():
                console.print(f"  {k}: {v}")
        else:
            console.print("  (none)")

        console.print()
        console.print("[bold]Billing[/bold]")
        if inventory.get("billing_enabled"):
            console.print(f"  Account: {inventory.get('billing_account')}")
        else:
            console.print("  Not enabled")

        console.print()
        console.print("[bold]Service Accounts[/bold]")
        sas = inventory.get("service_accounts", [])
        if sas:
            for sa in sas:
                console.print(f"  {sa}")
        else:
            console.print("  (none)")

        console.print()
        console.print("[bold]Enabled Services[/bold]")
        services = inventory.get("enabled_services", [])
        if services:
            for svc in sorted(services):
                console.print(f"  {svc}")
            console.print(f"  Total: {len(services)}")
        else:
            console.print("  (none)")

        return None

    def gcp_init(
        self,
        project_id: str,
        billing_account: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any] | None:
        """Create a new GCP project from scratch with YouTube API enabled.

        Creates a fresh GCP project (not cloning from an existing one), enables
        the YouTube Data API v3, and optionally links a billing account.

        Requires gcloud CLI installed and authenticated.

        Args:
            project_id: Unique project ID (e.g., 'my-ytrix-project')
            billing_account: Optional billing account ID to link
            dry_run: Show what would be done without making changes

        Example:
            ytrix gcp_init my-ytrix-project --dry-run
            ytrix gcp_init my-ytrix-project
            ytrix gcp_init my-ytrix-project --billing-account 012345-6789AB-CDEF01
        """
        from ytrix import gcptrix

        if self._verbose:
            gcptrix.set_verbose(True)

        if self._json:
            gcptrix.set_quiet(True)

        # Check gcloud CLI
        if not gcptrix.check_gcloud_installed():
            msg = "gcloud CLI not found. Install from https://cloud.google.com/sdk/docs/install"
            if self._json:
                return self._output({"success": False, "error": msg})
            console.print(f"[red]{msg}[/red]")
            return None

        # Check authentication
        try:
            auth_info = gcptrix.check_authentication()
            if not self._json:
                console.print(f"[blue]Authenticated as: {auth_info['account']}[/blue]")
        except gcptrix.AuthenticationError as e:
            if self._json:
                return self._output({"success": False, "error": str(e)})
            console.print(f"[red]{e}[/red]")
            console.print("Run 'gcloud auth login' to authenticate")
            return None

        # Check if project already exists
        if gcptrix.project_exists(project_id, dry_run):
            msg = f"Project already exists: {project_id}"
            if self._json:
                return self._output({"success": False, "error": msg})
            console.print(f"[red]{msg}[/red]")
            return None

        if not self._json:
            console.print(f"[bold]Creating GCP project: {project_id}[/bold]")
            if dry_run:
                console.print("  [yellow]DRY RUN - no changes will be made[/yellow]")

        # Create project
        try:
            gcptrix.create_project(project_id, parent=None, dry_run=dry_run)
            if not dry_run and not self._json:
                console.print(f"[green]Created project: {project_id}[/green]")
        except gcptrix.GcloudError as e:
            if self._json:
                return self._output({"success": False, "error": str(e)})
            console.print(f"[red]Failed to create project: {e}[/red]")
            return None

        # Link billing if provided
        if billing_account:
            try:
                gcptrix.link_billing(project_id, billing_account, dry_run)
                if not dry_run and not self._json:
                    console.print(f"  Linked billing account: {billing_account}")
            except gcptrix.GcloudError as e:
                if not self._json:
                    console.print(f"[yellow]Warning: Could not link billing: {e}[/yellow]")

        # Enable YouTube API
        try:
            gcptrix.enable_service(project_id, "youtube.googleapis.com", dry_run)
            if not dry_run and not self._json:
                console.print("  [green]YouTube Data API v3 enabled[/green]")
        except gcptrix.GcloudError as e:
            if not self._json:
                console.print(f"[yellow]Warning: Could not enable YouTube API: {e}[/yellow]")

        if self._json:
            return self._output(
                {
                    "success": True,
                    "project_id": project_id,
                    "dry_run": dry_run,
                    "billing_linked": billing_account is not None,
                }
            )

        if not dry_run:
            console.print(f"\n[green]Project created: {project_id}[/green]")
            console.print(
                f"Console: https://console.cloud.google.com/home/dashboard?project={project_id}"
            )

        console.print("\n[yellow]Next steps:[/yellow]")
        console.print(f"  Run: ytrix gcp_guide {project_id}")
        console.print("  to see OAuth setup instructions")

        return None

    def gcp_guide(self, project_id: str) -> dict[str, Any] | None:
        """Show OAuth setup guide for a GCP project.

        Prints step-by-step instructions for configuring OAuth consent screen,
        creating credentials, and adding the project to ytrix config.

        Args:
            project_id: GCP project ID to show guide for

        Example:
            ytrix gcp_guide my-ytrix-project
            ytrix gcp_guide fontlabtv-c1
        """
        from ytrix import gcptrix

        guide = gcptrix.get_oauth_guide(project_id)

        if self._json:
            return self._output(
                {
                    "project_id": project_id,
                    "consent_url": f"https://console.cloud.google.com/apis/credentials/consent?project={project_id}",
                    "credentials_url": f"https://console.cloud.google.com/apis/credentials?project={project_id}",
                    "guide": guide,
                }
            )

        print(guide)
        return None

    def projects_add(self, name: str) -> dict[str, Any] | None:
        """Add a new GCP project to ytrix configuration.

        Guides through adding a new project by prompting for OAuth client ID
        and client secret. After adding, run 'projects_auth <name>' to authenticate.

        Args:
            name: Name for the new project (used in config)

        Example:
            ytrix projects_add backup
            ytrix projects_add secondary
        """
        import tomllib

        config_dir = get_config_dir()
        config_file = config_dir / "config.toml"

        # Check if config exists
        if not config_file.exists():
            msg = f"Config file not found: {config_file}"
            if self._json:
                return self._output({"success": False, "error": msg})
            console.print(f"[red]{msg}[/red]")
            console.print("Run a command first to create the default config")
            return None

        # Load existing config
        with open(config_file, "rb") as f:
            config_data = tomllib.load(f)

        # Check if project name already exists
        existing_projects = config_data.get("projects", [])
        for proj in existing_projects:
            if proj.get("name") == name:
                msg = f"Project '{name}' already exists in config"
                if self._json:
                    return self._output({"success": False, "error": msg})
                console.print(f"[red]{msg}[/red]")
                return None

        console.print(f"[bold]Adding new project: {name}[/bold]")
        console.print()
        console.print("You need OAuth credentials from Google Cloud Console:")
        console.print("  1. Go to https://console.cloud.google.com/apis/credentials")
        console.print("  2. Create or select an OAuth 2.0 Client ID (Desktop app)")
        console.print("  3. Copy the Client ID and Client Secret")
        console.print()

        # Prompt for credentials
        try:
            client_id = input("Client ID: ").strip()
            if not client_id:
                msg = "Client ID is required"
                if self._json:
                    return self._output({"success": False, "error": msg})
                console.print(f"[red]{msg}[/red]")
                return None

            client_secret = input("Client Secret: ").strip()
            if not client_secret:
                msg = "Client Secret is required"
                if self._json:
                    return self._output({"success": False, "error": msg})
                console.print(f"[red]{msg}[/red]")
                return None
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Cancelled[/yellow]")
            return None

        # Prompt for quota_group (ToS compliance)
        console.print()
        console.print("[bold]Quota Group Configuration[/bold]")
        console.print(
            "[dim]Projects in the same quota_group can switch automatically "
            "on quota exhaustion.[/dim]"
        )
        console.print(
            "[dim]Use different groups for different purposes (e.g., personal, client-a).[/dim]"
        )
        console.print()

        try:
            quota_group = input("Quota group [default]: ").strip() or "default"
            environment = input("Environment (dev/staging/prod) [prod]: ").strip() or "prod"
            priority_str = input("Priority (lower = higher priority) [0]: ").strip() or "0"
            try:
                priority = int(priority_str)
                if priority < 0:
                    priority = 0
            except ValueError:
                priority = 0
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Cancelled[/yellow]")
            return None

        # Validate: warn if too many projects in same quota_group
        projects_in_group = [
            p for p in existing_projects if p.get("quota_group", "default") == quota_group
        ]
        if len(projects_in_group) >= 5:
            console.print()
            console.print(
                f"[yellow]Warning: You already have {len(projects_in_group)} projects "
                f"in quota_group '{quota_group}'.[/yellow]"
            )
            console.print(
                "[yellow]Having many projects in the same group may violate Google's ToS "
                "if used to circumvent quota limits.[/yellow]"
            )
            console.print(
                "[dim]Consider using different quota_groups for truly different purposes.[/dim]"
            )
            console.print()
            try:
                confirm = input("Continue anyway? [y/N]: ").strip().lower()
                if confirm not in ("y", "yes"):
                    console.print("[yellow]Cancelled[/yellow]")
                    return None
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Cancelled[/yellow]")
                return None

        # Validate environment
        if environment not in ("dev", "staging", "prod"):
            console.print(f"[yellow]Invalid environment '{environment}', using 'prod'[/yellow]")
            environment = "prod"

        # Read current config as text to preserve formatting
        config_text = config_file.read_text()

        # Build new project entry
        new_project = f'''
[[projects]]
name = "{name}"
client_id = "{client_id}"
client_secret = "{client_secret}"
quota_group = "{quota_group}"
environment = "{environment}"
priority = {priority}
'''

        # Append to config
        config_file.write_text(config_text.rstrip() + "\n" + new_project)

        if self._json:
            return self._output(
                {
                    "success": True,
                    "name": name,
                    "quota_group": quota_group,
                    "environment": environment,
                    "priority": priority,
                    "message": f"Project '{name}' added. Run 'ytrix projects_auth {name}'.",
                }
            )

        console.print(f"\n[green]Project '{name}' added to config[/green]")
        console.print(f"  Quota group: {quota_group}")
        console.print(f"  Environment: {environment}")
        console.print(f"  Priority: {priority}")
        console.print(f"\nNext step: ytrix projects_auth {name}")

        return None

    def journal_status(
        self, clear: bool = False, pending_only: bool = False
    ) -> dict[str, Any] | None:
        """Show batch operation journal status.

        Displays the current batch operation journal, including task counts by status
        and details of incomplete tasks. Use --clear to delete the journal.

        Args:
            clear: Delete the journal file
            pending_only: Show only pending and failed tasks (tasks that need work)

        Example:
            ytrix journal_status               # Show journal status
            ytrix journal_status --clear       # Clear the journal
            ytrix journal_status --pending-only # Show only incomplete tasks
            ytrix --json-output journal_status
        """
        if clear:
            clear_journal()
            msg = "Journal cleared"
            if self._json:
                return self._output({"cleared": True})
            console.print(f"[green]{msg}[/green]")
            return None

        journal = load_journal()
        if journal is None:
            if self._json:
                return self._output({"exists": False})
            console.print("[yellow]No journal found[/yellow]")
            return None

        summary = get_journal_summary(journal)

        # Filter tasks if pending_only
        if pending_only:
            filtered_tasks = [
                t
                for t in journal.tasks
                if t.status in (TaskStatus.PENDING, TaskStatus.FAILED, TaskStatus.IN_PROGRESS)
            ]
        else:
            filtered_tasks = journal.tasks

        if self._json:
            tasks_data = [t.to_dict() for t in filtered_tasks]
            return self._output(
                {
                    "batch_id": journal.batch_id,
                    "created_at": journal.created_at,
                    "summary": summary,
                    "tasks": tasks_data,
                    "pending_only": pending_only,
                }
            )

        console.print(f"[bold]Batch:[/bold] {journal.batch_id}")
        console.print(f"[bold]Created:[/bold] {journal.created_at}")
        console.print()
        console.print("[bold]Summary:[/bold]")
        console.print(f"  Total: {summary['total']}")
        console.print(f"  [green]Completed: {summary['completed']}[/green]")
        console.print(f"  [blue]Skipped: {summary['skipped']}[/blue]")
        console.print(f"  [yellow]Pending: {summary['pending']}[/yellow]")
        console.print(f"  [red]Failed: {summary['failed']}[/red]")

        # Show failed tasks with errors
        failed = [t for t in filtered_tasks if t.status == TaskStatus.FAILED]
        if failed:
            console.print()
            console.print("[bold red]Failed tasks:[/bold red]")
            for t in failed:
                console.print(f"  {t.source_title}")
                console.print(f"    [dim]Error: {t.error}[/dim]")
                console.print(f"    [dim]Retries: {t.retry_count}[/dim]")

        # Show pending tasks if pending_only
        if pending_only:
            pending = [t for t in filtered_tasks if t.status == TaskStatus.PENDING]
            if pending:
                console.print()
                console.print("[bold yellow]Pending tasks:[/bold yellow]")
                for t in pending:
                    console.print(f"  {t.source_title}")

        return None

    def ls(
        self, count: bool = False, user: str | None = None, urls: bool = False
    ) -> dict[str, Any] | None:
        """List playlists.

        Args:
            count: Show video count for each playlist (slower, requires extra API calls)
            user: Channel URL, @handle, or channel ID to list playlists from (uses yt-dlp)
            urls: Output only playlist URLs, one per line (for piping to plists2mlist)

        Example:
            ytrix ls                          # List your playlists
            ytrix ls --count                  # Include video counts
            ytrix ls --user @fontlabtv        # List another channel's playlists
            ytrix ls --user @fontlabtv --urls # URLs only, pipe to file
            ytrix --json-output ls
        """
        # List another user's playlists via yt-dlp
        if user:
            if not self._json and not urls:
                console.print(f"[blue]Fetching playlists from {user}...[/blue]")

            playlists = extractor.extract_channel_playlists(user)

            # URLs-only output for piping to plists2mlist
            if urls:
                for p in playlists:
                    print(f"https://youtube.com/playlist?list={p.id}")
                return None

            # Fetch video counts if requested (uses yt-dlp, no API quota)
            video_counts: dict[str, int] = {}
            if count and playlists:
                if not self._json:
                    console.print("[blue]Fetching video counts...[/blue]")
                for p in playlists:
                    video_counts[p.id] = extractor.get_video_count(p.id)

            if self._json:
                playlist_data = []
                for p in playlists:
                    entry: dict[str, Any] = {"id": p.id, "title": p.title, "privacy": p.privacy}
                    if count:
                        entry["video_count"] = video_counts.get(p.id, 0)
                    playlist_data.append(entry)
                return self._output({"count": len(playlists), "playlists": playlist_data})

            if not playlists:
                console.print("[yellow]No playlists found[/yellow]")
                return None

            console.print(f"Found {len(playlists)} playlists:\n")
            for p in playlists:
                count_tag = f" ({video_counts[p.id]} videos)" if count else ""
                console.print(f"  {p.title}{count_tag}")
                console.print(f"    [dim]https://youtube.com/playlist?list={p.id}[/dim]")
            return None

        # List own playlists via YouTube API
        config = load_config()
        client = self._get_youtube_client(config)

        if not self._json and not urls:
            console.print("[blue]Fetching playlists...[/blue]")

        playlists = api.list_my_playlists(client, config.channel_id)

        # URLs-only output for piping to plists2mlist
        if urls:
            for p in playlists:
                print(f"https://youtube.com/playlist?list={p.id}")
            return None

        # Fetch video counts if requested (uses yt-dlp to avoid API quota)
        my_video_counts: dict[str, int] = {}
        if count and playlists:
            if not self._json:
                console.print("[blue]Fetching video counts...[/blue]")
            for p in playlists:
                try:
                    # Try yt-dlp first (no API quota)
                    my_video_counts[p.id] = extractor.get_video_count(p.id)
                except Exception:
                    # Fall back to API for private playlists
                    videos = api.get_playlist_videos(client, p.id)
                    my_video_counts[p.id] = len(videos)

        if self._json:
            playlist_data = []
            for p in playlists:
                pl_entry: dict[str, Any] = {"id": p.id, "title": p.title, "privacy": p.privacy}
                if count:
                    pl_entry["video_count"] = my_video_counts.get(p.id, 0)
                playlist_data.append(pl_entry)
            return self._output({"count": len(playlists), "playlists": playlist_data})

        if not playlists:
            console.print("[yellow]No playlists found[/yellow]")
            return None

        console.print(f"Found {len(playlists)} playlists:\n")
        for p in playlists:
            privacy_tag = f" \\[{p.privacy}]" if p.privacy != "public" else ""
            count_tag = f" ({my_video_counts[p.id]} videos)" if count else ""
            console.print(f"  {p.title}{privacy_tag}{count_tag}")
            console.print(f"    [dim]https://youtube.com/playlist?list={p.id}[/dim]")

        return None

    def plist2mlist(
        self,
        url_or_id: str,
        dry_run: bool = False,
        dedup: bool = True,
        title: str | None = None,
        privacy: str = "public",
    ) -> str | dict[str, Any] | None:
        """Copy external playlist to your channel.

        Args:
            url_or_id: Playlist URL or ID to copy
            dry_run: Show what would be created without making changes
            dedup: Check for existing duplicates before creating (default: True)
            title: Custom title for the new playlist (default: use source title)
            privacy: Privacy setting: public, unlisted, or private (default: public)

        Example:
            ytrix plist2mlist "https://youtube.com/playlist?list=PLxxx"
            ytrix plist2mlist PLxxx --dry-run
            ytrix plist2mlist PLxxx --no-dedup
            ytrix plist2mlist PLxxx --title "My Copy"
            ytrix plist2mlist PLxxx --privacy unlisted
        """
        if privacy not in ("public", "unlisted", "private"):
            raise ValueError("--privacy must be 'public', 'unlisted', or 'private'")
        from ytrix.dedup import MatchType, find_matching_playlist

        logger.debug("plist2mlist called with url_or_id={}, dedup={}", url_or_id, dedup)

        if not self._json:
            console.print("[blue]Extracting playlist...[/blue]")
        source = extractor.extract_playlist(url_or_id)
        logger.debug("Extracted playlist: {} with {} videos", source.title, len(source.videos))

        if not self._json:
            console.print(f"Found: {source.title} ({len(source.videos)} videos)")

        config = load_config()

        # Deduplication check
        match_result = None
        if dedup and not dry_run:
            if not self._json:
                console.print("[blue]Checking for duplicates...[/blue]")
            target_playlists = load_target_playlists_with_videos(config.channel_id)
            if target_playlists:
                match_result = find_matching_playlist(source, target_playlists)

                if match_result.match_type == MatchType.EXACT:
                    target = match_result.target_playlist
                    assert target is not None  # guaranteed by EXACT match
                    url = f"https://www.youtube.com/playlist?list={target.id}"
                    if not self._json:
                        console.print(f"[green]Exact match found: {target.title}[/green]")
                        console.print(f"[green]Skipping - existing playlist: {url}[/green]")
                        return url
                    return self._output(
                        {
                            "action": "skipped",
                            "reason": "exact_match",
                            "existing_playlist_id": target.id,
                            "existing_playlist_title": target.title,
                            "url": url,
                        }
                    )

                if match_result.match_type == MatchType.PARTIAL:
                    target = match_result.target_playlist
                    assert target is not None  # guaranteed by PARTIAL match
                    missing = match_result.missing_videos or []
                    if not self._json:
                        pct = match_result.overlap_percent * 100
                        msg = f"[yellow]Partial match ({pct:.0f}%): {target.title}[/yellow]"
                        console.print(msg)
                        console.print(f"[yellow]Adding {len(missing)} missing videos...[/yellow]")

        # Pre-flight quota check
        num_videos = len(source.videos)
        if match_result and match_result.match_type == MatchType.PARTIAL:
            # Only adding missing videos
            num_videos = len(match_result.missing_videos or [])
            estimate = estimate_copy_cost(num_videos, create_playlist=False)
        else:
            estimate = estimate_copy_cost(num_videos, create_playlist=True)

        can_afford, quota_msg = can_afford_operation(estimate)
        if not can_afford and not dry_run:
            if not self._json:
                console.print(f"[red]{quota_msg}[/red]")
            raise ValueError(quota_msg)

        if dry_run:
            playlist_title = title or source.title
            result: dict[str, Any] = {
                "dry_run": True,
                "title": playlist_title,
                "privacy": privacy,
                "description": source.description,
                "video_count": len(source.videos),
                "videos": [{"id": v.id, "title": v.title} for v in source.videos],
                "quota_estimate": estimate.breakdown(),
            }
            if match_result:
                result["dedup"] = {
                    "match_type": match_result.match_type.value,
                    "overlap_percent": match_result.overlap_percent,
                }
                if match_result.target_playlist:
                    result["dedup"]["target_playlist_id"] = match_result.target_playlist.id
            if self._json:
                return self._output(result)
            console.print("[yellow]Dry run - would create:[/yellow]")
            console.print(f"  Title: {playlist_title}")
            console.print(f"  Privacy: {privacy}")
            console.print(f"  Videos: {len(source.videos)}")
            for v in source.videos[:5]:
                console.print(f"    - {v.title[:50]}")
            if len(source.videos) > 5:
                console.print(f"    ... and {len(source.videos) - 5} more")
            return None

        client = self._get_youtube_client(config)

        # Handle partial match - add missing videos to existing playlist
        if match_result and match_result.match_type == MatchType.PARTIAL:
            target = match_result.target_playlist
            assert target is not None  # guaranteed by PARTIAL match
            missing_ids = set(match_result.missing_videos or [])
            videos_to_add = [v for v in source.videos if v.id in missing_ids]

            added = 0
            skipped = []
            if self._json:
                for video in videos_to_add:
                    try:
                        api.add_video_to_playlist(client, target.id, video.id)
                        added += 1
                    except Exception as e:
                        skipped.append({"id": video.id, "error": str(e)})
            else:
                with Progress(console=console) as progress:
                    task = progress.add_task("Adding videos...", total=len(videos_to_add))
                    for video in videos_to_add:
                        try:
                            api.add_video_to_playlist(client, target.id, video.id)
                            added += 1
                        except Exception as e:
                            skipped.append({"id": video.id, "error": str(e)})
                            console.print(f"[yellow]Skipped {video.id}: {e}[/yellow]")
                        progress.advance(task)

            url = f"https://www.youtube.com/playlist?list={target.id}"
            if not self._json:
                console.print(f"[green]Updated: {url}[/green]")
                return url

            return self._output(
                {
                    "action": "updated",
                    "playlist_id": target.id,
                    "url": url,
                    "title": target.title,
                    "videos_added": added,
                    "videos_skipped": skipped,
                }
            )

        # No match - create new playlist
        playlist_title = title or source.title
        if not self._json:
            console.print("[blue]Creating playlist on your channel...[/blue]")

        new_id = api.create_playlist(client, playlist_title, source.description, privacy)
        logger.debug("Created playlist with id={}", new_id)

        added = 0
        skipped = []
        if self._json:
            for video in source.videos:
                try:
                    api.add_video_to_playlist(client, new_id, video.id)
                    added += 1
                except Exception as e:
                    skipped.append({"id": video.id, "error": str(e)})
        else:
            with Progress(console=console) as progress:
                task = progress.add_task("Adding videos...", total=len(source.videos))
                for video in source.videos:
                    try:
                        api.add_video_to_playlist(client, new_id, video.id)
                        added += 1
                    except Exception as e:
                        skipped.append({"id": video.id, "error": str(e)})
                        console.print(f"[yellow]Skipped {video.id}: {e}[/yellow]")
                    progress.advance(task)

        url = f"https://www.youtube.com/playlist?list={new_id}"
        if not self._json:
            console.print(f"[green]Created: {url}[/green]")
            return url

        return self._output(
            {
                "playlist_id": new_id,
                "url": url,
                "title": playlist_title,
                "privacy": privacy,
                "videos_added": added,
                "videos_skipped": skipped,
            }
        )

    def plists2mlist(
        self,
        file_path: str,
        title: str | None = None,
        dry_run: bool = False,
        privacy: str = "public",
    ) -> str | dict[str, Any] | None:
        """Merge multiple playlists into one on your channel.

        Args:
            file_path: Text file with playlist URLs/IDs (one per line)
            title: Optional title for the merged playlist
            dry_run: Show what would be created without making changes
            privacy: Privacy setting: public, unlisted, or private (default: public)

        Example:
            ytrix plists2mlist playlists.txt
            ytrix plists2mlist playlists.txt --title "My Collection"
            ytrix plists2mlist playlists.txt --privacy unlisted
        """
        if privacy not in ("public", "unlisted", "private"):
            raise ValueError("--privacy must be 'public', 'unlisted', or 'private'")
        # Read playlist URLs/IDs from file
        lines = Path(file_path).read_text().strip().split("\n")
        lines = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
        if not lines:
            raise ValueError("No playlist URLs found in file")

        if not self._json:
            console.print(f"[blue]Processing {len(lines)} playlists...[/blue]")

        all_videos = []
        source_playlists = []
        for line in lines:
            try:
                playlist = extractor.extract_playlist(line)
                if not self._json:
                    console.print(f"  {playlist.title}: {len(playlist.videos)} videos")
                source_playlists.append(
                    {"title": playlist.title, "video_count": len(playlist.videos)}
                )
                all_videos.extend(playlist.videos)
            except Exception as e:
                if not self._json:
                    console.print(f"[yellow]Skipped {line}: {e}[/yellow]")

        if not all_videos:
            raise ValueError("No videos found in any playlist")

        # Detect duplicates
        seen_ids: set[str] = set()
        duplicates: list[str] = []
        unique_videos = []
        for video in all_videos:
            if video.id in seen_ids:
                duplicates.append(video.id)
            else:
                seen_ids.add(video.id)
                unique_videos.append(video)

        if duplicates and not self._json:
            console.print(f"[yellow]Found {len(duplicates)} duplicate videos (skipped)[/yellow]")

        playlist_title = title or f"Merged Playlist ({len(unique_videos)} videos)"

        if dry_run:
            if self._json:
                return self._output(
                    {
                        "dry_run": True,
                        "title": playlist_title,
                        "privacy": privacy,
                        "source_playlists": source_playlists,
                        "unique_videos": len(unique_videos),
                        "duplicates_skipped": len(duplicates),
                    }
                )
            console.print("[yellow]Dry run - would create:[/yellow]")
            console.print(f"  Title: {playlist_title}")
            console.print(f"  Privacy: {privacy}")
            console.print(f"  Unique videos: {len(unique_videos)}")
            if duplicates:
                console.print(f"  Duplicates skipped: {len(duplicates)}")
            console.print(f"  From {len(source_playlists)} playlists")
            return None

        config = load_config()
        client = self._get_youtube_client(config)

        if not self._json:
            console.print(f"[blue]Creating merged playlist: {playlist_title}[/blue]")
        new_id = api.create_playlist(client, playlist_title, privacy=privacy)

        added = 0
        if self._json:
            for video in unique_videos:
                try:
                    api.add_video_to_playlist(client, new_id, video.id)
                    added += 1
                except Exception:
                    pass
        else:
            with Progress(console=console) as progress:
                task = progress.add_task("Adding videos...", total=len(unique_videos))
                for video in unique_videos:
                    try:
                        api.add_video_to_playlist(client, new_id, video.id)
                        added += 1
                    except Exception as e:
                        console.print(f"[yellow]Skipped {video.id}: {e}[/yellow]")
                    progress.advance(task)

        url = f"https://www.youtube.com/playlist?list={new_id}"
        if not self._json:
            console.print(f"[green]Created: {url}[/green]")
            return url

        return self._output(
            {
                "playlist_id": new_id,
                "url": url,
                "title": playlist_title,
                "privacy": privacy,
                "videos_added": added,
                "duplicates_skipped": len(duplicates),
            }
        )

    def plist2mlists(
        self, url_or_id: str, by: str = "channel", dry_run: bool = False
    ) -> list[str] | dict[str, Any] | None:
        """Split playlist into sub-playlists by criterion.

        Args:
            url_or_id: Playlist URL or ID to split
            by: Criterion to split by ('channel' or 'year')
            dry_run: Show what would be created without making changes

        Example:
            ytrix plist2mlists PLxxx --by=channel
            ytrix plist2mlists PLxxx --by=year --dry-run
        """
        if by not in ("channel", "year"):
            raise ValueError("--by must be 'channel' or 'year'")

        if not self._json:
            console.print("[blue]Extracting playlist...[/blue]")
        source = extractor.extract_playlist(url_or_id)
        if not self._json:
            console.print(f"Found: {source.title} ({len(source.videos)} videos)")

        # Group videos by criterion
        groups: dict[str, list[Any]] = defaultdict(list)
        for video in source.videos:
            if by == "channel":
                key = video.channel or "Unknown Channel"
            else:  # year
                key = video.upload_date[:4] if video.upload_date else "Unknown Year"
            groups[key].append(video)

        # Preview mode
        if dry_run:
            planned = [
                {"title": f"{source.title} - {name}", "group": name, "video_count": len(vids)}
                for name, vids in groups.items()
            ]
            if self._json:
                return self._output(
                    {
                        "dry_run": True,
                        "source_title": source.title,
                        "split_by": by,
                        "playlists_planned": len(planned),
                        "playlists": planned,
                    }
                )
            console.print("[yellow]Dry run - would create:[/yellow]")
            for p in planned:
                console.print(f"  {p['title']}: {p['video_count']} videos")
            return None

        config = load_config()
        client = self._get_youtube_client(config)

        if not self._json:
            console.print(f"[blue]Creating {len(groups)} playlists...[/blue]")

        created_playlists: list[dict[str, Any]] = []

        for group_name, videos in groups.items():
            title = f"{source.title} - {group_name}"
            if not self._json:
                console.print(f"  {title}: {len(videos)} videos")

            new_id = api.create_playlist(client, title, source.description)

            added = 0
            for video in videos:
                try:
                    api.add_video_to_playlist(client, new_id, video.id)
                    added += 1
                except Exception as e:
                    if not self._json:
                        console.print(f"[yellow]Skipped {video.id}: {e}[/yellow]")

            url = f"https://www.youtube.com/playlist?list={new_id}"
            created_playlists.append(
                {
                    "playlist_id": new_id,
                    "url": url,
                    "title": title,
                    "group": group_name,
                    "videos_added": added,
                }
            )
            if not self._json:
                console.print(f"[green]Created: {url}[/green]")

        if self._json:
            return self._output(
                {
                    "source_title": source.title,
                    "split_by": by,
                    "playlists_created": len(created_playlists),
                    "playlists": created_playlists,
                }
            )

        return [p["url"] for p in created_playlists]

    def plists2mlists(
        self, file_path: str, dry_run: bool = False, resume: bool = False
    ) -> dict[str, Any] | None:
        """Batch copy playlists one-to-one with deduplication and journaling.

        Copies each source playlist to a separate playlist on your channel.
        Handles API quota limits gracefully - use --resume to continue after quota resets.

        Features:
            - Skips playlists that already exist with identical videos
            - Updates existing playlists if >75% videos match
            - Journals progress for resume across sessions
            - Retries failed operations with exponential backoff

        Args:
            file_path: Text file with playlist URLs/IDs (one per line)
            dry_run: Preview operations without making changes
            resume: Continue from previous journal (for quota limit recovery)

        Example:
            ytrix plists2mlists playlists.txt --dry-run
            ytrix plists2mlists playlists.txt
            ytrix plists2mlists playlists.txt --resume  # After quota resets
        """
        config = load_config()

        # Check for existing journal if resuming
        journal: Journal | None = None
        if resume:
            journal = load_journal()
            if journal:
                summary = get_journal_summary(journal)
                if not self._json:
                    console.print(f"[blue]Resuming batch: {journal.batch_id}[/blue]")
                    console.print(
                        f"  Completed: {summary['completed']}, "
                        f"Pending: {summary['pending']}, "
                        f"Failed: {summary['failed']}"
                    )
            else:
                if not self._json:
                    console.print("[yellow]No journal found, starting fresh[/yellow]")

        # Read source playlists from file if not resuming with existing journal
        if not journal:
            lines = Path(file_path).read_text().strip().split("\n")
            lines = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
            if not lines:
                raise ValueError("No playlist URLs found in file")

            if not self._json:
                console.print(f"[blue]Extracting {len(lines)} source playlists...[/blue]")

            source_playlists = []
            for line in lines:
                try:
                    playlist = extractor.extract_playlist(line)
                    source_playlists.append(playlist)
                    if not self._json:
                        console.print(f"  {playlist.title}: {len(playlist.videos)} videos")
                except Exception as e:
                    if not self._json:
                        console.print(f"[yellow]Skipped {line}: {e}[/yellow]")

            if not source_playlists:
                raise ValueError("No valid playlists found")

            # Create journal for new batch
            journal = create_journal([(p.id, p.title) for p in source_playlists])

            # Load target channel playlists for deduplication (uses yt-dlp, no quota)
            if not self._json:
                console.print("[blue]Loading target channel playlists for deduplication...[/blue]")
            target_playlists = load_target_playlists_with_videos(config.channel_id)

            # Analyze deduplication
            dedup_results = analyze_batch_deduplication(source_playlists, target_playlists)

            # Update journal with deduplication results
            for source in source_playlists:
                result = dedup_results.get(source.id)
                if result:
                    if result.match_type == MatchType.EXACT:
                        target_id = result.target_playlist.id if result.target_playlist else None
                        update_task(
                            journal,
                            source.id,
                            status=TaskStatus.SKIPPED,
                            match_type="exact",
                            match_playlist_id=target_id,
                        )
                    elif result.match_type == MatchType.PARTIAL:
                        target_id = result.target_playlist.id if result.target_playlist else None
                        update_task(
                            journal,
                            source.id,
                            match_type="partial",
                            match_playlist_id=target_id,
                        )
        else:
            # Resuming - reload source playlists for pending tasks
            source_playlists = []
            for task in get_pending_tasks(journal):
                try:
                    playlist = extractor.extract_playlist(task.source_playlist_id)
                    source_playlists.append(playlist)
                except Exception as e:
                    logger.warning("Failed to reload {}: {}", task.source_playlist_id, e)

        # Calculate quota estimate
        pending_tasks = get_pending_tasks(journal)
        pending_ids = {t.source_playlist_id for t in pending_tasks}
        total_videos = sum(len(p.videos) for p in source_playlists if p.id in pending_ids)
        estimate = QuotaEstimate(
            playlist_creates=len([t for t in pending_tasks if t.match_type != "partial"]),
            video_adds=total_videos,
            playlist_updates=len([t for t in pending_tasks if t.match_type == "partial"]),
        )

        # Pre-flight quota check
        can_afford, quota_msg = can_afford_operation(estimate)
        if not self._json:
            console.print()
            console.print(format_quota_warning(estimate))
            if not can_afford:
                console.print(f"[yellow]Warning: {quota_msg}[/yellow]")
            console.print()

        if dry_run:
            summary = get_journal_summary(journal)
            if self._json:
                return self._output(
                    {
                        "dry_run": True,
                        "batch_id": journal.batch_id,
                        "summary": summary,
                        "quota_estimate": estimate.breakdown(),
                        "tasks": [t.to_dict() for t in journal.tasks],
                    }
                )
            console.print("[yellow]Dry run - no changes made[/yellow]")
            console.print(f"  Would create: {summary['pending']} playlists")
            console.print(f"  Will skip: {summary['skipped']} (already exist)")
            return None

        # Execute batch operations
        client = self._get_youtube_client(config)
        source_by_id = {p.id: p for p in source_playlists}
        handler = BatchOperationHandler(max_consecutive_errors=3)

        for task in pending_tasks:
            source_playlist = source_by_id.get(task.source_playlist_id)
            if not source_playlist:
                continue

            update_task(journal, task.source_playlist_id, status=TaskStatus.IN_PROGRESS)

            try:
                if task.match_type == "partial" and task.match_playlist_id:
                    # Update existing playlist - add missing videos
                    if not self._json:
                        console.print(f"[blue]Updating: {source_playlist.title}[/blue]")
                    target_id = task.match_playlist_id
                    existing_ids = extractor.get_playlist_video_ids(target_id)
                    added = 0
                    for video in source_playlist.videos:
                        if video.id not in existing_ids:
                            try:
                                api.add_video_to_playlist(client, target_id, video.id)
                                added += 1
                            except Exception as e:
                                video_error = classify_error(e)
                                if video_error.category == api.ErrorCategory.QUOTA_EXCEEDED:
                                    raise  # Stop batch on quota exhaustion
                                logger.warning("Failed to add {}: {}", video.id, e)
                    update_task(
                        journal,
                        task.source_playlist_id,
                        status=TaskStatus.COMPLETED,
                        target_playlist_id=target_id,
                        videos_added=added,
                    )
                    handler.on_success()
                    if not self._json:
                        console.print(
                            f"[green]Updated: https://youtube.com/playlist?list={target_id} "
                            f"(+{added} videos)[/green]"
                        )
                else:
                    # Create new playlist
                    if not self._json:
                        console.print(f"[blue]Creating: {source_playlist.title}[/blue]")
                    new_id = api.create_playlist(
                        client, source_playlist.title, source_playlist.description
                    )

                    added = 0
                    with Progress(console=console, disable=self._json) as progress:
                        prog_task = progress.add_task(
                            "Adding videos...", total=len(source_playlist.videos)
                        )
                        for video in source_playlist.videos:
                            try:
                                api.add_video_to_playlist(client, new_id, video.id)
                                added += 1
                            except Exception as e:
                                video_error = classify_error(e)
                                if video_error.category == api.ErrorCategory.QUOTA_EXCEEDED:
                                    raise  # Stop batch on quota exhaustion
                                logger.warning("Failed to add {}: {}", video.id, e)
                            progress.advance(prog_task)

                    update_task(
                        journal,
                        task.source_playlist_id,
                        status=TaskStatus.COMPLETED,
                        target_playlist_id=new_id,
                        videos_added=added,
                    )
                    handler.on_success()
                    if not self._json:
                        console.print(
                            f"[green]Created: https://youtube.com/playlist?list={new_id}[/green]"
                        )

            except Exception as e:
                action = handler.handle_error(task.source_playlist_id, e)
                api_error = classify_error(e)
                update_task(
                    journal,
                    task.source_playlist_id,
                    status=TaskStatus.FAILED,
                    error=str(e),
                    error_category=api_error.category.name,
                    increment_retry=True,
                )
                if not self._json:
                    display_error(api_error)

                if action == BatchAction.STOP_ALL:
                    # Batch must stop - quota exhausted or too many errors
                    break

        # Final summary
        summary = get_journal_summary(journal)
        if summary["pending"] == 0 and summary["failed"] == 0:
            clear_journal()
            if not self._json:
                console.print("[green]Batch complete![/green]")
        else:
            if not self._json:
                console.print(
                    f"[yellow]Batch incomplete: {summary['pending']} pending, "
                    f"{summary['failed']} failed[/yellow]"
                )
                console.print("Use --resume to continue after quota resets at midnight PT")

        if self._json:
            return self._output(
                {
                    "batch_id": journal.batch_id,
                    "summary": summary,
                    "tasks": [t.to_dict() for t in journal.tasks],
                }
            )
        return None

    def mlists2yaml(
        self, output: str = "playlists.yaml", details: bool = False
    ) -> str | dict[str, Any] | None:
        """Export all your playlists to YAML.

        Args:
            output: Output file path
            details: Include video details in export

        Example:
            ytrix mlists2yaml
            ytrix mlists2yaml --output my_playlists.yaml --details
        """
        config = load_config()
        client = self._get_youtube_client(config)

        if not self._json:
            console.print("[blue]Fetching playlists...[/blue]")
        playlists = api.list_my_playlists(client, config.channel_id)
        if not self._json:
            console.print(f"Found {len(playlists)} playlists")

        if details:
            # Use yt-dlp to avoid API quota, fall back to API for private playlists
            if self._json:
                for playlist in playlists:
                    try:
                        extracted = extractor.extract_playlist(playlist.id)
                        playlist.videos = extracted.videos
                    except Exception:
                        playlist.videos = api.get_playlist_videos(client, playlist.id)
            else:
                with Progress(console=console) as progress:
                    task = progress.add_task("Fetching video details...", total=len(playlists))
                    for playlist in playlists:
                        try:
                            extracted = extractor.extract_playlist(playlist.id)
                            playlist.videos = extracted.videos
                        except Exception:
                            playlist.videos = api.get_playlist_videos(client, playlist.id)
                        progress.advance(task)

        # With --json-output, print JSON and skip file
        if self._json:
            return self._output(
                {
                    "playlists": [p.to_dict(include_videos=details) for p in playlists],
                    "count": len(playlists),
                }
            )

        yaml_ops.save_yaml(output, playlists, include_videos=details)
        console.print(f"[green]Saved to: {output}[/green]")
        return output

    def yaml2mlists(self, file_path: str, dry_run: bool = False) -> dict[str, Any] | None:
        """Apply YAML edits to your playlists.

        Args:
            file_path: YAML file with playlist data
            dry_run: Show changes without applying

        Example:
            ytrix yaml2mlists playlists.yaml --dry-run
            ytrix yaml2mlists playlists.yaml
        """
        config = load_config()
        client = self._get_youtube_client(config)

        new_playlists = yaml_ops.load_yaml(file_path)
        if not self._json:
            console.print(f"[blue]Processing {len(new_playlists)} playlists...[/blue]")

        results: list[dict[str, Any]] = []

        for new_pl in new_playlists:
            try:
                # Get current state
                current = api.get_playlist_with_videos(client, new_pl.id)
                changes = yaml_ops.diff_playlists(current, new_pl)

                result: dict[str, Any] = {
                    "playlist_id": new_pl.id,
                    "title": new_pl.title,
                    "changes": changes,
                    "applied": False,
                }

                if not changes:
                    if not self._json:
                        console.print(f"  {new_pl.title}: no changes")
                    results.append(result)
                    continue

                if not self._json:
                    console.print(f"  {new_pl.title}:")
                    for key, val in changes.items():
                        console.print(f"    {key}: {val}")

                if dry_run:
                    results.append(result)
                    continue

                # Apply metadata changes
                if any(k in changes for k in ("title", "description", "privacy")):
                    api.update_playlist(
                        client,
                        new_pl.id,
                        title=new_pl.title if "title" in changes else None,
                        description=new_pl.description if "description" in changes else None,
                        privacy=new_pl.privacy if "privacy" in changes else None,
                    )

                # Handle video removals
                if "videos_removed" in changes:
                    items = api.get_playlist_items(client, new_pl.id)
                    item_by_video = {item.video_id: item for item in items}
                    for vid_id in changes["videos_removed"]:
                        if vid_id in item_by_video:
                            api.remove_video_from_playlist(client, item_by_video[vid_id].item_id)
                            logger.debug("Removed video {}", vid_id)

                # Handle video additions
                if "videos_added" in changes:
                    for vid_id in changes["videos_added"]:
                        try:
                            api.add_video_to_playlist(client, new_pl.id, vid_id)
                            logger.debug("Added video {}", vid_id)
                        except Exception as e:
                            logger.warning("Failed to add video {}: {}", vid_id, e)

                # Handle reordering (after adds/removes)
                if "videos_reordered" in changes and new_pl.videos:
                    new_order = [v.id for v in new_pl.videos]
                    api.reorder_playlist_videos(client, new_pl.id, new_order)
                    logger.debug("Reordered playlist videos")

                result["applied"] = True
                results.append(result)

            except Exception as e:
                if not self._json:
                    console.print(f"[red]Error processing {new_pl.id}: {e}[/red]")
                results.append(
                    {
                        "playlist_id": new_pl.id,
                        "title": new_pl.title,
                        "error": str(e),
                    }
                )

        if self._json:
            return self._output(
                {
                    "dry_run": dry_run,
                    "playlists_processed": len(results),
                    "playlists": results,
                }
            )

        if dry_run:
            console.print("[yellow]Dry run - no changes applied[/yellow]")
        else:
            console.print("[green]Done[/green]")
        return None

    def mlist2yaml(self, url_or_id: str, output: str | None = None) -> str | dict[str, Any] | None:
        """Export single playlist to YAML.

        Args:
            url_or_id: Playlist URL or ID (must be on your channel)
            output: Output file path

        Example:
            ytrix mlist2yaml PLxxx
            ytrix mlist2yaml PLxxx --output mylist.yaml
        """
        config = load_config()
        client = self._get_youtube_client(config)

        playlist_id = extract_playlist_id(url_or_id)

        # Get playlist metadata from API (need privacy status)
        response = client.playlists().list(part="snippet,status", id=playlist_id).execute()
        if not response["items"]:
            raise ValueError(f"Playlist not found: {playlist_id}")
        item = response["items"][0]

        # Try yt-dlp for videos (no API quota), fall back to API for private playlists
        try:
            extracted = extractor.extract_playlist(playlist_id)
            videos = extracted.videos
        except Exception:
            videos = api.get_playlist_videos(client, playlist_id)

        playlist = Playlist(
            id=playlist_id,
            title=item["snippet"]["title"],
            description=item["snippet"].get("description", ""),
            privacy=item["status"]["privacyStatus"],
            videos=videos,
        )

        if self._json:
            return self._output({"playlist": playlist.to_dict(include_videos=True)})

        out_path = output or f"playlist_{playlist_id}.yaml"
        yaml_ops.save_yaml(out_path, [playlist])

        console.print(f"[green]Saved to: {out_path}[/green]")
        return out_path

    def yaml2mlist(self, file_path: str, dry_run: bool = False) -> dict[str, Any] | None:
        """Apply YAML edits to single playlist.

        Args:
            file_path: YAML file with playlist data
            dry_run: Show changes without applying

        Example:
            ytrix yaml2mlist mylist.yaml --dry-run
            ytrix --json-output yaml2mlist mylist.yaml
        """
        # Reuse yaml2mlists since it handles single playlists too
        return self.yaml2mlists(file_path, dry_run=dry_run)

    def plist2info(
        self,
        url_or_id: str,
        output: str | None = None,
        max_languages: int = 5,
        langs: str | tuple[str, ...] | list[str] | None = None,
        delay: float = 0.5,
        subtitle_delay: int = 1000,
        video: bool = False,
        video_lang: str = "en",
        video_proxy: bool = False,
    ) -> str | dict[str, Any] | None:
        """Extract playlist info with subtitles and transcripts.

        Downloads all available subtitles and converts them to markdown transcripts.
        Creates a folder structure:
          output_folder/Playlist_Title/
            001_Video_Title.en.srt
            001_Video_Title.en.md
            001_Video_Title.mp4  (if --video)
            playlist.yaml

        Args:
            url_or_id: Playlist URL or ID
            output: Output directory (default: current directory)
            max_languages: Max subtitle languages per video (default: 5)
            langs: Comma-separated ISO language codes (e.g., "en,ru").
                   Takes precedence over max_languages when provided.
            delay: Seconds between video processing (default: 0.5)
            subtitle_delay: Milliseconds between subtitle downloads (default: 1000,
                           increase to 2000-3000 if hitting 429 rate limit errors)
            video: Download videos (highest quality with preferred audio language)
            video_lang: Preferred audio language for video (default: "en").
                       Useful for YouTube auto-dubbed videos.
            video_proxy: Use rotating proxy for video downloads (default: False)

        Example:
            ytrix plist2info PLxxx
            ytrix plist2info PLxxx --output ./transcripts
            ytrix plist2info PLxxx --langs en,ru  # Only English and Russian
            ytrix plist2info PLxxx --max-languages 3 --delay 1.0
            ytrix plist2info PLxxx --subtitle-delay 2000  # Slower for rate limits
            ytrix plist2info PLxxx --video  # Also download videos
            ytrix plist2info PLxxx --video --video-lang de  # German audio preferred
        """
        output_dir = Path(output) if output else Path.cwd()

        # Configure subtitle throttle delay
        info.set_subtitle_throttle_delay(subtitle_delay)

        if not self._json:
            console.print("[blue]Extracting playlist info...[/blue]")

        def progress_cb(idx: int, total: int, title: str) -> None:
            if not self._json:
                console.print(f"  [{idx + 1}/{total}] {title[:60]}...")

        playlist = info.extract_and_save_playlist_info(
            url_or_id,
            output_dir,
            max_languages=max_languages,
            langs=langs,
            progress_callback=progress_cb,
            video_delay=delay,
        )

        playlist_folder = output_dir / info._sanitize_filename(playlist.title)

        # Deferred video download: process after all metadata/subtitles are done
        videos_downloaded = 0
        videos_failed = 0
        if video and playlist.videos:
            if not self._json:
                console.print(f"\n[blue]Downloading {len(playlist.videos)} videos...[/blue]")

            # Build download tasks
            video_tasks = [
                info.VideoDownloadTask(
                    video_id=v.id,
                    output_path=playlist_folder / info._video_filename(i, v.title),
                    title=v.title,
                )
                for i, v in enumerate(playlist.videos)
            ]

            def video_progress_cb(idx: int, total: int, title: str) -> None:
                if not self._json:
                    console.print(f"  [{idx + 1}/{total}] {title[:50]}...")

            videos_downloaded, videos_failed = info.download_videos_batch(
                video_tasks,
                lang=video_lang,
                use_proxy=video_proxy,
                progress_callback=video_progress_cb,
            )

        if self._json:
            result = {
                "playlist_id": playlist.id,
                "title": playlist.title,
                "video_count": len(playlist.videos),
                "output_folder": str(playlist_folder),
            }
            if video:
                result["videos_downloaded"] = videos_downloaded
                result["videos_failed"] = videos_failed
            return self._output(result)

        console.print(f"[green]Saved to: {playlist_folder}[/green]")
        console.print(f"  {len(playlist.videos)} videos processed")
        if video:
            console.print(f"  {videos_downloaded} videos downloaded, {videos_failed} failed")
        return str(playlist_folder)

    def plists2info(
        self,
        file_path: str,
        output: str | None = None,
        max_languages: int = 5,
        langs: str | tuple[str, ...] | list[str] | None = None,
        delay: float = 0.5,
        subtitle_delay: int = 1000,
        parallel: bool | None = None,
        video: bool = False,
        video_lang: str = "en",
        video_proxy: bool = False,
    ) -> list[str] | dict[str, Any] | None:
        """Extract info from multiple playlists with subtitles and transcripts.

        Processes each playlist from the input file and creates a subfolder for each.
        Downloads all available subtitles and converts them to markdown transcripts.

        When rotating proxy is configured, playlists are processed in parallel for
        significant speedup (each parallel request uses a different IP).

        Video downloads are deferred until ALL playlists' metadata and subtitles
        have been processed, then downloaded sequentially at the end.

        Args:
            file_path: Text file with playlist URLs/IDs (one per line)
            output: Output directory (default: current directory)
            max_languages: Max subtitle languages per video (default: 5)
            langs: Comma-separated ISO language codes (e.g., "en,ru").
                   Takes precedence over max_languages when provided.
            delay: Seconds between video processing (default: 0.5, ignored with proxy)
            subtitle_delay: Milliseconds between subtitle downloads (default: 1000,
                           increase to 2000-3000 if hitting 429 rate limit errors)
            parallel: Use parallel processing (default: auto based on proxy status)
            video: Download videos (highest quality with preferred audio language)
            video_lang: Preferred audio language for video (default: "en").
                       Useful for YouTube auto-dubbed videos.
            video_proxy: Use rotating proxy for video downloads (default: False)

        Example:
            ytrix plists2info playlists.txt
            ytrix plists2info playlists.txt --output ./transcripts
            ytrix plists2info playlists.txt --langs en,ru  # Only English and Russian
            ytrix plists2info playlists.txt --max-languages 2 --delay 1.0
            ytrix plists2info playlists.txt --subtitle-delay 2000  # Slower for rate limits
            ytrix plists2info playlists.txt --video  # Also download all videos
            ytrix plists2info playlists.txt --video --video-lang de  # German audio
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        output_dir = Path(output) if output else Path.cwd()

        # Configure subtitle throttle delay
        info.set_subtitle_throttle_delay(subtitle_delay)

        # Read playlist URLs/IDs from file
        lines = Path(file_path).read_text().strip().split("\n")
        lines = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
        if not lines:
            raise ValueError("No playlist URLs found in file")

        use_parallel = parallel if parallel is not None else info.is_proxy_enabled()
        workers = info.MAX_PARALLEL_WORKERS if use_parallel else 1

        if not self._json:
            mode = f"parallel ({workers} workers)" if workers > 1 else "sequential"
            console.print(f"[blue]Processing {len(lines)} playlists ({mode})...[/blue]")

        results: list[dict[str, Any]] = []
        output_folders: list[str] = []
        # Collect video download tasks from all playlists for deferred download
        all_video_tasks: list[info.VideoDownloadTask] = []

        def process_playlist(url: str) -> tuple[dict[str, Any], list[info.VideoDownloadTask]]:
            """Process a single playlist and return result dict + video tasks."""
            video_tasks: list[info.VideoDownloadTask] = []
            try:
                playlist = info.extract_and_save_playlist_info(
                    url,
                    output_dir,
                    max_languages=max_languages,
                    langs=langs,
                    progress_callback=None,  # No per-video progress in parallel mode
                    video_delay=delay,
                )
                playlist_folder = output_dir / info._sanitize_filename(playlist.title)

                # Build video download tasks if video flag is set
                if video:
                    for i, v in enumerate(playlist.videos):
                        video_tasks.append(
                            info.VideoDownloadTask(
                                video_id=v.id,
                                output_path=playlist_folder / info._video_filename(i, v.title),
                                title=v.title,
                            )
                        )

                return (
                    {
                        "playlist_id": playlist.id,
                        "title": playlist.title,
                        "video_count": len(playlist.videos),
                        "output_folder": str(playlist_folder),
                        "success": True,
                    },
                    video_tasks,
                )
            except Exception as e:
                return ({"url": url, "error": str(e), "success": False}, video_tasks)

        if workers > 1 and len(lines) > 1:
            # Parallel playlist processing
            completed = 0
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(process_playlist, url): url for url in lines}
                for future in as_completed(futures):
                    url = futures[future]
                    result, video_tasks = future.result()
                    completed += 1
                    results.append(result)
                    all_video_tasks.extend(video_tasks)

                    if not self._json:
                        if result.get("success"):
                            title = result.get("title", url)[:50]
                            console.print(f"[{completed}/{len(lines)}] [green]✓[/green] {title}")
                            output_folders.append(result["output_folder"])
                        else:
                            err = result.get("error")
                            console.print(f"[{completed}/{len(lines)}] [red]✗[/red] {url}: {err}")
        else:
            # Sequential processing (original behavior)
            for i, line in enumerate(lines):
                if not self._json:
                    console.print(f"\n[bold][{i + 1}/{len(lines)}][/bold] {line}")

                result, video_tasks = process_playlist(line)
                results.append(result)
                all_video_tasks.extend(video_tasks)

                if result.get("success"):
                    output_folders.append(result["output_folder"])
                    if not self._json:
                        console.print(f"  [green]Saved: {result['output_folder']}[/green]")
                else:
                    if not self._json:
                        console.print(f"  [red]Error: {result.get('error')}[/red]")

        # Deferred video download: process ALL videos after ALL metadata/subtitles done
        videos_downloaded = 0
        videos_failed = 0
        if video and all_video_tasks:
            if not self._json:
                console.print(
                    f"\n[blue]Downloading {len(all_video_tasks)} videos "
                    f"(deferred from {len(output_folders)} playlists)...[/blue]"
                )

            def video_progress_cb(idx: int, total: int, title: str) -> None:
                if not self._json:
                    console.print(f"  [{idx + 1}/{total}] {title[:50]}...")

            videos_downloaded, videos_failed = info.download_videos_batch(
                all_video_tasks,
                lang=video_lang,
                use_proxy=video_proxy,
                progress_callback=video_progress_cb,
            )

        if self._json:
            result_dict: dict[str, Any] = {
                "playlists_processed": len(results),
                "playlists": results,
            }
            if video:
                result_dict["videos_downloaded"] = videos_downloaded
                result_dict["videos_failed"] = videos_failed
            return self._output(result_dict)

        success_count = len([r for r in results if r.get("success")])
        console.print(f"\n[green]Done! Processed {success_count}/{len(lines)} playlists.[/green]")
        if video:
            console.print(
                f"[green]Videos: {videos_downloaded} downloaded, {videos_failed} failed[/green]"
            )
        return output_folders


def main() -> None:
    """CLI entry point."""
    fire.Fire(YtrixCLI)


if __name__ == "__main__":
    main()
