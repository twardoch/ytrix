"""Tests for ytrix.api with mocked YouTube API client."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from ytrix.api import (
    APIError,
    ErrorCategory,
    PlaylistItem,
    Throttler,
    _chunk_video_ids,
    _is_quota_exceeded,
    _is_retryable_error,
    _parse_upload_date,
    add_video_to_playlist,
    batch_video_metadata,
    classify_error,
    create_playlist,
    get_credentials,
    get_playlist_items,
    get_playlist_videos,
    get_playlist_with_videos,
    get_throttle_delay,
    get_youtube_client,
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


class TestParseUploadDate:
    """Tests for _parse_upload_date helper."""

    def test_parse_upload_date_when_valid_iso_then_compact(self) -> None:
        """Parses ISO date into YYYYMMDD format."""
        result = _parse_upload_date("2024-02-03T12:34:56Z")
        assert result == "20240203", "Expected YYYYMMDD from ISO date"

    def test_parse_upload_date_when_invalid_then_none(self) -> None:
        """Returns None for invalid or missing dates."""
        assert _parse_upload_date("not-a-date") is None, "Invalid date should return None"
        assert _parse_upload_date(None) is None, "None should return None"


class TestChunkVideoIds:
    """Tests for _chunk_video_ids helper."""

    def test_chunk_video_ids_when_longer_than_size_then_splits(self) -> None:
        """Splits list into multiple chunks of requested size."""
        ids = [f"v{i}" for i in range(55)]
        chunks = _chunk_video_ids(ids, chunk_size=50)
        assert len(chunks) == 2, "Expected two chunks for 55 ids with size 50"
        assert chunks[0] == ids[:50], "First chunk should contain first 50 ids"
        assert chunks[1] == ids[50:], "Second chunk should contain remaining ids"


class TestBatchVideoMetadata:
    """Tests for batch_video_metadata function."""

    def test_batch_video_metadata_when_empty_then_no_calls(self, mock_client: MagicMock) -> None:
        """Returns empty list without API calls for empty input."""
        result = batch_video_metadata(mock_client, [])
        assert result == [], "Expected empty list for empty input"
        mock_client.videos.assert_not_called()

    def test_batch_video_metadata_when_out_of_order_then_matches_input(
        self, mock_client: MagicMock
    ) -> None:
        """Preserves input order even if API returns different order."""
        mock_client.videos().list().execute.return_value = {
            "items": [
                {
                    "id": "a",
                    "snippet": {
                        "title": "Video A",
                        "channelTitle": "Chan",
                        "publishedAt": "2024-01-02T00:00:00Z",
                    },
                },
                {
                    "id": "b",
                    "snippet": {
                        "title": "Video B",
                        "channelTitle": "Chan",
                        "publishedAt": "2024-01-01T00:00:00Z",
                    },
                },
            ]
        }

        result = batch_video_metadata(mock_client, ["b", "a"])

        assert [video.id for video in result] == ["b", "a"], "Expected output order to match input"
        assert result[1].upload_date == "20240102", "Expected parsed YYYYMMDD upload_date"

    def test_batch_video_metadata_when_more_than_50_ids_then_chunks(
        self, mock_client: MagicMock
    ) -> None:
        """Splits requests into 50-id chunks."""
        ids = [f"v{i}" for i in range(60)]
        first_items = [
            {"id": vid, "snippet": {"title": vid, "channelTitle": ""}} for vid in ids[:50]
        ]
        second_items = [
            {"id": vid, "snippet": {"title": vid, "channelTitle": ""}} for vid in ids[50:]
        ]
        mock_client.videos().list().execute.side_effect = [
            {"items": first_items},
            {"items": second_items},
        ]

        with patch("ytrix.api.record_quota") as record_quota:
            result = batch_video_metadata(mock_client, ids)

        assert len(result) == 60, "Expected metadata for all ids"
        assert mock_client.videos().list.call_count == 2, "Expected two API calls for 60 ids"
        first_call = mock_client.videos().list.call_args_list[0].kwargs
        second_call = mock_client.videos().list.call_args_list[1].kwargs
        assert first_call["id"] == ",".join(ids[:50]), "First call should include first 50 ids"
        assert second_call["id"] == ",".join(ids[50:]), "Second call should include remaining ids"
        assert record_quota.call_count == 2, "Expected quota recorded per batch"

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

    def test_quota_exceeded_with_malformed_json(self) -> None:
        """Handles malformed JSON in error response gracefully."""
        resp = MagicMock()
        resp.status = 403
        # Invalid JSON that will cause JSONDecodeError
        content = b"not valid json {{"
        error = HttpError(resp, content, uri="https://api.example.com")
        # Should return False, not raise
        assert _is_quota_exceeded(error) is False

    def test_quota_exceeded_with_missing_error_key(self) -> None:
        """Handles missing error key in response."""
        resp = MagicMock()
        resp.status = 403
        # Valid JSON but missing expected structure
        content = json.dumps({"something": "else"}).encode()
        error = HttpError(resp, content, uri="https://api.example.com")
        assert _is_quota_exceeded(error) is False


class TestClassifyError:
    """Tests for classify_error function and ErrorCategory enum."""

    def _make_http_error(self, status: int, reason: str = "unknown") -> HttpError:
        """Create a mock HttpError."""
        resp = MagicMock()
        resp.status = status
        resp.reason = f"Error: {reason}"
        content = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()
        return HttpError(resp, content, uri="https://api.example.com")

    def test_classifies_429_as_rate_limited(self) -> None:
        """429 errors are classified as RATE_LIMITED."""
        error = self._make_http_error(429, "rateLimitExceeded")
        result = classify_error(error)
        assert result.category == ErrorCategory.RATE_LIMITED
        assert result.retryable is True
        assert "rate limit" in result.message.lower()

    def test_classifies_403_quota_as_quota_exceeded(self) -> None:
        """403 quotaExceeded is classified as QUOTA_EXCEEDED."""
        error = self._make_http_error(403, "quotaExceeded")
        result = classify_error(error)
        assert result.category == ErrorCategory.QUOTA_EXCEEDED
        assert result.retryable is False
        assert "midnight PT" in result.user_action

    def test_classifies_403_forbidden_as_permission_denied(self) -> None:
        """403 forbidden (not quota) is classified as PERMISSION_DENIED."""
        error = self._make_http_error(403, "forbidden")
        result = classify_error(error)
        assert result.category == ErrorCategory.PERMISSION_DENIED
        assert result.retryable is False

    def test_classifies_404_as_not_found(self) -> None:
        """404 errors are classified as NOT_FOUND."""
        error = self._make_http_error(404, "playlistNotFound")
        result = classify_error(error)
        assert result.category == ErrorCategory.NOT_FOUND
        assert result.retryable is False

    def test_classifies_400_as_invalid_request(self) -> None:
        """400 errors are classified as INVALID_REQUEST."""
        error = self._make_http_error(400, "badRequest")
        result = classify_error(error)
        assert result.category == ErrorCategory.INVALID_REQUEST
        assert result.retryable is False

    def test_classifies_500_as_server_error(self) -> None:
        """5xx errors are classified as SERVER_ERROR."""
        error = self._make_http_error(500, "internalError")
        result = classify_error(error)
        assert result.category == ErrorCategory.SERVER_ERROR
        assert result.retryable is True

    def test_classifies_502_as_server_error(self) -> None:
        """502 gateway errors are also SERVER_ERROR."""
        error = self._make_http_error(502, "badGateway")
        result = classify_error(error)
        assert result.category == ErrorCategory.SERVER_ERROR
        assert result.retryable is True

    def test_classifies_connection_error_as_network_error(self) -> None:
        """ConnectionError is classified as NETWORK_ERROR."""
        error = ConnectionError("Connection refused")
        result = classify_error(error)
        assert result.category == ErrorCategory.NETWORK_ERROR
        assert result.retryable is True

    def test_classifies_timeout_as_network_error(self) -> None:
        """TimeoutError is classified as NETWORK_ERROR."""
        error = TimeoutError("Connection timed out")
        result = classify_error(error)
        assert result.category == ErrorCategory.NETWORK_ERROR
        assert result.retryable is True

    def test_classifies_unknown_exception_as_unknown(self) -> None:
        """Unknown exceptions are classified as UNKNOWN."""
        error = ValueError("Something unexpected")
        result = classify_error(error)
        assert result.category == ErrorCategory.UNKNOWN
        assert result.retryable is False

    def test_api_error_str_representation(self) -> None:
        """APIError has useful string representation."""
        error = APIError(
            category=ErrorCategory.RATE_LIMITED,
            message="Rate limit hit",
            retryable=True,
            user_action="Wait and retry",
        )
        assert "RATE_LIMITED" in str(error)
        assert "Rate limit hit" in str(error)

    def test_retryable_error_check_uses_classify_error(self) -> None:
        """_is_retryable_error uses classify_error internally."""
        error_429 = self._make_http_error(429, "rateLimitExceeded")
        error_403 = self._make_http_error(403, "quotaExceeded")

        # 429 should be retryable
        assert _is_retryable_error(error_429) is True
        # 403 quota should not be retryable
        assert _is_retryable_error(error_403) is False


class TestUpdatePlaylistFields:
    """Tests for update_playlist with different field combinations."""

    def test_updates_description_only(self, mock_client: MagicMock) -> None:
        """Updates only description field."""
        mock_client.playlists().list().execute.return_value = {
            "items": [
                {
                    "id": "PL123",
                    "snippet": {"title": "Test", "description": "Old desc"},
                    "status": {"privacyStatus": "public"},
                }
            ]
        }

        update_playlist(mock_client, "PL123", description="New description")

        call_args = mock_client.playlists().update.call_args
        body = call_args.kwargs.get("body", call_args[1].get("body", {}))
        assert body["snippet"]["description"] == "New description"
        assert body["snippet"]["title"] == "Test"  # Unchanged

    def test_updates_privacy_only(self, mock_client: MagicMock) -> None:
        """Updates only privacy field."""
        mock_client.playlists().list().execute.return_value = {
            "items": [
                {
                    "id": "PL123",
                    "snippet": {"title": "Test", "description": "Desc"},
                    "status": {"privacyStatus": "public"},
                }
            ]
        }

        update_playlist(mock_client, "PL123", privacy="private")

        call_args = mock_client.playlists().update.call_args
        body = call_args.kwargs.get("body", call_args[1].get("body", {}))
        assert body["status"]["privacyStatus"] == "private"


class TestGetCredentials:
    """Tests for get_credentials function."""

    def test_loads_credentials_from_token_file(self, tmp_path: Path) -> None:
        """Loads credentials from existing token file."""
        from ytrix.config import Config, OAuthConfig

        config = Config(
            channel_id="UC123",
            oauth=OAuthConfig(client_id="id1", client_secret="s1"),
        )
        token_path = tmp_path / "token.json"
        token_path.write_text('{"token": "test", "refresh_token": "rt"}')

        mock_creds = MagicMock()
        mock_creds.valid = True

        with (
            patch("ytrix.api.get_token_path", return_value=token_path),
            patch(
                "ytrix.api.Credentials.from_authorized_user_info",
                return_value=mock_creds,
            ),
        ):
            result = get_credentials(config)
            assert result is mock_creds

    def test_refreshes_expired_credentials(self, tmp_path: Path) -> None:
        """Refreshes credentials when expired."""
        from ytrix.config import Config, OAuthConfig

        config = Config(
            channel_id="UC123",
            oauth=OAuthConfig(client_id="id1", client_secret="s1"),
        )
        token_path = tmp_path / "token.json"
        token_path.write_text('{"token": "test", "refresh_token": "rt"}')

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "rt"
        mock_creds.to_json.return_value = '{"token": "new"}'

        mock_request = MagicMock()

        with (
            patch("ytrix.api.get_token_path", return_value=token_path),
            patch(
                "ytrix.api.Credentials.from_authorized_user_info",
                return_value=mock_creds,
            ),
            patch("google.auth.transport.requests.Request", return_value=mock_request),
        ):
            result = get_credentials(config)
            mock_creds.refresh.assert_called_once_with(mock_request)
            assert result is mock_creds

    def test_raises_on_missing_oauth_config(self, tmp_path: Path) -> None:
        """Raises ValueError when oauth config is missing."""
        from ytrix.config import Config

        config = Config(channel_id="UC123")  # No oauth
        token_path = tmp_path / "token.json"
        # No token file exists

        with (
            patch("ytrix.api.get_token_path", return_value=token_path),
            pytest.raises(ValueError, match="No OAuth credentials configured"),
        ):
            get_credentials(config)


class TestGetYoutubeClient:
    """Tests for get_youtube_client function."""

    def test_builds_client_with_credentials(self, tmp_path: Path) -> None:
        """Builds YouTube client with credentials."""
        from ytrix.config import Config, OAuthConfig

        config = Config(
            channel_id="UC123",
            oauth=OAuthConfig(client_id="id", client_secret="s"),
        )
        mock_creds = MagicMock()
        mock_client = MagicMock()

        with (
            patch("ytrix.api.get_credentials", return_value=mock_creds),
            patch("ytrix.api.build", return_value=mock_client) as mock_build,
        ):
            result = get_youtube_client(config)
            mock_build.assert_called_once_with("youtube", "v3", credentials=mock_creds)
            assert result is mock_client


class TestReorderPositionLogic:
    """Tests for reorder_playlist_videos position shifting logic."""

    def test_reorder_moves_item_backward(self, mock_client: MagicMock) -> None:
        """Moving item to earlier position shifts other items forward."""
        # Setup: 3 items at positions 0, 1, 2
        mock_items = [
            PlaylistItem(item_id="item0", video_id="vid0", title="V0", channel="C", position=0),
            PlaylistItem(item_id="item1", video_id="vid1", title="V1", channel="C", position=1),
            PlaylistItem(item_id="item2", video_id="vid2", title="V2", channel="C", position=2),
        ]
        mock_client.playlistItems().list().execute.return_value = {
            "items": [
                {
                    "id": item.item_id,
                    "snippet": {
                        "resourceId": {"videoId": item.video_id},
                        "title": item.title,
                        "videoOwnerChannelTitle": item.channel,
                    },
                }
                for item in mock_items
            ]
        }

        # Move vid2 to position 0 (backward move)
        new_order = ["vid2", "vid0", "vid1"]
        reorder_playlist_videos(mock_client, "PL123", new_order)

        # Should have called update for vid2 moving to position 0
        mock_client.playlistItems().update.assert_called()

    def test_reorder_moves_item_forward(self, mock_client: MagicMock) -> None:
        """Moving item to later position shifts other items backward."""
        # Setup: 3 items at positions 0, 1, 2
        mock_items = [
            PlaylistItem(item_id="item0", video_id="vid0", title="V0", channel="C", position=0),
            PlaylistItem(item_id="item1", video_id="vid1", title="V1", channel="C", position=1),
            PlaylistItem(item_id="item2", video_id="vid2", title="V2", channel="C", position=2),
        ]
        mock_client.playlistItems().list().execute.return_value = {
            "items": [
                {
                    "id": item.item_id,
                    "snippet": {
                        "resourceId": {"videoId": item.video_id},
                        "title": item.title,
                        "videoOwnerChannelTitle": item.channel,
                    },
                }
                for item in mock_items
            ]
        }

        # Move vid0 to position 2 (forward move)
        new_order = ["vid1", "vid2", "vid0"]
        reorder_playlist_videos(mock_client, "PL123", new_order)

        # Should have called update
        mock_client.playlistItems().update.assert_called()
