"""Playlist and video info extraction with subtitles.

This module extracts comprehensive info from YouTube playlists including:
- Full video metadata (title, description, duration, etc.)
- Subtitles in all available languages (manual and auto-generated)
- Markdown transcripts derived from subtitles
"""

from __future__ import annotations

import random
import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from yt_dlp import YoutubeDL

from ytrix.logging import logger
from ytrix.models import extract_playlist_id

# --- Rate limiting and retry logic ---


class Throttler:
    """Enforces minimum delay between yt-dlp operations with adaptive backoff.

    Helps avoid 429 RATE_LIMIT_EXCEEDED errors by pacing requests.
    Automatically increases delay when errors occur.
    """

    def __init__(self, delay_ms: int = 500) -> None:
        """Initialize throttler.

        Args:
            delay_ms: Minimum milliseconds between calls (default: 500ms)
        """
        self._delay_ms = delay_ms
        self._base_delay_ms = delay_ms
        self._last_call: float = 0.0
        self._consecutive_errors: int = 0

    @property
    def delay_ms(self) -> int:
        """Current delay in milliseconds."""
        return self._delay_ms

    def wait(self) -> None:
        """Wait if needed to maintain minimum delay between calls."""
        if self._delay_ms <= 0:
            return

        now = time.monotonic()
        elapsed_ms = (now - self._last_call) * 1000

        if elapsed_ms < self._delay_ms:
            sleep_ms = self._delay_ms - elapsed_ms
            # Add small jitter to avoid thundering herd
            jitter = random.uniform(0, sleep_ms * 0.1)
            time.sleep((sleep_ms + jitter) / 1000)

        self._last_call = time.monotonic()

    def on_success(self) -> None:
        """Called after successful request - gradually reduce delay."""
        self._consecutive_errors = 0
        if self._delay_ms > self._base_delay_ms:
            self._delay_ms = max(self._base_delay_ms, int(self._delay_ms * 0.9))

    def on_error(self, is_rate_limit: bool = False) -> None:
        """Called after error - increase delay with exponential backoff."""
        self._consecutive_errors += 1
        if is_rate_limit:
            # Rate limit: aggressive backoff
            self._delay_ms = min(30000, self._delay_ms * 2 + 1000)
            logger.warning("Rate limit hit, throttle delay now {}ms", self._delay_ms)
        else:
            # Other error: modest increase
            self._delay_ms = min(10000, int(self._delay_ms * 1.5))

    def get_retry_delay(self, attempt: int) -> float:
        """Get delay before retry attempt (exponential backoff with jitter)."""
        base = min(60, 2**attempt)  # 2, 4, 8, 16, 32, 60s
        jitter = random.uniform(0, base * 0.5)
        return float(base + jitter)


# Global throttlers for yt-dlp operations
# Base delay is conservative to avoid YouTube rate limits (HTTP 429)
_ytdlp_throttler = Throttler(delay_ms=500)
_subtitle_throttler = Throttler(delay_ms=1000)  # Subtitles are more rate-limited


def set_ytdlp_throttle_delay(delay_ms: int) -> None:
    """Set the throttle delay for yt-dlp operations.

    Args:
        delay_ms: Minimum milliseconds between yt-dlp calls (default: 500)
    """
    _ytdlp_throttler._delay_ms = delay_ms
    _ytdlp_throttler._base_delay_ms = delay_ms


def set_subtitle_throttle_delay(delay_ms: int) -> None:
    """Set the throttle delay for subtitle download operations.

    Args:
        delay_ms: Minimum milliseconds between subtitle downloads (default: 1000)

    Note: YouTube rate-limits subtitle requests more aggressively than video metadata.
    If hitting 429 errors, increase this value (e.g., 2000-3000ms).
    """
    _subtitle_throttler._delay_ms = delay_ms
    _subtitle_throttler._base_delay_ms = delay_ms


def _is_rate_limit_error(exc: BaseException) -> bool:
    """Check if exception indicates a rate limit error."""
    msg = str(exc).lower()
    return "429" in msg or "rate" in msg or "too many" in msg


# --- yt-dlp rate limiting configuration ---
# Based on community experience: 10-20 seconds between requests avoids rate limits.
# See: https://github.com/yt-dlp/yt-dlp/issues/


