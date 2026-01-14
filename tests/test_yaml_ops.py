"""Tests for ytrix.yaml_ops."""

from pathlib import Path

import pytest

from ytrix.models import Playlist, Video
from ytrix.yaml_ops import (
    diff_playlists,
    load_yaml,
    playlists_to_yaml,
    save_yaml,
    yaml_to_playlists,
)


class TestPlaylistsToYaml:
    """Tests for YAML serialization."""

    def test_serializes_single_playlist(self) -> None:
        """Serializes single playlist to YAML."""
        playlist = Playlist(id="PL123", title="Test", description="Desc")
        yaml_str = playlists_to_yaml([playlist], include_videos=False)
        assert "PL123" in yaml_str
        assert "Test" in yaml_str

    def test_serializes_multiple_playlists(self) -> None:
        """Serializes multiple playlists."""
        playlists = [
            Playlist(id="PL1", title="First"),
            Playlist(id="PL2", title="Second"),
        ]
        yaml_str = playlists_to_yaml(playlists)
        assert "PL1" in yaml_str
        assert "PL2" in yaml_str

    def test_includes_videos_when_requested(self) -> None:
        """Includes video details when include_videos=True."""
        video = Video(id="v1", title="Video", channel="Ch", position=0)
        playlist = Playlist(id="PL1", title="Test", videos=[video])
        yaml_str = playlists_to_yaml([playlist], include_videos=True)
        assert "v1" in yaml_str
        assert "Video" in yaml_str


class TestYamlToPlaylists:
    """Tests for YAML deserialization."""

    def test_deserializes_basic_yaml(self) -> None:
        """Deserializes YAML string to playlists."""
        yaml_str = """
playlists:
  - id: PL123
    title: Test Playlist
    description: Description
    privacy: public
"""
        playlists = yaml_to_playlists(yaml_str)
        assert len(playlists) == 1
        assert playlists[0].id == "PL123"
        assert playlists[0].title == "Test Playlist"

    def test_deserializes_with_videos(self) -> None:
        """Deserializes playlists with videos."""
        yaml_str = """
playlists:
  - id: PL123
    title: Test
    videos:
      - id: v1
        title: Video 1
        channel: Channel
"""
        playlists = yaml_to_playlists(yaml_str)
        assert len(playlists[0].videos) == 1
        assert playlists[0].videos[0].id == "v1"

    def test_raises_on_invalid_yaml(self) -> None:
        """Raises ValueError on missing playlists key."""
        with pytest.raises(ValueError, match="missing 'playlists' key"):
            yaml_to_playlists("some_other_key: value")


class TestSaveLoadYaml:
    """Tests for file I/O."""

    def test_round_trip(self, tmp_path: Path) -> None:
        """Saving and loading produces equivalent data."""
        original = [
            Playlist(
                id="PL123",
                title="Test",
                description="Desc",
                privacy="unlisted",
                videos=[Video(id="v1", title="Video", channel="Ch", position=0)],
            )
        ]
        path = tmp_path / "test.yaml"
        save_yaml(path, original)
        loaded = load_yaml(path)

        assert len(loaded) == 1
        assert loaded[0].id == original[0].id
        assert loaded[0].title == original[0].title
        assert len(loaded[0].videos) == 1
        assert loaded[0].videos[0].id == "v1"


class TestDiffPlaylists:
    """Tests for playlist diff detection."""

    def test_no_changes(self) -> None:
        """Returns empty dict when playlists are identical."""
        old = Playlist(id="PL1", title="Test", description="Desc")
        new = Playlist(id="PL1", title="Test", description="Desc")
        assert diff_playlists(old, new) == {}

    def test_detects_title_change(self) -> None:
        """Detects title change."""
        old = Playlist(id="PL1", title="Old Title")
        new = Playlist(id="PL1", title="New Title")
        diff = diff_playlists(old, new)
        assert "title" in diff
        assert diff["title"]["old"] == "Old Title"
        assert diff["title"]["new"] == "New Title"

    def test_detects_description_change(self) -> None:
        """Detects description change."""
        old = Playlist(id="PL1", title="Test", description="Old")
        new = Playlist(id="PL1", title="Test", description="New")
        diff = diff_playlists(old, new)
        assert "description" in diff

    def test_detects_privacy_change(self) -> None:
        """Detects privacy change."""
        old = Playlist(id="PL1", title="Test", privacy="public")
        new = Playlist(id="PL1", title="Test", privacy="private")
        diff = diff_playlists(old, new)
        assert "privacy" in diff

    def test_detects_videos_removed(self) -> None:
        """Detects removed videos."""
        old = Playlist(
            id="PL1",
            title="Test",
            videos=[
                Video(id="v1", title="V1", channel="Ch", position=0),
                Video(id="v2", title="V2", channel="Ch", position=1),
            ],
        )
        new = Playlist(
            id="PL1",
            title="Test",
            videos=[Video(id="v1", title="V1", channel="Ch", position=0)],
        )
        diff = diff_playlists(old, new)
        assert "videos_removed" in diff
        assert "v2" in diff["videos_removed"]

    def test_detects_videos_added(self) -> None:
        """Detects added videos."""
        old = Playlist(
            id="PL1",
            title="Test",
            videos=[Video(id="v1", title="V1", channel="Ch", position=0)],
        )
        new = Playlist(
            id="PL1",
            title="Test",
            videos=[
                Video(id="v1", title="V1", channel="Ch", position=0),
                Video(id="v2", title="V2", channel="Ch", position=1),
            ],
        )
        diff = diff_playlists(old, new)
        assert "videos_added" in diff
        assert "v2" in diff["videos_added"]

    def test_detects_reorder(self) -> None:
        """Detects video reordering (same videos, different order)."""
        old = Playlist(
            id="PL1",
            title="Test",
            videos=[
                Video(id="v1", title="V1", channel="Ch", position=0),
                Video(id="v2", title="V2", channel="Ch", position=1),
            ],
        )
        new = Playlist(
            id="PL1",
            title="Test",
            videos=[
                Video(id="v2", title="V2", channel="Ch", position=0),
                Video(id="v1", title="V1", channel="Ch", position=1),
            ],
        )
        diff = diff_playlists(old, new)
        assert "videos_reordered" in diff
        assert diff["videos_reordered"] is True


