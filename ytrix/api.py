"""YouTube API client with OAuth2 authentication."""

import json
from dataclasses import dataclass
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

SCOPES = ["https://www.googleapis.com/auth/youtube"]
console = Console(stderr=True)


def _is_retryable_error(exc: BaseException) -> bool:
    """Check if an HTTP error is retryable (rate limit, server error)."""
    if isinstance(exc, HttpError):
        status = exc.resp.status
        # Retry on rate limit (429) and server errors (5xx)
        if status == 429 or status >= 500:
            logger.warning("API error {} (will retry): {}", status, exc.reason)
            return True
    return False


# Retry decorator for API calls: 5 attempts, exponential backoff 1-60s with jitter
api_retry = retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60, jitter=5),
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


@api_retry
def create_playlist(
    client: Resource, title: str, description: str = "", privacy: str = "public"
) -> str:
    """Create a new playlist and return its ID. (50 quota units)"""
    body = {
        "snippet": {"title": title, "description": description},
        "status": {"privacyStatus": privacy},
    }
    response = client.playlists().insert(part="snippet,status", body=body).execute()
    playlist_id: str = response["id"]
    return playlist_id


@api_retry
def update_playlist(
    client: Resource,
    playlist_id: str,
    title: str | None = None,
    description: str | None = None,
    privacy: str | None = None,
) -> None:
    """Update playlist metadata. (51 quota units: 1 list + 50 update)"""
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


@api_retry
def add_video_to_playlist(client: Resource, playlist_id: str, video_id: str) -> str:
    """Add video to playlist and return playlistItem ID. (50 quota units)"""
    body = {
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {"kind": "youtube#video", "videoId": video_id},
        }
    }
    response = client.playlistItems().insert(part="snippet", body=body).execute()
    item_id: str = response["id"]
    return item_id


@api_retry
def remove_video_from_playlist(client: Resource, playlist_item_id: str) -> None:
    """Remove video from playlist by playlistItem ID. (50 quota units)"""
    client.playlistItems().delete(id=playlist_item_id).execute()


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
    """Move a playlist item to a new position."""
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
