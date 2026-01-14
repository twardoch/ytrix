"""Tests for ytrix.extractor with mocked yt-dlp."""

from unittest.mock import MagicMock, patch

import pytest

from ytrix import cache
from ytrix.extractor import (
    extract_channel_playlists,
    extract_channel_playlists_with_videos,
    extract_playlist,
    extract_video_metadata,
    get_playlist_video_ids,
    get_video_count,
)


@pytest.fixture(autouse=True)
def clear_cache_before_test() -> None:
    """Clear the cache before each test to prevent test pollution."""
    cache.init_db()
    cache.clear_cache()


def _mock_ydl(return_value: dict) -> MagicMock:
    """Create a mock YoutubeDL context manager that returns given data."""
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = return_value
    mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
    mock_ydl.__exit__ = MagicMock(return_value=False)
    return mock_ydl


class TestExtractPlaylist:
    """Tests for extract_playlist function."""

    def test_extracts_playlist_metadata(self) -> None:
        """Extracts playlist title and description."""
        playlist_data = {
            "id": "PLtest123",
            "title": "My Test Playlist",
            "description": "A test playlist",
            "entries": [],
        }
        mock_ydl = _mock_ydl(playlist_data)

        with patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl):
            playlist = extract_playlist("PLtest123")
            assert playlist.id == "PLtest123"
            assert playlist.title == "My Test Playlist"
            assert playlist.description == "A test playlist"
            assert playlist.privacy == "public"

    def test_extracts_videos_from_entries(self) -> None:
        """Extracts video list from entries."""
        playlist_data = {
            "id": "PLtest",
            "title": "Test",
            "entries": [
                {
                    "id": "vid1",
                    "title": "Video 1",
                    "channel": "Channel A",
                    "upload_date": "20230101",
                },
                {"id": "vid2", "title": "Video 2", "uploader": "Channel B"},
            ],
        }
        mock_ydl = _mock_ydl(playlist_data)

        with patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl):
            playlist = extract_playlist("PLtest")
            assert len(playlist.videos) == 2
            assert playlist.videos[0].id == "vid1"
            assert playlist.videos[0].title == "Video 1"
            assert playlist.videos[0].channel == "Channel A"
            assert playlist.videos[0].upload_date == "20230101"
            assert playlist.videos[0].position == 0
            assert playlist.videos[1].id == "vid2"
            assert playlist.videos[1].channel == "Channel B"  # Falls back to uploader
            assert playlist.videos[1].position == 1

    def test_skips_none_entries(self) -> None:
        """Skips None entries (deleted/private videos)."""
        playlist_data = {
            "id": "PLtest",
            "title": "Test",
            "entries": [
                {"id": "vid1", "title": "Video 1", "channel": "Ch"},
                None,  # Deleted video
                {"id": "vid3", "title": "Video 3", "channel": "Ch"},
            ],
        }
        mock_ydl = _mock_ydl(playlist_data)

        with patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl):
            playlist = extract_playlist("PLtest")
            assert len(playlist.videos) == 2
            assert playlist.videos[0].id == "vid1"
            assert playlist.videos[1].id == "vid3"

    def test_extracts_from_url(self) -> None:
        """Extracts playlist ID from full URL."""
        playlist_data = {"id": "PLfromurl", "title": "Test", "entries": []}
        mock_ydl = _mock_ydl(playlist_data)

        with patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl):
            playlist = extract_playlist("https://youtube.com/playlist?list=PLfromurl")
            assert playlist.id == "PLfromurl"

    def test_raises_on_none_result(self) -> None:
        """Raises RuntimeError when yt-dlp returns None."""
        mock_ydl = _mock_ydl(None)  # type: ignore[arg-type]

        with (
            patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl),
            pytest.raises(RuntimeError, match="yt-dlp returned no info"),
        ):
            extract_playlist("PLbadid")