@dataclass
class YtdlpRateLimitConfig:
    """Configuration for yt-dlp rate limiting.

    These options are passed directly to yt-dlp to avoid YouTube's bot detection.
    Recommended: 10-20 seconds between requests for sustained downloads.
    """

    # Sleep between requests during metadata extraction (seconds)
    sleep_interval_requests: float = 5.0

    # Sleep before each download (min, for randomization)
    sleep_interval: float = 5.0

    # Sleep before each download (max, for randomization)
    # If set, yt-dlp picks random value between sleep_interval and max_sleep_interval
    max_sleep_interval: float = 10.0

    # Sleep before each subtitle download (seconds)
    sleep_interval_subtitles: float = 10.0

    # Rate limit in bytes/sec (e.g., 2_500_000 = 2.5 MB/s), None = no limit
    ratelimit: int | None = None

    def to_ytdlp_opts(self) -> dict[str, Any]:
        """Convert to yt-dlp options dict."""
        opts: dict[str, Any] = {}
        if self.sleep_interval_requests > 0:
            opts["sleep_interval_requests"] = self.sleep_interval_requests
        if self.sleep_interval > 0:
            opts["sleep_interval"] = self.sleep_interval
        if self.max_sleep_interval > 0:
            opts["max_sleep_interval"] = self.max_sleep_interval
        if self.sleep_interval_subtitles > 0:
            opts["sleep_interval_subtitles"] = self.sleep_interval_subtitles
        if self.ratelimit:
            opts["ratelimit"] = self.ratelimit
        return opts


# Global rate limit config - can be modified via configure_ytdlp_rate_limits()
_rate_limit_config = YtdlpRateLimitConfig()


def configure_ytdlp_rate_limits(
    sleep_requests: float | None = None,
    sleep_interval: float | None = None,
    max_sleep_interval: float | None = None,
    sleep_subtitles: float | None = None,
    ratelimit: int | None = None,
) -> None:
    """Configure yt-dlp rate limiting settings.

    Args:
        sleep_requests: Seconds to sleep between requests during extraction
        sleep_interval: Min seconds to sleep before each download
        max_sleep_interval: Max seconds to sleep (for randomization)
        sleep_subtitles: Seconds to sleep before subtitle downloads
        ratelimit: Rate limit in bytes/sec (e.g., 2_500_000 for 2.5 MB/s)
    """
    global _rate_limit_config
    if sleep_requests is not None:
        _rate_limit_config.sleep_interval_requests = sleep_requests
    if sleep_interval is not None:
        _rate_limit_config.sleep_interval = sleep_interval
    if max_sleep_interval is not None:
        _rate_limit_config.max_sleep_interval = max_sleep_interval
    if sleep_subtitles is not None:
        _rate_limit_config.sleep_interval_subtitles = sleep_subtitles
    if ratelimit is not None:
        _rate_limit_config.ratelimit = ratelimit


def get_ytdlp_base_opts(
    quiet: bool = True,
    skip_download: bool = True,
    extract_flat: bool = False,
    include_rate_limits: bool = True,
) -> dict[str, Any]:
    """Get base yt-dlp options with rate limiting.

    Args:
        quiet: Suppress yt-dlp output (default: True)
        skip_download: Don't download video files (default: True)
        extract_flat: Extract flat metadata only (default: False)
        include_rate_limits: Include rate limiting options (default: True)

    Returns:
        Dict of yt-dlp options ready for YoutubeDL()
    """
    opts: dict[str, Any] = {
        "quiet": quiet,
        "no_warnings": quiet,
        "skip_download": skip_download,
    }
    if extract_flat:
        opts["extract_flat"] = True

    if include_rate_limits:
        opts.update(_rate_limit_config.to_ytdlp_opts())

    return opts


@dataclass
class SubtitleInfo:
    """Information about a single subtitle track."""

    lang: str  # ISO language code (e.g., "en", "de")
    source: str  # "manual" or "automatic"
    ext: str  # File extension (e.g., "srt", "vtt")
    url: str | None = None  # URL to download subtitle file


