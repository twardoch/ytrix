# Ytrix Codebase Improvement Specification

## Credential Rotation (Multi-Project)

To avoid hitting the YouTube Data API’s per-project quota (10,000 units/day),
enhance Ytrix’s credential rotation across multiple Google Cloud projects. The
goal is to seamlessly distribute API calls over 3–5 projects so heavy batch
operations no longer stall at 10k units. All commands performing write
operations (e.g. creating or updating playlists/videos) must use this rotation
mechanism transparently. Key implementation tasks:

  * **Integrate Rotation into All Writes:** Ensure every command that invokes YouTube Data API write operations goes through the multi-project credential selection logic. Ytrix already supports multiple project credentials via config (`[[projects]]` entries in `config.toml`) and per-project OAuth tokens. Expand the existing `projects.py` management to wrap all API client initialization so that no write uses a single project’s credentials exclusively. For example, functions in `api.py` that call `youtube.v3` endpoints should obtain their credentials from a `ProjectManager` or similar mechanism rather than a fixed token.

  * **Detect Quota Exhaustion & Rotate:** Implement robust error handling to catch daily quota errors and trigger rotation. If a request returns an HTTP 403 with error `quotaExceeded` (daily limit hit), Ytrix should immediately switch to the next available project’s credentials. Similarly, detect HTTP 429 rate-limit responses and, after applying any backoff, switch to a different project if one is available (this helps if a project hits a per-minute quota). This logic can be added in the centralized API call wrapper (e.g., in `api.py` or within the `ProjectManager.rotate_on_quota_exceeded()` method). Track which project was active when an error occurred, mark it as exhausted, and round-robin to the next project in the list.

  * **Persist and Reset Quota Usage:** Extend the quota tracking so that each project’s used units are recorded and can be persisted across runs (e.g., in `~/.ytrix/quota_state.json` as already planned). Implement logic to automatically reset each project’s daily quota usage at midnight Pacific Time. For instance, on each program start or before any new operation, check the current time; if past midnight PT since last update, reset internal counters for all projects. The `ProjectManager._check_quota_reset()` (or a new function in `quota.py`) can handle this by comparing timestamps and clearing usage stats. This ensures that a project marked “exhausted” yesterday becomes eligible again after the daily reset.

  * **Error Handling and Messaging:** When a quota limit is hit, provide clear feedback. Immediately inform the user that the active project’s quota is exhausted and Ytrix is switching credentials. If no alternate project remains (all quotas exhausted), gracefully stop further API calls (see **Resilience & UX** below) and explain the situation. Also, log or display the time until quotas reset (compute time until midnight PT) to inform the user. For example: “Project X quota exhausted – switching to Project Y” or “All project quotas exhausted (reset in 5h 30m).” These messages should be visible even without `--verbose`, so users aren’t left wondering why operations paused.

  * **Maintain Backward Compatibility:** Ensure that single-project configurations and existing token files remain supported. Ytrix currently allows a single `[oauth]` config section and stores its token in `~/.ytrix/token.json` for legacy setups. The improved rotation code should detect if multiple projects are configured; if not, continue using the single project as before (no rotation). Likewise, keep using the existing per-project token files `~/.ytrix/tokens/{project}.json` for OAuth credentials – do not break or duplicate these. The rotation logic should work with the token management, e.g. ensure `projects_auth` and token refresh flows still store credentials under the correct project name.

## GCP Project Cloning (Semi-Automated)