class TestExtractVideoMetadata:
    """Tests for extract_video_metadata function."""

    def test_extracts_video_metadata(self) -> None:
        """Extracts video title, channel, and upload_date."""
        video_data = {
            "id": "abc123",
            "title": "Test Video",
            "channel": "Test Channel",
            "upload_date": "20231215",
        }
        mock_ydl = _mock_ydl(video_data)

        with patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl):
            video = extract_video_metadata("abc123")
            assert video.id == "abc123"
            assert video.title == "Test Video"
            assert video.channel == "Test Channel"
            assert video.upload_date == "20231215"
            assert video.position == 0

    def test_falls_back_to_uploader(self) -> None:
        """Falls back to uploader if channel not present."""
        video_data = {"id": "xyz", "title": "Test", "uploader": "Uploader Name"}
        mock_ydl = _mock_ydl(video_data)

        with patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl):
            video = extract_video_metadata("xyz")
            assert video.channel == "Uploader Name"

    def test_raises_on_none_result(self) -> None:
        """Raises RuntimeError when yt-dlp returns None."""
        mock_ydl = _mock_ydl(None)  # type: ignore[arg-type]

        with (
            patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl),
            pytest.raises(RuntimeError, match="yt-dlp returned no info"),
        ):
            extract_video_metadata("badid")


class TestExtractChannelPlaylists:
    """Tests for extract_channel_playlists function."""

    def test_extracts_playlists_from_handle(self) -> None:
        """Extracts playlists using @handle."""
        channel_data = {
            "id": "UCtest",
            "title": "Test Channel - Playlists",
            "entries": [
                {"id": "PLlist1", "title": "Playlist One"},
                {"id": "PLlist2", "title": "Playlist Two"},
            ],
        }
        mock_ydl = _mock_ydl(channel_data)

        with patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl):
            playlists = extract_channel_playlists("@testchannel")
            assert len(playlists) == 2
            assert playlists[0].id == "PLlist1"
            assert playlists[0].title == "Playlist One"
            assert playlists[1].id == "PLlist2"
            # Check URL was constructed correctly
            call_args = mock_ydl.extract_info.call_args
            assert "https://www.youtube.com/@testchannel/playlists" in call_args[0]

    def test_extracts_playlists_from_channel_id(self) -> None:
        """Extracts playlists using channel ID."""
        channel_data = {"id": "UCtest", "entries": [{"id": "PLtest", "title": "Test"}]}
        mock_ydl = _mock_ydl(channel_data)

        with patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl):
            playlists = extract_channel_playlists("UCjVBzB6UR5GM5Pk7ooOY8Rw")
            assert len(playlists) == 1
            call_args = mock_ydl.extract_info.call_args
            assert "/channel/UCjVBzB6UR5GM5Pk7ooOY8Rw/playlists" in call_args[0][0]

    def test_extracts_playlists_from_full_url(self) -> None:
        """Extracts playlists from full channel URL."""
        channel_data = {"id": "UCtest", "entries": [{"id": "PLtest", "title": "Test"}]}
        mock_ydl = _mock_ydl(channel_data)

        with patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl):
            playlists = extract_channel_playlists("https://www.youtube.com/@fontlabtv")
            assert len(playlists) == 1
            call_args = mock_ydl.extract_info.call_args
            assert "https://www.youtube.com/@fontlabtv/playlists" in call_args[0][0]

    def test_skips_none_entries(self) -> None:
        """Skips None entries."""
        channel_data = {
            "id": "UCtest",
            "entries": [{"id": "PLtest", "title": "Test"}, None],
        }
        mock_ydl = _mock_ydl(channel_data)

        with patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl):
            playlists = extract_channel_playlists("@test")
            assert len(playlists) == 1

    def test_raises_on_none_result(self) -> None:
        """Raises RuntimeError when yt-dlp returns None."""
        mock_ydl = _mock_ydl(None)  # type: ignore[arg-type]

        with (
            patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl),
            pytest.raises(RuntimeError, match="yt-dlp returned no info"),
        ):
            extract_channel_playlists("@nonexistent")


