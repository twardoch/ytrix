"""Data models for ytrix."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Video:
    """Video metadata."""

    id: str
    title: str
    channel: str
    position: int
    upload_date: str | None = None  # YYYYMMDD format for year extraction

    def to_dict(self) -> dict[str, Any]:
        """Serialize for YAML."""
        d = {"id": self.id, "title": self.title, "channel": self.channel, "position": self.position}
        if self.upload_date:
            d["upload_date"] = self.upload_date
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any], position: int = 0) -> "Video":
        """Deserialize from YAML."""
        return cls(
            id=data["id"],
            title=data.get("title", ""),
            channel=data.get("channel", ""),
            position=data.get("position", position),
            upload_date=data.get("upload_date"),
        )


@dataclass
class Playlist:
    """Playlist metadata."""

    id: str
    title: str
    description: str = ""
    privacy: str = "public"  # public, unlisted, private
    videos: list[Video] = field(default_factory=list)

    def to_dict(self, include_videos: bool = True) -> dict[str, Any]:
        """Serialize for YAML."""
        d: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "privacy": self.privacy,
        }
        if include_videos and self.videos:
            d["videos"] = [v.to_dict() for v in self.videos]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Playlist":
        """Deserialize from YAML."""
        videos = []
        if "videos" in data:
            videos = [Video.from_dict(v, i) for i, v in enumerate(data["videos"])]
        return cls(
            id=data["id"],
            title=data["title"],
            description=data.get("description", ""),
            privacy=data.get("privacy", "public"),
            videos=videos,
        )


class InvalidPlaylistError(ValueError):
    """Raised when playlist URL/ID is invalid."""

    pass


def extract_playlist_id(url_or_id: str) -> str:
    """Extract and validate playlist ID from URL or ID.

    Args:
        url_or_id: YouTube playlist URL or playlist ID

    Returns:
        Valid playlist ID

    Raises:
        InvalidPlaylistError: If input is not a valid playlist URL/ID
    """
    url_or_id = url_or_id.strip()
    if not url_or_id:
        raise InvalidPlaylistError("Empty playlist URL/ID")

    playlist_id = url_or_id
    if "list=" in url_or_id:
        # URL format: ...?list=PLxxxxxx or &list=PLxxxxxx
        for part in url_or_id.split("?")[-1].split("&"):
            if part.startswith("list="):
                playlist_id = part[5:]
                break

    # Validate: YouTube playlist IDs are alphanumeric with - and _
    # Typical prefixes: PL (user), UU (uploads), LL (liked), FL (favorites), RD (mix)
    if not playlist_id:
        raise InvalidPlaylistError(f"No playlist ID found in: {url_or_id}")

    # Allow alphanumeric, dash, underscore. Min 10 chars (mixes can be shorter)
    valid_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    if not all(c in valid_chars for c in playlist_id):
        raise InvalidPlaylistError(f"Invalid characters in playlist ID: {playlist_id}")

    if len(playlist_id) < 2:
        raise InvalidPlaylistError(f"Playlist ID too short: {playlist_id}")

    return playlist_id
