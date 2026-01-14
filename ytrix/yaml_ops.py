"""YAML serialization and diff operations."""

from dataclasses import dataclass, field
from enum import Enum, auto
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


class DiffOperation(Enum):
    """Types of operations needed to sync playlist."""

    UPDATE_METADATA = auto()  # Update title/description/privacy
    ADD_VIDEO = auto()  # Insert video at position
    REMOVE_VIDEO = auto()  # Remove video from playlist
    MOVE_VIDEO = auto()  # Change video position


@dataclass
class PlaylistDiff:
    """Calculated diff with minimal operations to sync playlists.

    Attributes:
        playlist_id: Target playlist ID
        update_metadata: Dict of fields to update (title, description, privacy)
        videos_to_add: List of (video_id, position) tuples
        videos_to_remove: List of video_ids to remove
        videos_to_move: List of (video_id, new_position) tuples
        estimated_quota: Estimated API quota cost
    """

    playlist_id: str
    update_metadata: dict[str, str] = field(default_factory=dict)
    videos_to_add: list[tuple[str, int]] = field(default_factory=list)
    videos_to_remove: list[str] = field(default_factory=list)
    videos_to_move: list[tuple[str, int]] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """Check if any changes are needed."""
        return bool(
            self.update_metadata
            or self.videos_to_add
            or self.videos_to_remove
            or self.videos_to_move
        )

    @property
    def estimated_quota(self) -> int:
        """Estimate API quota cost for this diff.

        Costs:
        - playlists.update: 50 units
        - playlistItems.insert: 50 units each
        - playlistItems.delete: 50 units each
        - playlistItems.update (move): 50 units each
        """
        quota = 0
        if self.update_metadata:
            quota += 51  # 1 list + 50 update
        quota += len(self.videos_to_add) * 50
        quota += len(self.videos_to_remove) * 50
        quota += len(self.videos_to_move) * 50
        return quota

    @property
    def operation_count(self) -> int:
        """Total number of API operations."""
        count = 0
        if self.update_metadata:
            count += 1
        count += len(self.videos_to_add)
        count += len(self.videos_to_remove)
        count += len(self.videos_to_move)
        return count


def _longest_common_subsequence(seq1: list[str], seq2: list[str]) -> list[str]:
    """Find longest common subsequence of two lists.

    Used to determine which videos are already in correct relative order.
    """
    m, n = len(seq1), len(seq2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if seq1[i - 1] == seq2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    # Backtrack to find LCS
    lcs: list[str] = []
    i, j = m, n
    while i > 0 and j > 0:
        if seq1[i - 1] == seq2[j - 1]:
            lcs.append(seq1[i - 1])
            i -= 1
            j -= 1
        elif dp[i - 1][j] > dp[i][j - 1]:
            i -= 1
        else:
            j -= 1

    return lcs[::-1]


def calculate_diff(current: Playlist, desired: Playlist) -> PlaylistDiff:
    """Calculate minimal operations to transform current playlist to desired state.

    Uses longest common subsequence to minimize video move operations.

    Args:
        current: Current playlist state (from API)
        desired: Desired playlist state (from YAML)

    Returns:
        PlaylistDiff with minimal operations needed
    """
    diff = PlaylistDiff(playlist_id=current.id)

    # 1. Metadata changes
    if current.title != desired.title:
        diff.update_metadata["title"] = desired.title
    if current.description != desired.description:
        diff.update_metadata["description"] = desired.description
    if current.privacy != desired.privacy:
        diff.update_metadata["privacy"] = desired.privacy

    # 2. Video changes
    current_ids = [v.id for v in current.videos]
    desired_ids = [v.id for v in desired.videos]
    current_set = set(current_ids)
    desired_set = set(desired_ids)

    # Videos to remove (in current but not in desired)
    diff.videos_to_remove = [vid for vid in current_ids if vid not in desired_set]

    # Videos to add (in desired but not in current)
    # Store with their target positions
    for pos, vid in enumerate(desired_ids):
        if vid not in current_set:
            diff.videos_to_add.append((vid, pos))

    # 3. Calculate moves for remaining videos using LCS
    # After removes and before adds, find optimal ordering
    remaining_current = [vid for vid in current_ids if vid in desired_set]
    remaining_desired = [vid for vid in desired_ids if vid in current_set]

    if remaining_current != remaining_desired:
        # Find LCS - videos in this subsequence don't need to move
        lcs = _longest_common_subsequence(remaining_current, remaining_desired)
        lcs_set = set(lcs)

        # Videos not in LCS need to be moved to their target positions
        desired_positions = {vid: pos for pos, vid in enumerate(remaining_desired)}
        for vid in remaining_desired:
            if vid not in lcs_set:
                diff.videos_to_move.append((vid, desired_positions[vid]))

    return diff
