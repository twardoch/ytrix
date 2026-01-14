"""Tests for ytrix.quota module."""

# this_file: tests/test_quota.py

from ytrix.quota import (
    DAILY_QUOTA_LIMIT,
    QUOTA_COSTS,
    QuotaEstimate,
    QuotaTracker,
    can_afford_operation,
    estimate_batch_copy,
    estimate_copy_cost,
    format_quota_warning,
    get_quota_summary,
    get_time_until_reset,
    get_tracker,
    record_quota,
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
        estimate = estimate_batch_copy(num_playlists=5, total_videos=50, skip_existing=2)
        assert estimate.playlist_creates == 3
        assert estimate.video_adds == 50

    def test_with_updates(self) -> None:
        """Counts updates instead of creates."""
        estimate = estimate_batch_copy(num_playlists=5, total_videos=50, update_existing=2)
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


class TestQuotaTracker:
    """Tests for QuotaTracker class."""

    def test_initial_state(self) -> None:
        """Tracker starts with zero usage."""
        tracker = QuotaTracker()
        assert tracker.used == 0
        assert tracker.remaining == DAILY_QUOTA_LIMIT
        assert tracker.usage_percent == 0.0

    def test_record_operation(self) -> None:
        """Records operation and updates usage."""
        tracker = QuotaTracker()
        tracker.record("playlists.insert")
        assert tracker.used == 50
        assert tracker.operations["playlists.insert"] == 1

    def test_record_multiple_operations(self) -> None:
        """Tracks multiple operations separately."""
        tracker = QuotaTracker()
        tracker.record("playlists.insert")
        tracker.record("playlists.insert")
        tracker.record("playlistItems.insert")
        assert tracker.used == 150
        assert tracker.operations["playlists.insert"] == 2
        assert tracker.operations["playlistItems.insert"] == 1

    def test_record_custom_units(self) -> None:
        """Can specify custom quota units."""
        tracker = QuotaTracker()
        tracker.record("custom_op", units=100)
        assert tracker.used == 100

    def test_remaining_calculation(self) -> None:
        """Calculates remaining quota correctly."""
        tracker = QuotaTracker()
        tracker.record("playlists.insert")  # 50 units
        assert tracker.remaining == DAILY_QUOTA_LIMIT - 50

    def test_usage_percent(self) -> None:
        """Calculates usage percentage correctly."""
        tracker = QuotaTracker()
        # Use 1000 out of 10000 = 10%
        for _ in range(20):
            tracker.record("playlists.insert")  # 20 * 50 = 1000
        assert tracker.usage_percent == 10.0

    def test_is_warning_threshold(self) -> None:
        """Warning triggers at 80% usage."""
        tracker = QuotaTracker()
        # Use 8000 units = 80%
        for _ in range(160):
            tracker.record("playlists.insert")  # 160 * 50 = 8000
        assert tracker.is_warning() is True

    def test_not_warning_below_threshold(self) -> None:
        """No warning below 80% usage."""
        tracker = QuotaTracker()
        # Use 7900 units = 79%
        for _ in range(158):
            tracker.record("playlists.insert")  # 158 * 50 = 7900
        assert tracker.is_warning() is False

    def test_is_exceeded(self) -> None:
        """Exceeded when at or over limit."""
        tracker = QuotaTracker()
        # Use exactly 10000 units
        for _ in range(200):
            tracker.record("playlists.insert")  # 200 * 50 = 10000
        assert tracker.is_exceeded() is True

    def test_check_and_warn_exceeded(self) -> None:
        """Returns exceeded message when over limit."""
        tracker = QuotaTracker()
        for _ in range(200):
            tracker.record("playlists.insert")
        warning = tracker.check_and_warn()
        assert warning is not None
        assert "limit reached" in warning

    def test_check_and_warn_warning(self) -> None:
        """Returns warning message when at threshold."""
        tracker = QuotaTracker()
        for _ in range(160):
            tracker.record("playlists.insert")  # 80%
        warning = tracker.check_and_warn()
        assert warning is not None
        assert "80%" in warning

    def test_check_and_warn_ok(self) -> None:
        """Returns None when under threshold."""
        tracker = QuotaTracker()
        tracker.record("playlists.insert")  # 50 units
        assert tracker.check_and_warn() is None

    def test_reset(self) -> None:
        """Reset clears all usage."""
        tracker = QuotaTracker()
        tracker.record("playlists.insert")
        tracker.reset()
        assert tracker.used == 0
        assert len(tracker.operations) == 0

    def test_summary(self) -> None:
        """Summary returns all tracking info."""
        tracker = QuotaTracker()
        tracker.record("playlists.insert")
        summary = tracker.summary()
        assert summary["used"] == 50
        assert summary["remaining"] == DAILY_QUOTA_LIMIT - 50
        assert summary["limit"] == DAILY_QUOTA_LIMIT
        assert summary["usage_percent"] == 0.5
        assert "playlists.insert" in summary["operations"]


class TestGlobalTracker:
    """Tests for global tracker functions."""

    def test_get_tracker(self) -> None:
        """get_tracker returns global tracker instance."""
        tracker = get_tracker()
        assert isinstance(tracker, QuotaTracker)

    def test_record_quota(self) -> None:
        """record_quota updates global tracker."""
        tracker = get_tracker()
        initial = tracker.used
        record_quota("playlistItems.insert")
        assert tracker.used == initial + 50

    def test_get_quota_summary(self) -> None:
        """get_quota_summary returns global tracker summary."""
        summary = get_quota_summary()
        assert "used" in summary
        assert "remaining" in summary
        assert "limit" in summary

    def test_get_time_until_reset(self) -> None:
        """get_time_until_reset returns formatted time string."""
        time_str = get_time_until_reset()
        # Should contain hours and/or minutes
        assert "h" in time_str or "m" in time_str


class TestEstimateCopyCost:
    """Tests for estimate_copy_cost function."""

    def test_with_playlist_create(self) -> None:
        """Includes playlist creation cost when creating new."""
        estimate = estimate_copy_cost(10, create_playlist=True)
        # 1 create (50) + 10 adds (500) + 1 list (1) = 551
        assert estimate.playlist_creates == 1
        assert estimate.video_adds == 10
        assert estimate.list_operations == 1
        assert estimate.total == 551

    def test_without_playlist_create(self) -> None:
        """Skips playlist creation when updating existing."""
        estimate = estimate_copy_cost(10, create_playlist=False)
        # 0 create + 10 adds (500) + 1 list (1) = 501
        assert estimate.playlist_creates == 0
        assert estimate.video_adds == 10
        assert estimate.total == 501

    def test_large_playlist(self) -> None:
        """Calculates correctly for large playlists."""
        estimate = estimate_copy_cost(200, create_playlist=True)
        # 1 create (50) + 200 adds (10000) + 1 list (1) = 10051
        assert estimate.total == 10051
        assert estimate.days_required == 2  # Needs 2 days


class TestCanAffordOperation:
    """Tests for can_afford_operation function."""

    def test_affordable_operation(self) -> None:
        """Returns True for operations within remaining quota."""
        tracker = get_tracker()
        original_used = tracker.used

        # Ensure enough quota
        tracker.used = 0
        estimate = QuotaEstimate(video_adds=10)  # 500 units

        can_afford, msg = can_afford_operation(estimate)

        assert can_afford is True
        assert "available" in msg
        assert "500" in msg

        tracker.used = original_used

    def test_unaffordable_operation(self) -> None:
        """Returns False for operations exceeding remaining quota."""
        tracker = get_tracker()
        original_used = tracker.used
        original_limit = tracker.limit

        # Set up low remaining quota
        tracker.used = 9800
        tracker.limit = 10000  # Only 200 remaining

        estimate = QuotaEstimate(video_adds=10)  # 500 units

        can_afford, msg = can_afford_operation(estimate)

        assert can_afford is False
        assert "Shortage" in msg
        assert "Wait" in msg

        tracker.used = original_used
        tracker.limit = original_limit

    def test_exactly_affordable(self) -> None:
        """Returns True when operation exactly fits remaining quota."""
        tracker = get_tracker()
        original_used = tracker.used
        original_limit = tracker.limit

        tracker.used = 9500
        tracker.limit = 10000  # 500 remaining

        estimate = QuotaEstimate(video_adds=10)  # 500 units exactly

        can_afford, msg = can_afford_operation(estimate)

        assert can_afford is True

        tracker.used = original_used
        tracker.limit = original_limit
