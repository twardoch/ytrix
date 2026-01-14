"""YouTube API client with OAuth2 authentication."""

import json
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from rich.console import Console
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ytrix.config import Config, get_token_path
from ytrix.logging import logger
from ytrix.models import Playlist, Video
from ytrix.quota import get_time_until_reset, record_quota

SCOPES = ["https://www.googleapis.com/auth/youtube"]
console = Console(stderr=True)


class ErrorCategory(Enum):
    """Categories for API errors to determine handling strategy."""

    RATE_LIMITED = auto()  # 429 - retry with backoff
    QUOTA_EXCEEDED = auto()  # 403 quotaExceeded - stop, wait until midnight PT
    NOT_FOUND = auto()  # 404 - skip item, continue batch
    PERMISSION_DENIED = auto()  # 403 (not quota) - skip item, continue
    INVALID_REQUEST = auto()  # 400 - skip item, log error
    SERVER_ERROR = auto()  # 5xx - retry with backoff
    NETWORK_ERROR = auto()  # Connection errors - retry with backoff
    UNKNOWN = auto()  # Unexpected errors - log and decide based on context


@dataclass
class APIError:
    """Structured API error with handling guidance."""

    category: ErrorCategory
    message: str
    retryable: bool
    user_action: str
    status_code: int | None = None
    reason: str | None = None

    def __str__(self) -> str:
        return f"{self.category.name}: {self.message}"


def classify_error(exc: BaseException) -> APIError:
    """Classify an exception into an APIError with handling guidance.

    Args:
        exc: The exception to classify

    Returns:
        APIError with category, retryability, and user action guidance
    """
    if isinstance(exc, HttpError):
        status = exc.resp.status
        reason = exc.reason or ""

        # Parse error details from response
        error_reason = None
        try:
            error_content = json.loads(exc.content.decode("utf-8"))
            errors = error_content.get("error", {}).get("errors", [])
            if errors:
                error_reason = errors[0].get("reason")
        except (json.JSONDecodeError, AttributeError):
            pass

        # 429 Rate Limit
        if status == 429:
            return APIError(
                category=ErrorCategory.RATE_LIMITED,
                message="Rate limit exceeded. Slowing down requests.",
                retryable=True,
                user_action="Wait a moment. Requests will automatically retry.",
                status_code=status,
                reason=error_reason,
            )

        # 403 Quota Exceeded vs Permission Denied
        if status == 403:
            if error_reason == "quotaExceeded":
                reset_time = get_time_until_reset()
                return APIError(
                    category=ErrorCategory.QUOTA_EXCEEDED,
                    message=f"Daily quota exceeded. Resets in {reset_time} (midnight PT).",
                    retryable=False,
                    user_action="Wait until midnight PT or use --project to switch projects.",
                    status_code=status,
                    reason=error_reason,
                )
            return APIError(
                category=ErrorCategory.PERMISSION_DENIED,
                message=f"Permission denied: {reason}",
                retryable=False,
                user_action="Check playlist ownership or re-authenticate with 'ytrix auth'.",
                status_code=status,
                reason=error_reason,
            )

        # 404 Not Found
        if status == 404:
            return APIError(
                category=ErrorCategory.NOT_FOUND,
                message=f"Resource not found: {reason}",
                retryable=False,
                user_action="Check if the video/playlist exists and is not deleted.",
                status_code=status,
                reason=error_reason,
            )

        # 400 Bad Request
        if status == 400:
            return APIError(
                category=ErrorCategory.INVALID_REQUEST,
                message=f"Invalid request: {reason}",
                retryable=False,
                user_action="Check input data. Video may be unavailable or restricted.",
                status_code=status,
                reason=error_reason,
            )

        # 5xx Server Error
        if status >= 500:
            return APIError(
                category=ErrorCategory.SERVER_ERROR,
                message=f"YouTube server error ({status}): {reason}",
                retryable=True,
                user_action="Server issue. Requests will automatically retry.",
                status_code=status,
                reason=error_reason,
            )

        # Other HTTP errors
        return APIError(
            category=ErrorCategory.UNKNOWN,
            message=f"HTTP error {status}: {reason}",
            retryable=False,
            user_action="Unexpected error. Check logs for details.",
            status_code=status,
            reason=error_reason,
        )

    # Network/connection errors
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return APIError(
            category=ErrorCategory.NETWORK_ERROR,
            message=f"Network error: {exc}",
            retryable=True,
            user_action="Check internet connection. Requests will retry.",
        )

    # Unknown errors
    return APIError(
        category=ErrorCategory.UNKNOWN,
        message=str(exc),
        retryable=False,
        user_action="Unexpected error. Check logs for details.",
    )


