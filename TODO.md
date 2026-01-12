# ytrix TODO

## In Progress (v0.2.0)

### All v0.2.0 tasks complete - ready for release

## Completed (v0.2.0-dev)

### plist2mlist Deduplication
- [x] Update `plist2mlist` with `--dedup` flag (default True)
- [x] Skip creation for exact matches, update for partial matches

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
- [x] 197 tests (was 127)
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
