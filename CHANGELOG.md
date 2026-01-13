# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- **Playlist info extraction** (Phase 8):
  - `plist2info`: Extract single playlist with video info and subtitles
  - `plists2info`: Batch extraction from text file of playlist URLs
  - Downloads subtitles (manual and automatic) in SRT/VTT format
  - Converts subtitles to plain text transcripts
  - Generates markdown files with YAML frontmatter
  - Output folder structure: `{playlist_name}/{video_title}.{lang}.md`
  - 29 new tests in test_info.py
- **Quota tracking** (Phase 7.4):
  - `quota_status`: View session quota usage
  - `QuotaTracker` class for actual units consumed per API call
  - Time until quota reset (midnight PT) in error messages
  - Warns when approaching daily limit (>80% consumed)
- `journal_status` CLI command to view batch operation progress
  - Shows summary counts by status (pending, completed, failed, skipped)
  - Displays details of failed tasks with error messages
  - `--clear` flag to delete the journal
  - `--pending-only` flag to show only incomplete tasks
  - JSON output support with `--json-output`
- Git-tag-based semantic versioning via hatch-vcs
- `plist2mlist --title` flag for custom playlist titles
- `plist2mlist --privacy` flag (public, unlisted, private)
- `plists2mlist --privacy` flag (public, unlisted, private)
- **Request throttling**: `--throttle` flag to set delay between API writes (default 200ms)
  - Helps avoid 429 rate limit errors on batch operations
  - Set to 0 to disable throttling
- **Smart throttling for yt-dlp operations** (info extraction and extractor):
  - Adaptive backoff: automatically increases delay on rate limit errors
  - Retry logic: up to 5 retries with exponential backoff (2-60s)
  - Jitter: randomized delays to avoid thundering herd
  - Graceful recovery: delay gradually decreases after successful requests
  - Subtitle downloads: 3 retries with backoff for 429 errors
  - Video delay: configurable pause between video processing (default 0.5s)
  - Progress summary: reports success/failure counts at completion
  - `--delay` flag for `plist2info` and `plists2info` commands
  - 17 new tests for throttling (311 total tests)

### Changed

- Version is now derived from git tags (e.g., `v1.1.0`)
- Updated test count to 308
- Added type ignore comments for tenacity decorators (mypy compatibility)
- **API quota optimization**: Read operations now use yt-dlp first, falling back to API only for private playlists
  - `ls --count`: Uses yt-dlp for video counts (saves ~1 quota unit per playlist)
  - `mlists2yaml --details`: Uses yt-dlp for video lists
  - `mlist2yaml`: Uses yt-dlp for video lists, API only for metadata (privacy status)
- **Improved retry strategy**: 10 attempts with up to 300s backoff (was 5/60s)
  - 429 rate limits: Retried with exponential backoff, auto-increases throttle delay
  - 403 quotaExceeded: Stops immediately (daily quota, no retry possible)
  - 5xx server errors: Retried with backoff

## [1.0.0] - 2026-01-12

### Added

- **Cache system**: SQLite-based cache at ~/.ytrix/cache.db
  - Caches yt-dlp reads (playlists, videos, channel playlists)
  - TTL-based expiration (1h playlists, 24h videos)
  - New `cache_stats` command to show cache statistics
  - New `cache_clear` command to clear cached data
- **Batch operations with journaling**:
  - New `plists2mlists` command for batch one-to-one playlist copying
  - `--resume` flag to continue interrupted operations
  - JSON journal at ~/.ytrix/journal.json for cross-session persistence
- **Deduplication**: `plist2mlist --dedup` flag (default: True)
  - Exact match (100% same videos): skip creation
  - Partial match (>75%): update existing playlist
  - No match: create new playlist
- **Retry with backoff**: tenacity-based exponential backoff for API rate limits
- **Quota estimation**: Helpers for estimating API quota usage
- 70 new tests (197 total):
  - test_cache.py: 14 tests
  - test_dedup.py: 17 tests
  - test_journal.py: 20 tests
  - test_quota.py: 19 tests

