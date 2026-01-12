"""Playlist deduplication helpers using yt-dlp for zero-quota reads."""

from dataclasses import dataclass
from enum import Enum

from ytrix import extractor
from ytrix.logging import logger
from ytrix.models import Playlist


class MatchType(str, Enum):
    """Type of match between source and target playlist."""

    EXACT = "exact"  # 100% same videos - skip creation
    PARTIAL = "partial"  # >75% same videos - update existing
    NONE = "none"  # <75% match - create new


@dataclass
class MatchResult:
    """Result of matching a source playlist against target playlists."""

    match_type: MatchType
    target_playlist: Playlist | None = None
    overlap_percent: float = 0.0
    missing_videos: list[str] | None = None  # Videos in source but not target
    extra_videos: list[str] | None = None  # Videos in target but not source


def calculate_overlap(source_ids: set[str], target_ids: set[str]) -> float:
    """Calculate percentage overlap between two video sets.

    Returns percentage of source videos that exist in target (0.0 to 1.0).
    """
    if not source_ids:
        return 1.0 if not target_ids else 0.0
    return len(source_ids & target_ids) / len(source_ids)


def find_matching_playlist(
    source: Playlist,
    target_playlists: list[Playlist],
    threshold: float = 0.75,
) -> MatchResult:
    """Find if source playlist matches any target playlist.

    Args:
        source: Source playlist with videos populated
        target_playlists: List of target playlists with videos populated
        threshold: Minimum overlap ratio for partial match (default 75%)

    Returns:
        MatchResult with match type and details
    """
    source_ids = {v.id for v in source.videos}

    if not source_ids:
        logger.debug("Source playlist {} is empty", source.id)
        return MatchResult(match_type=MatchType.NONE)

    best_match: MatchResult | None = None
    best_overlap = 0.0

    for target in target_playlists:
        target_ids = {v.id for v in target.videos}
        overlap = calculate_overlap(source_ids, target_ids)

        logger.debug(
            "Comparing {} vs {}: {:.1%} overlap",
            source.title[:30],
            target.title[:30],
            overlap,
        )

        if overlap > best_overlap:
            best_overlap = overlap
            missing = list(source_ids - target_ids)
            extra = list(target_ids - source_ids)

            if overlap >= 1.0:
                best_match = MatchResult(
                    match_type=MatchType.EXACT,
                    target_playlist=target,
                    overlap_percent=overlap,
                    missing_videos=[],
                    extra_videos=extra,
                )
            elif overlap >= threshold:
                best_match = MatchResult(
                    match_type=MatchType.PARTIAL,
                    target_playlist=target,
                    overlap_percent=overlap,
                    missing_videos=missing,
                    extra_videos=extra,
                )

    if best_match:
        logger.info(
            "{} match for '{}': '{}' ({:.1%})",
            best_match.match_type.value.upper(),
            source.title[:30],
            best_match.target_playlist.title[:30] if best_match.target_playlist else "",
            best_match.overlap_percent,
        )
        return best_match

    return MatchResult(match_type=MatchType.NONE)


def load_target_playlists_with_videos(channel_id: str) -> list[Playlist]:
    """Load all playlists from target channel with their videos.

    Uses yt-dlp for zero API quota cost.

    Args:
        channel_id: YouTube channel ID (UCxxx format)

    Returns:
        List of Playlist objects with videos populated
    """
    logger.info("Loading target channel playlists via yt-dlp (no quota)...")
    try:
        playlists = extractor.extract_channel_playlists_with_videos(channel_id)
        logger.info("Loaded {} playlists from target channel", len(playlists))
        return playlists
    except Exception as e:
        logger.warning("Failed to load target playlists: {}", e)
        return []


def analyze_batch_deduplication(
    source_playlists: list[Playlist],
    target_playlists: list[Playlist],
    threshold: float = 0.75,
) -> dict[str, MatchResult]:
    """Analyze all source playlists against target playlists.

    Args:
        source_playlists: Source playlists with videos
        target_playlists: Target playlists with videos
        threshold: Minimum overlap for partial match

    Returns:
        Dict mapping source playlist ID to MatchResult
    """
    results: dict[str, MatchResult] = {}

    for source in source_playlists:
        result = find_matching_playlist(source, target_playlists, threshold)
        results[source.id] = result

    # Summary
    exact = sum(1 for r in results.values() if r.match_type == MatchType.EXACT)
    partial = sum(1 for r in results.values() if r.match_type == MatchType.PARTIAL)
    new = sum(1 for r in results.values() if r.match_type == MatchType.NONE)

    logger.info(
        "Deduplication analysis: {} exact, {} partial, {} new",
        exact,
        partial,
        new,
    )

    return results