class TestExtractInfoRetry:
    """Tests for _extract_info retry logic."""

    def test_retries_on_rate_limit_error(self) -> None:
        """Retries when rate limit error occurs."""
        from ytrix.extractor import _extract_info

        call_count = 0

        def create_mock(opts: dict) -> MagicMock:  # type: ignore[type-arg]
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            mock.__enter__ = MagicMock(return_value=mock)
            mock.__exit__ = MagicMock(return_value=False)
            if call_count < 3:
                mock.extract_info.side_effect = Exception("HTTP Error 429: Too Many Requests")
            else:
                mock.extract_info.return_value = {"id": "test", "title": "Test", "entries": []}
            return mock

        with (
            patch("ytrix.extractor.YoutubeDL", side_effect=create_mock),
            patch("ytrix.extractor.time.sleep"),
        ):
            result = _extract_info("https://example.com", max_retries=5)

        assert call_count == 3
        assert result["id"] == "test"

    def test_raises_after_max_retries(self) -> None:
        """Raises exception after max retries exhausted."""
        from ytrix.extractor import _extract_info

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = Exception("HTTP Error 429: Too Many Requests")

        with (
            patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl),
            patch("ytrix.extractor.time.sleep"),
            pytest.raises(Exception, match="429"),
        ):
            _extract_info("https://example.com", max_retries=2)

    def test_no_retry_on_non_rate_limit_error(self) -> None:
        """Does not retry on non-rate-limit errors."""
        from ytrix.extractor import _extract_info

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = Exception("Video not found")

        with (
            patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl),
            pytest.raises(Exception, match="Video not found"),
        ):
            _extract_info("https://example.com", max_retries=5)

        # Should only be called once since it's not a rate limit error
        assert mock_ydl.extract_info.call_count == 1


class TestCacheHitPaths:
    """Tests for cache hit paths in extractor functions."""

    def test_extract_playlist_uses_cache(self) -> None:
        """Returns cached playlist without calling yt-dlp."""
        from ytrix.models import Playlist, Video

        # Pre-populate cache - need both metadata and videos
        playlist = Playlist(
            id="PLcached",
            title="Cached Playlist",
            description="From cache",
            privacy="public",
            videos=[Video(id="vid1", title="Video 1", channel="Ch", position=0)],
        )
        cache.cache_playlist(playlist)
        cache.cache_playlist_videos(playlist.id, playlist.videos)

        mock_ydl = _mock_ydl({"should": "not be called"})
        with patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl):
            result = extract_playlist("PLcached", use_cache=True)

        assert result.id == "PLcached"
        assert result.title == "Cached Playlist"
        assert len(result.videos) == 1
        # yt-dlp should NOT have been called
        mock_ydl.extract_info.assert_not_called()

    def test_extract_video_uses_cache(self) -> None:
        """Returns cached video without calling yt-dlp."""
        from ytrix.models import Video

        # Pre-populate cache
        video = Video(id="vidcached", title="Cached Video", channel="Ch", position=0)
        cache.cache_video(video)

        mock_ydl = _mock_ydl({"should": "not be called"})
        with patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl):
            result = extract_video_metadata("vidcached", use_cache=True)

        assert result.id == "vidcached"
        assert result.title == "Cached Video"
        mock_ydl.extract_info.assert_not_called()

    def test_extract_channel_playlists_uses_cache(self) -> None:
        """Returns cached channel playlists without calling yt-dlp."""
        from ytrix.models import Playlist

        # Pre-populate cache with channel playlists
        playlists = [
            Playlist(id="PL1", title="Playlist 1", description="", privacy="public"),
            Playlist(id="PL2", title="Playlist 2", description="", privacy="public"),
        ]
        cache.cache_channel_playlists("@cachedchannel", playlists)

        mock_ydl = _mock_ydl({"should": "not be called"})
        with patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl):
            result = extract_channel_playlists("@cachedchannel", use_cache=True)

        assert len(result) == 2
        assert result[0].id == "PL1"
        mock_ydl.extract_info.assert_not_called()