Improve the `gcptrix.py` module and CLI commands for cloning Google Cloud
projects, making it easier to set up multiple credential sets. The cloning
process should be as automated as possible while guiding the user through any
required manual steps (especially OAuth consent screen configuration). Key
enhancements:

  * **Clone Project Infrastructure:** The `ytrix gcp_clone <source_project> <suffix>` command (already implemented) should be refined to reliably duplicate a project’s essential settings. This likely involves using the Google Cloud API or gcloud CLI to create a new project with an ID derived from the source plus the given suffix, enable the same APIs (e.g. YouTube Data API, OAuth, etc.), and copy relevant configurations. Ensure that after running `gcp_clone`, the new project has YouTube Data API enabled and any required IAM roles or service accounts from the source project are recreated (unless `--skip_service_accounts` was used). Use the existing `gcp_inventory` to gather source project details and then apply them to the new project.

  * **Error Handling and Retries:** Enhance `gcptrix.py` to handle common errors during cloning. For example, if creating the project or enabling services hits a rate limit or quota (Google Cloud may impose limits on project creation frequency or API enabling), catch these errors and either retry with exponential backoff or present a clear message to the user. If an IAM conflict occurs (e.g. attempting to create a service account or OAuth client that already exists), the tool should detect this and either skip creating duplicates or prompt the user for how to proceed. For instance, if `ytrix gcp_clone` is run twice with the same suffix, it should recognize the project already exists and warn rather than fail on a name collision. Provide suggestions like “Project ID already in use, try a different suffix” or “Service account XYZ already exists in target – skipping creation”. In cases of transient Google Cloud errors, suggest the user wait and retry (“Google Cloud API rate limit reached, pausing 30s...”).

  * **Guide Manual OAuth Setup:** Certain steps cannot be fully automated via API (e.g., configuring the OAuth consent screen and creating OAuth client credentials for the new project). After the clone operation completes, the CLI must clearly list what manual steps the user needs to perform for the new project. For example, output instructions such as: “**Manual steps required:** Go to Google Cloud Console for project `<newProjectId>` and configure the OAuth consent screen (add test user and scope for YouTube API), then create an OAuth 2.0 Client ID (Desktop app) and obtain the client_id and client_secret. Update your `config.toml` with the new credentials and run `ytrix projects_auth <name>`.” These messages can be printed to the console in a formatted list after clone, and should also be included in the JSON output (if `--json-output` is used, provide a structured list of steps or links). Consider adding a confirmation prompt or flag: for instance, `ytrix gcp_clone` could accept `--guide` to automatically run a guidance output (or always do so by default). Leverage any existing helper (perhaps `gcp_guide`) to generate these instructions. This ensures users know how to finalize the cloned project’s setup.

  * **Interactive Prompts (Optional):** Where feasible, add interactive prompts to improve user experience. For example, if the clone operation finds that the user hasn’t set up a billing account or hits an org policy restriction, pause and explain (“Project created but no billing account. Please link a billing account in the console if required for API access.”). Direct prompts for manual steps might be tricky (since the user must go to a browser), so primarily focus on printing clear next-step instructions rather than waiting for user input.

  * **CLI Output and Logging:** Make the output of `gcp_clone` and `gcp_inventory` human-readable. Use `rich` to format statuses (e.g., steps like “Enabling YouTube Data API... ✅”) for console output, and ensure the command returns a summary object for JSON output. For instance, on success, return the new project ID, name, and a list of actions performed (APIs enabled, service accounts cloned, etc.) so that `--json-output` yields a machine-readable report. If `gcloud` CLI is used under the hood, capture its output and errors to include in our logging. If the user does not have the gcloud tool or is not authenticated, detect that early and surface a clear error (the tests suggest we already check for gcloud presence). In case of missing prerequisites, instruct how to install or authenticate gcloud rather than a generic stack trace.

## CLI-Based Reporting Enhancements

Extend Ytrix’s CLI commands to provide better visibility into which project is
in use, how much quota remains, and any rotation or failure events. By
improving reporting, users can understand the tool’s internal decisions and
get data for scripting if needed. Changes to implement:

  * **Active Project Status:** Modify the `ytrix projects` command (or introduce a new `ytrix status` command) to clearly indicate the current active project and its status. The `projects` listing should mark which project is currently being used (e.g., with an asterisk or “[ACTIVE]” label) and which are on standby. This can be done by querying the `ProjectManager.current_project()` and highlighting that entry in the output. For example, console output could be:
        
        text
        
        Copy code
        
        Projects:
        * main – 6500 units used today, ~3500 remaining (Active)
          backup – 0 used today, 10000 remaining
        

