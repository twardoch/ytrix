"""Multi-project credential management and rotation.

Manages multiple GCP projects for quota distribution. Automatically
rotates to the next project when quota is exhausted.

State is persisted to ~/.ytrix/quota_state.json for cross-session tracking.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ytrix.config import Config, ProjectConfig, get_config_dir, get_token_path
from ytrix.logging import logger
from ytrix.quota import DAILY_QUOTA_LIMIT

if TYPE_CHECKING:
    from typing import Any

# Pacific timezone for quota reset
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


@dataclass
class ProjectState:
    """Quota state for a single project."""

    name: str
    quota_used: int = 0
    last_reset_date: str = ""  # YYYY-MM-DD in Pacific Time
    is_exhausted: bool = False
    last_error: str | None = None

    def to_dict(self) -> dict[str, str | int | bool | None]:
        """Convert to dict for JSON serialization."""
        return {
            "name": self.name,
            "quota_used": self.quota_used,
            "last_reset_date": self.last_reset_date,
            "is_exhausted": self.is_exhausted,
            "last_error": self.last_error,
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
        )


@dataclass
class ProjectManager:
    """Manages multiple GCP projects with quota-aware rotation.

    Usage:
        config = load_config()
        manager = ProjectManager(config)

        # Get current project and client
        project = manager.current_project
        client = manager.get_client()

        # Record quota usage
        manager.record_quota(50)

        # Handle quota exceeded error
        if manager.rotate_on_quota_exceeded():
            client = manager.get_client()  # New client for next project
        else:
            # All projects exhausted
            raise QuotaExceededError(...)
    """

    config: Config
    _current_index: int = 0
    _states: dict[str, ProjectState] = field(default_factory=dict)
    _client: "Any" = field(default=None, repr=False)
    _credentials: "Any" = field(default=None, repr=False)

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

    def rotate_on_quota_exceeded(self) -> bool:
        """Attempt to rotate to next available project.

        Returns:
            True if rotation succeeded (new project available).
            False if all projects are exhausted.
        """
        self.mark_exhausted()

        # Clear cached client/credentials
        self._client = None
        self._credentials = None

        # Find next non-exhausted project
        names = self.project_names
        start_index = self._current_index
        for _ in range(len(names)):
            self._current_index = (self._current_index + 1) % len(names)
            if self._current_index == start_index:
                break  # Back to start, all exhausted
            state = self._states.get(names[self._current_index])
            if state and not state.is_exhausted:
                logger.info("Rotated to project '{}'", names[self._current_index])
                self._save_state()
                return True

        logger.error("All projects quota exhausted!")
        return False

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

    def get_credentials(self) -> "Any":
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

    def get_client(self) -> "Any":
        """Get YouTube API client for current project.

        Caches client until project changes.
        """
        if self._client is not None:
            return self._client

        from googleapiclient.discovery import build

        creds = self.get_credentials()
        self._client = build("youtube", "v3", credentials=creds)
        return self._client

    def status_summary(self) -> list[dict[str, str | int | bool]]:
        """Get status summary for all projects."""
        self._check_quota_reset()
        result = []
        current_name = self.current_project.name
        for name in self.project_names:
            state = self._states.get(name, ProjectState(name=name))
            result.append({
                "name": name,
                "current": name == current_name,
                "quota_used": state.quota_used,
                "quota_remaining": max(0, DAILY_QUOTA_LIMIT - state.quota_used),
                "quota_limit": DAILY_QUOTA_LIMIT,
                "is_exhausted": state.is_exhausted,
            })
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