class TestHelperFunctions:
    """Tests for get_playlist_video_ids and get_video_count."""

    def test_get_playlist_video_ids(self) -> None:
        """Returns set of video IDs from playlist."""
        playlist_data = {
            "id": "PLtest",
            "title": "Test",
            "entries": [
                {"id": "vid1", "title": "V1", "channel": "C"},
                {"id": "vid2", "title": "V2", "channel": "C"},
                {"id": "vid3", "title": "V3", "channel": "C"},
            ],
        }
        mock_ydl = _mock_ydl(playlist_data)

        with patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl):
            video_ids = get_playlist_video_ids("PLtest")

        assert video_ids == {"vid1", "vid2", "vid3"}

    def test_get_video_count(self) -> None:
        """Returns count of videos in playlist."""
        playlist_data = {
            "id": "PLtest",
            "title": "Test",
            "entries": [
                {"id": "vid1", "title": "V1", "channel": "C"},
                {"id": "vid2", "title": "V2", "channel": "C"},
            ],
        }
        mock_ydl = _mock_ydl(playlist_data)

        with patch("ytrix.extractor.YoutubeDL", return_value=mock_ydl):
            count = get_video_count("PLtest")

        assert count == 2


class TestExtractChannelPlaylistsWithVideos:
    """Tests for extract_channel_playlists_with_videos function."""

    def test_extracts_playlists_with_videos(self) -> None:
        """Extracts playlists and populates videos."""
        # Mock for channel playlists extraction
        channel_data = {
            "id": "UCtest",
            "entries": [
                {"id": "PL1", "title": "Playlist 1"},
            ],
        }
        # Mock for individual playlist extraction
        playlist_data = {
            "id": "PL1",
            "title": "Playlist 1",
            "description": "",
            "entries": [
                {"id": "vid1", "title": "V1", "channel": "C"},
            ],
        }

        call_count = 0

        def create_mock(opts: dict) -> MagicMock:  # type: ignore[type-arg]
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            mock.__enter__ = MagicMock(return_value=mock)
            mock.__exit__ = MagicMock(return_value=False)
            # First call is for channel playlists, second for playlist details
            if call_count == 1:
                mock.extract_info.return_value = channel_data
            else:
                mock.extract_info.return_value = playlist_data
            return mock

        with patch("ytrix.extractor.YoutubeDL", side_effect=create_mock):
            # Force sequential mode to ensure deterministic call order
            playlists = extract_channel_playlists_with_videos("@test", parallel=False)

        assert len(playlists) == 1
        assert playlists[0].id == "PL1"
        assert len(playlists[0].videos) == 1
        assert playlists[0].videos[0].id == "vid1"

    def test_skips_failed_playlist_extraction(self) -> None:
        """Continues when individual playlist extraction fails."""
        channel_data = {
            "id": "UCtest",
            "entries": [
                {"id": "PL1", "title": "Playlist 1"},
                {"id": "PL2", "title": "Playlist 2"},
            ],
        }

        call_count = 0

        def create_mock(opts: dict) -> MagicMock:  # type: ignore[type-arg]
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            mock.__enter__ = MagicMock(return_value=mock)
            mock.__exit__ = MagicMock(return_value=False)
            if call_count == 1:
                mock.extract_info.return_value = channel_data
            elif call_count == 2:
                # First playlist fails
                mock.extract_info.side_effect = Exception("Private playlist")
            else:
                # Second playlist succeeds
                mock.extract_info.return_value = {
                    "id": "PL2",
                    "title": "Playlist 2",
                    "entries": [{"id": "vid1", "title": "V", "channel": "C"}],
                }
            return mock

        with patch("ytrix.extractor.YoutubeDL", side_effect=create_mock):
            # Force sequential mode to ensure deterministic call order
            playlists = extract_channel_playlists_with_videos("@test", parallel=False)

        assert len(playlists) == 2
        # First playlist should have no videos (failed)
        assert playlists[0].videos == []
        # Second playlist should have videos
        assert len(playlists[1].videos) == 1
