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

## Phase 7: Quota & Rate Limit Handling - MOSTLY COMPLETE

### 7.1 Problem Analysis

The `plists2mlists` command hits HTTP 429 `RATE_LIMIT_EXCEEDED` errors because:

1. **No request pacing**: API calls fire as fast as possible
2. **Insufficient backoff**: 5 attempts with max 60s isn't enough for sustained rate limits
3. **No error type distinction**: 429 (per-minute rate limit) vs 403 (daily quota) need different handling
4. **No quota tracking**: Only estimates, no actual usage tracking

**Key insight**: YouTube API has TWO limit types:
- **Daily quota** (10,000 units, resets midnight PT) → HTTP 403 `quotaExceeded`
- **Per-minute rate limit** (undocumented, ~100-300 req/min) → HTTP 429 `RATE_LIMIT_EXCEEDED`

### 7.2 Request Throttling (api.py) - COMPLETE

- [x] Add `Throttler` class with configurable delay between requests (default: 200ms)
- [x] Apply throttling to all write operations (create, update, delete)
- [x] Make delay configurable via config.toml or CLI flag

### 7.3 Improved Retry Strategy (api.py) - COMPLETE

- [x] Increase max retry attempts for 429 errors (5 → 10)
- [x] Increase max backoff time (60s → 300s)
- [x] Add longer initial delay after 429 (start at 5s instead of 1s)
- [x] Distinguish 429 RATE_LIMIT_EXCEEDED from 403 quotaExceeded
- [x] For 403 quotaExceeded: Stop immediately, report quota reset time

### 7.4 Session Quota Tracking (quota.py) - COMPLETE

- [x] Add `QuotaTracker` class to track actual units consumed per session
- [x] Increment counter after each successful API call
- [x] Warn user when approaching daily limit (>80% consumed)
- [x] Auto-pause when estimated to exceed quota
- [x] Display remaining quota in `quota_status` command

### 7.5 Adaptive Pacing (plists2mlists) - COMPLETE

- [x] Start with normal pacing (200ms between calls)
- [x] On first 429: double delay, log warning
- [x] On repeated 429s: exponential increase up to 5s between calls
- [x] Reset to normal pacing after 10 successful calls
- [x] Add `--throttle` flag to set initial delay (ms)

### 7.6 Better User Feedback - COMPLETE

- [x] Show quota used/remaining via `quota_status` command
- [x] On 403 quotaExceeded: Show time until midnight PT reset
- [x] On 429 rate limit: Show "slowing down, will retry in Xs"
- [x] On persistent failure: Suggest `--throttle 500` or `--resume` later

### 7.7 Testing - COMPLETE

- [x] Test throttler with mock time
- [x] Test retry behavior for 429 vs 403 errors
- [x] Test quota tracking increments
- [x] Test adaptive pacing logic

## Phase 8: Playlist Info Extraction - COMPLETE

### 8.1 Info Module
- [x] Create `info.py` with VideoInfo, PlaylistInfo dataclasses
- [x] Extract full video metadata via yt-dlp
- [x] Extract available subtitles (manual and automatic)
- [x] Download subtitle files (SRT, VTT)
- [x] Add `format_duration()` helper for HH:MM:SS formatting
- [x] Add `duration_formatted` to VideoInfo.to_dict()
- [x] Add `total_duration` and `total_duration_formatted` to PlaylistInfo.to_dict()
- [x] Export `format_duration` from package for external use

### 8.2 Transcript Conversion
- [x] Parse SRT format to plain text
- [x] Parse VTT format to plain text
- [x] Generate markdown with YAML frontmatter
- [x] Handle multi-language subtitle extraction

### 8.3 CLI Commands
- [x] `plist2info`: Single playlist extraction
- [x] `plists2info`: Batch playlist extraction
- [x] Output folder structure with playlist.yaml
- [x] Progress reporting during extraction

### 8.4 Testing
- [x] 29 unit tests for info module
- [x] Live testing with example playlists

## Phase 9: Multi-Project Credential Rotation - MOSTLY COMPLETE

### 9.1 Problem Analysis

YouTube Data API has a 10,000 units/day quota per GCP project. For heavy users:
- Batch operations exhaust quota quickly
- Users must wait until midnight PT for reset
- No way to distribute load across multiple projects

**Solution**: Support multiple GCP projects with automatic credential rotation.

### 9.2 Multi-Project Configuration - COMPLETE

- [x] Extend config to support `[[projects]]` array in config.toml
- [x] Each project has: name, client_id, client_secret
- [x] Backwards compatible: single `[oauth]` section still works
- [x] Store per-project tokens in ~/.ytrix/tokens/{project_name}.json

### 9.3 Credential Rotation Logic - COMPLETE

- [x] Create `projects.py` module for project management
- [x] Track quota usage per project (persist to ~/.ytrix/quota_state.json)
- [x] Auto-rotate to next project when quota exhausted (403 quotaExceeded)
- [x] Round-robin selection with quota awareness
- [x] `--project` flag to force specific project

### 9.4 GCP Project Cloning (gcptrix integration)

- [x] Move gcptrix.py into ytrix/gcptrix.py
- [ ] Add `gcp_clone <source> <suffix>` CLI command
- [ ] Add `gcp_inventory <project>` CLI command
- [ ] Document manual steps required after cloning

### 9.5 CLI Commands - MOSTLY COMPLETE

- [x] `projects`: Show configured projects and quota status
- [ ] `projects_add <name>`: Interactive setup for new project
- [x] `projects_auth <name>`: Authenticate specific project
- [x] `projects_select <name>`: Select active project

### 9.6 Documentation - COMPLETE

- [x] SETUP.txt: Add multi-project setup instructions
- [x] README: Document project rotation
- [x] Help text: Explain --project flag and rotation behavior

## Success Criteria

- [x] All 17 commands functional (14 core + plist2info + plists2info + quota_status)
- [x] Tests pass with 79% coverage (321 tests)
- [x] Can round-trip: export to YAML, edit, import
- [x] Handles 100+ video playlists
- [x] Clear error messages for all failure modes
- [x] --json-output flag for scripting on all commands
- [x] Git-tag-based semantic versioning via hatch-vcs
- [x] Batch operations complete without 429 errors under normal load
- [x] Graceful handling of quota limits with clear user guidance
- [~] Multi-project credential rotation (Phase 9 - core complete, docs pending)