@dataclass
class VideoInfo:
    """Extended video information including subtitles."""

    id: str
    title: str
    description: str
    channel: str
    duration: int  # seconds
    upload_date: str | None = None  # YYYYMMDD format
    view_count: int | None = None
    like_count: int | None = None
    position: int = 0
    subtitles: list[SubtitleInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for YAML."""
        d: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "channel": self.channel,
            "duration": self.duration,
            "duration_formatted": format_duration(self.duration),
        }
        if self.upload_date:
            d["upload_date"] = self.upload_date
        if self.view_count is not None:
            d["view_count"] = self.view_count
        if self.like_count is not None:
            d["like_count"] = self.like_count
        if self.subtitles:
            d["subtitles"] = [
                {"lang": s.lang, "source": s.source, "ext": s.ext} for s in self.subtitles
            ]
        return d


@dataclass
class PlaylistInfo:
    """Extended playlist information."""

    id: str
    title: str
    description: str
    channel: str
    videos: list[VideoInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for YAML."""
        total_duration = sum(v.duration for v in self.videos)
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "channel": self.channel,
            "video_count": len(self.videos),
            "total_duration": total_duration,
            "total_duration_formatted": format_duration(total_duration),
            "videos": {_video_filename(i, v.title): v.to_dict() for i, v in enumerate(self.videos)},
        }


def format_duration(seconds: int) -> str:
    """Format duration in seconds to human-readable HH:MM:SS or MM:SS.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted string like "2:05" or "1:02:05"
    """
    if seconds < 0:
        seconds = 0
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _sanitize_filename(name: str) -> str:
    """Sanitize string for use as filename."""
    # Replace problematic characters
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    # Remove leading/trailing dots and spaces
    name = name.strip(". ")
    # Limit length
    if len(name) > 100:
        name = name[:100].rsplit(" ", 1)[0]
    return name or "untitled"


def _video_filename(position: int, title: str) -> str:
    """Generate filename prefix for video (e.g., '001_Video_Title')."""
    safe_title = _sanitize_filename(title)
    return f"{position + 1:03d}_{safe_title}"


