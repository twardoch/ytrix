"""Data models for ytrix.

These models structure the metadata we pull from YouTube. They map directly 
to the YAML schema we use for configuration and caching.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Video:
    """A YouTube video and its metadata.
    
    Holds the core data for a single video. We use this to track what videos 
    belong where, and to quickly look up details like the channel or upload date.
    """

    id: str
    title: str
    channel: str
    position: int
    upload_date: str | None = None  # YYYYMMDD format for year extraction

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dictionary for YAML serialization.
        
        Strips out empty optional fields (like upload_date) to keep the YAML clean.
        """
        d = {"id": self.id, "title": self.title, "channel": self.channel, "position": self.position}
        if self.upload_date:
            d["upload_date"] = self.upload_date
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any], position: int = 0) -> "Video":
        """Reconstruct a Video from a YAML dictionary.
        
        Fills missing fields with empty strings to prevent NoneType crashes later.
        """
        return cls(
            id=data["id"],
            title=data.get("title", ""),
            channel=data.get("channel", ""),
            position=data.get("position", position),
            upload_date=data.get("upload_date"),
        )


@dataclass
class Playlist:
    """A YouTube playlist containing metadata and its associated videos.
    
    Represents both source playlists we pull from, and destination playlists 
    we write to. It holds a list of Video models.
    """

    id: str
    title: str
    description: str = ""
    privacy: str = "public"  # public, unlisted, private
    videos: list[Video] = field(default_factory=list)

    def to_dict(self, include_videos: bool = True) -> dict[str, Any]:
        """Convert to a dictionary for YAML serialization.
        
        Set include_videos=False to get just the playlist metadata without 
        dumping the entire video list.
        """
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
        """Reconstruct a Video from a YAML dictionary.
        
        Fills missing fields with empty strings to prevent NoneType crashes later.
        """
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
    """Raised when we can't extract a valid playlist ID from a URL or string."""

    pass


def extract_playlist_id(url_or_id: str) -> str:
    """Extract a raw YouTube playlist ID from a URL or string.

    Parses full URLs (e.g., youtube.com/playlist?list=PL123) and returns just the ID.
    If given just an ID, it validates the characters and length.

    Args:
        url_or_id: The URL or ID string to parse.

    Returns:
        A valid YouTube playlist ID.

    Raises:
        InvalidPlaylistError: If the input is empty, lacks an ID, or contains invalid characters.
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
