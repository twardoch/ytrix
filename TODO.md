# ytrix TODO

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
- [ ] Audit `plist2mlist` command - verify reads use extractor.py only
- [ ] Audit `plists2mlist` command - verify reads use extractor.py only
- [ ] Audit `plist2mlists` command - verify reads use extractor.py only
- [ ] Audit `mlists2yaml` command - verify reads use extractor.py only
- [ ] Audit `yaml2mlists` command - verify reads use extractor.py only
- [ ] Audit `ls` command - verify reads use extractor.py only
- [ ] Add deprecation warning to any API read functions in api.py
- [ ] Implement `calculate_diff()` in yaml_ops.py for minimal writes
- [ ] Add `sleep_interval=1` to yt-dlp options for bulk operations
- [ ] Add `--api-fallback` flag for yt-dlp failures (with quota warning)
- [ ] Implement `get_playlist_smart()` with fallback logic

### 10.3 Quota Optimization ([03-quota-optimization.md](issues/401/03-quota-optimization.md))
- [ ] Add `batch_video_metadata(client, video_ids)` to api.py
- [ ] Implement chunking logic for batches of 50 IDs
- [ ] Add `etag` column to `playlists` table in cache.py
- [ ] Add `etag` column to `videos` table in cache.py
- [ ] Implement ETag conditional request logic in api.py
- [ ] Update cache lookup to return ETag with data
- [x] Audit `playlistItems().list()` calls for `maxResults=50`
- [x] Audit `playlists().list()` calls for `maxResults=50`
- [x] Audit `videos().list()` calls for `maxResults=50`
- [ ] Add `estimate_copy_cost()` function to quota.py
- [ ] Add pre-flight quota check to `plist2mlist` command
- [ ] Add pre-flight quota check to `plists2mlists` command
- [ ] Search codebase for `search.list` and remove/deprecate

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
- [ ] Create `ProjectSetupResult` dataclass in gcptrix.py
- [ ] Implement `guide_oauth_setup(project_id, console)` function
- [ ] Add deep link URL generation for OAuth consent screen
- [ ] Add deep link URL generation for credentials page
- [ ] Add `Prompt.ask()` for client_id and client_secret entry
- [ ] Implement `_update_config_with_project()` to auto-append to config.toml
- [ ] Add `gcp_init <project-name>` CLI command
- [ ] Add `--guide-oauth` flag to `gcp_clone` command
- [ ] Implement `handle_clone_error()` with resolution steps
- [ ] Add exponential backoff to IAM policy operations
- [ ] Add `gcp_guide <project>` command to print setup instructions

### 10.6 Enhanced Error Handling ([06-error-handling.md](issues/401/06-error-handling.md))
- [ ] Create `ErrorCategory` enum in api.py
- [ ] Create `APIError` dataclass with message, category, retryable, user_action
- [ ] Implement `classify_error(exc)` function
- [ ] Implement `_parse_error_content(exc)` helper for JSON parsing
- [ ] Update `_should_retry()` to use `classify_error()`
- [ ] Remove retry for `ErrorCategory.QUOTA_EXCEEDED`
- [ ] Add `_log_retry_attempt()` callback for tenacity
- [ ] Implement `display_error(error)` with Rich panels
- [ ] Create `BatchOperationHandler` class
- [ ] Implement `BatchAction` enum (CONTINUE, SKIP_CURRENT, STOP_ALL)
- [ ] Add `handle_error()` method to BatchOperationHandler
- [ ] Implement `_pause_batch()` with resume instructions
- [ ] Update `plists2mlists` to use BatchOperationHandler
- [ ] Add error_category field to journal entries

### 10.7 CLI Dashboard & Quota Display ([07-cli-dashboard.md](issues/401/07-cli-dashboard.md))
- [ ] Create `ytrix/dashboard.py` module
- [ ] Implement `get_time_until_reset()` function with zoneinfo
- [ ] Implement `create_quota_dashboard()` with Rich panel
- [ ] Add progress bar visualization (green/yellow/red thresholds)
- [ ] Add operations table (reads, creates, adds, removes)
- [ ] Add "Remaining Capacity" calculation
- [ ] Implement `show_quota_warning(percentage, remaining)`
- [ ] Implement `show_rate_limit_feedback(wait, attempt, max)`
- [ ] Implement `show_session_summary(started, operations, quota, errors)`
- [ ] Update `quota_status` command to use rich dashboard
- [ ] Add `--all` flag to `quota_status` for all projects
- [ ] Add `--progress` flag to batch commands (default for TTY)
- [ ] Add `--quiet` flag to batch commands

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
- [ ] Create `tests/conftest.py` with shared fixtures
- [ ] Add `mock_youtube_client` fixture
- [ ] Add `quota_exceeded_error` fixture (403)
- [ ] Add `rate_limit_error` fixture (429)
- [ ] Add `mock_yt_dlp` fixture
- [ ] Create `tests/test_error_handling.py`
- [ ] Add `test_classify_429_as_rate_limited`
- [ ] Add `test_classify_403_quota_as_not_retryable`
- [ ] Add `test_retry_decorator_skips_quota_errors`
- [ ] Add `test_batch_pauses_on_quota_exhausted`
- [ ] Add `test_batch_continues_on_not_found`
- [ ] Create `tests/test_quota.py`
- [ ] Add `test_record_usage_increments_counter`
- [ ] Add `test_remaining_quota_calculation`
- [ ] Add `test_warning_threshold_triggers`
- [ ] Add `test_pre_check_blocks_oversized_operation`
- [ ] Add `test_reset_calculation_before_midnight`
- [ ] Create `tests/test_projects.py`
- [ ] Add `test_select_by_quota_group`
- [ ] Add `test_failover_within_same_group`
- [ ] Add `test_no_cross_group_failover`
- [ ] Create `tests/test_journal.py` for enhanced journal
- [ ] Create `tests/test_dashboard.py` for Rich display
- [ ] Mark integration tests with `@pytest.mark.integration`
- [ ] Update README.md with multi-project setup section
- [ ] Update README.md with quota management section
- [ ] Update README.md with error recovery section
- [ ] Create `docs/errors.md` with error catalog
- [ ] Update CHANGELOG.md with Phase 10 changes
- [ ] Run coverage report and ensure 80%+ for new modules

## Future (Not Planned)
- [ ] Playlist description templates
- [ ] Watch later playlist support
- [ ] Playlist thumbnail management
