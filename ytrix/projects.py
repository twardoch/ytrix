"""Multi-project credential management with context switching.

Manages multiple GCP projects for quota distribution. Automatically
switches to the next available project when quota is exhausted.

State is persisted to ~/.ytrix/quota_state.json for cross-session tracking.

Note: Context switching is ToS-compliant when used for distinct purposes
(e.g., dev vs prod) within quota_groups. Using multiple projects to
circumvent quota limits for a single purpose violates Google ToS.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from ytrix.config import Config, ProjectConfig, get_config_dir, get_token_path
from ytrix.logging import logger
from ytrix.quota import DAILY_QUOTA_LIMIT


def get_api_proxy_url() -> str | None:
    """Get proxy URL for API calls from environment variables.

    Uses the same Webshare rotating proxy config as yt-dlp.
    """
    user = os.getenv("WEBSHARE_PROXY_USER")
    password = os.getenv("WEBSHARE_PROXY_PASS")
    host = os.getenv("WEBSHARE_DOMAIN_NAME")
    port = os.getenv("WEBSHARE_PROXY_PORT")

    if not all([user, password, host, port]):
        return None

    return f"http://{user}:{password}@{host}:{port}"


def _create_proxied_http() -> Any:
    """Create an httplib2.Http object with proxy support if configured.

    Returns:
        httplib2.Http object, optionally configured with proxy.
    """
    import httplib2

    proxy_url = get_api_proxy_url()
    if not proxy_url:
        return httplib2.Http(timeout=60)

    # Use httplib2's built-in proxy_info_from_url for simpler parsing
    proxy_info = httplib2.proxy_info_from_url(proxy_url)

    # Parse for logging only
    parsed = urlparse(proxy_url)
    logger.info(
        "API proxy enabled: {}:{} (rotating IPs)",
        parsed.hostname,
        parsed.port,
    )

    return httplib2.Http(proxy_info=proxy_info, timeout=60)


# YouTube API quota extension request form
QUOTA_EXTENSION_URL = "https://support.google.com/youtube/contact/yt_api_form"

# Pacific timezone for quota reset
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

# Rate limit cooldown duration in seconds (how long to avoid a rate-limited project)
RATE_LIMIT_COOLDOWN_SECONDS = 60.0
# Number of consecutive rate limits before marking project for cooldown
RATE_LIMIT_THRESHOLD = 3


@dataclass
class ProjectState:
    """Quota state for a single project."""

    name: str
    quota_used: int = 0
    last_reset_date: str = ""  # YYYY-MM-DD in Pacific Time
    is_exhausted: bool = False
    last_error: str | None = None
    # Rate limit tracking (not persisted - resets on restart)
    rate_limit_hits: int = 0
    rate_limit_cooldown_until: float = 0.0  # time.monotonic() value

    def to_dict(self) -> dict[str, str | int | bool | None]:
        """Convert to dict for JSON serialization."""
        return {
            "name": self.name,
            "quota_used": self.quota_used,
            "last_reset_date": self.last_reset_date,
            "is_exhausted": self.is_exhausted,
            "last_error": self.last_error,
            # Note: rate_limit_hits and cooldown are NOT persisted (transient)
        }

    @classmethod
    def from_dict(cls, data: dict[str, str | int | bool | None]) -> ProjectState:
        """Create from dict."""
        name = data.get("name")
        quota_used = data.get("quota_used")
        last_reset_date = data.get("last_reset_date")
        is_exhausted = data.get("is_exhausted")
        last_error = data.get("last_error")
        return cls(
            name=str(name) if name else "",
            quota_used=int(quota_used) if isinstance(quota_used, int) else 0,
            last_reset_date=str(last_reset_date) if last_reset_date else "",
            is_exhausted=bool(is_exhausted) if is_exhausted else False,
            last_error=str(last_error) if isinstance(last_error, str) else None,
            rate_limit_hits=0,
            rate_limit_cooldown_until=0.0,
        )

    def is_in_cooldown(self) -> bool:
        """Check if project is in rate limit cooldown."""
        return time.monotonic() < self.rate_limit_cooldown_until

    def is_available(self) -> bool:
        """Check if project is available (not exhausted and not in cooldown)."""
        return not self.is_exhausted and not self.is_in_cooldown()

    def reset_rate_limits(self) -> None:
        """Reset rate limit counters (called after successful operation)."""
        self.rate_limit_hits = 0

    def record_rate_limit(self) -> bool:
        """Record a rate limit hit. Returns True if threshold exceeded."""
        self.rate_limit_hits += 1
        if self.rate_limit_hits >= RATE_LIMIT_THRESHOLD:
            self.rate_limit_cooldown_until = time.monotonic() + RATE_LIMIT_COOLDOWN_SECONDS
            return True
        return False


@dataclass
class ProjectManager:
    """Manages multiple GCP projects with quota-aware context switching.

    Selects projects based on quota_group (for purpose-based separation)
    and switches to another project within the same group when exhausted.

    Usage:
        config = load_config()
        manager = ProjectManager(config)

        # Get current project and client
        project = manager.current_project
        client = manager.get_client()

        # Record quota usage
        manager.record_quota(50)

        # Handle quota exceeded error
        if manager.handle_quota_exhausted():
            client = manager.get_client()  # New client for next project
        else:
            # All projects in group exhausted
            raise QuotaExceededError(...)
    """

    config: Config
    _current_index: int = 0
    _states: dict[str, ProjectState] = field(default_factory=dict)
    _client: Any = field(default=None, repr=False)
    _credentials: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Initialize state for all projects."""
        self._load_state()
        self._check_quota_reset()

    @property
    def state_path(self) -> Path:
        """Path to quota state file."""
        return get_config_dir() / "quota_state.json"

    def _load_state(self) -> None:
        """Load persisted quota state."""
        if not self.state_path.exists():
            # Initialize state for all projects
            for name in self.config.get_project_names():
                self._states[name] = ProjectState(name=name)
            return

        try:
            with open(self.state_path) as f:
                data = json.load(f)
            self._current_index = data.get("current_index", 0)
            for state_data in data.get("projects", []):
                state = ProjectState.from_dict(state_data)
                self._states[state.name] = state
            # Add any new projects not in saved state
            for name in self.config.get_project_names():
                if name not in self._states:
                    self._states[name] = ProjectState(name=name)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load quota state: {}", e)
            for name in self.config.get_project_names():
                self._states[name] = ProjectState(name=name)

    def _save_state(self) -> None:
        """Persist quota state to disk."""
        data = {
            "current_index": self._current_index,
            "projects": [s.to_dict() for s in self._states.values()],
        }
        with open(self.state_path, "w") as f:
            json.dump(data, f, indent=2)
        self.state_path.chmod(0o600)

    def _check_quota_reset(self) -> None:
        """Reset quota counters if a new day has started (PT)."""
        today = datetime.now(PACIFIC_TZ).strftime("%Y-%m-%d")
        for state in self._states.values():
            if state.last_reset_date != today:
                logger.debug("Resetting quota for project '{}' (new day)", state.name)
                state.quota_used = 0
                state.is_exhausted = False
                state.last_error = None
                state.last_reset_date = today
        self._save_state()

    @property
    def project_names(self) -> list[str]:
        """Get list of configured project names."""
        return self.config.get_project_names()

    @property
    def current_project(self) -> ProjectConfig:
        """Get the current active project configuration."""
        names = self.project_names
        if not names:
            msg = "No projects configured"
            raise ValueError(msg)
        if self._current_index >= len(names):
            self._current_index = 0
        return self.config.get_project(names[self._current_index])

    @property
    def current_state(self) -> ProjectState:
        """Get quota state for current project."""
        return self._states[self.current_project.name]

    def get_state(self, project_name: str) -> ProjectState:
        """Get quota state for a specific project."""
        return self._states.get(project_name, ProjectState(name=project_name))

    def record_quota(self, units: int) -> None:
        """Record quota usage for current project."""
        state = self.current_state
        state.quota_used += units
        logger.debug(
            "Project '{}': +{} units (total: {}/{})",
            state.name,
            units,
            state.quota_used,
            DAILY_QUOTA_LIMIT,
        )
        self._save_state()

    def mark_exhausted(self, error_msg: str | None = None) -> None:
        """Mark current project as quota-exhausted."""
        state = self.current_state
        state.is_exhausted = True
        state.last_error = error_msg
        logger.warning("Project '{}' quota exhausted", state.name)
        self._save_state()

    def handle_quota_exhausted(self, project_name: str | None = None) -> bool:
        """Handle quota exhaustion by switching to another project in same quota_group.

        ToS Compliance: Only switches within the same quota_group to avoid
        circumventing quota limits across unrelated projects (forbidden by
        Google's ToS Section III.D.1.c).

        Args:
            project_name: Name of exhausted project (defaults to current).

        Returns:
            True if switch succeeded (another project available in same group).
            False if all projects in the group are exhausted.
        """
        if project_name is None:
            project_name = self.current_project.name

        self.mark_exhausted()

        # Clear cached client/credentials
        self._client = None
        self._credentials = None

        # Get current project's quota_group
        current_project = self.config.get_project(project_name)
        quota_group = current_project.quota_group

        # Find candidates in same quota_group
        candidates = self._get_candidates(quota_group)
        available = [
            c
            for c in candidates
            if not self._states.get(c.name, ProjectState(name=c.name)).is_exhausted
        ]

        # Exclude current project
        available = [c for c in available if c.name != project_name]

        if not available:
            logger.error(
                "All projects in quota_group '{}' exhausted! "
                "Wait for quota reset at midnight PT, use a different quota_group, "
                "or request more quota: {}",
                quota_group,
                QUOTA_EXTENSION_URL,
            )
            return False

        # Select next available project (sorted by priority)
        next_project = available[0]
        self._current_index = self.project_names.index(next_project.name)
        logger.info(
            "Switched to project '{}' (same quota_group '{}')",
            next_project.name,
            quota_group,
        )
        self._save_state()
        return True

    def _get_candidates(self, quota_group: str) -> list[ProjectConfig]:
        """Get projects in a quota group, sorted by priority."""
        return self.config.get_projects_by_quota_group(quota_group)

    # Backwards compatibility alias
    def rotate_on_quota_exceeded(self) -> bool:
        """Deprecated: Use handle_quota_exhausted() instead."""
        logger.warning("rotate_on_quota_exceeded() is deprecated, use handle_quota_exhausted()")
        return self.handle_quota_exhausted()

    def handle_rate_limited(self, project_name: str | None = None) -> bool:
        """Handle rate limit (429) by potentially switching to another project.

        Unlike quota exhaustion, rate limits are temporary. This method:
        1. Records the rate limit hit for the project
        2. If threshold exceeded, marks project for cooldown and switches
        3. Otherwise, returns False (let retry handle it)

        Args:
            project_name: Name of rate-limited project (defaults to current).

        Returns:
            True if switched to another project (caller should get new client).
            False if staying on current project (let retry/backoff handle it).
        """
        if project_name is None:
            project_name = self.current_project.name

        state = self._states.get(project_name)
        if state is None:
            return False

        # Record the hit - returns True if threshold exceeded
        threshold_exceeded = state.record_rate_limit()

        if not threshold_exceeded:
            logger.debug(
                "Project '{}' rate limited ({}/{} hits)",
                project_name,
                state.rate_limit_hits,
                RATE_LIMIT_THRESHOLD,
            )
            return False

        logger.warning(
            "Project '{}' exceeded rate limit threshold, entering cooldown for {}s",
            project_name,
            RATE_LIMIT_COOLDOWN_SECONDS,
        )

        # Clear cached client to force new connection (new proxy IP)
        self._client = None
        self._credentials = None

        # Try to switch to another available project
        current_project = self.config.get_project(project_name)
        quota_group = current_project.quota_group
        candidates = self._get_candidates(quota_group)

        # Find available projects (not exhausted AND not in cooldown)
        available = [
            c
            for c in candidates
            if c.name != project_name
            and self._states.get(c.name, ProjectState(name=c.name)).is_available()
        ]

        if not available:
            logger.warning(
                "No other projects available in quota_group '{}', "
                "staying on '{}' (will retry with backoff)",
                quota_group,
                project_name,
            )
            return False

        # Switch to next available project
        next_project = available[0]
        self._current_index = self.project_names.index(next_project.name)
        logger.info(
            "Switched to project '{}' due to rate limits on '{}'",
            next_project.name,
            project_name,
        )
        return True

    def on_success(self) -> None:
        """Call after successful API operation to reset rate limit counters."""
        state = self.current_state
        if state.rate_limit_hits > 0:
            state.reset_rate_limits()
            logger.debug("Reset rate limit counters for project '{}'", state.name)

    def rotate_project(self) -> bool:
        """Rotate to next available project for load distribution.

        Use this for proactive round-robin distribution across projects.
        Cycles through projects in order, wrapping around at the end.

        Returns:
            True if rotated to a different project.
            False if no other projects available or only one project.
        """
        names = self.project_names
        if len(names) <= 1:
            return False

        current_name = self.current_project.name
        quota_group = self.current_project.quota_group

        # Get names of available projects in same quota group
        available_names = set()
        for c in self._get_candidates(quota_group):
            state = self._states.get(c.name, ProjectState(name=c.name))
            if c.name != current_name and state.is_available():
                available_names.add(c.name)

        if not available_names:
            return False

        # True round-robin: start from current position and find next available
        current_idx = names.index(current_name)
        for i in range(1, len(names)):
            next_idx = (current_idx + i) % len(names)
            next_name = names[next_idx]
            if next_name in available_names:
                self._current_index = next_idx
                self._client = None
                self._credentials = None
                logger.debug("Rotated to project '{}' (round-robin)", next_name)
                return True

        return False

    def invalidate_client(self) -> None:
        """Invalidate cached client to force recreation.

        Call this to get a new HTTP connection (and potentially new proxy IP).
        """
        self._client = None
        logger.debug("Invalidated client cache for project '{}'", self.current_project.name)

    def get_available_project_count(self) -> int:
        """Get count of available projects (not exhausted, not in cooldown)."""
        quota_group = self.current_project.quota_group
        candidates = self._get_candidates(quota_group)
        return sum(
            1
            for c in candidates
            if self._states.get(c.name, ProjectState(name=c.name)).is_available()
        )

    def select_project(self, name: str) -> None:
        """Manually select a project by name.

        Args:
            name: Project name to select.

        Raises:
            ValueError: If project not found.
        """
        names = self.project_names
        if name not in names:
            available = ", ".join(names)
            msg = f"Project '{name}' not found. Available: {available}"
            raise ValueError(msg)

        self._current_index = names.index(name)
        self._client = None
        self._credentials = None
        logger.info("Selected project '{}'", name)
        self._save_state()

    def select_context(
        self,
        quota_group: str | None = None,
        environment: str | None = None,
        force_project: str | None = None,
    ) -> ProjectConfig:
        """Select project by quota_group and/or environment.

        Args:
            quota_group: Restrict to projects in this quota group.
            environment: Restrict to projects with this environment.
            force_project: If provided, select this project regardless of filters.

        Returns:
            The selected ProjectConfig.

        Raises:
            ValueError: If no matching project found.
        """
        if force_project:
            self.select_project(force_project)
            return self.current_project

        candidates = list(self.config.projects) if self.config.projects else []

        # Filter by quota_group
        if quota_group:
            candidates = [p for p in candidates if p.quota_group == quota_group]

        # Filter by environment
        if environment:
            candidates = [p for p in candidates if p.environment == environment]

        # Filter out exhausted projects
        candidates = [
            p
            for p in candidates
            if not self._states.get(p.name, ProjectState(name=p.name)).is_exhausted
        ]

        if not candidates:
            filters = []
            if quota_group:
                filters.append(f"quota_group='{quota_group}'")
            if environment:
                filters.append(f"environment='{environment}'")
            filter_str = " and ".join(filters) if filters else "any"
            msg = f"No available projects matching {filter_str}"
            raise ValueError(msg)

        # Sort by priority and select first
        candidates.sort(key=lambda p: p.priority)
        selected = candidates[0]
        self.select_project(selected.name)
        return selected

    def get_credentials(self) -> Any:
        """Get OAuth credentials for current project.

        Caches credentials until project changes.
        """
        if self._credentials is not None:
            return self._credentials

        project = self.current_project
        token_path = get_token_path(project.name)

        from google.oauth2.credentials import Credentials as GoogleCredentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        SCOPES = ["https://www.googleapis.com/auth/youtube"]
        creds: GoogleCredentials | None = None

        if token_path.exists():
            with open(token_path) as f:
                token_data = json.load(f)
            creds = GoogleCredentials.from_authorized_user_info(token_data, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                from google.auth.transport.requests import Request

                creds.refresh(Request())
            else:
                client_config = {
                    "installed": {
                        "client_id": project.client_id,
                        "client_secret": project.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"],
                    }
                }
                flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
                creds = flow.run_local_server(port=0)

            # Save token
            if creds is not None:
                with open(token_path, "w") as f:
                    json.dump(json.loads(creds.to_json()), f)
                token_path.chmod(0o600)

        if creds is None:
            msg = f"Failed to obtain credentials for project '{project.name}'"
            raise RuntimeError(msg)

        self._credentials = creds
        return creds

    def get_client(self) -> Any:
        """Get YouTube API client for current project.

        Uses rotating proxy if configured via WEBSHARE_* environment variables.
        Caches client until project changes.
        """
        if self._client is not None:
            return self._client

        import google_auth_httplib2
        from googleapiclient.discovery import build

        creds = self.get_credentials()

        # Create proxied HTTP transport
        http = _create_proxied_http()
        authed_http = google_auth_httplib2.AuthorizedHttp(creds, http=http)

        self._client = build("youtube", "v3", http=authed_http)
        return self._client

    def status_summary(self) -> list[dict[str, str | int | bool]]:
        """Get status summary for all projects, grouped by quota_group."""
        self._check_quota_reset()
        result: list[dict[str, str | int | bool]] = []
        current_name = self.current_project.name

        for name in self.project_names:
            state = self._states.get(name, ProjectState(name=name))
            project = self.config.get_project(name)
            result.append(
                {
                    "name": name,
                    "current": name == current_name,
                    "quota_group": project.quota_group,
                    "environment": project.environment,
                    "priority": project.priority,
                    "quota_used": state.quota_used,
                    "quota_remaining": max(0, DAILY_QUOTA_LIMIT - state.quota_used),
                    "quota_limit": DAILY_QUOTA_LIMIT,
                    "is_exhausted": state.is_exhausted,
                }
            )

        # Sort by quota_group, then priority
        result.sort(key=lambda x: (str(x.get("quota_group", "")), int(x.get("priority", 0))))
        return result


# Global manager instance
_manager: ProjectManager | None = None


def get_project_manager(config: Config | None = None) -> ProjectManager:
    """Get or create the global project manager.

    Args:
        config: Configuration to use. If None and no manager exists,
               loads config from disk.

    Returns:
        Global ProjectManager instance.
    """
    global _manager
    if _manager is None:
        if config is None:
            from ytrix.config import load_config

            config = load_config()
        _manager = ProjectManager(config)
    return _manager


def reset_project_manager() -> None:
    """Reset the global project manager (for testing)."""
    global _manager
    _manager = None
