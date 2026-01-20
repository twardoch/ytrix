# ytrix TODO

## Urgent

- [x] When downloading and a proxy turns out to be extremely slow, we should have some timeout and then we retry (Webshare endpoint will give us a different proxy)
  - Added `socket_timeout=30` and `retries=3` to yt-dlp when using rotating proxy
  - Each retry gets a new IP from Webshare


## Phase 10: ToS-Compliant Architecture & UX Improvements

Full specification: [issues/401/](issues/401/)

### 10.1 ToS Compliance & Architecture Pivot ([01-overview-compliance.md](issues/401/01-overview-compliance.md))
- [x] Rename `rotate_on_quota_exceeded()` to `handle_quota_exhausted()` in projects.py
- [x] Add `quota_group: str` field to `ProjectConfig` dataclass in config.py
- [x] Add `environment: str` field (dev/staging/prod) to `ProjectConfig`
- [x] Add `priority: int` field for selection order within quota groups
- [x] Update config.py schema validation for new fields
- [x] Add `show_tos_reminder()` function in cli.py
- [x] Add first-run detection for ToS reminder display
- [x] Update README.md with multi-project ToS guidance section
- [x] Add docstring warnings about ToS to projects.py functions
- [x] Add validation in `projects_add` to prevent > 5 projects in same group

### 10.2 Hybrid Read/Write Architecture ([02-hybrid-architecture.md](issues/401/02-hybrid-architecture.md))
- [x] Audit `plist2mlist` command - uses yt-dlp for source, API for writes only
- [x] Audit `plists2mlist` command - uses yt-dlp for source, API for writes only
- [x] Audit `plist2mlists` command - uses yt-dlp for source, API for writes only
- [x] Audit `mlists2yaml` command - hybrid: API to list own, yt-dlp for video details
- [x] Audit `yaml2mlists` command - API required for private playlist access
- [x] Audit `ls` command - yt-dlp for --user, API for own (private access needed)
- [x] Implement `calculate_diff()` in yaml_ops.py for minimal writes
- [x] Add `sleep_interval` to yt-dlp options for bulk operations (YtdlpRateLimitConfig)

