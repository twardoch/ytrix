"""YAML serialization and diff operations."""

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from ytrix.models import Playlist


def playlists_to_yaml(playlists: list[Playlist], include_videos: bool = True) -> str:
    """Serialize playlists to YAML string."""
    data = {"playlists": [p.to_dict(include_videos=include_videos) for p in playlists]}
    result: str = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return result


def yaml_to_playlists(yaml_content: str) -> list[Playlist]:
    """Deserialize YAML string to playlists."""
    data = yaml.safe_load(yaml_content)
    if not data or "playlists" not in data:
        raise ValueError("Invalid YAML: missing 'playlists' key")
    return [Playlist.from_dict(p) for p in data["playlists"]]


def save_yaml(path: Path | str, playlists: list[Playlist], include_videos: bool = True) -> None:
    """Save playlists to YAML file."""
    content = playlists_to_yaml(playlists, include_videos)
    Path(path).write_text(content, encoding="utf-8")


def load_yaml(path: Path | str) -> list[Playlist]:
    """Load playlists from YAML file."""
    content = Path(path).read_text(encoding="utf-8")
    return yaml_to_playlists(content)


def diff_playlists(old: Playlist, new: Playlist) -> dict[str, Any]:
    """Compare two playlist states and return changes."""
    changes: dict[str, Any] = {}

    if old.title != new.title:
        changes["title"] = {"old": old.title, "new": new.title}
    if old.description != new.description:
        changes["description"] = {"old": old.description, "new": new.description}
    if old.privacy != new.privacy:
        changes["privacy"] = {"old": old.privacy, "new": new.privacy}

    # Video changes
    old_ids = [v.id for v in old.videos]
    new_ids = [v.id for v in new.videos]

    removed = [vid for vid in old_ids if vid not in new_ids]
    added = [vid for vid in new_ids if vid not in old_ids]
    reordered = old_ids != new_ids and not (removed or added)

    if removed:
        changes["videos_removed"] = removed
    if added:
        changes["videos_added"] = added
    if reordered:
        changes["videos_reordered"] = True

    return changes