class QuotaExceededError(Exception):
    """Raised when daily quota is exceeded (403 quotaExceeded).

    Unlike rate limits (429), quota exceeded cannot be retried until midnight PT.
    """

    pass


class Throttler:
    """Enforces minimum delay between API write operations.

    This helps avoid 429 RATE_LIMIT_EXCEEDED errors by pacing requests.

    Usage:
        throttler = Throttler(delay_ms=200)
        throttler.wait()  # Call before each API write operation
    """

    def __init__(self, delay_ms: int = 200) -> None:
        """Initialize throttler.

        Args:
            delay_ms: Minimum milliseconds between calls (default: 200ms)
        """
        self._delay_ms = delay_ms
        self._last_call: float = 0.0

    @property
    def delay_ms(self) -> int:
        """Current delay in milliseconds."""
        return self._delay_ms

    @delay_ms.setter
    def delay_ms(self, value: int) -> None:
        """Set delay in milliseconds."""
        self._delay_ms = max(0, value)

    def wait(self) -> None:
        """Wait if needed to maintain minimum delay between calls."""
        if self._delay_ms <= 0:
            return

        now = time.monotonic()
        elapsed_ms = (now - self._last_call) * 1000

        if elapsed_ms < self._delay_ms:
            sleep_ms = self._delay_ms - elapsed_ms
            time.sleep(sleep_ms / 1000)

        self._last_call = time.monotonic()

    def increase_delay(self, factor: float = 2.0, max_ms: int = 5000) -> None:
        """Increase delay (e.g., after hitting rate limit)."""
        self._delay_ms = min(int(self._delay_ms * factor), max_ms)
        logger.warning("Increased throttle delay to {}ms", self._delay_ms)

    def reset_delay(self, default_ms: int = 200) -> None:
        """Reset delay to default."""
        self._delay_ms = default_ms


# Global throttler instance (can be configured via set_throttle_delay)
_throttler = Throttler(delay_ms=200)


def set_throttle_delay(delay_ms: int) -> None:
    """Set the global throttle delay for API write operations.

    Args:
        delay_ms: Minimum milliseconds between API calls (0 to disable)
    """
    _throttler.delay_ms = delay_ms
    logger.debug("Throttle delay set to {}ms", delay_ms)


def get_throttle_delay() -> int:
    """Get current throttle delay in milliseconds."""
    return _throttler.delay_ms


def _is_quota_exceeded(exc: HttpError) -> bool:
    """Check if error is daily quota exceeded (403 quotaExceeded)."""
    if exc.resp.status == 403:
        try:
            error_content = json.loads(exc.content.decode("utf-8"))
            errors = error_content.get("error", {}).get("errors", [])
            for error in errors:
                if error.get("reason") == "quotaExceeded":
                    return True
        except (json.JSONDecodeError, AttributeError):
            pass
    return False


