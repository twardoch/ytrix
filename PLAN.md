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

## Phase 9: Multi-Project Context Switching - COMPLETE

### 9.1 Problem Analysis

YouTube Data API has a 10,000 units/day quota per GCP project. For heavy users:
- Batch operations exhaust quota quickly
- Users must wait until midnight PT for reset
- No way to distribute load across multiple projects

**Solution**: Support multiple GCP projects with context switching (ToS-compliant).

### 9.2 Multi-Project Configuration - COMPLETE

- [x] Extend config to support `[[projects]]` array in config.toml
- [x] Each project has: name, client_id, client_secret
- [x] Backwards compatible: single `[oauth]` section still works
- [x] Store per-project tokens in ~/.ytrix/tokens/{project_name}.json

### 9.3 Context Switching Logic - COMPLETE

- [x] Create `projects.py` module for project management
- [x] Track quota usage per project (persist to ~/.ytrix/quota_state.json)
- [x] Auto-switch to next project when quota exhausted (403 quotaExceeded)
- [x] Round-robin selection with quota awareness
- [x] `--project` flag to force specific project

### 9.4 GCP Project Cloning (gcptrix integration)

- [x] Move gcptrix.py into ytrix/gcptrix.py
- [x] Add `gcp_clone <source> <suffix>` CLI command
- [x] Add `gcp_inventory <project>` CLI command
- [x] Document manual steps required after cloning

### 9.5 CLI Commands - COMPLETE

- [x] `projects`: Show configured projects and quota status
- [x] `projects_add <name>`: Interactive setup for new project
- [x] `projects_auth <name>`: Authenticate specific project
- [x] `projects_select <name>`: Select active project

### 9.6 Documentation - COMPLETE

- [x] SETUP.txt: Add multi-project setup instructions
- [x] README: Document project context switching
- [x] Help text: Explain --project flag and context switching behavior

## Phase 10: ToS-Compliant Architecture & UX Improvements

**Full specification**: See [issues/401/](issues/401/) for detailed 9-part spec.

### 10.1 ToS Compliance & Architecture Pivot

**Critical finding**: Multi-project quota circumvention for a single application is explicitly forbidden by Google's ToS (Section III.D.1.c). See [01-overview-compliance.md](issues/401/01-overview-compliance.md).

- [x] Rename "rotation" to "context switching" throughout codebase
- [x] Add `quota_group` field to ProjectConfig for purpose-based grouping
- [x] Restrict automatic project switching to within same quota_group
- [x] Add ToS reminder on first run or after update
- [x] Update README with multi-project guidance and ToS warnings
- [x] Add validation to prevent obvious quota circumvention patterns

### 10.2 Hybrid Read/Write Architecture

Zero-quota reads via yt-dlp where possible, API for authenticated access. See [02-hybrid-architecture.md](issues/401/02-hybrid-architecture.md).

- [x] Audit all commands for read path usage
  - External playlist reads: yt-dlp (plist2mlist, plists2mlist, plist2mlists, ls --user)
  - Own playlist listing: API required (private/unlisted access)
  - Video details: yt-dlp with API fallback for private
- [ ] Implement diff-based writes for yaml2mlist (minimize API calls)
- [ ] Add `--sleep-interval` to yt-dlp for bulk operations

### 10.3 Quota Optimization

Batching, ETags, maxResults. See [03-quota-optimization.md](issues/401/03-quota-optimization.md).

- [ ] Add `batch_video_metadata()` to api.py (up to 50 IDs per request)
- [ ] Add ETag support to cache.py schema (new column)
- [ ] Implement ETag conditional requests for playlist reads
- [x] Audit all API calls for `maxResults=50`
- [ ] Add pre-flight quota estimation to batch commands
- [ ] Remove or deprecate any `search.list` usage

### 10.4 Project Context Management

ToS-compliant context switching. See [04-project-context.md](issues/401/04-project-context.md).

- [x] Add `quota_group` and `environment` fields to ProjectConfig
- [x] Replace `rotate_on_quota_exceeded()` with `handle_quota_exhausted()`
- [x] Add `--quota-group` CLI flag
- [x] Update `projects` command to show projects grouped by quota_group
- [x] Add priority-based selection within quota groups

### 10.5 GCP Setup Automation

Guided OAuth setup. See [05-gcp-automation.md](issues/401/05-gcp-automation.md).