In JSON mode, `ytrix projects` should output an array of project objects
including fields like `name`, `active` (bool), `quota_used`,
`quota_remaining`, etc. The underlying `projects.py` can provide a
`status_summary()` method that returns these details for formatting.

  * **Quota Usage and Reset Info:** Include quota statistics in the report. For each project, show how many units have been consumed and the remaining quota (assuming 10,000 total) for the current day. If possible, also show an estimated reset time (midnight PT) or time to reset. For example: “resets in 5h 30m”. This information can be computed using the Pacific Time zone and the current time (the `quota.py` module could provide a helper for this, given `DAILY_QUOTA_LIMIT` and perhaps a stored last-reset timestamp). If a project is exhausted, mark it clearly (e.g., “**EXHAUSTED** until reset”). This gives users immediate insight into whether they are close to limits.

  * **Rotation History Logging:** Implement a mechanism to record credential rotations during a long-running operation and display this history on demand. This could be an extension of the `projects` command (e.g., `ytrix projects --history` to show when project switches occurred) or a separate `quota_status` command. At minimum, if a rotation has happened in the current session, the `projects` output should note it (e.g., “Project main exhausted at 10:45, switched to backup”). You can maintain an in-memory log of rotation events in `ProjectManager` (and optionally persist it to the quota state file). For example, whenever `rotate_on_quota_exceeded()` triggers, append an entry with timestamp, from-project, to-project, and reason. Then `projects --history` can print these entries in chronological order. In JSON output, provide an array of rotation events (with fields like `timestamp` and `project_switched_to`). This history helps users auditing what happened during batch operations.

  * **Report Failed Operations by Project:** Enhance the reporting of any failed API operations, tied to the project on which they failed. This likely integrates with the existing journaling system for batch processes. When an API call fails (e.g., due to quota exhaustion or other errors) in a batch, ensure the journal entry or error log captures the project name that was in use. You might extend the `Journal` data model to include a `project` field for each task, or have the error message include it. Then update `ytrix journal_status` or a new `ytrix projects --errors` flag to list failures grouped by project. For example: “Project main: 2 playlist creations failed (quota exceeded); Project backup: 1 playlist update failed (403 forbidden).” This can be printed in a summary table. By surfacing this, the user knows if a particular project is causing errors (e.g., missing permissions or out of quota). In JSON mode, output a structured report, e.g. `{ "failures": [ { "project": "main", "operations_failed": 2, "last_error": "quotaExceeded" }, ... ] }`.

  * **Human-Friendly and JSON Output:** Use Rich library features (tables, coloring) to make the text reports easy to read. For example, color code warning states (if quota <20% remaining, show in yellow/orange). Align columns for project name, usage, etc. Ensure that all this information is also accessible via `--json-output` for automation. Likely, the CLI methods (`projects()`, `quota_status()` etc.) should construct a Python dict with all relevant info and either pretty-print it for console or dump as JSON when the flag is set (this pattern may already exist in Ytrix’s CLI design). Verify that every new field or command we add respects the global `--json-output` flag (tests indicate that the CLI already supports JSON output for all commands).

## Resilience & UX Improvements

These changes focus on making Ytrix more resilient to API limits and providing
a smoother user experience under error conditions. The CLI should fail
gracefully, guide the user to recovery, and adjust to conditions like rate
limiting automatically. Key improvements:

  * **Graceful Degradation When Out of Quota:** If all configured projects’ quotas are exhausted (i.e. after rotating through all and each returned 403 quotaExceeded), Ytrix should pause or terminate the operation in a controlled way, rather than simply erroring out. For batch operations using the journal system, implement an automatic pause: mark remaining tasks as pending and stop making further API calls. Inform the user that processing has halted due to quota limits and can be resumed after quota reset. For example: “**All projects exhausted.** Pausing operations – please resume after 00:00 Pacific Time when quotas reset.” Provide a hint like “Use `ytrix plists2mlists --resume` to continue where you left off.” The code can detect the condition in the rotation logic: if a rotate is attempted but no project is available, set a flag that triggers the pause. For single operations (not batch), simply exit with a clear error message instead of a stack trace. Possibly return a specific error code or message in JSON output (e.g., an error field indicating quota exhaustion).

  * **Adaptive Throttling Feedback:** Ytrix already implements exponential backoff for 429 rate-limit errors using tenacity, but we need to make this behavior visible to the user. When the tool encounters a 429 (Too Many Requests) from the YouTube API, it should log a warning like “Rate limit reached, slowing down API calls”. If repeated 429s occur, increase the throttle delay and inform the user: e.g., “Increasing delay to 500ms after continued 429 errors”. This messaging aligns with the plan to show “slowing down, will retry in X seconds”. Implement this in the retry logic: perhaps in the tenacity retry handler or a custom wrapper in `api.py`, after a 429 is caught the first time, print a one-time notice. If the issue persists and we escalate backoff, print another notice with the new wait interval. Use the logging framework or Rich console to ensure these notices are always shown (maybe as yellow warnings) even if not in verbose mode. Additionally, on persistent failures (e.g., after max retries), suggest to the user to try a higher base throttle via the `--throttle` flag or to resume later. For instance: “Still receiving 429 errors; you may try re-running with `--throttle 500` or wait and `--resume` later.”

  * **Consolidated Error Messages and Recovery Hints:** Audit all places where Ytrix outputs errors or exceptions, and improve the consistency and helpfulness of these messages. Each error case should ideally tell the user what went wrong in plain language and how they might fix or avoid it. For example:

    * If an API call fails with a 403 error that is not quota-related (like “accessForbidden”), the message could be “Error: The request was forbidden. (Are your OAuth scopes correct for this action?)”.

    * If a network timeout occurs, “Network error, please check your connection and try again.”

    * For quota or rate-limit issues, consolidate with the guidance above (e.g., “Quota exceeded – wait until tomorrow or add more projects” or “Rate limit hit – slowing down requests”).