def _is_retryable_error(exc: BaseException) -> bool:
    """Check if an HTTP error is retryable using classify_error.

    Returns True for:
    - 429 RATE_LIMIT_EXCEEDED (per-minute rate limit, retryable)
    - 5xx server errors (retryable)
    - Network errors (retryable)

    Returns False for:
    - 403 quotaExceeded (daily quota, NOT retryable until midnight PT)
    - Other client errors (not retryable)
    """
    api_error = classify_error(exc)

    # Log the error with appropriate level
    if api_error.category == ErrorCategory.QUOTA_EXCEEDED:
        logger.error("{}. {}", api_error.message, api_error.user_action)
    elif api_error.category == ErrorCategory.RATE_LIMITED:
        logger.warning("{}. {}", api_error.message, api_error.user_action)
        _throttler.increase_delay()  # Slow down future requests
    elif api_error.retryable:
        logger.warning("{} (will retry)", api_error.message)

    return api_error.retryable


# Retry decorator for API calls: 10 attempts, exponential backoff 2-300s with jitter
# Increased from 5 attempts/60s max to handle sustained rate limits better
api_retry = retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(10),
    wait=wait_exponential_jitter(initial=2, max=300, jitter=5),
    reraise=True,
)


def get_credentials(config: Config) -> Credentials:
    """Get or refresh OAuth2 credentials."""
    token_path = get_token_path()
    creds: Credentials | None = None

    if token_path.exists():
        with open(token_path) as f:
            token_data = json.load(f)
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request

            creds.refresh(Request())
        else:
            # Create client config from our config
            if config.oauth is None:
                msg = "No OAuth credentials configured. Add [oauth] section to config.toml"
                raise ValueError(msg)
            client_config = {
                "installed": {
                    "client_id": config.oauth.client_id,
                    "client_secret": config.oauth.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save token
        with open(token_path, "w") as f:
            json.dump(json.loads(creds.to_json()), f)
        token_path.chmod(0o600)

    return creds


def get_youtube_client(config: Config) -> Resource:
    """Get authenticated YouTube API client."""
    creds = get_credentials(config)
    return build("youtube", "v3", credentials=creds)


@api_retry  # type: ignore[untyped-decorator]
def create_playlist(
    client: Resource, title: str, description: str = "", privacy: str = "public"
) -> str:
    """Create a new playlist and return its ID. (50 quota units)"""
    _throttler.wait()
    body = {
        "snippet": {"title": title, "description": description},
        "status": {"privacyStatus": privacy},
    }
    response = client.playlists().insert(part="snippet,status", body=body).execute()
    record_quota("playlists.insert")
    playlist_id: str = response["id"]
    return playlist_id


@api_retry  # type: ignore[untyped-decorator]
def update_playlist(
    client: Resource,
    playlist_id: str,
    title: str | None = None,
    description: str | None = None,
    privacy: str | None = None,
) -> None:
    """Update playlist metadata. (51 quota units: 1 list + 50 update)"""
    _throttler.wait()
    # First get current data
    current = client.playlists().list(part="snippet,status", id=playlist_id).execute()
    if not current["items"]:
        raise ValueError(f"Playlist not found: {playlist_id}")

    item = current["items"][0]
    body: dict[str, Any] = {"id": playlist_id, "snippet": item["snippet"], "status": item["status"]}

    if title is not None:
        body["snippet"]["title"] = title
    if description is not None:
        body["snippet"]["description"] = description
    if privacy is not None:
        body["status"]["privacyStatus"] = privacy

    client.playlists().update(part="snippet,status", body=body).execute()
    record_quota("playlists.list")  # list call
    record_quota("playlists.update")  # update call


@api_retry  # type: ignore[untyped-decorator]
def add_video_to_playlist(client: Resource, playlist_id: str, video_id: str) -> str:
    """Add video to playlist and return playlistItem ID. (50 quota units)"""
    _throttler.wait()
    body = {
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        }
    }
    response = client.playlistItems().insert(part="snippet", body=body).execute()
    record_quota("playlistItems.insert")
    item_id: str = response["id"]
    return item_id


@api_retry  # type: ignore[untyped-decorator]
def remove_video_from_playlist(client: Resource, playlist_item_id: str) -> None:
    """Remove video from playlist by playlistItem ID. (50 quota units)"""
    _throttler.wait()
    client.playlistItems().delete(id=playlist_item_id).execute()
    record_quota("playlistItems.delete")


def list_my_playlists(client: Resource, channel_id: str) -> list[Playlist]:
    """List all playlists for a channel."""
    playlists = []
    page_token = None

    while True:
        response = (
            client.playlists()
            .list(
                part="snippet,status",
                channelId=channel_id,
                maxResults=50,
                pageToken=page_token,
            )
            .execute()
        )

        for item in response["items"]:
            playlists.append(
                Playlist(
                    id=item["id"],
                    title=item["snippet"]["title"],
                    description=item["snippet"].get("description", ""),
                    privacy=item["status"]["privacyStatus"],
                )
            )

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return playlists


@dataclass
class PlaylistItem:
    """Playlist item with its API ID for updates."""

    item_id: str  # playlistItem ID (for API updates)
    video_id: str
    title: str
    channel: str
    position: int


def get_playlist_items(client: Resource, playlist_id: str) -> list[PlaylistItem]:
    """Get all playlist items with their API IDs for reordering."""
    items = []
    page_token = None
    position = 0

    while True:
        response = (
            client.playlistItems()
            .list(
                part="snippet,contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=page_token,
            )
            .execute()
        )

        for item in response["items"]:
            snippet = item["snippet"]
            items.append(
                PlaylistItem(
                    item_id=item["id"],
                    video_id=snippet["resourceId"]["videoId"],
                    title=snippet.get("title", ""),
                    channel=snippet.get("videoOwnerChannelTitle", ""),
                    position=position,
                )
            )
            position += 1

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return items


def get_playlist_videos(client: Resource, playlist_id: str) -> list[Video]:
    """Get all videos in a playlist."""
    items = get_playlist_items(client, playlist_id)
    return [
        Video(
            id=item.video_id,
            title=item.title,
            channel=item.channel,
            position=item.position,
        )
        for item in items
    ]


def get_playlist_with_videos(client: Resource, playlist_id: str) -> Playlist:
    """Get playlist with all its videos."""
    # Get playlist metadata
    response = client.playlists().list(part="snippet,status", id=playlist_id).execute()
    if not response["items"]:
        raise ValueError(f"Playlist not found: {playlist_id}")

    item = response["items"][0]
    videos = get_playlist_videos(client, playlist_id)

    return Playlist(
        id=playlist_id,
        title=item["snippet"]["title"],
        description=item["snippet"].get("description", ""),
        privacy=item["status"]["privacyStatus"],
        videos=videos,
    )


def update_playlist_item_position(
    client: Resource,
    playlist_id: str,
    item_id: str,
    video_id: str,
    new_position: int,
) -> None:
    """Move a playlist item to a new position. (50 quota units)"""
    _throttler.wait()
    body = {
        "id": item_id,
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
            "position": new_position,
        },
    }
    client.playlistItems().update(part="snippet", body=body).execute()


def reorder_playlist_videos(client: Resource, playlist_id: str, new_video_order: list[str]) -> None:
    """Reorder playlist videos to match the given order.

    Args:
        client: YouTube API client
        playlist_id: Playlist to reorder
        new_video_order: List of video IDs in desired order
    """
    # Get current items with their API IDs
    current_items = get_playlist_items(client, playlist_id)
    item_by_video = {item.video_id: item for item in current_items}

    # Move each video to its target position
    for target_pos, video_id in enumerate(new_video_order):
        if video_id not in item_by_video:
            continue  # Video not in playlist, skip
        item = item_by_video[video_id]
        if item.position != target_pos:
            update_playlist_item_position(client, playlist_id, item.item_id, video_id, target_pos)
            # Update our local tracking (items shift after move)
            for other in current_items:
                if other.video_id != video_id:
                    if item.position < other.position <= target_pos:
                        other.position -= 1
                    elif target_pos <= other.position < item.position:
                        other.position += 1
            item.position = target_pos
