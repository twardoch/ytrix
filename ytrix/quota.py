"""YouTube API quota tracking and estimation."""

from dataclasses import dataclass

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