Where possible, catch exceptions in a higher-level try/except (for the CLI
commands) so that stack traces are not shown to the end-user. Instead, use
`loguru` to log debug details to a file (if needed) but present a clean
message on stdout. Also, group related messages: for instance, if a batch
finishes with some failures, print a summary: “5 playlists copied, 2 failed.”
and then for each failed one a brief reason and next step (those reasons would
include project info as mentioned above). Use Rich to highlight these
summaries (maybe a final status box or table).

  * **Logging and Verbosity:** Continue to use the `--verbose` flag to control debug output, but ensure that essential warnings (quota exhaustion, major retry notices) appear even in normal mode (possibly as one-liners). In verbose mode, include more details like full stack traces or HTTP error content for troubleshooting. Also, consider writing out a log file under `~/.ytrix/log.txt` (rotating) for later analysis of what happened, especially for long runs. This isn’t strictly required by the user prompt, but it aligns with improving UX for error cases – the user could be pointed to a log file for more info on failures.

  * **User Guidance on Recovery:** Integrate hints into the CLI output wherever appropriate. Examples: after stopping due to quota, explicitly mention the `--resume` flag and which command to use it with; after encountering certain errors, suggest checking the config or token (e.g., if a 401 Unauthorized appears, recommend re-running `projects_auth` to refresh credentials). These hints should be concise and appear right after the error message. By consolidating such hints into the error handling routines, we make the tool more user-friendly and self-documenting in failure scenarios.

## Futureproofing for Multi-User Support

Although multi-user support (managing multiple YouTube accounts/profiles) is
not needed immediately, we should prepare the codebase for this future
capability. The idea is to allow a “user” namespace so that Ytrix could handle
separate configurations and tokens for different YouTube channel accounts. To
futureproof for this:

  * **Config Structure for Users:** Plan an extension of the configuration format to distinguish multiple user profiles. Currently, `config.toml` holds a single `channel_id` and associated credentials/projects. In the future, we might have an overarching config with multiple user entries (each with their own channel_id and projects list). To avoid a major refactor later, design the config loader to potentially handle a structure like:
        
        toml
        
        Copy code
        
        [[users]]
        name = "primary"
        channel_id = "UCxxxxx"
        [[users.projects]]
        name = "main"
        client_id = "..."
        client_secret = "..."
        [[users.projects]]
        name = "backup"
        client_id = "..."
        client_secret = "..."
        