def extract_video_info(video_id: str, max_retries: int = 5) -> VideoInfo:
    """Extract full video metadata including available subtitles.

    Args:
        video_id: YouTube video ID
        max_retries: Maximum retry attempts on rate limit errors

    Returns:
        VideoInfo with all available metadata and subtitle info
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    info = None

    for attempt in range(max_retries):
        _ytdlp_throttler.wait()
        try:
            opts = get_ytdlp_base_opts()
            opts["writesubtitles"] = False
            opts["writeautomaticsub"] = False
            with YoutubeDL(opts) as ydl:  # pyright: ignore[reportArgumentType]
                info = ydl.extract_info(url, download=False)
                if info is None:
                    raise RuntimeError(f"yt-dlp returned no info for {video_id}")
            _ytdlp_throttler.on_success()
            break
        except Exception as e:
            is_rate_limit = _is_rate_limit_error(e)
            _ytdlp_throttler.on_error(is_rate_limit=is_rate_limit)

            if attempt < max_retries - 1 and is_rate_limit:
                delay = _ytdlp_throttler.get_retry_delay(attempt)
                logger.warning(
                    "Rate limit on video {}, retry {}/{} in {:.1f}s",
                    video_id,
                    attempt + 1,
                    max_retries,
                    delay,
                )
                time.sleep(delay)
            else:
                raise

    if info is None:
        raise RuntimeError(f"Failed to extract info for {video_id} after {max_retries} attempts")

    # Collect subtitle info
    subtitles: list[SubtitleInfo] = []

    # Manual subtitles
    for lang, formats in info.get("subtitles", {}).items():
        if formats:
            # Prefer SRT format
            fmt = next((f for f in formats if f.get("ext") == "srt"), formats[0])
            subtitles.append(
                SubtitleInfo(
                    lang=lang,
                    source="manual",
                    ext=fmt.get("ext", "vtt"),
                    url=fmt.get("url"),
                )
            )

    # Auto-generated subtitles (only if no manual for that lang)
    manual_langs = {s.lang for s in subtitles}
    for lang, formats in info.get("automatic_captions", {}).items():
        if lang not in manual_langs and formats:
            # Prefer SRT format
            fmt = next((f for f in formats if f.get("ext") == "srt"), formats[0])
            subtitles.append(
                SubtitleInfo(
                    lang=lang,
                    source="automatic",
                    ext=fmt.get("ext", "vtt"),
                    url=fmt.get("url"),
                )
            )

    return VideoInfo(
        id=video_id,
        title=info.get("title") or "",
        description=info.get("description") or "",
        channel=info.get("channel") or info.get("uploader") or "",
        duration=info.get("duration") or 0,
        upload_date=info.get("upload_date"),
        view_count=info.get("view_count"),
        like_count=info.get("like_count"),
        subtitles=subtitles,
    )


def extract_playlist_info(url_or_id: str, max_retries: int = 5) -> PlaylistInfo:
    """Extract full playlist metadata (without full video details yet).

    Args:
        url_or_id: Playlist URL or ID
        max_retries: Maximum retry attempts on rate limit errors

    Returns:
        PlaylistInfo with basic video list
    """
    playlist_id = extract_playlist_id(url_or_id)
    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    data = None

    for attempt in range(max_retries):
        _ytdlp_throttler.wait()
        try:
            opts = get_ytdlp_base_opts(extract_flat=True)
            with YoutubeDL(opts) as ydl:  # pyright: ignore[reportArgumentType]
                data = ydl.extract_info(url, download=False)
                if data is None:
                    raise RuntimeError(f"yt-dlp returned no info for {playlist_id}")
            _ytdlp_throttler.on_success()
            break
        except Exception as e:
            is_rate_limit = _is_rate_limit_error(e)
            _ytdlp_throttler.on_error(is_rate_limit=is_rate_limit)

            if attempt < max_retries - 1 and is_rate_limit:
                delay = _ytdlp_throttler.get_retry_delay(attempt)
                logger.warning(
                    "Rate limit on playlist {}, retry {}/{} in {:.1f}s",
                    playlist_id,
                    attempt + 1,
                    max_retries,
                    delay,
                )
                time.sleep(delay)
            else:
                raise

    if data is None:
        raise RuntimeError(f"Failed to extract info for {playlist_id} after {max_retries} attempts")

    videos = []
    for i, entry in enumerate(data.get("entries", [])):
        if entry is None:
            continue
        videos.append(
            VideoInfo(
                id=entry.get("id", ""),
                title=entry.get("title") or "",
                description="",  # Not available from flat extract
                channel=entry.get("channel") or entry.get("uploader") or "",
                duration=entry.get("duration") or 0,
                upload_date=entry.get("upload_date"),
                position=i,
            )
        )

    return PlaylistInfo(
        id=playlist_id,
        title=data.get("title") or "",
        description=data.get("description") or "",
        channel=data.get("channel") or data.get("uploader") or "",
        videos=videos,
    )


def download_subtitle(
    sub: SubtitleInfo, video_id: str | None = None, max_retries: int = 5
) -> str | None:
    """Download subtitle content using yt-dlp.

    Uses yt-dlp for downloading to benefit from its rate limiting,
    session management, and retry logic.

    Args:
        sub: SubtitleInfo with language and source info
        video_id: YouTube video ID (required for yt-dlp download)
        max_retries: Maximum retry attempts

    Returns:
        Subtitle file content as string, or None if failed
    """
    if not video_id:
        logger.warning("video_id required for subtitle download")
        return None

    for attempt in range(max_retries):
        _subtitle_throttler.wait()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Configure yt-dlp for subtitle-only download
                opts = get_ytdlp_base_opts()
                opts.update(
                    {
                        "writesubtitles": sub.source == "manual",
                        "writeautomaticsub": sub.source == "automatic",
                        "subtitleslangs": [sub.lang],
                        "subtitlesformat": sub.ext if sub.ext in ("srt", "vtt") else "srt",
                        "outtmpl": f"{tmpdir}/%(id)s.%(ext)s",
                    }
                )

                with YoutubeDL(opts) as ydl:  # pyright: ignore[reportArgumentType]
                    url = f"https://www.youtube.com/watch?v={video_id}"
                    ydl.download([url])

                # Find the downloaded subtitle file
                tmppath = Path(tmpdir)
                sub_files = list(tmppath.glob(f"{video_id}.{sub.lang}.*"))
                if not sub_files:
                    # Try broader pattern (auto subs may have different naming)
                    sub_files = list(tmppath.glob(f"{video_id}.*{sub.lang}*"))

                if sub_files:
                    content = sub_files[0].read_text(encoding="utf-8")
                    _subtitle_throttler.on_success()
                    return content
                else:
                    logger.debug("No subtitle file found for {} lang={}", video_id, sub.lang)
                    return None

        except Exception as e:
            is_rate_limit = _is_rate_limit_error(e)
            _subtitle_throttler.on_error(is_rate_limit=is_rate_limit)
            if is_rate_limit and attempt < max_retries - 1:
                delay = _subtitle_throttler.get_retry_delay(attempt)
                logger.debug("Subtitle rate limit, retry in {:.1f}s", delay)
                time.sleep(delay)
                continue
            logger.warning("Failed to download subtitle for {}: {}", video_id, e)
            return None

    return None


def srt_to_transcript(srt_content: str) -> str:
    """Convert SRT subtitle content to plain text transcript.

    Removes timestamps and sequence numbers, joining text naturally.

    Args:
        srt_content: SRT file content

    Returns:
        Plain text transcript
    """
    lines: list[str] = []
    current_text: list[str] = []

    for line in srt_content.split("\n"):
        line = line.strip()

        # Skip sequence numbers (just digits)
        if line.isdigit():
            continue

        # Skip timestamp lines (contain -->)
        if "-->" in line:
            continue

        # Skip empty lines but flush accumulated text
        if not line:
            if current_text:
                lines.append(" ".join(current_text))
                current_text = []
            continue

        # Remove HTML tags like <font color="#CCCCCC">
        line = re.sub(r"<[^>]+>", "", line)

        # Add text
        if line:
            current_text.append(line)

    # Flush remaining text
    if current_text:
        lines.append(" ".join(current_text))

    # Join paragraphs with double newlines for better readability
    return "\n\n".join(lines)


def vtt_to_transcript(vtt_content: str) -> str:
    """Convert VTT subtitle content to plain text transcript.

    Similar to SRT but handles VTT header and cue settings.

    Args:
        vtt_content: VTT file content

    Returns:
        Plain text transcript
    """
    lines: list[str] = []
    current_text: list[str] = []
    in_header = True

    for line in vtt_content.split("\n"):
        line = line.strip()

        # Skip VTT header
        if in_header:
            if not line or line == "WEBVTT":
                continue
            if "-->" in line:
                in_header = False
            else:
                continue

        # Skip timestamp lines (contain -->)
        if "-->" in line:
            continue

        # Skip empty lines but flush accumulated text
        if not line:
            if current_text:
                lines.append(" ".join(current_text))
                current_text = []
            continue

        # Remove HTML tags and VTT cue tags like <c.colorE5E5E5>
        line = re.sub(r"<[^>]+>", "", line)

        # Add text
        if line:
            current_text.append(line)

    # Flush remaining text
    if current_text:
        lines.append(" ".join(current_text))

    return "\n\n".join(lines)


def subtitle_to_transcript(content: str, ext: str) -> str:
    """Convert subtitle content to plain text based on format.

    Args:
        content: Subtitle file content
        ext: File extension (srt, vtt, etc.)

    Returns:
        Plain text transcript
    """
    if ext == "srt":
        return srt_to_transcript(content)
    elif ext in ("vtt", "webvtt"):
        return vtt_to_transcript(content)
    else:
        # Try SRT parser first, fall back to VTT
        if "-->" in content:
            if "WEBVTT" in content[:50]:
                return vtt_to_transcript(content)
            return srt_to_transcript(content)
        return content  # Unknown format, return as-is


def create_video_markdown(video: VideoInfo, lang: str, transcript: str) -> str:
    """Create markdown file content with YAML frontmatter and transcript.

    Args:
        video: VideoInfo with metadata
        lang: Language code
        transcript: Plain text transcript

    Returns:
        Markdown file content
    """
    duration_str = format_duration(video.duration)

    # Format upload date as YYYY-MM-DD
    upload_date_str = ""
    if video.upload_date and len(video.upload_date) == 8:
        upload_date_str = (
            f"{video.upload_date[:4]}-{video.upload_date[4:6]}-{video.upload_date[6:]}"
        )

    # Build YAML frontmatter
    frontmatter = {
        "id": video.id,
        "title": video.title,
        "channel": video.channel,
        "language": lang,
        "duration": duration_str,
    }
    if upload_date_str:
        frontmatter["upload_date"] = upload_date_str
    if video.description:
        # Truncate long descriptions
        desc = video.description
        if len(desc) > 500:
            desc = desc[:500] + "..."
        frontmatter["description"] = desc

    yaml_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)

    return f"---\n{yaml_str}---\n\n{transcript}\n"


def extract_and_save_playlist_info(
    url_or_id: str,
    output_dir: Path | str,
    max_languages: int = 5,
    progress_callback: Callable[[int, int, str], None] | None = None,
    video_delay: float = 0.5,
) -> PlaylistInfo:
    """Extract full playlist info and save to output directory.

    Creates a folder structure:
    output_dir/
      Playlist_Title/
        001_Video_Title.en.srt
        001_Video_Title.en.md
        playlist.yaml

    Args:
        url_or_id: Playlist URL or ID
        output_dir: Base output directory
        max_languages: Maximum number of language tracks to download per video
        progress_callback: Optional callback(video_index, total_videos, video_title)
        video_delay: Minimum seconds between processing videos (default: 0.5)

    Returns:
        PlaylistInfo with all extracted data
    """
    output_dir = Path(output_dir)

    # Extract playlist metadata
    logger.info("Extracting playlist metadata...")
    playlist = extract_playlist_info(url_or_id)

    # Create playlist folder
    playlist_folder = output_dir / _sanitize_filename(playlist.title)
    playlist_folder.mkdir(parents=True, exist_ok=True)

    total_videos = len(playlist.videos)
    failed_videos: list[str] = []
    logger.info("Processing {} videos...", total_videos)

    for i, video in enumerate(playlist.videos):
        if progress_callback:
            progress_callback(i, total_videos, video.title)

        logger.debug("Processing video {}/{}: {}", i + 1, total_videos, video.title)

        # Add delay between videos to be gentle
        if i > 0 and video_delay > 0:
            time.sleep(video_delay + random.uniform(0, video_delay * 0.2))

        try:
            # Get full video info including subtitles
            full_video = extract_video_info(video.id)
            video.description = full_video.description
            video.duration = full_video.duration
            video.view_count = full_video.view_count
            video.like_count = full_video.like_count
            video.subtitles = full_video.subtitles

            # Generate filename prefix
            file_prefix = _video_filename(i, video.title)

            # Sort subtitles: manual first, then by language
            subs = sorted(
                video.subtitles,
                key=lambda s: (0 if s.source == "manual" else 1, s.lang),
            )

            # Limit number of languages
            seen_langs = set()
            selected_subs = []
            for sub in subs:
                if sub.lang not in seen_langs:
                    selected_subs.append(sub)
                    seen_langs.add(sub.lang)
                if len(selected_subs) >= max_languages:
                    break

            # Download and save subtitles
            for sub in selected_subs:
                content = download_subtitle(sub, video_id=video.id)
                if not content:
                    continue

                # Save subtitle file
                sub_ext = sub.ext if sub.ext in ("srt", "vtt") else "srt"
                sub_path = playlist_folder / f"{file_prefix}.{sub.lang}.{sub_ext}"
                sub_path.write_text(content, encoding="utf-8")

                # Convert to transcript and save markdown
                transcript = subtitle_to_transcript(content, sub.ext)
                md_content = create_video_markdown(video, sub.lang, transcript)
                md_path = playlist_folder / f"{file_prefix}.{sub.lang}.md"
                md_path.write_text(md_content, encoding="utf-8")

                logger.debug("Saved {} subtitle and transcript", sub.lang)

        except Exception as e:
            failed_videos.append(video.id)
            is_rate_limit = _is_rate_limit_error(e)
            if is_rate_limit:
                logger.warning("Rate limit on video {}, skipping (try again later)", video.id)
            else:
                logger.warning("Failed to process video {}: {}", video.id, e)
            continue

    # Save playlist.yaml
    playlist_yaml_path = playlist_folder / "playlist.yaml"
    with open(playlist_yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(playlist.to_dict(), f, default_flow_style=False, allow_unicode=True, width=120)

    # Report summary
    success_count = total_videos - len(failed_videos)
    logger.info("Saved playlist info to {}", playlist_folder)
    logger.info("Processed {}/{} videos successfully", success_count, total_videos)
    if failed_videos:
        logger.warning("Failed videos ({}): {}", len(failed_videos), ", ".join(failed_videos[:5]))
        if len(failed_videos) > 5:
            logger.warning("... and {} more", len(failed_videos) - 5)

    return playlist
