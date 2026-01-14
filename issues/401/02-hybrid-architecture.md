# Part 2: Hybrid Read/Write Architecture

## Core Principle

**Zero-quota reads, minimal-quota writes.**

- **Read Path**: All data retrieval via yt-dlp (no API quota consumed)
- **Write Path**: YouTube Data API only for mutations (creates, updates, deletes)

## Current Problem

ytrix currently uses the YouTube API for both reading and writing. This wastes quota on operations that could be free:

| Operation | Current Cost | Optimized Cost |
|-----------|--------------|----------------|
| Read playlist (100 videos) | 2 units (pagination) | **0 units** (yt-dlp) |
| Read video metadata | 1 unit | **0 units** (yt-dlp) |
| Copy 200-video playlist | 10,002 units | **10,000 units** (writes only) |

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      ytrix Application                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────┐         ┌──────────────────┐          │
│  │   READ PATH      │         │   WRITE PATH     │          │
│  │   (Zero Quota)   │         │   (API Quota)    │          │
│  ├──────────────────┤         ├──────────────────┤          │
│  │  yt-dlp          │         │  YouTube API v3  │          │
│  │  - playlist info │         │  - create        │          │
│  │  - video info    │         │  - update        │          │
│  │  - channel info  │         │  - delete        │          │
│  │  - subtitles     │         │  - insert items  │          │
│  └────────┬─────────┘         └────────┬─────────┘          │
│           │                            │                     │
│           ▼                            ▼                     │
│  ┌──────────────────┐         ┌──────────────────┐          │
│  │  Local Cache     │         │  Quota Tracker   │          │
│  │  (SQLite)        │         │  (quota.py)      │          │
│  └──────────────────┘         └──────────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Changes

### 2.1 Extractor Module (`extractor.py`)

Already uses yt-dlp. Ensure ALL read operations route through here:

```python
# Verify: extractor.py should be the ONLY source of playlist/video reads
# API client should NEVER be used for reads in normal operations
```

### 2.2 API Module (`api.py`)

Remove or deprecate read functions that use quota:

```python
# DEPRECATED - Use extractor.get_playlist() instead
def get_playlist_with_videos(client, playlist_id):
    """Use extractor.py instead to avoid quota consumption."""
    raise DeprecationWarning("Use extractor.get_playlist() for zero-quota reads")
```

### 2.3 Command Updates

Each command should clarify its read/write split:

| Command | Reads (yt-dlp) | Writes (API) |
|---------|---------------|--------------|
| `plist2mlist` | Source playlist | Create playlist + add videos |
| `plists2mlist` | All source playlists | Create merged playlist + add videos |
| `plist2mlists` | Source + video metadata | Create sub-playlists + add videos |
| `mlists2yaml` | All playlists | None |
| `yaml2mlists` | Current state for diff | Updates only |
| `ls` | Channel playlists | None |
| `plist2info` | Playlist + video details | None |

### 2.4 Diff-Based Writes

For `yaml2mlist` operations, calculate precise diff before writing:

```python
def calculate_diff(current_state: Playlist, desired_state: Playlist) -> PlaylistDiff:
    """Calculate minimal changes needed.

    Returns:
        PlaylistDiff with:
        - videos_to_add: list[str]
        - videos_to_remove: list[str]
        - videos_to_reorder: list[tuple[str, int]]
        - metadata_changes: dict
    """
```

This minimizes API calls to only what's necessary.

### 2.5 yt-dlp Rate Limiting

yt-dlp scrapes the web frontend, which has its own (undocumented) rate limits:

```python
# Add --sleep-interval for bulk operations
YDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'extract_flat': 'in_playlist',
    'sleep_interval': 1,  # 1 second between requests for bulk ops
    'max_sleep_interval': 3,
}
```

### 2.6 Fallback Strategy

If yt-dlp fails (e.g., age-restricted content), fall back to API with user notification:

```python
def get_playlist_smart(playlist_id: str, use_api_fallback: bool = False) -> Playlist:
    """Get playlist via yt-dlp with optional API fallback.

    Args:
        playlist_id: YouTube playlist ID
        use_api_fallback: If True, use API when yt-dlp fails (costs quota)
    """
    try:
        return extractor.get_playlist(playlist_id)
    except ExtractorError as e:
        if use_api_fallback:
            logger.warning("yt-dlp failed, falling back to API (costs quota): {}", e)
            return api.get_playlist_with_videos(client, playlist_id)
        raise
```

## Quota Impact Analysis

For a typical operation (copy 200-video playlist):

| Approach | Read Cost | Write Cost | Total |
|----------|-----------|------------|-------|
| Current (all API) | 4 units | 10,050 units | 10,054 units |
| Hybrid (yt-dlp reads) | 0 units | 10,050 units | **10,050 units** |

Savings are modest for single operations but compound for batch operations and repeated reads.

## Testing Requirements

1. Verify all `ls`, `mlists2yaml`, `mlist2yaml` use zero API quota
2. Verify `plist2mlist` reads source via yt-dlp only
3. Verify API quota tracking only counts actual API calls
4. Test yt-dlp fallback behavior for edge cases
