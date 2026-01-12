"""Tests for ytrix.cache module."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from ytrix import cache
from ytrix.models import Playlist, Video


@pytest.fixture
def temp_cache_dir(tmp_path: Path):
    """Use a temporary directory for cache during tests."""
    with patch("ytrix.cache.get_config_dir", return_value=tmp_path):
        yield tmp_path


class TestCacheInit:
    """Tests for cache initialization."""

    def test_init_db_creates_tables(self, temp_cache_dir: Path) -> None:
        """init_db creates all required tables."""
        cache.init_db()
        db_path = temp_cache_dir / "cache.db"
        assert db_path.exists()

        # Verify tables exist by querying them
        with cache.get_connection() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {row["name"] for row in tables}

        assert "playlists" in table_names
        assert "videos" in table_names
        assert "playlist_videos" in table_names
        assert "channel_playlists" in table_names


class TestPlaylistCache:
    """Tests for playlist caching."""

    def test_cache_and_retrieve_playlist(self, temp_cache_dir: Path) -> None:
        """Can cache and retrieve a playlist."""
        playlist = Playlist(
            id="PLtest123",
            title="Test Playlist",
            description="A test playlist",
            privacy="public",
        )

        cache.cache_playlist(playlist)
        cached = cache.get_cached_playlist("PLtest123")

        assert cached is not None
        assert cached.id == "PLtest123"
        assert cached.title == "Test Playlist"
        assert cached.description == "A test playlist"
        assert cached.privacy == "public"

    def test_returns_none_for_missing_playlist(self, temp_cache_dir: Path) -> None:
        """Returns None when playlist not in cache."""
        cache.init_db()
        cached = cache.get_cached_playlist("PLnonexistent")
        assert cached is None

    def test_returns_none_for_expired_playlist(self, temp_cache_dir: Path) -> None:
        """Returns None when playlist has expired."""
        playlist = Playlist(id="PLexpired", title="Expired", privacy="public")
        cache.cache_playlist(playlist)

        # Manually expire the entry
        with cache.get_connection() as conn:
            past = (datetime.now() - timedelta(hours=2)).isoformat()
            conn.execute(
                "UPDATE playlists SET expires_at = ? WHERE id = ?",
                (past, "PLexpired"),
            )

        cached = cache.get_cached_playlist("PLexpired")
        assert cached is None


class TestVideoCache:
    """Tests for video caching."""

    def test_cache_and_retrieve_video(self, temp_cache_dir: Path) -> None:
        """Can cache and retrieve a video."""
        video = Video(
            id="vid123",
            title="Test Video",
            channel="Test Channel",
            position=0,
            upload_date="20231215",
        )

        cache.cache_video(video)
        cached = cache.get_cached_video("vid123")

        assert cached is not None
        assert cached.id == "vid123"
        assert cached.title == "Test Video"
        assert cached.channel == "Test Channel"
        assert cached.upload_date == "20231215"

    def test_cache_multiple_videos(self, temp_cache_dir: Path) -> None:
        """Can cache multiple videos at once."""
        videos = [
            Video(id="v1", title="Video 1", channel="Ch", position=0),
            Video(id="v2", title="Video 2", channel="Ch", position=1),
            Video(id="v3", title="Video 3", channel="Ch", position=2),
        ]

        cache.cache_videos(videos)

        for i, v in enumerate(videos):
            cached = cache.get_cached_video(v.id)
            assert cached is not None
            assert cached.title == f"Video {i + 1}"


class TestPlaylistVideosCache:
    """Tests for playlist videos caching."""

    def test_cache_and_retrieve_playlist_videos(self, temp_cache_dir: Path) -> None:
        """Can cache and retrieve videos for a playlist."""
        videos = [
            Video(id="v1", title="Video 1", channel="Ch", position=0),
            Video(id="v2", title="Video 2", channel="Ch", position=1),
        ]

        cache.cache_playlist_videos("PLtest", videos)
        cached = cache.get_cached_playlist_videos("PLtest")

        assert cached is not None
        assert len(cached) == 2
        assert cached[0].id == "v1"
        assert cached[0].position == 0
        assert cached[1].id == "v2"
        assert cached[1].position == 1

    def test_returns_none_for_missing_playlist_videos(
        self, temp_cache_dir: Path
    ) -> None:
        """Returns None when playlist videos not in cache."""
        cache.init_db()
        cached = cache.get_cached_playlist_videos("PLnonexistent")
        assert cached is None

    def test_replaces_old_entries(self, temp_cache_dir: Path) -> None:
        """Caching new videos replaces old entries."""
        old_videos = [Video(id="old", title="Old", channel="Ch", position=0)]
        new_videos = [Video(id="new", title="New", channel="Ch", position=0)]

        cache.cache_playlist_videos("PLtest", old_videos)
        cache.cache_playlist_videos("PLtest", new_videos)

        cached = cache.get_cached_playlist_videos("PLtest")
        assert cached is not None
        assert len(cached) == 1
        assert cached[0].id == "new"


class TestChannelPlaylistsCache:
    """Tests for channel playlists caching."""

    def test_cache_and_retrieve_channel_playlists(self, temp_cache_dir: Path) -> None:
        """Can cache and retrieve playlists for a channel."""
        playlists = [
            Playlist(id="PL1", title="Playlist 1", privacy="public"),
            Playlist(id="PL2", title="Playlist 2", privacy="public"),
        ]

        cache.cache_channel_playlists("UCtest", playlists)
        cached = cache.get_cached_channel_playlists("UCtest")

        assert cached is not None
        assert len(cached) == 2
        assert cached[0].id == "PL1"
        assert cached[1].id == "PL2"


class TestPlaylistWithVideos:
    """Tests for high-level playlist+videos caching."""

    def test_cache_playlist_with_videos(self, temp_cache_dir: Path) -> None:
        """Can cache a playlist with its videos."""
        playlist = Playlist(
            id="PLfull",
            title="Full Playlist",
            privacy="public",
            videos=[
                Video(id="v1", title="Video 1", channel="Ch", position=0),
                Video(id="v2", title="Video 2", channel="Ch", position=1),
            ],
        )

        cache.cache_playlist_with_videos(playlist)
        cached = cache.get_cached_playlist_with_videos("PLfull")

        assert cached is not None
        assert cached.id == "PLfull"
        assert cached.title == "Full Playlist"
        assert cached.videos is not None
        assert len(cached.videos) == 2
        assert cached.videos[0].id == "v1"


class TestCacheManagement:
    """Tests for cache management operations."""

    def test_clear_cache(self, temp_cache_dir: Path) -> None:
        """clear_cache removes all entries."""
        playlist = Playlist(id="PLclear", title="To Clear", privacy="public")
        video = Video(id="vclear", title="To Clear", channel="Ch", position=0)

        cache.cache_playlist(playlist)
        cache.cache_video(video)

        deleted = cache.clear_cache()
        assert deleted >= 2

        assert cache.get_cached_playlist("PLclear") is None
        assert cache.get_cached_video("vclear") is None

    def test_clear_expired(self, temp_cache_dir: Path) -> None:
        """clear_expired removes only expired entries."""
        # Cache a playlist that will be manually expired
        expired = Playlist(id="PLexpired", title="Expired", privacy="public")
        valid = Playlist(id="PLvalid", title="Valid", privacy="public")

        cache.cache_playlist(expired)
        cache.cache_playlist(valid)

        # Manually expire one entry
        with cache.get_connection() as conn:
            past = (datetime.now() - timedelta(hours=2)).isoformat()
            conn.execute(
                "UPDATE playlists SET expires_at = ? WHERE id = ?",
                (past, "PLexpired"),
            )

        deleted = cache.clear_expired()
        assert deleted >= 1

        assert cache.get_cached_playlist("PLexpired") is None
        assert cache.get_cached_playlist("PLvalid") is not None

    def test_get_cache_stats(self, temp_cache_dir: Path) -> None:
        """get_cache_stats returns statistics."""
        cache.init_db()
        playlist = Playlist(id="PLstats", title="Stats Test", privacy="public")
        cache.cache_playlist(playlist)

        stats = cache.get_cache_stats()

        assert "path" in stats
        assert "playlists" in stats
        assert stats["playlists"]["total"] >= 1
        assert stats["playlists"]["valid"] >= 1
