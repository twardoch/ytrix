# ytrix TODO

## Completed (v1.2.0-dev) - Quota & Rate Limit + Info Extraction

### Smart Throttling for yt-dlp
- [x] Throttler class with adaptive backoff in info.py
- [x] Apply throttling to extractor.py (shared with info.py)
- [x] `--delay` flag for plist2info/plists2info commands
- [x] 14 tests for Throttler class (43 total in test_info.py)

### Playlist Info Extraction (Phase 8)
- [x] Create info.py module with VideoInfo, PlaylistInfo dataclasses
- [x] Extract subtitles (manual and automatic) via yt-dlp
- [x] Parse SRT/VTT to plain text transcripts
- [x] Generate markdown with YAML frontmatter
- [x] `plist2info` command for single playlist extraction
- [x] `plists2info` command for batch extraction
- [x] 29 tests in test_info.py

### Session Quota Tracking (quota.py)
- [x] Add `QuotaTracker` class for actual usage tracking
- [x] Warn at 80% quota consumed
- [x] Show time until midnight PT reset on quota errors
- [x] `quota_status` CLI command

### User Feedback
- [x] Show quota used/remaining via quota_status command
- [x] Show time until midnight PT reset on quota errors
- [x] Suggest `--throttle` or `--resume` on failures

## Completed (v1.2.0-dev) - Throttling & Retry

### Request Throttling (api.py)
- [x] Add `Throttler` class with configurable delay (default 200ms)
- [x] Apply throttling to write operations (create, update, delete)
- [x] Add `--throttle` CLI flag for custom delay

### Improved Retry Strategy (api.py)
- [x] Increase max retry attempts for 429 (5 → 10)
- [x] Increase max backoff time (60s → 300s)
- [x] Distinguish 429 RATE_LIMIT_EXCEEDED from 403 quotaExceeded
- [x] Stop immediately on 403 quotaExceeded (no retry)

### Adaptive Pacing
- [x] Start with normal pacing (200ms)
- [x] Double delay on 429, exponential up to 5s

### Testing
- [x] Test throttler with mock time
- [x] Test 429 vs 403 handling

## Completed (v1.1.0-dev)

### Build & Version
- [x] Configure hatch-vcs for git-tag-based semver
- [x] Add `journal_status` CLI command

### plist2mlist Enhancements
- [x] Update `plist2mlist` with `--dedup` flag (default True)
- [x] Skip creation for exact matches, update for partial matches
- [x] Add `--title` flag for custom playlist title
- [x] Add `--privacy` flag (public/unlisted/private)

### Test Coverage
- [x] Add tests for cache_stats and cache_clear commands
- [x] Add tests for config token status display
- [x] Add tests for ls --user --count flag
- [x] Add tests for --title and --privacy flags

### Tests for New Modules
- [x] Write tests for cache module (14 tests)
- [x] Write tests for dedup module (17 tests)
- [x] Write tests for journal module (20 tests)
- [x] Write tests for quota module (19 tests)

### Cache System
- [x] SQLite cache at ~/.ytrix/cache.db
- [x] Cache yt-dlp reads (playlists, videos, channel playlists)
- [x] TTL-based expiration (1h playlists, 24h videos)
- [x] `cache_stats` and `cache_clear` CLI commands

### Batch Operations & Journaling
- [x] Add tenacity dependency for retry with backoff
- [x] Create journal.py module for operation tracking
- [x] Add retry decorators to api.py
- [x] Add deduplication helpers (compare video sets)
- [x] Implement `plists2mlists` command (batch one-to-one copy)
- [x] Add `--resume` flag for journal continuation
- [x] Create quota.py for API quota estimation

## Completed (v0.1.13)

### Core Features
- [x] 10 CLI commands: ls, version, config, plist2mlist, plists2mlist, plist2mlists, mlists2yaml, yaml2mlists, mlist2yaml, yaml2mlist
- [x] --verbose, --dry-run, --json-output flags on all applicable commands
- [x] --count flag for ls command
- [x] --user flag for ls command (list any channel's playlists via yt-dlp)
- [x] --urls flag for ls command (output URLs for piping to plists2mlist)
- [x] OAuth2 authentication with token caching
- [x] yt-dlp Python API integration (native YoutubeDL class, no subprocess)
- [x] YAML-based playlist editing workflow

### Testing & Quality
- [x] 294 tests with 76% coverage
- [x] mypy strict mode compliant
- [x] ruff linting and formatting

### Documentation
- [x] README with examples
- [x] CHANGELOG.md
- [x] DEPENDENCIES.md with rationale

## Future Ideas (not planned)

- [ ] Playlist description templates
- [ ] Watch later playlist support
- [ ] Playlist thumbnail management
