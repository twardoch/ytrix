"""Shared pytest fixtures for ytrix tests."""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

# --- HTTP Error Fixtures ---


def make_http_error(status: int, reason: str = "unknown") -> HttpError:
    """Create a mock HttpError with the given status and reason.

    Args:
        status: HTTP status code (e.g., 400, 403, 404, 429, 500)
        reason: Error reason string (e.g., "quotaExceeded", "rateLimitExceeded")

    Returns:
        HttpError with mocked response and content
    """
    resp = MagicMock()
    resp.status = status
    resp.reason = f"Error: {reason}"
    content = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()
    return HttpError(resp, content, uri="https://www.googleapis.com/youtube/v3/test")


@pytest.fixture
def quota_exceeded_error() -> HttpError:
    """Create a 403 quotaExceeded error."""
    return make_http_error(403, "quotaExceeded")


@pytest.fixture
def rate_limit_error() -> HttpError:
    """Create a 429 rateLimitExceeded error."""
    return make_http_error(429, "rateLimitExceeded")


@pytest.fixture
def not_found_error() -> HttpError:
    """Create a 404 playlistNotFound error."""
    return make_http_error(404, "playlistNotFound")


@pytest.fixture
def bad_request_error() -> HttpError:
    """Create a 400 badRequest error."""
    return make_http_error(400, "badRequest")


@pytest.fixture
def server_error() -> HttpError:
    """Create a 500 internalError error."""
    return make_http_error(500, "internalError")


# --- Mock Client Fixtures ---


@pytest.fixture
def mock_youtube_client() -> MagicMock:
    """Create a mock YouTube API client.

    Returns:
        MagicMock configured to simulate YouTube API Resource
    """
    client = MagicMock()

    # Setup common method chains
    client.playlists().list().execute.return_value = {"items": []}
    client.playlists().insert().execute.return_value = {"id": "PLnew123"}
    client.playlistItems().list().execute.return_value = {"items": []}
    client.playlistItems().insert().execute.return_value = {"id": "PLI123"}
    client.videos().list().execute.return_value = {"items": []}

    return client


# --- yt-dlp Fixtures ---


@pytest.fixture
def mock_ytdlp_info() -> dict[str, Any]:
    """Create a mock yt-dlp extract_info response for a video.

    Returns:
        Dict mimicking yt-dlp video info
    """
    return {
        "id": "dQw4w9WgXcQ",
        "title": "Test Video",
        "description": "Test description",
        "channel": "Test Channel",
        "uploader": "Test Channel",
        "duration": 120,
        "upload_date": "20240115",
        "view_count": 1000000,
        "like_count": 50000,
        "subtitles": {
            "en": [{"ext": "srt", "url": "https://example.com/en.srt"}],
        },
        "automatic_captions": {
            "de": [{"ext": "vtt", "url": "https://example.com/de.vtt"}],
        },
    }


@pytest.fixture
def mock_ytdlp_playlist_info() -> dict[str, Any]:
    """Create a mock yt-dlp extract_info response for a playlist.

    Returns:
        Dict mimicking yt-dlp playlist info
    """
    return {
        "id": "PLtest123",
        "title": "Test Playlist",
        "description": "Test playlist description",
        "uploader": "Test Channel",
        "entries": [
            {
                "id": "vid1",
                "title": "Video 1",
                "channel": "Channel 1",
                "duration": 60,
                "upload_date": "20240101",
            },
            {
                "id": "vid2",
                "title": "Video 2",
                "channel": "Channel 2",
                "duration": 90,
                "upload_date": "20240102",
            },
        ],
    }


# --- Sample Data Fixtures ---


@pytest.fixture
def sample_playlist_data() -> dict[str, Any]:
    """Sample playlist data as returned by YouTube API.

    Returns:
        Dict matching YouTube API playlist response format
    """
    return {
        "id": "PL123abc",
        "snippet": {
            "title": "Sample Playlist",
            "description": "A sample playlist for testing",
            "channelId": "UC123",
            "channelTitle": "Test Channel",
        },
        "status": {"privacyStatus": "public"},
        "contentDetails": {"itemCount": 5},
    }


@pytest.fixture
def sample_video_data() -> dict[str, Any]:
    """Sample video data as returned by YouTube API.

    Returns:
        Dict matching YouTube API video response format
    """
    return {
        "id": "abc123xyz",
        "snippet": {
            "title": "Sample Video",
            "description": "A sample video for testing",
            "channelId": "UC123",
            "channelTitle": "Test Channel",
            "publishedAt": "2024-01-15T10:00:00Z",
        },
        "contentDetails": {"duration": "PT2M30S"},
        "statistics": {"viewCount": "1000", "likeCount": "100"},
    }
