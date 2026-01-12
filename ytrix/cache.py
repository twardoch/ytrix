"""SQLite-based cache for YouTube metadata to minimize API calls."""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ytrix.config import get_config_dir
from ytrix.logging import logger
from ytrix.models import Playlist, Video

# Cache TTL settings (in hours)
TTL_PLAYLIST_METADATA = 1  # Playlist title/description can change
TTL_PLAYLIST_VIDEOS = 1  # Video order can change
TTL_VIDEO_METADATA = 24  # Video metadata rarely changes
TTL_CHANNEL_PLAYLISTS = 1  # New playlists can be added

SCHEMA = """
CREATE TABLE IF NOT EXISTS playlists (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    privacy TEXT DEFAULT 'public',
    fetched_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    channel TEXT DEFAULT '',
    upload_date TEXT,
    fetched_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS playlist_videos (
    playlist_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (playlist_id, video_id)
);

CREATE TABLE IF NOT EXISTS channel_playlists (
    channel_id TEXT NOT NULL,
    playlist_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (channel_id, playlist_id)
);

CREATE INDEX IF NOT EXISTS idx_playlist_videos_playlist ON playlist_videos(playlist_id);
CREATE INDEX IF NOT EXISTS idx_channel_playlists_channel ON channel_playlists(channel_id);
"""


def get_cache_path() -> Path:
    """Get path to cache database."""
    return get_config_dir() / "cache.db"


def _now() -> str:
    """Get current timestamp as ISO string."""
    return datetime.now().isoformat()


def _expires(hours: int) -> str:
    """Get expiration timestamp as ISO string."""
    return (datetime.now() + timedelta(hours=hours)).isoformat()


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Get database connection with auto-commit."""
    path = get_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Initialize database schema."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
    logger.debug("Cache database initialized at {}", get_cache_path())


def clear_cache() -> int:
    """Clear all cached data. Returns number of rows deleted."""
    with get_connection() as conn:
        counts = []
        for table in ["playlists", "videos", "playlist_videos", "channel_playlists"]:
            cursor = conn.execute(f"DELETE FROM {table}")  # noqa: S608
            counts.append(cursor.rowcount)
        total = sum(counts)
    logger.info("Cleared {} cached entries", total)
    return total


def clear_expired() -> int:
    """Clear only expired entries. Returns number of rows deleted."""
    now = _now()
    with get_connection() as conn:
        counts = []
        for table in ["playlists", "videos", "playlist_videos", "channel_playlists"]:
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE expires_at < ?",
                (now,),  # noqa: S608
            )
            counts.append(cursor.rowcount)
        total = sum(counts)
    if total > 0:
        logger.debug("Cleared {} expired cache entries", total)
    return total


def get_cache_stats() -> dict[str, Any]:
    """Get cache statistics."""
    init_db()
    now = _now()
    stats: dict[str, Any] = {"path": str(get_cache_path())}

    with get_connection() as conn:
        for table in ["playlists", "videos", "playlist_videos", "channel_playlists"]:
            row = conn.execute(
                f"SELECT COUNT(*) as total, "  # noqa: S608
                f"SUM(CASE WHEN expires_at >= ? THEN 1 ELSE 0 END) as valid "
                f"FROM {table}",
                (now,),
            ).fetchone()
            stats[table] = {"total": row["total"], "valid": row["valid"] or 0}

    # Calculate size
    path = get_cache_path()
    if path.exists():
        stats["size_bytes"] = path.stat().st_size
        stats["size_mb"] = round(path.stat().st_size / (1024 * 1024), 2)

    return stats


# --- Playlist caching ---


def cache_playlist(playlist: Playlist) -> None:
    """Cache playlist metadata."""
    init_db()
    now = _now()
    expires = _expires(TTL_PLAYLIST_METADATA)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO playlists
                (id, title, description, privacy, fetched_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (playlist.id, playlist.title, playlist.description, playlist.privacy, now, expires),
        )
    logger.debug("Cached playlist {}: {}", playlist.id, playlist.title[:30])


def get_cached_playlist(playlist_id: str) -> Playlist | None:
    """Get playlist from cache if valid."""
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM playlists WHERE id = ? AND expires_at >= ?",
            (playlist_id, _now()),
        ).fetchone()

    if row:
        logger.debug("Cache hit for playlist {}", playlist_id)
        return Playlist(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            privacy=row["privacy"],
        )
    return None


# --- Video caching ---


def cache_video(video: Video) -> None:
    """Cache video metadata."""
    init_db()
    now = _now()
    expires = _expires(TTL_VIDEO_METADATA)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO videos (id, title, channel, upload_date, fetched_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (video.id, video.title, video.channel, video.upload_date, now, expires),
        )


def cache_videos(videos: list[Video]) -> None:
    """Cache multiple videos efficiently."""
    if not videos:
        return
    init_db()
    now = _now()
    expires = _expires(TTL_VIDEO_METADATA)

    with get_connection() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO videos (id, title, channel, upload_date, fetched_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [(v.id, v.title, v.channel, v.upload_date, now, expires) for v in videos],
        )
    logger.debug("Cached {} videos", len(videos))


def get_cached_video(video_id: str) -> Video | None:
    """Get video from cache if valid."""
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM videos WHERE id = ? AND expires_at >= ?",
            (video_id, _now()),
        ).fetchone()

    if row:
        return Video(
            id=row["id"],
            title=row["title"],
            channel=row["channel"],
            position=0,
            upload_date=row["upload_date"],
        )
    return None


# --- Playlist videos caching ---


def cache_playlist_videos(playlist_id: str, videos: list[Video]) -> None:
    """Cache videos for a playlist with their positions."""
    init_db()
    now = _now()
    expires = _expires(TTL_PLAYLIST_VIDEOS)

    with get_connection() as conn:
        # Clear old entries for this playlist
        conn.execute("DELETE FROM playlist_videos WHERE playlist_id = ?", (playlist_id,))

        # Insert new entries
        conn.executemany(
            """
            INSERT INTO playlist_videos (playlist_id, video_id, position, fetched_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(playlist_id, v.id, v.position, now, expires) for v in videos],
        )

    # Also cache the video metadata
    cache_videos(videos)
    logger.debug("Cached {} videos for playlist {}", len(videos), playlist_id)