For now, we won’t implement parsing of multiple users, but we can adjust our
parsing logic so that it’s not too tightly coupled to a single global channel.
For example, the `Config` dataclass could have a field for `user_name`
(defaulting to None or a single default user) to accommodate this later.
Ensuring that functions that retrieve `channel_id` or project lists can be
easily modified to select a given user context will make multi-user addition
easier.

  * **File Path Namespace:** Change how Ytrix stores tokens, cache, and state on disk to allow separation by user. Presently, everything is under `~/.ytrix/`. We should introduce an optional user-specific subdirectory. For example, tokens could reside at `~/.ytrix/tokens/{project}.json` for single-user (as now) but in multi-user mode, move to `~/.ytrix/users/{username}/tokens/{project}.json`. Similarly, `quota_state.json` could become `~/.ytrix/users/{username}/quota_state.json` per user, and the journal file `~/.ytrix/journal.json` could be per user as well. In code, this means creating paths through a function that incorporates the user context. We can implement this now in a backward-compatible way: e.g., have `Config.get_config_dir(user: str = None)` that by default returns `~/.ytrix`, but if a `user` is specified, returns `~/.ytrix/users/{user}`. Use this helper whenever constructing file paths (in `projects.py`, `quota.py`, `journal.py`, etc.), so that enabling multi-user later is just a matter of passing a user name. For now, we would always call it with the default (no user), but the codepath is ready.

  * **Internal Data Models:** Update relevant classes and functions to carry an optional user identifier. For instance, in a future multi-user scenario, one might run `ytrix --user alice ls` to list playlists for Alice’s channel vs Bob’s. To prepare, the `ProjectManager` or config should be keyed by user. We can introduce a top-level `UserManager` or simply extend `ProjectManager` to handle multiple sets of projects indexed by user. In the immediate term, this could be as simple as adding a `user: str` attribute to `ProjectConfig`/`ProjectState` classes (or the Config object) that defaults to a single value. It won’t be actively used yet, but it ensures that functions like `projects_select` or `projects_auth` can later be scoped to a user. Likewise, consider naming collisions: two users might have a project both named “main”, so internal logic should qualify projects by user to avoid confusion. Storing state as `{user -> {project -> data}}` in memory and in files (when multi-user is active) is a possible approach.

  * **Optional CLI Extensions (Not active yet):** We won’t expose multi-user switches in the CLI immediately, but we can lay groundwork. For example, the Fire CLI could be prepared to accept a `--user` global flag. We can define it now (hidden or inoperative) so that it doesn’t break anything. This flag would select the user profile for the command. Internally, it would set the context so that `Config` and managers load that user’s data. For now, it can default to the single user. Document in code (comments or docstrings) how multi-user could be activated, to guide future developers. Ensure that nothing in the code inherently assumes a single channel – audit for any global variables like a single `channel_id` usage. Instead, make sure it’s always accessed via the config object, which in future could hold multiple.

By making these adjustments now, adding real multi-user support later will be
much less invasive. The directory structure and data models will already
accommodate an extra dimension of separation. This futureproofing does not
change Ytrix’s outward behavior in the current single-user mode, but it sets
the stage for supporting multiple accounts without a complete redesign.

Citations

[llms.txtfile://file_00000000185471f4b501af53b61e24c9](file://file_00000000185471f4b501af53b61e24c9#:~:text=,resume%60%20later)[llms.txtfile://file_00000000185471f4b501af53b61e24c9](file://file_00000000185471f4b501af53b61e24c9#:~:text=,to%20be%20configured%20separately%2C%20etc)[llms.txtfile://file_00000000185471f4b501af53b61e24c9](file://file_00000000185471f4b501af53b61e24c9#:~:text=def%20test_gcp_clone_command_exists%28%28self%29%29%20,None)[llms.txtfile://file_00000000185471f4b501af53b61e24c9](file://file_00000000185471f4b501af53b61e24c9#:~:text=def%20test_gcp_clone_requires_gcloud%28%28self%29%29%20)[llms.txtfile://file_00000000185471f4b501af53b61e24c9](file://file_00000000185471f4b501af53b61e24c9#:~:text=def%20status_summary%28%28self%29%29%20,bool)[llms.txtfile://file_00000000185471f4b501af53b61e24c9](file://file_00000000185471f4b501af53b61e24c9#:~:text=def%20get_client%28%28self%29%29%20)[llms.txtfile://file_00000000185471f4b501af53b61e24c9](file://file_00000000185471f4b501af53b61e24c9#:~:text=,Phase%209%20complete%29)[llms.txtfile://file_00000000185471f4b501af53b61e24c9](file://file_00000000185471f4b501af53b61e24c9#:~:text=match%20at%20L919%20ytrix%20plists2mlists,Resume%20interrupted%20batch)[llms.txtfile://file_00000000185471f4b501af53b61e24c9](file://file_00000000185471f4b501af53b61e24c9#:~:text=ytrix%20plists2mlists%20playlists.txt%20,Resume%20interrupted%20batch)

All Sources

[llms.txt](llms.txt)

