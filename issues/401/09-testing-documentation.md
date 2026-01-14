# Part 9: Testing & Documentation Requirements

## Testing Strategy

### 9.1 Test Categories

| Category | Focus | Tools | Coverage Target |
|----------|-------|-------|-----------------|
| Unit | Individual functions | pytest, pytest-mock | 90% for new code |
| Integration | API interactions | pytest, responses/httpx-mock | Critical paths |
| E2E | Full command execution | pytest, temp directories | Happy paths |
| Regression | Error handling | pytest, mock exceptions | All error types |

### 9.2 Mock Strategy for API Tests

```python
# tests/conftest.py

import pytest
from unittest.mock import MagicMock, patch
from googleapiclient.errors import HttpError
import httplib2


@pytest.fixture
def mock_youtube_client():
    """Create mock YouTube API client."""
    client = MagicMock()

    # Default successful responses
    client.playlists().list().execute.return_value = {
        "items": [{"id": "PLtest", "snippet": {"title": "Test"}}]
    }
    client.playlistItems().insert().execute.return_value = {
        "id": "item123"
    }

    return client


@pytest.fixture
def quota_exceeded_error():
    """Create 403 quotaExceeded error."""
    resp = httplib2.Response({"status": 403})
    content = b'{"error": {"errors": [{"reason": "quotaExceeded"}]}}'
    return HttpError(resp, content)


@pytest.fixture
def rate_limit_error():
    """Create 429 rate limit error."""
    resp = httplib2.Response({"status": 429})
    content = b'{"error": {"message": "Too Many Requests"}}'
    return HttpError(resp, content)


@pytest.fixture
def mock_yt_dlp():
    """Mock yt-dlp extractor."""
    with patch("ytrix.extractor.YoutubeDL") as mock:
        mock.return_value.__enter__.return_value.extract_info.return_value = {
            "id": "PLtest",
            "title": "Test Playlist",
            "entries": [
                {"id": "vid1", "title": "Video 1"},
                {"id": "vid2", "title": "Video 2"},
            ]
        }
        yield mock
```

### 9.3 Required Test Modules

#### Error Handling Tests

```python
# tests/test_error_handling.py

import pytest
from ytrix.api import classify_error, ErrorCategory, APIError


class TestErrorClassification:
    """Test error classification logic."""

    def test_classify_429_as_rate_limited(self, rate_limit_error):
        """429 errors should be classified as rate limited."""
        error = classify_error(rate_limit_error)
        assert error.category == ErrorCategory.RATE_LIMITED
        assert error.retryable is True

    def test_classify_403_quota_as_not_retryable(self, quota_exceeded_error):
        """403 quotaExceeded should NOT be retryable."""
        error = classify_error(quota_exceeded_error)
        assert error.category == ErrorCategory.QUOTA_EXCEEDED
        assert error.retryable is False

    def test_retry_decorator_skips_quota_errors(
        self, mock_youtube_client, quota_exceeded_error
    ):
        """Retry decorator should not retry quota errors."""
        mock_youtube_client.playlists().insert().execute.side_effect = quota_exceeded_error

        with pytest.raises(HttpError) as exc_info:
            # Function should not retry, should raise immediately
            create_playlist(mock_youtube_client, "Test")

        # Should have been called only once (no retries)
        assert mock_youtube_client.playlists().insert().execute.call_count == 1


class TestBatchErrorHandling:
    """Test batch operation error recovery."""

    def test_batch_pauses_on_quota_exhausted(self, journal, quota_exceeded_error):
        """Batch should pause when quota exhausted."""
        handler = BatchOperationHandler(journal)
        error = classify_error(quota_exceeded_error)

        action = handler.handle_error("task-1", error)

        assert action == BatchAction.STOP_ALL

    def test_batch_continues_on_not_found(self, journal):
        """Batch should skip and continue on 404."""
        handler = BatchOperationHandler(journal)
        error = APIError(
            category=ErrorCategory.NOT_FOUND,
            message="Playlist not found",
            http_status=404,
            retryable=False,
            user_action="Check playlist ID",
        )

        action = handler.handle_error("task-1", error)

        assert action == BatchAction.SKIP_CURRENT
```