def get_cached_playlist_videos(playlist_id: str) -> list[Video] | None:
    """Get videos for a playlist from cache if valid."""
    init_db()
    now = _now()

    with get_connection() as conn:
        # Check if we have valid playlist_videos entries
        count = conn.execute(
            "SELECT COUNT(*) FROM playlist_videos WHERE playlist_id = ? AND expires_at >= ?",
            (playlist_id, now),
        ).fetchone()[0]

        if count == 0:
            return None

        # Get videos with positions, joined with video metadata
        rows = conn.execute(
            """
            SELECT v.id, v.title, v.channel, v.upload_date, pv.position
            FROM playlist_videos pv
            JOIN videos v ON pv.video_id = v.id
            WHERE pv.playlist_id = ? AND pv.expires_at >= ?
            ORDER BY pv.position
            """,
            (playlist_id, now),
        ).fetchall()

    if rows:
        logger.debug("Cache hit for playlist {} videos ({} videos)", playlist_id, len(rows))
        return [
            Video(
                id=row["id"],
                title=row["title"],
                channel=row["channel"],
                position=row["position"],
                upload_date=row["upload_date"],
            )
            for row in rows
        ]
    return None


# --- Channel playlists caching ---


def cache_channel_playlists(channel_id: str, playlists: list[Playlist]) -> None:
    """Cache playlists for a channel."""
    init_db()
    now = _now()
    expires = _expires(TTL_CHANNEL_PLAYLISTS)

    with get_connection() as conn:
        # Clear old entries for this channel
        conn.execute("DELETE FROM channel_playlists WHERE channel_id = ?", (channel_id,))

        # Insert new entries
        conn.executemany(
            """
            INSERT INTO channel_playlists (channel_id, playlist_id, fetched_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            [(channel_id, p.id, now, expires) for p in playlists],
        )

    # Also cache the playlist metadata
    for p in playlists:
        cache_playlist(p)

    logger.debug("Cached {} playlists for channel {}", len(playlists), channel_id)


def get_cached_channel_playlists(channel_id: str) -> list[Playlist] | None:
    """Get playlists for a channel from cache if valid."""
    init_db()
    now = _now()

    with get_connection() as conn:
        # Check if we have valid channel_playlists entries
        count = conn.execute(
            "SELECT COUNT(*) FROM channel_playlists WHERE channel_id = ? AND expires_at >= ?",
            (channel_id, now),
        ).fetchone()[0]

        if count == 0:
            return None

        # Get playlist IDs
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.description, p.privacy
            FROM channel_playlists cp
            JOIN playlists p ON cp.playlist_id = p.id
            WHERE cp.channel_id = ? AND cp.expires_at >= ?
            """,
            (channel_id, now),
        ).fetchall()

    if rows:
        logger.debug("Cache hit for channel {} playlists ({} playlists)", channel_id, len(rows))
        return [
            Playlist(
                id=row["id"],
                title=row["title"],
                description=row["description"],
                privacy=row["privacy"],
            )
            for row in rows
        ]
    return None


# --- High-level caching functions ---


def cache_playlist_with_videos(playlist: Playlist) -> None:
    """Cache a playlist with all its videos."""
    cache_playlist(playlist)
    if playlist.videos:
        cache_playlist_videos(playlist.id, playlist.videos)


def get_cached_playlist_with_videos(playlist_id: str) -> Playlist | None:
    """Get a playlist with all its videos from cache."""
    playlist = get_cached_playlist(playlist_id)
    if not playlist:
        return None

    videos = get_cached_playlist_videos(playlist_id)
    if videos is not None:
        playlist.videos = videos

    return playlist
