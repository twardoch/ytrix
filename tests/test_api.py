"""Tests for ytrix.api with mocked YouTube API client."""

import json
import time
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from ytrix.api import (
    PlaylistItem,
    Throttler,
    _is_quota_exceeded,
    _is_retryable_error,
    add_video_to_playlist,
    create_playlist,
    get_playlist_items,
    get_playlist_videos,
    get_playlist_with_videos,
    get_throttle_delay,
    list_my_playlists,
    remove_video_from_playlist,
    reorder_playlist_videos,
    set_throttle_delay,
    update_playlist,
    update_playlist_item_position,
)


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock YouTube API client."""
    return MagicMock()


class TestCreatePlaylist:
    """Tests for create_playlist function."""

    def test_creates_playlist_with_defaults(self, mock_client: MagicMock) -> None:
        """Creates playlist with default privacy."""
        mock_client.playlists().insert().execute.return_value = {"id": "PLnew123"}

        result = create_playlist(mock_client, "Test Playlist")

        assert result == "PLnew123"
        mock_client.playlists().insert.assert_called()

    def test_creates_playlist_with_description(self, mock_client: MagicMock) -> None:
        """Creates playlist with description."""
        mock_client.playlists().insert().execute.return_value = {"id": "PLnew"}

        create_playlist(mock_client, "Test", description="My description")

        call_kwargs = mock_client.playlists().insert.call_args
        body = call_kwargs.kwargs.get("body", call_kwargs[1].get("body", {}))
        assert body["snippet"]["description"] == "My description"

    def test_creates_unlisted_playlist(self, mock_client: MagicMock) -> None:
        """Creates unlisted playlist."""
        mock_client.playlists().insert().execute.return_value = {"id": "PLnew"}

        create_playlist(mock_client, "Test", privacy="unlisted")

        call_kwargs = mock_client.playlists().insert.call_args
        body = call_kwargs.kwargs.get("body", call_kwargs[1].get("body", {}))
        assert body["status"]["privacyStatus"] == "unlisted"


class TestUpdatePlaylist:
    """Tests for update_playlist function."""

    def test_updates_title(self, mock_client: MagicMock) -> None:
        """Updates playlist title."""
        mock_client.playlists().list().execute.return_value = {
            "items": [
                {
                    "id": "PL123",
                    "snippet": {"title": "Old Title", "description": ""},
                    "status": {"privacyStatus": "public"},
                }
            ]
        }

        update_playlist(mock_client, "PL123", title="New Title")

        mock_client.playlists().update.assert_called()

    def test_raises_when_playlist_not_found(self, mock_client: MagicMock) -> None:
        """Raises ValueError when playlist not found."""
        mock_client.playlists().list().execute.return_value = {"items": []}

        with pytest.raises(ValueError, match="Playlist not found"):
            update_playlist(mock_client, "PLbad", title="New")


class TestAddVideoToPlaylist:
    """Tests for add_video_to_playlist function."""

    def test_adds_video_returns_item_id(self, mock_client: MagicMock) -> None:
        """Adds video and returns playlistItem ID."""
        mock_client.playlistItems().insert().execute.return_value = {"id": "item123"}

        result = add_video_to_playlist(mock_client, "PL123", "vid456")

        assert result == "item123"


class TestRemoveVideoFromPlaylist:
    """Tests for remove_video_from_playlist function."""

    def test_removes_video(self, mock_client: MagicMock) -> None:
        """Removes video by item ID."""
        remove_video_from_playlist(mock_client, "item123")

        mock_client.playlistItems().delete.assert_called_with(id="item123")


class TestListMyPlaylists:
    """Tests for list_my_playlists function."""

    def test_returns_playlists(self, mock_client: MagicMock) -> None:
        """Returns list of playlists."""
        mock_client.playlists().list().execute.return_value = {
            "items": [
                {
                    "id": "PL1",
                    "snippet": {"title": "Playlist 1", "description": "Desc 1"},
                    "status": {"privacyStatus": "public"},
                },
                {
                    "id": "PL2",
                    "snippet": {"title": "Playlist 2"},
                    "status": {"privacyStatus": "unlisted"},
                },
            ]
        }

        result = list_my_playlists(mock_client, "UC123")

        assert len(result) == 2
        assert result[0].id == "PL1"
        assert result[0].title == "Playlist 1"
        assert result[1].privacy == "unlisted"

    def test_handles_pagination(self, mock_client: MagicMock) -> None:
        """Handles paginated results."""
        mock_client.playlists().list().execute.side_effect = [
            {
                "items": [
                    {"id": "PL1", "snippet": {"title": "P1"}, "status": {"privacyStatus": "public"}}
                ],
                "nextPageToken": "token123",
            },
            {
                "items": [
                    {"id": "PL2", "snippet": {"title": "P2"}, "status": {"privacyStatus": "public"}}
                ],
            },
        ]

        result = list_my_playlists(mock_client, "UC123")

        assert len(result) == 2


class TestGetPlaylistItems:
    """Tests for get_playlist_items function."""

    def test_returns_items_with_ids(self, mock_client: MagicMock) -> None:
        """Returns PlaylistItem objects with item IDs."""
        mock_client.playlistItems().list().execute.return_value = {
            "items": [
                {
                    "id": "itemA",
                    "snippet": {
                        "resourceId": {"videoId": "vid1"},
                        "title": "Video 1",
                        "videoOwnerChannelTitle": "Channel",
                    },
                },
                {
                    "id": "itemB",
                    "snippet": {
                        "resourceId": {"videoId": "vid2"},
                        "title": "Video 2",
                    },
                },
            ]
        }

        result = get_playlist_items(mock_client, "PL123")

        assert len(result) == 2
        assert isinstance(result[0], PlaylistItem)
        assert result[0].item_id == "itemA"
        assert result[0].video_id == "vid1"
        assert result[0].position == 0
        assert result[1].position == 1


class TestGetPlaylistVideos:
    """Tests for get_playlist_videos function."""

    def test_returns_videos(self, mock_client: MagicMock) -> None:
        """Returns Video objects."""
        mock_client.playlistItems().list().execute.return_value = {
            "items": [
                {
                    "id": "item1",
                    "snippet": {
                        "resourceId": {"videoId": "vid1"},
                        "title": "Video 1",
                        "videoOwnerChannelTitle": "Ch",
                    },
                }
            ]
        }

        result = get_playlist_videos(mock_client, "PL123")

        assert len(result) == 1
        assert result[0].id == "vid1"
        assert result[0].title == "Video 1"


class TestGetPlaylistWithVideos:
    """Tests for get_playlist_with_videos function."""

    def test_returns_playlist_with_videos(self, mock_client: MagicMock) -> None:
        """Returns complete playlist with videos."""
        mock_client.playlists().list().execute.return_value = {
            "items": [
                {
                    "id": "PL123",
                    "snippet": {"title": "My Playlist", "description": "Desc"},
                    "status": {"privacyStatus": "public"},
                }
            ]
        }
        mock_client.playlistItems().list().execute.return_value = {
            "items": [
                {
                    "id": "item1",
                    "snippet": {
                        "resourceId": {"videoId": "vid1"},
                        "title": "V1",
                    },
                }
            ]
        }

        result = get_playlist_with_videos(mock_client, "PL123")

        assert result.id == "PL123"
        assert result.title == "My Playlist"
        assert len(result.videos) == 1

    def test_raises_when_not_found(self, mock_client: MagicMock) -> None:
        """Raises ValueError when playlist not found."""
        mock_client.playlists().list().execute.return_value = {"items": []}

        with pytest.raises(ValueError, match="Playlist not found"):
            get_playlist_with_videos(mock_client, "PLbad")


class TestUpdatePlaylistItemPosition:
    """Tests for update_playlist_item_position function."""

    def test_updates_position(self, mock_client: MagicMock) -> None:
        """Updates item position via API."""
        update_playlist_item_position(mock_client, "PL123", "itemA", "vid1", 5)

        mock_client.playlistItems().update.assert_called()
        call_kwargs = mock_client.playlistItems().update.call_args
        body = call_kwargs.kwargs.get("body", call_kwargs[1].get("body", {}))
        assert body["snippet"]["position"] == 5


class TestReorderPlaylistVideos:
    """Tests for reorder_playlist_videos function."""

    def test_reorders_videos(self, mock_client: MagicMock) -> None:
        """Reorders videos to match new order."""
        # Current order: vid1 (pos 0), vid2 (pos 1)
        mock_client.playlistItems().list().execute.return_value = {
            "items": [
                {"id": "itemA", "snippet": {"resourceId": {"videoId": "vid1"}, "title": "V1"}},
                {"id": "itemB", "snippet": {"resourceId": {"videoId": "vid2"}, "title": "V2"}},
            ]
        }

        # New order: vid2, vid1
        reorder_playlist_videos(mock_client, "PL123", ["vid2", "vid1"])

        # Should have called update to move vid2 to position 0
        mock_client.playlistItems().update.assert_called()

    def test_skips_videos_not_in_playlist(self, mock_client: MagicMock) -> None:
        """Skips videos not found in playlist."""
        mock_client.playlistItems().list().execute.return_value = {
            "items": [
                {"id": "itemA", "snippet": {"resourceId": {"videoId": "vid1"}, "title": "V1"}},
            ]
        }

        # vid2 not in playlist - should not raise
        reorder_playlist_videos(mock_client, "PL123", ["vid2", "vid1"])


class TestThrottler:
    """Tests for Throttler class."""

    def test_default_delay(self) -> None:
        """Default delay is 200ms."""
        throttler = Throttler()
        assert throttler.delay_ms == 200

    def test_custom_delay(self) -> None:
        """Can set custom delay."""
        throttler = Throttler(delay_ms=500)
        assert throttler.delay_ms == 500

    def test_delay_setter(self) -> None:
        """Can change delay after creation."""
        throttler = Throttler(delay_ms=100)
        throttler.delay_ms = 300
        assert throttler.delay_ms == 300

    def test_delay_cannot_be_negative(self) -> None:
        """Negative delay is clamped to 0."""
        throttler = Throttler(delay_ms=100)
        throttler.delay_ms = -50
        assert throttler.delay_ms == 0

    def test_wait_with_zero_delay(self) -> None:
        """Wait does nothing with 0 delay."""
        throttler = Throttler(delay_ms=0)
        start = time.monotonic()
        throttler.wait()
        throttler.wait()
        elapsed = time.monotonic() - start
        assert elapsed < 0.01  # Should be nearly instant

    def test_wait_enforces_delay(self) -> None:
        """Wait enforces minimum delay between calls."""
        throttler = Throttler(delay_ms=50)
        throttler.wait()  # First call sets baseline
        start = time.monotonic()
        throttler.wait()  # Should wait ~50ms
        elapsed_ms = (time.monotonic() - start) * 1000
        assert elapsed_ms >= 40  # Allow some timing tolerance

    def test_increase_delay(self) -> None:
        """Increase delay doubles by default."""
        throttler = Throttler(delay_ms=100)
        throttler.increase_delay()
        assert throttler.delay_ms == 200

    def test_increase_delay_with_max(self) -> None:
        """Increase delay respects max limit."""
        throttler = Throttler(delay_ms=3000)
        throttler.increase_delay(max_ms=5000)
        assert throttler.delay_ms == 5000

    def test_reset_delay(self) -> None:
        """Reset delay returns to default."""
        throttler = Throttler(delay_ms=1000)
        throttler.reset_delay(default_ms=200)
        assert throttler.delay_ms == 200


class TestThrottleGlobalFunctions:
    """Tests for global throttle functions."""

    def test_set_and_get_throttle_delay(self) -> None:
        """Can set and get global throttle delay."""
        original = get_throttle_delay()
        try:
            set_throttle_delay(500)
            assert get_throttle_delay() == 500
        finally:
            set_throttle_delay(original)


class TestErrorHandling:
    """Tests for error detection functions."""

    def _make_http_error(self, status: int, reason: str = "quotaExceeded") -> HttpError:
        """Create a mock HttpError."""
        resp = MagicMock()
        resp.status = status
        content = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()
        return HttpError(resp, content, uri="https://api.example.com")

    def test_quota_exceeded_detected(self) -> None:
        """Detects 403 quotaExceeded error."""
        error = self._make_http_error(403, "quotaExceeded")
        assert _is_quota_exceeded(error) is True

    def test_other_403_not_quota_exceeded(self) -> None:
        """Other 403 errors are not quotaExceeded."""
        error = self._make_http_error(403, "forbidden")
        assert _is_quota_exceeded(error) is False

    def test_429_is_retryable(self) -> None:
        """429 rate limit is retryable."""
        error = self._make_http_error(429, "rateLimitExceeded")
        assert _is_retryable_error(error) is True

    def test_500_is_retryable(self) -> None:
        """5xx server errors are retryable."""
        error = self._make_http_error(500, "internalError")
        assert _is_retryable_error(error) is True

    def test_403_quota_exceeded_not_retryable(self) -> None:
        """403 quotaExceeded is NOT retryable."""
        error = self._make_http_error(403, "quotaExceeded")
        assert _is_retryable_error(error) is False

    def test_400_not_retryable(self) -> None:
        """400 client errors are not retryable."""
        error = self._make_http_error(400, "badRequest")
        assert _is_retryable_error(error) is False