### Changed

- `plist2mlist` now checks for existing duplicates before creating playlists

## [0.1.13] - 2026-01-12

### Added

- `--user` flag for `ls` command to list playlists from any YouTube channel
- `--urls` flag for `ls` command for piping URLs to plists2mlist
- Tests for new ls flags (5 new tests, 127 total)

### Changed

- Migrated yt-dlp integration from subprocess to native Python API (YoutubeDL class)
- Improved reliability and error handling in metadata extraction

## [0.1.12] - 2025-01-12

### Added

- Author and maintainer info in pyproject.toml
- Project URLs (homepage, repository, issues) in pyproject.toml
- MIT LICENSE file

## [0.1.11] - 2025-01-12

### Added

- `config` command to show configuration status and detailed setup guide
- Bundled SETUP.txt with step-by-step YouTube API OAuth setup instructions
- Tests for config command (5 new tests)

## [0.1.9] - 2025-01-12

### Added

- CLI command existence and docstring smoke tests
- Consolidated TODO.md with completion summary

### Changed

- Updated PLAN.md success criteria with actual metrics (112 tests, 86% coverage)

## [0.1.8] - 2025-01-12

### Added

- `--count` flag for `ls` command to show video counts per playlist
- Tests for `ls` empty playlist list and config error handling

## [0.1.7] - 2025-01-12

### Fixed

- `yaml2mlist` now returns JSON output (was ignoring return value)

### Changed

- Updated PLAN.md and TODO.md to reflect all 9 commands and --json-output

## [0.1.6] - 2025-01-12

### Added

- `--dry-run` flag for `plist2mlists` command (preview splits before creating)
- Documentation for `ls` command in README

### Fixed

- mypy strict mode type error in `plist2mlists`

## [0.1.5] - 2025-01-12

### Added

- `ls` command to list all your playlists
- `--json-output` support for `yaml2mlists` command

### Changed

- Test coverage files (.coverage, htmlcov/) added to .gitignore

## [0.1.4] - 2025-01-12

### Added

- `--json-output` support for `plist2mlists` command
- `--json-output` support for `mlist2yaml` command
- Error case tests for input validation (6 new tests)

## [0.1.3] - 2025-01-12

### Added

- `py.typed` marker for PEP 561 type stub compliance
- Usage examples in CLI help output (--help)

### Fixed

- mypy strict mode compliance (10 type errors fixed)

## [0.1.2] - 2025-01-12

### Added

- `version` command to display ytrix version
- `--dry-run` flag for `plist2mlist` and `plists2mlist` commands
- Duplicate video detection in `plists2mlist` (auto-skips duplicates)
- Package exports: `InvalidPlaylistError`, `Playlist`, `Video` now importable from `ytrix`
- Tests for logging module (4 new tests)

### Documentation

- README updated with global flags section (--verbose, --json-output, version)

## [0.1.1] - 2025-01-12

### Added

- `--json-output` flag for machine-readable JSON output (plist2mlist, mlists2yaml)
- Input validation for playlist URLs/IDs with clear error messages
- Integration tests for yt-dlp extraction (auto-skipped if yt-dlp not installed)

### Changed

- `extract_playlist_id()` now raises `InvalidPlaylistError` for invalid input

## [0.1.0] - 2025-01-12

### Added

- Initial release of ytrix CLI
- `plist2mlist`: Copy external playlist to your channel
- `plists2mlist`: Merge multiple playlists from text file
- `plist2mlists`: Split playlist by channel or year
- `mlists2yaml`: Export all your playlists to YAML
- `yaml2mlists`: Apply YAML edits to your playlists
- `mlist2yaml`: Export single playlist to YAML
- `yaml2mlist`: Apply YAML edits to single playlist
- OAuth2 authentication with token caching
- yt-dlp integration for quota-free metadata extraction
- YAML-based playlist editing workflow
- Progress bars for long operations
- `--dry-run` flag for preview before applying changes