#### Quota Tracking Tests

```python
# tests/test_quota.py

import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from ytrix.quota import QuotaTracker, get_time_until_reset


class TestQuotaTracker:
    """Test quota tracking functionality."""

    def test_record_usage_increments_counter(self):
        """Usage recording should increment counter."""
        tracker = QuotaTracker()
        tracker.record_usage(50, "playlists.insert")
        tracker.record_usage(50, "playlistItems.insert")

        assert tracker.get_session_usage() == 100

    def test_remaining_quota_calculation(self):
        """Should correctly calculate remaining quota."""
        tracker = QuotaTracker(daily_limit=10000)
        tracker.record_usage(5000, "test")

        assert tracker.get_remaining() == 5000

    def test_warning_threshold_triggers(self):
        """Should trigger warning at 80% usage."""
        tracker = QuotaTracker(daily_limit=10000, warning_threshold=0.8)
        tracker.record_usage(8000, "test")

        assert tracker.should_warn() is True

    def test_pre_check_blocks_oversized_operation(self):
        """Should block operations that would exceed quota."""
        tracker = QuotaTracker(daily_limit=10000)
        tracker.record_usage(9980, "test")

        can_proceed, reason = tracker.can_proceed(50)

        assert can_proceed is False
        assert "exceed" in reason.lower()


class TestTimeUntilReset:
    """Test Pacific Time reset calculation."""

    def test_reset_calculation_before_midnight(self):
        """Should calculate hours until midnight PT."""
        # Mock time to 6 PM Pacific
        pacific = ZoneInfo("America/Los_Angeles")
        mock_now = datetime(2024, 1, 15, 18, 0, 0, tzinfo=pacific)

        with patch("ytrix.quota.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = get_time_until_reset()

        assert "6h" in result or "5h" in result  # Approximately 6 hours
```

#### Project Context Tests

```python
# tests/test_projects.py

import pytest
from ytrix.projects import ProjectManager


class TestProjectSelection:
    """Test project context selection."""

    def test_select_by_quota_group(self, config_with_projects):
        """Should select project within quota group."""
        manager = ProjectManager(config_with_projects)

        project = manager.select_context(quota_group="personal")

        assert project.quota_group == "personal"

    def test_failover_within_same_group(self, config_with_projects):
        """Failover should stay within same quota group."""
        manager = ProjectManager(config_with_projects)
        manager.select_project("proj-1")  # personal group
        manager._states["proj-1"].is_exhausted = True

        success = manager.handle_quota_exhausted("proj-1")

        assert success is True
        # Should have switched to another project in personal group
        assert manager.current_project.quota_group == "personal"
        assert manager.current_project.name != "proj-1"

    def test_no_cross_group_failover(self, config_with_projects):
        """Should NOT failover across quota groups."""
        manager = ProjectManager(config_with_projects)
        manager.select_project("proj-1")  # personal group

        # Exhaust all personal group projects
        for proj in manager._get_candidates("personal"):
            manager._states[proj.name].is_exhausted = True

        success = manager.handle_quota_exhausted("proj-1")

        assert success is False  # No failover available
```

### 9.4 Integration Test Examples

