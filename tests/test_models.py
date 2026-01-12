"""Tests for ytrix.models."""

import pytest

from ytrix.models import InvalidPlaylistError, Playlist, Video, extract_playlist_id


class TestVideo:
    """Tests for Video dataclass."""

    def test_to_dict_basic(self) -> None:
        """Video converts to dict with required fields."""
        video = Video(id="abc123", title="Test Video", channel="Test Channel", position=0)
        result = video.to_dict()
        assert result == {
            "id": "abc123",
            "title": "Test Video",
            "channel": "Test Channel",
            "position": 0,
        }

    def test_to_dict_with_upload_date(self) -> None:
        """Video includes upload_date when present."""
        video = Video(id="abc123", title="Test", channel="Ch", position=0, upload_date="20230115")
        result = video.to_dict()
        assert result["upload_date"] == "20230115"

    def test_from_dict_basic(self) -> None:
        """Video deserializes from dict."""
        data = {"id": "xyz789", "title": "Another", "channel": "Ch", "position": 5}
        video = Video.from_dict(data)
        assert video.id == "xyz789"
        assert video.title == "Another"
        assert video.position == 5

    def test_from_dict_uses_position_param_as_default(self) -> None:
        """Video.from_dict uses position parameter when not in data."""
        data = {"id": "xyz789", "title": "Test", "channel": "Ch"}
        video = Video.from_dict(data, position=10)
        assert video.position == 10

    def test_from_dict_missing_fields(self) -> None:
        """Video.from_dict handles missing optional fields."""
        data = {"id": "abc"}
        video = Video.from_dict(data)
        assert video.id == "abc"
        assert video.title == ""
        assert video.channel == ""


class TestPlaylist:
    """Tests for Playlist dataclass."""

    def test_to_dict_without_videos(self) -> None:
        """Playlist converts to dict without videos."""
        playlist = Playlist(id="PL123", title="My Playlist", description="Desc")
        result = playlist.to_dict(include_videos=False)
        assert result == {
            "id": "PL123",
            "title": "My Playlist",
            "description": "Desc",
            "privacy": "public",
        }

    def test_to_dict_with_videos(self) -> None:
        """Playlist includes videos when requested."""
        video = Video(id="v1", title="Video 1", channel="Ch", position=0)
        playlist = Playlist(id="PL123", title="Test", videos=[video])
        result = playlist.to_dict(include_videos=True)
        assert "videos" in result
        assert len(result["videos"]) == 1
        assert result["videos"][0]["id"] == "v1"

    def test_from_dict_basic(self) -> None:
        """Playlist deserializes from dict."""
        data = {
            "id": "PL456",
            "title": "Loaded Playlist",
            "description": "A description",
            "privacy": "unlisted",
        }
        playlist = Playlist.from_dict(data)
        assert playlist.id == "PL456"
        assert playlist.title == "Loaded Playlist"
        assert playlist.privacy == "unlisted"
        assert playlist.videos == []

    def test_from_dict_with_videos(self) -> None:
        """Playlist deserializes videos from dict."""
        data = {
            "id": "PL789",
            "title": "With Videos",
            "videos": [
                {"id": "v1", "title": "Video 1", "channel": "Ch1"},
                {"id": "v2", "title": "Video 2", "channel": "Ch2"},
            ],
        }
        playlist = Playlist.from_dict(data)
        assert len(playlist.videos) == 2
        assert playlist.videos[0].id == "v1"
        assert playlist.videos[1].position == 1  # Auto-assigned


class TestExtractPlaylistId:
    """Tests for extract_playlist_id function."""

    def test_extracts_from_full_url(self) -> None:
        """Extracts ID from full playlist URL."""
        url = "https://www.youtube.com/playlist?list=PLxxxxxx"
        assert extract_playlist_id(url) == "PLxxxxxx"

    def test_extracts_from_watch_url_with_list(self) -> None:
        """Extracts ID from watch URL with list parameter."""
        url = "https://www.youtube.com/watch?v=abc123&list=PLyyyyyy"
        assert extract_playlist_id(url) == "PLyyyyyy"

    def test_returns_id_as_is(self) -> None:
        """Returns plain ID unchanged."""
        assert extract_playlist_id("PLzzzzz") == "PLzzzzz"

    def test_handles_id_with_special_chars(self) -> None:
        """Handles IDs with dashes and underscores."""
        assert extract_playlist_id("PL_abc-123") == "PL_abc-123"

    def test_strips_whitespace(self) -> None:
        """Strips leading/trailing whitespace."""
        assert extract_playlist_id("  PLtest123  ") == "PLtest123"

    def test_raises_on_empty_string(self) -> None:
        """Raises InvalidPlaylistError on empty input."""
        with pytest.raises(InvalidPlaylistError, match="Empty playlist"):
            extract_playlist_id("")

    def test_raises_on_whitespace_only(self) -> None:
        """Raises InvalidPlaylistError on whitespace-only input."""
        with pytest.raises(InvalidPlaylistError, match="Empty playlist"):
            extract_playlist_id("   ")

    def test_raises_on_invalid_characters(self) -> None:
        """Raises InvalidPlaylistError on invalid characters."""
        with pytest.raises(InvalidPlaylistError, match="Invalid characters"):
            extract_playlist_id("PL!@#$%")

    def test_raises_on_too_short(self) -> None:
        """Raises InvalidPlaylistError on too-short ID."""
        with pytest.raises(InvalidPlaylistError, match="too short"):
            extract_playlist_id("P")

    def test_accepts_various_prefixes(self) -> None:
        """Accepts various YouTube playlist prefixes."""
        assert extract_playlist_id("UUabc123def456") == "UUabc123def456"  # Uploads
        assert extract_playlist_id("LLabc123") == "LLabc123"  # Liked
        assert extract_playlist_id("RDabc") == "RDabc"  # Mix (short)
