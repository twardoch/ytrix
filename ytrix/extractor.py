"""yt-dlp wrapper for metadata extraction using Python API with caching."""

import time
from typing import Any

from yt_dlp import YoutubeDL

from ytrix import cache
from ytrix.info import _is_rate_limit_error, _ytdlp_throttler
from ytrix.logging import logger
from ytrix.models import Playlist, Video, extract_playlist_id

# Shared options for all yt-dlp operations
_BASE_OPTS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,  # For playlists: get metadata only, not full video info
    "skip_download": True,
}


def _extract_info(url: str, flat: bool = True, max_retries: int = 5) -> dict[str, Any]:
    """Run yt-dlp extract_info with throttling and retry logic."""
    opts = {**_BASE_OPTS, "extract_flat": flat}

    for attempt in range(max_retries):
        _ytdlp_throttler.wait()
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    raise RuntimeError(f"yt-dlp returned no info for {url}")
            _ytdlp_throttler.on_success()
            return info
        except Exception as e:
            is_rate_limit = _is_rate_limit_error(e)
            _ytdlp_throttler.on_error(is_rate_limit=is_rate_limit)

            if attempt < max_retries - 1 and is_rate_limit:
                delay = _ytdlp_throttler.get_retry_delay(attempt)
                logger.warning(
                    "Rate limit on {}, retry {}/{} in {:.1f}s",
                    url[:50],
                    attempt + 1,
                    max_retries,
                    delay,
                )
                time.sleep(delay)
            else:
                raise

    raise RuntimeError(f"Failed to extract info for {url} after {max_retries} attempts")


def extract_playlist(url_or_id: str, use_cache: bool = True) -> Playlist:
    """Extract playlist metadata and video list via yt-dlp with caching.

    Args:
        url_or_id: Playlist URL or ID
        use_cache: Whether to use cached data (default True)

    Returns:
        Playlist with videos populated
    """
    playlist_id = extract_playlist_id(url_or_id)

    # Check cache first
    if use_cache:
        cached = cache.get_cached_playlist_with_videos(playlist_id)
        if cached and cached.videos:
            logger.debug("Using cached playlist: {}", playlist_id)
            return cached

    # Fetch from yt-dlp
    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    data = _extract_info(url, flat=True)

    videos = []
    for i, entry in enumerate(data.get("entries", [])):
        if entry is None:
            continue  # Deleted/private video
        video = Video(
            id=entry.get("id", ""),
            title=entry.get("title", ""),
            channel=entry.get("channel", entry.get("uploader", "")),
            position=i,
            upload_date=entry.get("upload_date"),
        )
        videos.append(video)

    playlist = Playlist(
        id=playlist_id,
        title=data.get("title", ""),
        description=data.get("description", ""),
        privacy="public",  # yt-dlp can't determine privacy
        videos=videos,
    )

    # Cache the result
    cache.cache_playlist_with_videos(playlist)
    logger.debug("Fetched and cached playlist: {} ({} videos)", playlist_id, len(videos))

    return playlist


def extract_video_metadata(video_id: str, use_cache: bool = True) -> Video:
    """Extract single video metadata with caching.

    Args:
        video_id: YouTube video ID
        use_cache: Whether to use cached data (default True)

    Returns:
        Video metadata
    """
    # Check cache first
    if use_cache:
        cached = cache.get_cached_video(video_id)
        if cached:
            logger.debug("Using cached video: {}", video_id)
            return cached

    # Fetch from yt-dlp
    url = f"https://www.youtube.com/watch?v={video_id}"
    data = _extract_info(url, flat=False)  # Need full info for single video

    video = Video(
        id=video_id,
        title=data.get("title", ""),
        channel=data.get("channel", data.get("uploader", "")),
        position=0,
        upload_date=data.get("upload_date"),
    )

    # Cache the result
    cache.cache_video(video)
    logger.debug("Fetched and cached video: {}", video_id)

    return video


def _normalize_channel_url(channel_url: str) -> tuple[str, str]:
    """Normalize channel URL and extract channel ID for caching.

    Returns:
        Tuple of (normalized_url, channel_id_for_cache)
    """
    url = channel_url.strip()
    cache_key = url  # Default cache key

    if url.startswith("@"):
        cache_key = url  # Use handle as cache key
        url = f"https://www.youtube.com/{url}/playlists"
    elif url.startswith("UC") and "/" not in url:
        cache_key = url  # Channel ID
        url = f"https://www.youtube.com/channel/{url}/playlists"
    elif "/playlists" not in url:
        url = url.rstrip("/") + "/playlists"

    return url, cache_key


def extract_channel_playlists(channel_url: str, use_cache: bool = True) -> list[Playlist]:
    """Extract all public playlists from a YouTube channel with caching.

    Args:
        channel_url: Channel URL, handle (@username), or channel ID
        use_cache: Whether to use cached data (default True)

    Returns:
        List of Playlist objects (without videos, just metadata)
    """
    url, cache_key = _normalize_channel_url(channel_url)

    # Check cache first
    if use_cache:
        cached = cache.get_cached_channel_playlists(cache_key)
        if cached:
            logger.debug("Using cached channel playlists: {}", cache_key)
            return cached

    # Fetch from yt-dlp
    data = _extract_info(url, flat=True)

    playlists = []
    for entry in data.get("entries", []):
        if entry is None:
            continue
        playlists.append(
            Playlist(
                id=entry.get("id", ""),
                title=entry.get("title", ""),
                description="",  # Not available from flat playlist
                privacy="public",  # Only public playlists are visible
            )
        )

    # Cache the result
    cache.cache_channel_playlists(cache_key, playlists)
    logger.debug("Fetched and cached {} playlists for channel: {}", len(playlists), cache_key)

    return playlists


def extract_channel_playlists_with_videos(channel_url: str) -> list[Playlist]:
    """Extract all public playlists from a channel WITH their video lists.

    Uses yt-dlp for all reads (0 API quota). Useful for deduplication.

    Args:
        channel_url: Channel URL, handle (@username), or channel ID

    Returns:
        List of Playlist objects with videos populated
    """
    playlists = extract_channel_playlists(channel_url)
    for playlist in playlists:
        try:
            full = extract_playlist(playlist.id)
            playlist.videos = full.videos
        except Exception:
            pass  # Skip playlists we can't read
    return playlists


def get_playlist_video_ids(url_or_id: str) -> set[str]:
    """Get just the video IDs from a playlist (fast, no API quota).

    Args:
        url_or_id: Playlist URL or ID

    Returns:
        Set of video IDs
    """
    playlist = extract_playlist(url_or_id)
    return {v.id for v in playlist.videos}


def get_video_count(url_or_id: str) -> int:
    """Get video count for a playlist (no API quota).

    Args:
        url_or_id: Playlist URL or ID

    Returns:
        Number of videos in playlist
    """
    playlist = extract_playlist(url_or_id)
    return len(playlist.videos)
