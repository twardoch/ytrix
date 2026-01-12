# ytrix Implementation Plan

## Phase 1: Foundation - COMPLETE

### 1.1 Project Setup
- [x] Initialize uv project with pyproject.toml
- [x] Set up package structure (ytrix/)
- [x] Configure ruff, mypy

### 1.2 Configuration Module
- [x] Load TOML config from ~/.ytrix/config.toml
- [x] Validate required fields (channel_id, oauth credentials)
- [x] Create config directory if missing

### 1.3 yt-dlp Integration
- [x] Wrapper function to extract playlist metadata
- [x] Parse JSON output into dataclasses
- [x] Handle errors (private, deleted, network)
- [x] Native Python API (YoutubeDL class) instead of subprocess

### 1.4 YouTube API Client
- [x] OAuth2 flow with token caching
- [x] Playlist operations: create, update, list
- [x] PlaylistItem operations: insert, delete, update position
- [x] Rate limiting awareness

## Phase 2: Core Commands - COMPLETE

### 2.1 plist2mlist
- [x] Extract source playlist via yt-dlp
- [x] Create destination playlist via API
- [x] Add videos preserving order
- [x] Return new playlist URL

### 2.2 plists2mlist
- [x] Parse input file
- [x] Iterate playlists, collect videos
- [x] Create merged playlist
- [x] Add all videos in order

### 2.3 plist2mlists
- [x] Extract playlist with video metadata
- [x] Implement channel grouping
- [x] Implement year grouping
- [x] Create sub-playlists with naming convention

## Phase 3: YAML Operations - COMPLETE

### 3.1 YAML Export
- [x] Define YAML schema matching dataclasses
- [x] mlists2yaml: export all playlists
- [x] mlist2yaml: export single playlist
- [x] Handle --details flag

### 3.2 YAML Import
- [x] Parse YAML with validation
- [x] Diff detection (what changed)
- [x] yaml2mlists: apply to all playlists
- [x] yaml2mlist: apply to single playlist
- [x] Implement video reordering logic

## Phase 4: CLI & Polish - COMPLETE

### 4.1 Fire CLI
- [x] Wire all commands in __main__.py
- [x] Add --verbose flag for logging
- [x] Add --dry-run flag where applicable
- [x] Add --json-output flag for scripting
- [x] Add `ls` command to list playlists
- [x] Add `ls --user` flag to list playlists from any channel
- [x] Add `ls --urls` flag for piping URLs to plists2mlist
- [x] Add `version` command
- [x] Help text and examples

### 4.2 Testing
- [x] Unit tests for each module
- [x] Mock YouTube API responses
- [x] YAML round-trip tests
- [x] Error case coverage

### 4.3 Documentation
- [x] Finalize README with examples
- [x] CHANGELOG for v0.1.0
- [x] DEPENDENCIES.md with rationale

## Phase 5: Batch Operations & Journaling - COMPLETE

### 5.1 Deduplication
- [x] Compare video sets before creating playlists (dedup.py)
- [x] Exact match (100% same videos) → skip creation
- [x] High match (>75% same videos) → update existing playlist
- [x] Otherwise → create new playlist

### 5.2 Journaling System
- [x] JSON journal file at ~/.ytrix/journal.json (journal.py)
- [x] Track: source_playlist_id, target_playlist_id, status, error, retry_count
- [x] Resume interrupted operations across sessions
- [x] Clear completed entries on success

### 5.3 Retry with Backoff
- [x] Add tenacity for exponential backoff (api.py)
- [x] Handle HTTP 429 (quota exceeded) gracefully
- [x] Configurable retry limits and delays

### 5.4 New Commands
- [x] `plists2mlists <file>`: Batch one-to-one copy with journaling
- [x] `--resume` flag for journal continuation
- [x] Update `plist2mlist` with `--dedup` flag (default: True)

## Phase 6: Caching - COMPLETE

### 6.1 Cache Schema
- [x] SQLite database at ~/.ytrix/cache.db
- [x] Tables: playlists, videos, playlist_videos, channel_playlists
- [x] TTL-based expiration (1h playlists, 24h videos)

### 6.2 Extractor Integration
- [x] Cache all yt-dlp reads automatically
- [x] Check cache before network calls
- [x] use_cache parameter for bypass when needed

### 6.3 CLI Commands
- [x] `cache_stats`: Show cache statistics
- [x] `cache_clear`: Clear cached data

## Dependencies

| Package | Purpose | Justification |
|---------|---------|---------------|
| fire | CLI framework | Simple, no decorators needed |
| rich | Console output | Progress bars, colors |
| google-api-python-client | YouTube API | Official Google client |
| google-auth-oauthlib | OAuth2 | Required for API auth |
| yt-dlp | Metadata extraction | No API quota, handles edge cases |
| pyyaml | YAML parsing | Standard, well-maintained |
| pydantic | Data validation | Type-safe config and models |
| loguru | Logging | Clean API, --verbose support |
| tenacity | Retry with backoff | Handles API rate limits gracefully |

## Risks

| Risk | Mitigation |
|------|------------|
| API quota limits | Use yt-dlp for reads, warn user |
| Private playlist access | Clear error messages |
| YAML editing mistakes | Validate before applying, no delete |
| OAuth complexity | Use existing google-auth libraries |

## Success Criteria

- [x] All 10 commands functional (7 core + ls + version + config)
- [x] Tests pass with >80% coverage (197 tests)
- [x] Can round-trip: export to YAML, edit, import
- [x] Handles 100+ video playlists
- [x] Clear error messages for all failure modes
- [x] --json-output flag for scripting on all commands
