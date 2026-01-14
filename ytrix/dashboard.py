"""Rich dashboard for quota visualization.

this_file: ytrix/dashboard.py
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def get_time_until_reset() -> str:
    """Calculate time until midnight Pacific Time when quota resets.

    Returns:
        Human-readable time string (e.g., "5h 23m")
    """
    pacific = ZoneInfo("America/Los_Angeles")
    now = datetime.now(pacific)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    delta = midnight - now
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours}h {minutes}m"


def create_quota_dashboard(
    project_name: str,
    quota_group: str,
    used: int,
    limit: int,
    operations: dict[str, tuple[int, int]] | None = None,
) -> Panel:
    """Create rich dashboard panel for quota visualization.

    Args:
        project_name: Active project name
        quota_group: Project's quota group (e.g., "personal", "work")
        used: Quota units consumed
        limit: Daily quota limit
        operations: Dict mapping operation name to (count, units) tuple

    Returns:
        Rich Panel with formatted dashboard
    """
    if operations is None:
        operations = {}

    # Calculate percentage and color
    percentage = (used / limit) * 100 if limit > 0 else 0
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
    content = Text()

    # Header
    content.append("Project: ")
    content.append(project_name, style="bold")
    content.append(f" ({quota_group})                    Status: ")
    content.append(status_text, style=f"bold {status_color}")
    content.append("\n\n")

    # Progress bar
    content.append("Daily Quota Usage\n", style="bold")
    filled = int((percentage / 100) * 40)
    empty = 40 - filled
    content.append("█" * filled, style=bar_color)
    content.append("░" * empty, style="dim")
    content.append(f"  {used:,} / {limit:,} ({percentage:.1f}%)\n\n")

    # Remaining capacity
    remaining = limit - used
    if remaining > 0:
        content.append("Remaining Capacity: ", style="dim")
        content.append(f"{remaining // 50} playlist creates", style="cyan")
        content.append(" OR ", style="dim")
        content.append(f"{remaining // 50} video operations\n", style="cyan")
    else:
        content.append("Quota exhausted - no operations possible\n", style="red")

    content.append("Quota resets in: ", style="dim")
    content.append(get_time_until_reset(), style="bold")
    content.append(" (midnight PT)\n", style="dim")

    return Panel(
        content,
        title="[bold]ytrix Quota Dashboard[/bold]",
        border_style="blue",
    )


def create_operations_table(operations: dict[str, tuple[int, int]]) -> Table:
    """Create table of today's operations.

    Args:
        operations: Dict mapping operation name to (count, units) tuple

    Returns:
        Rich Table with operation breakdown
    """
    table = Table(title="Today's Operations", box=None, show_header=True, header_style="bold")
    table.add_column("Operation")
    table.add_column("Count", justify="right")
    table.add_column("Units", justify="right")
    table.add_column("Note", style="dim")

    for op_name, (count, units) in operations.items():
        note = "(via yt-dlp: FREE)" if "Read" in op_name and units == 0 else ""
        table.add_row(op_name, str(count), str(units), note)

    return table


def show_quota_warning(percentage: float, remaining: int) -> None:
    """Show quota warning at thresholds.

    Args:
        percentage: Quota usage percentage
        remaining: Units remaining
    """
    console = Console()

    if percentage >= 95:
        console.print(
            Panel(
                f"[red bold]Quota Critical: {percentage:.1f}% used[/red bold]\n\n"
                f"Only {remaining:,} units remaining.\n"
                f"Consider pausing and resuming tomorrow.",
                title="Quota Warning",
                border_style="red",
            )
        )
    elif percentage >= 80:
        msg = f"Quota at {percentage:.1f}% - {remaining:,} units remaining"
        console.print(f"[yellow]{msg}[/yellow]")


def show_rate_limit_feedback(wait_seconds: float, attempt: int, max_attempts: int) -> None:
    """Show rate limit retry feedback.

    Args:
        wait_seconds: Seconds until next retry
        attempt: Current attempt number
        max_attempts: Maximum retry attempts
    """
    console = Console()
    console.print(
        f"[yellow]Rate limited. Waiting {wait_seconds:.0f}s before retry "
        f"(attempt {attempt}/{max_attempts})[/yellow]"
    )


def show_session_summary(
    started: datetime,
    operations: dict[str, int],
    quota_consumed: int,
    errors: list[str] | None = None,
) -> None:
    """Display end-of-session summary.

    Args:
        started: Session start time
        operations: Dict mapping operation type to count
        quota_consumed: Total quota units consumed
        errors: List of error messages
    """
    console = Console()
    if errors is None:
        errors = []
    duration = datetime.now() - started

    table = Table(title="Session Summary", show_header=True, header_style="bold")
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
            console.print(f"  - {err}")
        if len(errors) > 5:
            console.print(f"  ... and {len(errors) - 5} more")
