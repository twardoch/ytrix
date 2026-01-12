"""Tests for ytrix.quota module."""

from ytrix.quota import (
    DAILY_QUOTA_LIMIT,
    QUOTA_COSTS,
    QuotaEstimate,
    estimate_batch_copy,
    format_quota_warning,
)


class TestQuotaCosts:
    """Tests for quota cost constants."""

    def test_insert_costs_50(self) -> None:
        """Insert operations cost 50 units."""
        assert QUOTA_COSTS["playlists.insert"] == 50
        assert QUOTA_COSTS["playlistItems.insert"] == 50

    def test_list_costs_1(self) -> None:
        """List operations cost 1 unit."""
        assert QUOTA_COSTS["playlists.list"] == 1
        assert QUOTA_COSTS["playlistItems.list"] == 1

    def test_daily_limit(self) -> None:
        """Daily limit is 10,000 units."""
        assert DAILY_QUOTA_LIMIT == 10_000


class TestQuotaEstimate:
    """Tests for QuotaEstimate dataclass."""

    def test_default_values(self) -> None:
        """Has zero defaults."""
        estimate = QuotaEstimate()
        assert estimate.playlist_creates == 0
        assert estimate.video_adds == 0
        assert estimate.total == 0

    def test_total_calculation(self) -> None:
        """Calculates total correctly."""
        estimate = QuotaEstimate(
            playlist_creates=2,  # 2 * 50 = 100
            video_adds=10,  # 10 * 50 = 500
            playlist_updates=1,  # 1 * 50 = 50
        )
        assert estimate.total == 650

    def test_total_with_all_operations(self) -> None:
        """Includes all operation types in total."""
        estimate = QuotaEstimate(
            playlist_creates=1,  # 50
            video_adds=1,  # 50
            playlist_updates=1,  # 50
            video_removes=1,  # 50
            video_reorders=1,  # 50
            list_operations=10,  # 10
        )
        assert estimate.total == 260

    def test_days_required_zero(self) -> None:
        """Returns 0 days for no operations."""
        estimate = QuotaEstimate()
        assert estimate.days_required == 0

    def test_days_required_one(self) -> None:
        """Returns 1 day when under limit."""
        estimate = QuotaEstimate(video_adds=100)  # 5,000 units
        assert estimate.days_required == 1

    def test_days_required_multiple(self) -> None:
        """Returns correct days when over limit."""
        estimate = QuotaEstimate(video_adds=500)  # 25,000 units
        assert estimate.days_required == 3

    def test_days_required_rounds_up(self) -> None:
        """Days required rounds up."""
        estimate = QuotaEstimate(video_adds=201)  # 10,050 units (just over 1 day)
        assert estimate.days_required == 2

    def test_breakdown(self) -> None:
        """Returns correct breakdown by operation type."""
        estimate = QuotaEstimate(
            playlist_creates=2,
            video_adds=5,
        )
        breakdown = estimate.breakdown()
        assert breakdown["playlist_creates"] == 100
        assert breakdown["video_adds"] == 250
        assert breakdown["total"] == 350


class TestEstimateBatchCopy:
    """Tests for estimate_batch_copy function."""

    def test_basic_copy(self) -> None:
        """Estimates basic batch copy."""
        estimate = estimate_batch_copy(num_playlists=3, total_videos=30)
        assert estimate.playlist_creates == 3
        assert estimate.video_adds == 30
        assert estimate.total == 3 * 50 + 30 * 50  # 1,650

    def test_with_skip(self) -> None:
        """Reduces creates when skipping existing."""
        estimate = estimate_batch_copy(
            num_playlists=5, total_videos=50, skip_existing=2
        )
        assert estimate.playlist_creates == 3
        assert estimate.video_adds == 50

    def test_with_updates(self) -> None:
        """Counts updates instead of creates."""
        estimate = estimate_batch_copy(
            num_playlists=5, total_videos=50, update_existing=2
        )
        assert estimate.playlist_creates == 3
        assert estimate.playlist_updates == 2

    def test_skip_and_update(self) -> None:
        """Handles both skip and update."""
        estimate = estimate_batch_copy(
            num_playlists=10, total_videos=100, skip_existing=3, update_existing=4
        )
        assert estimate.playlist_creates == 3
        assert estimate.playlist_updates == 4


class TestFormatQuotaWarning:
    """Tests for format_quota_warning function."""

    def test_basic_output(self) -> None:
        """Formats basic quota info."""
        estimate = QuotaEstimate(playlist_creates=1, video_adds=10)
        output = format_quota_warning(estimate)
        assert "550 units" in output
        assert "Playlist creates: 1 x 50" in output
        assert "Video adds: 10 x 50" in output

    def test_shows_updates(self) -> None:
        """Shows update count when present."""
        estimate = QuotaEstimate(playlist_updates=2)
        output = format_quota_warning(estimate)
        assert "Playlist updates: 2 x 50" in output

    def test_warns_over_limit(self) -> None:
        """Shows warning when over daily limit."""
        estimate = QuotaEstimate(video_adds=300)  # 15,000 units
        output = format_quota_warning(estimate)
        assert "requires ~2 days" in output
        assert "--resume" in output

    def test_no_warning_under_limit(self) -> None:
        """No warning when under daily limit."""
        estimate = QuotaEstimate(video_adds=100)  # 5,000 units
        output = format_quota_warning(estimate)
        assert "requires" not in output
        assert "--resume" not in output