class TestCalculateDiff:
    """Tests for calculate_diff with minimal operations."""

    def test_no_changes_returns_empty_diff(self) -> None:
        """Returns diff with no operations when playlists are identical."""
        from ytrix.yaml_ops import calculate_diff

        current = Playlist(id="PL1", title="Test", description="Desc")
        desired = Playlist(id="PL1", title="Test", description="Desc")
        diff = calculate_diff(current, desired)
        assert not diff.has_changes
        assert diff.estimated_quota == 0

    def test_metadata_change_detected(self) -> None:
        """Detects title/description/privacy changes."""
        from ytrix.yaml_ops import calculate_diff

        current = Playlist(id="PL1", title="Old", description="Old Desc", privacy="public")
        desired = Playlist(id="PL1", title="New", description="New Desc", privacy="private")
        diff = calculate_diff(current, desired)
        assert diff.update_metadata == {
            "title": "New",
            "description": "New Desc",
            "privacy": "private",
        }
        assert diff.estimated_quota == 51  # 1 list + 50 update

    def test_video_removal_detected(self) -> None:
        """Detects videos to remove."""
        from ytrix.yaml_ops import calculate_diff

        current = Playlist(
            id="PL1",
            title="Test",
            videos=[
                Video(id="v1", title="V1", channel="Ch", position=0),
                Video(id="v2", title="V2", channel="Ch", position=1),
            ],
        )
        desired = Playlist(
            id="PL1",
            title="Test",
            videos=[Video(id="v1", title="V1", channel="Ch", position=0)],
        )
        diff = calculate_diff(current, desired)
        assert diff.videos_to_remove == ["v2"]
        assert diff.estimated_quota == 50  # 1 delete

    def test_video_addition_detected(self) -> None:
        """Detects videos to add with positions."""
        from ytrix.yaml_ops import calculate_diff

        current = Playlist(
            id="PL1",
            title="Test",
            videos=[Video(id="v1", title="V1", channel="Ch", position=0)],
        )
        desired = Playlist(
            id="PL1",
            title="Test",
            videos=[
                Video(id="v1", title="V1", channel="Ch", position=0),
                Video(id="v2", title="V2", channel="Ch", position=1),
            ],
        )
        diff = calculate_diff(current, desired)
        assert diff.videos_to_add == [("v2", 1)]
        assert diff.estimated_quota == 50  # 1 insert

    def test_reorder_uses_lcs_for_minimal_moves(self) -> None:
        """Uses LCS to minimize move operations."""
        from ytrix.yaml_ops import calculate_diff

        current = Playlist(
            id="PL1",
            title="Test",
            videos=[
                Video(id="A", title="A", channel="Ch", position=0),
                Video(id="B", title="B", channel="Ch", position=1),
                Video(id="C", title="C", channel="Ch", position=2),
                Video(id="D", title="D", channel="Ch", position=3),
            ],
        )
        desired = Playlist(
            id="PL1",
            title="Test",
            videos=[
                Video(id="A", title="A", channel="Ch", position=0),
                Video(id="C", title="C", channel="Ch", position=1),
                Video(id="B", title="B", channel="Ch", position=2),
                Video(id="D", title="D", channel="Ch", position=3),
            ],
        )
        diff = calculate_diff(current, desired)
        # Only 1 video needs to move
        assert len(diff.videos_to_move) == 1
        assert diff.estimated_quota == 50  # 1 move

    def test_operation_count_is_correct(self) -> None:
        """operation_count sums all operations."""
        from ytrix.yaml_ops import calculate_diff

        current = Playlist(id="PL1", title="Old")
        desired = Playlist(
            id="PL1",
            title="New",
            videos=[Video(id="v1", title="V1", channel="Ch", position=0)],
        )
        diff = calculate_diff(current, desired)
        # 1 metadata update + 1 video add = 2 operations
        assert diff.operation_count == 2
