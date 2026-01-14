# Part 7: CLI Dashboard & Quota Display

## Current State

The existing `quota_status` command provides basic quota information, but lacks:
- Visual representation of quota consumption
- Per-project breakdown in multi-project setups
- Time-until-reset display
- Operation history within the session

## Rich Dashboard Design

### 7.1 Main Dashboard View (`ytrix quota`)

```
┌──────────────────────────────────────────────────────────────────────┐
│                        ytrix Quota Dashboard                         │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Project: ytrix-prod (personal)                    Status: ACTIVE    │
│                                                                      │
│  Daily Quota Usage                                                   │
│  ████████████████████████░░░░░░░░░░░░░░░░░░░  6,234 / 10,000 (62.3%) │
│                                                                      │
│  Today's Operations                                                  │
│  ┌──────────────────┬─────────┬───────────┐                         │
│  │ Operation        │  Count  │ Units     │                         │
│  ├──────────────────┼─────────┼───────────┤                         │
│  │ Playlists Read   │     12  │     12    │  (via yt-dlp: FREE)     │
│  │ Playlists Created│      3  │    150    │                         │
│  │ Videos Added     │    121  │  6,050    │                         │
│  │ Videos Removed   │      0  │      0    │                         │
│  │ Metadata Updates │      1  │     50    │                         │
│  └──────────────────┴─────────┴───────────┘                         │
│                                                                      │
│  Remaining Capacity: 75 playlist creates OR 3,766 video additions   │
│  Quota resets in: 5h 23m (midnight Pacific Time)                    │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 7.2 Implementation

```python
# ytrix/dashboard.py

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn
from rich.layout import Layout
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def get_time_until_reset() -> str:
    """Calculate time until midnight Pacific Time."""
    pacific = ZoneInfo("America/Los_Angeles")
    now = datetime.now(pacific)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if now > midnight:
        midnight = midnight.replace(day=midnight.day + 1)
    delta = midnight - now
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours}h {minutes}m"


def create_quota_dashboard(
    project_name: str,
    quota_group: str,
    used: int,
    limit: int,
    operations: dict[str, tuple[int, int]],  # operation -> (count, units)
) -> Panel:
    """Create rich dashboard panel."""
    console = Console()

    # Calculate percentage and color
    percentage = (used / limit) * 100
    if percentage < 80:
        bar_color = "green"
        status_color = "green"
        status_text = "ACTIVE"
    elif percentage < 95:
        bar_color = "yellow"
        status_color = "yellow"
        status_text = "WARNING"
    else:
        bar_color = "red"
        status_color = "red"
        status_text = "CRITICAL"

    # Build the dashboard content
    lines = []

    # Header
    lines.append(f"Project: [bold]{project_name}[/bold] ({quota_group})")
    lines.append(f"Status: [{status_color}]{status_text}[/{status_color}]")
    lines.append("")

    # Progress bar
    filled = int((used / limit) * 40)
    empty = 40 - filled
    bar = f"[{bar_color}]{'█' * filled}[/{bar_color}]{'░' * empty}"
    lines.append("Daily Quota Usage")
    lines.append(f"{bar}  {used:,} / {limit:,} ({percentage:.1f}%)")
    lines.append("")

    # Operations table
    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("Operation")
    table.add_column("Count", justify="right")
    table.add_column("Units", justify="right")
    table.add_column("Note")

    for op_name, (count, units) in operations.items():
        note = "(via yt-dlp: FREE)" if "Read" in op_name and units == 0 else ""
        table.add_row(op_name, str(count), str(units), note)

    # Remaining capacity
    remaining = limit - used
    lines.append("")
    lines.append(f"Remaining: {remaining // 50} playlist creates OR {remaining // 50} video operations")
    lines.append(f"Quota resets in: [bold]{get_time_until_reset()}[/bold] (midnight PT)")

    return Panel(
        "\n".join(lines),
        title="[bold]ytrix Quota Dashboard[/bold]",
        border_style="blue",
    )
```

### 7.3 Inline Progress Display

During batch operations, show live progress:

```python
def batch_progress_display(
    total_tasks: int,
    completed: int,
    quota_used: int,
    quota_remaining: int,
) -> None:
    """Display inline progress during batch operations."""
    console = Console()

    with console.status("[bold blue]Processing...") as status:
        # This would be called in a loop
        console.print(
            f"[dim]Progress: {completed}/{total_tasks} | "
            f"Quota: {quota_used:,} used, {quota_remaining:,} remaining[/dim]",
            end="\r"
        )
```

### 7.4 Warning Displays

```python
def show_quota_warning(percentage: float, remaining: int) -> None:
    """Show quota warning at thresholds."""
    console = Console()

    if percentage >= 95:
        console.print(Panel(
            f"[red bold]Quota Critical: {percentage:.1f}% used[/red bold]\n\n"
            f"Only {remaining:,} units remaining.\n"
            f"Consider pausing and resuming tomorrow.",
            title="⚠️ Quota Warning",
            border_style="red",
        ))
    elif percentage >= 80:
        console.print(
            f"[yellow]Quota at {percentage:.1f}% - {remaining:,} units remaining[/yellow]"
        )


def show_rate_limit_feedback(wait_seconds: float, attempt: int, max_attempts: int) -> None:
    """Show rate limit retry feedback."""
    console = Console()
    console.print(
        f"[yellow]Rate limited. Waiting {wait_seconds:.0f}s before retry "
        f"(attempt {attempt}/{max_attempts})[/yellow]"
    )
```

### 7.5 Session Summary

After batch operations complete:

```python
def show_session_summary(
    started: datetime,
    operations: dict[str, int],
    quota_consumed: int,
    errors: list[str],
) -> None:
    """Display end-of-session summary."""
    console = Console()
    duration = datetime.now() - started

    table = Table(title="Session Summary", box="ROUNDED")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Duration", str(duration).split(".")[0])
    table.add_row("Quota Consumed", f"{quota_consumed:,} units")

    for op, count in operations.items():
        table.add_row(f"  {op}", str(count))

    if errors:
        table.add_row("Errors", f"[red]{len(errors)}[/red]")
    else:
        table.add_row("Errors", "[green]0[/green]")

    console.print(table)

    if errors:
        console.print("\n[yellow]Errors encountered:[/yellow]")
        for err in errors[:5]:  # Show first 5
            console.print(f"  • {err}")
        if len(errors) > 5:
            console.print(f"  ... and {len(errors) - 5} more")
```

## CLI Commands

### Existing Commands to Enhance

```bash
# Enhanced quota display
ytrix quota_status
ytrix quota_status --project ytrix-prod
ytrix quota_status --all  # Show all projects

# During batch operations, show progress
ytrix plists2mlists file.txt --progress  # Default on for TTY
ytrix plists2mlists file.txt --quiet     # Suppress progress
```

## Implementation Checklist

- [ ] Create `ytrix/dashboard.py` module
- [ ] Add `get_time_until_reset()` function
- [ ] Add `create_quota_dashboard()` function
- [ ] Add `show_quota_warning()` function
- [ ] Add `show_rate_limit_feedback()` function
- [ ] Add `show_session_summary()` function
- [ ] Update `quota_status` command to use rich dashboard
- [ ] Add `--progress` and `--quiet` flags to batch commands
- [ ] Add `--all` flag to show all projects' quota status
- [ ] Test dashboard rendering on various terminal widths
