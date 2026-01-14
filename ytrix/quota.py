"""YouTube API quota tracking and estimation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from ytrix.logging import logger

# YouTube Data API v3 quota costs
# https://developers.google.com/youtube/v3/determine_quota_cost
QUOTA_COSTS = {
    "playlists.list": 1,
    "playlists.insert": 50,
    "playlists.update": 50,
    "playlists.delete": 50,
    "playlistItems.list": 1,
    "playlistItems.insert": 50,
    "playlistItems.update": 50,
    "playlistItems.delete": 50,
}

# Default daily quota limit
DAILY_QUOTA_LIMIT = 10_000

# Pacific timezone (quota resets at midnight PT)
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


@dataclass
class QuotaTracker:
    """Tracks actual API quota usage during a session.

    YouTube API quota resets at midnight Pacific Time daily.
    This tracker monitors usage and warns when approaching limits.
    """

    used: int = 0
    limit: int = DAILY_QUOTA_LIMIT
    warn_threshold: float = 0.8  # Warn at 80%
    operations: dict[str, int] = field(default_factory=dict)

    def record(self, operation: str, units: int | None = None) -> None:
        """Record an API operation and its quota cost.

        Args:
            operation: API operation name (e.g., "playlists.insert")
            units: Quota units consumed (defaults to QUOTA_COSTS lookup)
        """
        if units is None:
            units = QUOTA_COSTS.get(operation, 50)
        self.used += units
        self.operations[operation] = self.operations.get(operation, 0) + 1
        logger.debug("Quota: +{} units for {} (total: {})", units, operation, self.used)

    @property
    def remaining(self) -> int:
        """Remaining quota units for the day."""
        return max(0, self.limit - self.used)

    @property
    def usage_percent(self) -> float:
        """Percentage of daily quota used."""
        return (self.used / self.limit) * 100 if self.limit > 0 else 100.0

    def is_warning(self) -> bool:
        """Check if usage exceeds warning threshold."""
        return self.used >= (self.limit * self.warn_threshold)

    def is_exceeded(self) -> bool:
        """Check if quota is fully consumed."""
        return self.used >= self.limit

    def check_and_warn(self) -> str | None:
        """Check quota and return warning message if needed."""
        if self.is_exceeded():
            return f"⚠️  Daily quota limit reached ({self.used:,}/{self.limit:,} units)"
        if self.is_warning():
            pct = self.usage_percent
            return f"⚠️  Quota usage at {pct:.0f}% ({self.used:,}/{self.limit:,} units)"
        return None

    def reset(self) -> None:
        """Reset the tracker for a new day."""
        self.used = 0
        self.operations.clear()

    def summary(self) -> dict[str, int | float | dict[str, int]]:
        """Get usage summary."""
        return {
            "used": self.used,
            "remaining": self.remaining,
            "limit": self.limit,
            "usage_percent": round(self.usage_percent, 1),
            "operations": dict(self.operations),
        }


# Global tracker instance
_tracker = QuotaTracker()


def get_tracker() -> QuotaTracker:
    """Get the global quota tracker."""
    return _tracker


def record_quota(operation: str, units: int | None = None) -> None:
    """Record quota usage for an API operation."""
    _tracker.record(operation, units)


def get_quota_summary() -> dict[str, int | float | dict[str, int]]:
    """Get current quota usage summary."""
    return _tracker.summary()


def get_time_until_reset() -> str:
    """Get human-readable time until quota reset (midnight PT).

    Returns:
        String like "5h 23m" or "23m" until midnight Pacific Time.
    """
    now = datetime.now(PACIFIC_TZ)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # If past midnight, calculate to next midnight
    if now >= midnight:
        from datetime import timedelta

        midnight = midnight + timedelta(days=1)

    delta = midnight - now
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60

    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


@dataclass
class QuotaEstimate:
    """Estimated quota usage for an operation."""

    playlist_creates: int = 0
    video_adds: int = 0
    playlist_updates: int = 0
    video_removes: int = 0
    video_reorders: int = 0
    list_operations: int = 0

    @property
    def total(self) -> int:
        """Total estimated quota units."""
        return (
            self.playlist_creates * QUOTA_COSTS["playlists.insert"]
            + self.video_adds * QUOTA_COSTS["playlistItems.insert"]
            + self.playlist_updates * QUOTA_COSTS["playlists.update"]
            + self.video_removes * QUOTA_COSTS["playlistItems.delete"]
            + self.video_reorders * QUOTA_COSTS["playlistItems.update"]
            + self.list_operations * QUOTA_COSTS["playlists.list"]
        )

    @property
    def days_required(self) -> int:
        """Minimum days required to complete at default quota."""
        if self.total == 0:
            return 0
        return (self.total + DAILY_QUOTA_LIMIT - 1) // DAILY_QUOTA_LIMIT

    def breakdown(self) -> dict[str, int]:
        """Get breakdown of quota costs by operation type."""
        return {
            "playlist_creates": self.playlist_creates * QUOTA_COSTS["playlists.insert"],
            "video_adds": self.video_adds * QUOTA_COSTS["playlistItems.insert"],
            "playlist_updates": self.playlist_updates * QUOTA_COSTS["playlists.update"],
            "video_removes": self.video_removes * QUOTA_COSTS["playlistItems.delete"],
            "video_reorders": self.video_reorders * QUOTA_COSTS["playlistItems.update"],
            "list_operations": self.list_operations * QUOTA_COSTS["playlists.list"],
            "total": self.total,
        }


def estimate_batch_copy(
    num_playlists: int,
    total_videos: int,
    skip_existing: int = 0,
    update_existing: int = 0,
) -> QuotaEstimate:
    """Estimate quota for batch playlist copy operation.

    Args:
        num_playlists: Number of playlists to create
        total_videos: Total number of videos to add
        skip_existing: Number of playlists to skip (exact match)
        update_existing: Number of playlists to update (partial match)
    """
    new_creates = num_playlists - skip_existing - update_existing
    return QuotaEstimate(
        playlist_creates=max(0, new_creates),
        video_adds=total_videos,
        playlist_updates=update_existing,
    )


def estimate_copy_cost(num_videos: int, create_playlist: bool = True) -> QuotaEstimate:
    """Estimate quota cost for copying a single playlist.

    This is used for pre-flight checks before plist2mlist and similar commands.

    Args:
        num_videos: Number of videos to copy
        create_playlist: Whether a new playlist will be created

    Returns:
        QuotaEstimate with breakdown of costs

    Example:
        >>> est = estimate_copy_cost(25, create_playlist=True)
        >>> est.total  # 50 (create) + 25*50 (adds) = 1300
        1300
    """
    return QuotaEstimate(
        playlist_creates=1 if create_playlist else 0,
        video_adds=num_videos,
        list_operations=1,  # Initial playlist fetch
    )


def can_afford_operation(estimate: QuotaEstimate) -> tuple[bool, str]:
    """Check if current quota allows the estimated operation.

    Args:
        estimate: QuotaEstimate for the planned operation

    Returns:
        Tuple of (can_afford, message)
    """
    remaining = _tracker.remaining
    if estimate.total <= remaining:
        return True, f"Operation needs {estimate.total:,} units, {remaining:,} available."

    shortage = estimate.total - remaining
    return False, (
        f"Operation needs {estimate.total:,} units but only {remaining:,} available. "
        f"Shortage: {shortage:,} units. Wait for quota reset at midnight PT."
    )


def format_quota_warning(estimate: QuotaEstimate) -> str:
    """Format a user-friendly quota warning message."""
    create_cost = estimate.playlist_creates * 50
    add_cost = estimate.video_adds * 50
    update_cost = estimate.playlist_updates * 50
    lines = [
        f"Estimated API quota: {estimate.total:,} units",
        f"  - Playlist creates: {estimate.playlist_creates} x 50 = {create_cost:,}",
        f"  - Video adds: {estimate.video_adds} x 50 = {add_cost:,}",
    ]
    if estimate.playlist_updates > 0:
        lines.append(f"  - Playlist updates: {estimate.playlist_updates} x 50 = {update_cost:,}")

    lines.append(f"Daily quota limit: {DAILY_QUOTA_LIMIT:,} units")

    if estimate.total > DAILY_QUOTA_LIMIT:
        days = estimate.days_required
        lines.append(f"⚠️  This operation requires ~{days} days to complete!")
        lines.append("   Use --resume to continue after quota resets at midnight PT.")

    return "\n".join(lines)