- [ ] Add `ProjectSetupResult` dataclass
- [ ] Implement `guide_oauth_setup()` with rich prompts and deep links
- [ ] Add automatic config.toml update after credential entry
- [ ] Improve error messages with resolution steps
- [ ] Add exponential backoff for IAM operations during clone
- [ ] Add `gcp_init` command for fresh project creation

### 10.6 Enhanced Error Handling

429 vs 403 distinction. See [06-error-handling.md](issues/401/06-error-handling.md).

- [ ] Add `ErrorCategory` enum (RATE_LIMITED, QUOTA_EXCEEDED, PERMISSION_DENIED, etc.)
- [ ] Add `APIError` dataclass with user_action field
- [ ] Implement `classify_error()` function
- [ ] Update `_is_retryable_error()` to use classify_error (no retry for quota)
- [ ] Add `_log_retry_attempt()` with user-friendly messages
- [ ] Implement `display_error()` with Rich panels
- [ ] Add `BatchOperationHandler` for batch error recovery
- [ ] Update all commands to use new error handling

### 10.7 CLI Dashboard & Quota Display

Rich quota visualization. See [07-cli-dashboard.md](issues/401/07-cli-dashboard.md).

- [ ] Create `ytrix/dashboard.py` module
- [ ] Add `get_time_until_reset()` function (midnight PT calculation)
- [ ] Add `create_quota_dashboard()` with progress bar and stats table
- [ ] Add `show_quota_warning()` at 80% and 95% thresholds
- [ ] Add `show_rate_limit_feedback()` for retry visibility
- [ ] Add `show_session_summary()` for end-of-batch reporting
- [ ] Update `quota_status` command to use rich dashboard
- [ ] Add `--progress` and `--quiet` flags to batch commands

### 10.8 Journaling Improvements

Enhanced resume and error tracking. See [08-journaling-improvements.md](issues/401/08-journaling-improvements.md).

- [ ] Add `ErrorCategory` enum to journal.py
- [ ] Add `TaskStatus.SKIPPED` for dedup scenarios
- [ ] Create enhanced `JournalTask` dataclass with full context
- [ ] Create `JournalBatch` dataclass for batch metadata
- [ ] Implement `JournalManager` class with batch support
- [ ] Add `get_batch_summary()` with ETA calculation
- [ ] Add `cleanup_completed()` for stale entry removal
- [ ] Add `--resume-batch` and `--skip-failed` flags to plists2mlists
- [ ] Add `journal_status` CLI command
- [ ] Add `journal_cleanup` CLI command

### 10.9 Testing & Documentation

Test coverage and docs. See [09-testing-documentation.md](issues/401/09-testing-documentation.md).

- [ ] Create test fixtures in `tests/conftest.py` (mock clients, errors)
- [ ] Add `test_error_handling.py` with error classification tests
- [ ] Add `test_quota.py` with quota tracking tests
- [ ] Add `test_projects.py` with context selection tests
- [ ] Add `test_journal.py` with enhanced journal tests
- [ ] Add `test_dashboard.py` for CLI display tests
- [ ] Update README with multi-project and quota sections
- [ ] Create `docs/errors.md` with error catalog
- [ ] Update CHANGELOG.md with Phase 10 changes
- [ ] Ensure 80%+ coverage for new modules

## Success Criteria

- [x] All 20 commands functional (core + info + quota + gcp + project management)
- [x] Tests pass with 80%+ coverage (398 tests)
- [x] Can round-trip: export to YAML, edit, import
- [x] Handles 100+ video playlists
- [x] Clear error messages for all failure modes
- [x] --json-output flag for scripting on all commands
- [x] Git-tag-based semantic versioning via hatch-vcs
- [x] Batch operations complete without 429 errors under normal load
- [x] Graceful handling of quota limits with clear user guidance
- [x] Multi-project context switching (Phase 9 complete)

### Phase 10 Success Criteria

- [ ] ToS-compliant project context switching (no quota circumvention)
- [ ] 429 vs 403 errors handled distinctly (retry vs stop)
- [ ] Rich quota dashboard with time-until-reset
- [ ] Enhanced journaling with batch tracking and ETA
- [ ] GCP setup guided with interactive prompts
- [ ] API calls reduced 50%+ through batching and caching
- [ ] 90%+ test coverage for new modules