Note: API reads are required for own private/unlisted playlists (yt-dlp can't access without login).
The hybrid approach is correct: yt-dlp for external reads, API for own playlist management.

### 10.3 Quota Optimization ([03-quota-optimization.md](issues/401/03-quota-optimization.md))
- [x] Add `batch_video_metadata(client, video_ids)` to api.py
- [x] Implement chunking logic for batches of 50 IDs
- [ ] Add `etag` column to `playlists` table in cache.py
- [ ] Add `etag` column to `videos` table in cache.py
- [ ] Implement ETag conditional request logic in api.py
- [ ] Update cache lookup to return ETag with data
- [x] Audit `playlistItems().list()` calls for `maxResults=50`
- [x] Audit `playlists().list()` calls for `maxResults=50`
- [x] Audit `videos().list()` calls for `maxResults=50`
- [x] Add `estimate_copy_cost()` function to quota.py
- [x] Add pre-flight quota check to `plist2mlist` command
- [x] Add pre-flight quota check to `plists2mlists` command
- [x] Search codebase for `search.list` and remove/deprecate (none found)

### 10.4 Project Context Management ([04-project-context.md](issues/401/04-project-context.md))
- [x] Create `select_context(quota_group, environment, force_project)` method
- [x] Implement `_get_candidates(quota_group, environment)` helper
- [x] Update `handle_quota_exhausted()` to only switch within same group
- [x] Add logging when context switch occurs with reason
- [x] Add `--quota-group` global flag to CLI
- [x] Update `projects` command output to group by quota_group
- [x] Add "[ACTIVE]" marker to currently selected project
- [x] Add remaining quota display per project in `projects` output
- [x] Add time-until-reset to `projects` output footer
- [x] Add quota increase URL to exhaustion message

### 10.5 GCP Setup Automation ([05-gcp-automation.md](issues/401/05-gcp-automation.md))
- [x] Implement `get_oauth_guide(project_id)` function with step-by-step instructions
- [x] Add deep link URL generation for OAuth consent screen
- [x] Add deep link URL generation for credentials page
- [x] Implement `init_project()` to create new GCP project
- [x] Add `gcp_init <project-name>` CLI command
- [x] Enable YouTube Data API automatically during init
- [x] Add `Prompt.ask()` for client_id and client_secret entry
- [ ] Implement `_update_config_with_project()` to auto-append to config.toml
- [ ] Add `--guide-oauth` flag to `gcp_clone` command
- [ ] Add exponential backoff to IAM policy operations
- [x] Add `gcp_guide <project>` command to print setup instructions separately

### 10.6 Enhanced Error Handling ([06-error-handling.md](issues/401/06-error-handling.md))
- [x] Create `ErrorCategory` enum in api.py
- [x] Create `APIError` dataclass with message, category, retryable, user_action
- [x] Implement `classify_error(exc)` function
- [x] JSON parsing integrated into classify_error (no separate helper needed)
- [x] Update `_is_retryable_error()` to use `classify_error()`
- [x] Remove retry for `ErrorCategory.QUOTA_EXCEEDED` (handled in classify_error)
- [x] Add `_log_retry_attempt()` callback for tenacity
- [x] Implement `display_error(error)` with Rich panels
- [x] Create `BatchOperationHandler` class
- [x] Implement `BatchAction` enum (CONTINUE, SKIP_CURRENT, STOP_ALL)
- [x] Add `handle_error()` method to BatchOperationHandler
- [x] Implement `_pause_batch()` with resume instructions (as `_show_pause_message()`)
- [x] Update `plists2mlists` to use BatchOperationHandler
- [x] Add error_category field to journal entries

### 10.7 CLI Dashboard & Quota Display ([07-cli-dashboard.md](issues/401/07-cli-dashboard.md))
- [x] Create `ytrix/dashboard.py` module
- [x] Implement `get_time_until_reset()` function with zoneinfo
- [x] Implement `create_quota_dashboard()` with Rich panel
- [x] Add progress bar visualization (green/yellow/red thresholds)
- [x] Add operations table (reads, creates, adds, removes)
- [x] Add "Remaining Capacity" calculation
- [x] Implement `show_quota_warning(percentage, remaining)`
- [x] Implement `show_rate_limit_feedback(wait, attempt, max)`
- [x] Implement `show_session_summary(started, operations, quota, errors)`
- [x] Update `quota_status` command to use rich dashboard (already implemented)
- [x] Add `--all` flag to `quota_status` for all projects (--all-projects flag exists)
- [x] Add `--progress` flag to batch commands (Progress bars respect _should_print)
- [x] Add `--quiet` flag to batch commands (global --quiet flag implemented)

### 10.8 Journaling Improvements ([08-journaling-improvements.md](issues/401/08-journaling-improvements.md))
- [ ] Add `ErrorCategory` enum to journal.py (mirror from api.py)
- [ ] Add `TaskStatus.SKIPPED` value
- [ ] Create enhanced `JournalTask` dataclass
- [ ] Add `batch_id`, `command`, `source_type` fields to JournalTask
- [ ] Add `started_at`, `completed_at` timestamps to JournalTask
- [ ] Add `error_category`, `quota_consumed`, `project_used` fields
- [ ] Create `JournalBatch` dataclass
- [ ] Add batch progress counters (total, completed, failed, skipped)
- [ ] Add `is_complete`, `is_paused`, `pause_reason` fields
- [ ] Implement `JournalManager` class
- [ ] Implement `create_batch()` method
- [ ] Implement `add_task()` method
- [ ] Implement `update_task()` method with batch counter updates
- [ ] Implement `get_resumable_tasks()` method
- [ ] Implement `pause_batch()` and `resume_batch()` methods
- [ ] Implement `get_batch_summary()` with ETA calculation
- [ ] Implement `cleanup_completed(max_age_days)` method
- [ ] Add `--resume-batch BATCH_ID` flag to plists2mlists
- [ ] Add `--skip-failed` flag to plists2mlists
- [ ] Add `journal_status` CLI command
- [ ] Add `journal_cleanup` CLI command
- [ ] Write migration script for existing journal.json

### 10.9 Testing & Documentation ([09-testing-documentation.md](issues/401/09-testing-documentation.md))
- [x] Create `tests/conftest.py` with shared fixtures
- [x] Add `mock_youtube_client` fixture
- [x] Add `quota_exceeded_error` fixture (403)
- [x] Add `rate_limit_error` fixture (429)
- [x] Add `mock_yt_dlp` fixture (mock_ytdlp_info, mock_ytdlp_playlist_info)
- [x] Create `tests/test_error_handling.py`
- [x] Add `test_classify_429_as_rate_limited`
- [x] Add `test_classify_403_quota_as_not_retryable`
- [x] Add `test_retry_decorator_skips_quota_errors` (covered by error handling tests)
- [x] Add `test_batch_pauses_on_quota_exhausted`
- [x] Add `test_batch_continues_on_not_found`
- [x] Create `tests/test_quota.py`
- [x] Add `test_record_usage_increments_counter`
- [x] Add `test_remaining_quota_calculation`
- [x] Add `test_warning_threshold_triggers`
- [x] Add `test_pre_check_blocks_oversized_operation`
- [x] Add `test_reset_calculation_before_midnight` (covered by get_time_until_reset test)
- [x] Create `tests/test_projects.py` (59 tests including rate limit handling)
- [x] Add `test_select_by_quota_group` (test_select_context_by_quota_group)
- [x] Add `test_failover_within_same_group` (test_handle_quota_exhausted_switches_within_same_group)
- [x] Add `test_no_cross_group_failover` (test_handle_quota_exhausted_does_not_cross_groups)
- [x] Create `tests/test_journal.py` for enhanced journal (24 tests)
- [x] Create `tests/test_dashboard.py` for Rich display (25 tests, 100% coverage)
- [x] Mark integration tests with `@pytest.mark.integration` (already configured in pyproject.toml)
- [x] Update README.md with multi-project setup section
- [x] Update README.md with quota management section
- [x] Update README.md with error recovery section
- [x] Create `docs/errors.md` with error catalog
- [x] Update CHANGELOG.md with Phase 10 changes
- [x] Run coverage report and ensure 80%+ for new modules (projects: 98%, quota: 99%, dashboard: 100%)

## Future (Not Planned)
- [ ] Playlist description templates
- [ ] Watch later playlist support
- [ ] Playlist thumbnail management