```python
# tests/test_integration.py

import pytest
from pathlib import Path


@pytest.mark.integration
class TestPlaylistCopy:
    """Integration tests for playlist copying."""

    def test_copy_small_playlist(self, mock_youtube_client, mock_yt_dlp):
        """Should copy a small playlist successfully."""
        result = plist2mlist(
            "PLtest123",
            client=mock_youtube_client,
        )

        assert result["status"] == "success"
        assert "playlist_id" in result

    def test_copy_respects_dedup(self, mock_youtube_client, mock_yt_dlp, tmp_path):
        """Should skip creation when duplicate exists."""
        # Set up: target already has same videos
        mock_youtube_client.playlistItems().list().execute.return_value = {
            "items": [
                {"snippet": {"resourceId": {"videoId": "vid1"}}},
                {"snippet": {"resourceId": {"videoId": "vid2"}}},
            ]
        }

        result = plist2mlist("PLtest", client=mock_youtube_client, dedup=True)

        assert result["status"] == "skipped"
        assert "duplicate" in result["reason"]


@pytest.mark.integration
class TestBatchOperations:
    """Integration tests for batch operations."""

    def test_resume_continues_from_checkpoint(self, tmp_path, mock_youtube_client):
        """Resume should continue from last checkpoint."""
        # Set up journal with partial progress
        journal_path = tmp_path / "journal.json"
        # ... create journal with 50/100 tasks complete

        result = plists2mlists(
            "playlists.txt",
            resume=True,
            journal_path=journal_path,
        )

        # Should only process remaining 50
        assert mock_youtube_client.playlists().insert().execute.call_count <= 50
```

## Documentation Requirements

### 9.5 README Updates

Add sections for:

1. **Multi-Project Setup** (with ToS compliance note)
2. **Quota Management** (explain limits, tracking, warnings)
3. **Error Recovery** (how to resume, what errors mean)
4. **GCP Project Creation** (guided setup walkthrough)

### 9.6 Error Message Catalog

Document all user-facing error messages in `docs/errors.md`:

```markdown
# ytrix Error Reference

## Quota Errors

### QE001: Daily Quota Exceeded
**Message:** "Daily quota exceeded. Resets in Xh Ym (midnight PT)"
**Cause:** The 10,000 unit daily limit has been reached.
**Resolution:**
1. Wait for quota reset at midnight Pacific Time
2. Use `--resume` flag to continue tomorrow
3. Request quota increase: https://support.google.com/youtube/contact/yt_api_form

### QE002: Operation Would Exceed Quota
**Message:** "This operation requires X units but only Y remain"
**Cause:** The requested operation is larger than remaining quota.
**Resolution:**
1. Wait for reset or run partial operation
2. Use `--max-videos N` to limit batch size

## Authentication Errors

### AE001: Token Expired
**Message:** "OAuth token expired. Run: ytrix projects_auth <project>"
...
```

### 9.7 CHANGELOG Entry Template

```markdown
## [Unreleased] - Phase 10

### Added
- ToS-compliant project context management with `quota_group` support
- Rich CLI dashboard for quota visualization (`ytrix quota_status`)
- Enhanced error classification (429 vs 403 distinction)
- Guided GCP project setup with OAuth walkthrough
- ETag-based caching for API reads
- Batch ID batching for video metadata (98% reduction)

### Changed
- Renamed "credential rotation" to "context switching" for clarity
- Restricted automatic project switching to within same `quota_group`
- Improved retry logic: no retries for quota exhaustion (403)
- Enhanced journal schema with error categorization

### Fixed
- Rate limit (429) errors now properly distinguished from quota (403)
- Batch operations now pause gracefully on quota exhaustion
- Journal resume now tracks error categories for better debugging

### Security
- Added ToS compliance warnings for multi-project configurations
- Added validation to prevent obvious quota circumvention patterns
```

## Implementation Checklist

- [ ] Create test fixtures in `tests/conftest.py`
- [ ] Add `test_error_handling.py` with error classification tests
- [ ] Add `test_quota.py` with quota tracking tests
- [ ] Add `test_projects.py` with context selection tests
- [ ] Add `test_journal.py` with enhanced journal tests
- [ ] Add `test_dashboard.py` for CLI display tests
- [ ] Mark integration tests with `@pytest.mark.integration`
- [ ] Update README with multi-project and quota sections
- [ ] Create `docs/errors.md` with error catalog
- [ ] Update CHANGELOG.md with Phase 10 changes
- [ ] Ensure 80%+ coverage for new modules
- [ ] Add GitHub Actions workflow for test automation
