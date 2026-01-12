"""Tests for ytrix.dedup module."""

from ytrix.dedup import (
    MatchResult,
    MatchType,
    analyze_batch_deduplication,
    calculate_overlap,
    find_matching_playlist,
)
from ytrix.models import Playlist, Video


class TestCalculateOverlap:
    """Tests for calculate_overlap function."""

    def test_identical_sets(self) -> None:
        """Returns 1.0 for identical sets."""
        source = {"a", "b", "c"}
        target = {"a", "b", "c"}
        assert calculate_overlap(source, target) == 1.0

    def test_no_overlap(self) -> None:
        """Returns 0.0 for completely different sets."""
        source = {"a", "b", "c"}
        target = {"x", "y", "z"}
        assert calculate_overlap(source, target) == 0.0

    def test_partial_overlap(self) -> None:
        """Returns correct percentage for partial overlap."""
        source = {"a", "b", "c", "d"}  # 4 items
        target = {"a", "b", "x", "y"}  # 2 overlap
        assert calculate_overlap(source, target) == 0.5

    def test_empty_source(self) -> None:
        """Returns 1.0 for empty source and empty target."""
        assert calculate_overlap(set(), set()) == 1.0

    def test_empty_source_nonempty_target(self) -> None:
        """Returns 0.0 for empty source but non-empty target."""
        assert calculate_overlap(set(), {"a"}) == 0.0

    def test_superset_target(self) -> None:
        """Returns 1.0 when target is superset of source."""
        source = {"a", "b"}
        target = {"a", "b", "c", "d"}
        assert calculate_overlap(source, target) == 1.0


class TestFindMatchingPlaylist:
    """Tests for find_matching_playlist function."""

    def _make_playlist(
        self, playlist_id: str, video_ids: list[str], title: str = "Test"
    ) -> Playlist:
        """Helper to create a playlist with videos."""
        videos = [
            Video(id=vid, title=f"Video {vid}", channel="Ch", position=i)
            for i, vid in enumerate(video_ids)
        ]
        return Playlist(id=playlist_id, title=title, privacy="public", videos=videos)

    def test_exact_match(self) -> None:
        """Returns EXACT match when videos are identical."""
        source = self._make_playlist("src", ["a", "b", "c"])
        target = self._make_playlist("tgt", ["a", "b", "c"])

        result = find_matching_playlist(source, [target])

        assert result.match_type == MatchType.EXACT
        assert result.target_playlist == target
        assert result.overlap_percent == 1.0
        assert result.missing_videos == []

    def test_partial_match(self) -> None:
        """Returns PARTIAL match when overlap is above threshold."""
        source = self._make_playlist("src", ["a", "b", "c", "d"])  # 4 videos
        target = self._make_playlist("tgt", ["a", "b", "c"])  # 3 overlap = 75%

        result = find_matching_playlist(source, [target], threshold=0.75)

        assert result.match_type == MatchType.PARTIAL
        assert result.target_playlist == target
        assert result.overlap_percent == 0.75
        assert result.missing_videos == ["d"]

    def test_no_match_below_threshold(self) -> None:
        """Returns NONE when overlap is below threshold."""
        source = self._make_playlist("src", ["a", "b", "c", "d"])  # 4 videos
        target = self._make_playlist("tgt", ["a", "b"])  # 2 overlap = 50%

        result = find_matching_playlist(source, [target], threshold=0.75)

        assert result.match_type == MatchType.NONE
        assert result.target_playlist is None

    def test_no_targets(self) -> None:
        """Returns NONE when no target playlists."""
        source = self._make_playlist("src", ["a", "b", "c"])

        result = find_matching_playlist(source, [])

        assert result.match_type == MatchType.NONE

    def test_empty_source(self) -> None:
        """Returns NONE when source playlist is empty."""
        source = self._make_playlist("src", [])
        target = self._make_playlist("tgt", ["a", "b", "c"])

        result = find_matching_playlist(source, [target])

        assert result.match_type == MatchType.NONE

    def test_best_match_selected(self) -> None:
        """Selects best match when multiple targets."""
        source = self._make_playlist("src", ["a", "b", "c", "d"])
        target1 = self._make_playlist("t1", ["a"])  # 25%
        target2 = self._make_playlist("t2", ["a", "b", "c"])  # 75%
        target3 = self._make_playlist("t3", ["a", "b"])  # 50%

        result = find_matching_playlist(source, [target1, target2, target3])

        assert result.match_type == MatchType.PARTIAL
        assert result.target_playlist == target2

    def test_extra_videos_tracked(self) -> None:
        """Tracks extra videos in target not in source."""
        source = self._make_playlist("src", ["a", "b"])
        target = self._make_playlist("tgt", ["a", "b", "x", "y"])

        result = find_matching_playlist(source, [target])

        assert result.match_type == MatchType.EXACT  # All source videos in target
        assert set(result.extra_videos or []) == {"x", "y"}


class TestAnalyzeBatchDeduplication:
    """Tests for analyze_batch_deduplication function."""

    def _make_playlist(self, playlist_id: str, video_ids: list[str]) -> Playlist:
        videos = [
            Video(id=vid, title=f"Video {vid}", channel="Ch", position=i)
            for i, vid in enumerate(video_ids)
        ]
        return Playlist(
            id=playlist_id, title=f"Playlist {playlist_id}", privacy="public", videos=videos
        )

    def test_batch_analysis(self) -> None:
        """Analyzes multiple source playlists."""
        sources = [
            self._make_playlist("s1", ["a", "b", "c"]),
            self._make_playlist("s2", ["x", "y"]),
            self._make_playlist("s3", ["a", "b"]),  # Both in t1 = 100% match
        ]
        targets = [
            self._make_playlist("t1", ["a", "b", "c"]),  # Exact match for s1 and s3
        ]

        results = analyze_batch_deduplication(sources, targets)

        assert len(results) == 3
        assert results["s1"].match_type == MatchType.EXACT
        assert results["s2"].match_type == MatchType.NONE
        assert results["s3"].match_type == MatchType.EXACT  # All s3 videos in t1

    def test_empty_sources(self) -> None:
        """Returns empty dict for no sources."""
        targets = [self._make_playlist("t1", ["a", "b"])]
        results = analyze_batch_deduplication([], targets)
        assert results == {}


class TestMatchType:
    """Tests for MatchType enum."""

    def test_values(self) -> None:
        """Enum has expected values."""
        assert MatchType.EXACT.value == "exact"
        assert MatchType.PARTIAL.value == "partial"
        assert MatchType.NONE.value == "none"


class TestMatchResult:
    """Tests for MatchResult dataclass."""

    def test_default_values(self) -> None:
        """Has correct default values."""
        result = MatchResult(match_type=MatchType.NONE)
        assert result.target_playlist is None
        assert result.overlap_percent == 0.0
        assert result.missing_videos is None
        assert result.extra_videos is None
