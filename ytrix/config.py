"""Configuration loading for ytrix.

Supports both single-project (legacy) and multi-project configurations.

Legacy config.toml:
    channel_id = "UCxxx"
    [oauth]
    client_id = "..."
    client_secret = "..."

Multi-project config.toml:
    channel_id = "UCxxx"

    [[projects]]
    name = "main"
    client_id = "..."
    client_secret = "..."

    [[projects]]
    name = "backup"
    client_id = "..."
    client_secret = "..."
"""

import tomllib
from pathlib import Path

from pydantic import BaseModel, field_validator


class OAuthConfig(BaseModel):  # type: ignore[misc]
    """OAuth credentials (legacy single-project config)."""

    client_id: str
    client_secret: str


class ProjectConfig(BaseModel):  # type: ignore[misc]
    """Configuration for a single GCP project.

    Attributes:
        name: Unique project identifier (filesystem-safe).
        client_id: OAuth2 client ID from GCP.
        client_secret: OAuth2 client secret from GCP.
        quota_group: Purpose-based grouping (e.g., "personal", "client-a").
            Automatic context switching only occurs within the same group.
            This prevents ToS-violating quota circumvention across unrelated projects.
        environment: Deployment environment (dev/staging/prod).
        priority: Selection order within quota_group (lower = higher priority).
    """

    name: str
    client_id: str
    client_secret: str
    quota_group: str = "default"
    environment: str = "prod"
    priority: int = 0

    @field_validator("name")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure project name is filesystem-safe."""
        if not v or not v.replace("-", "").replace("_", "").isalnum():
            msg = "Project name must be alphanumeric with dashes/underscores"
            raise ValueError(msg)
        return v

    @field_validator("environment")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate environment is one of dev/staging/prod."""
        valid = {"dev", "staging", "prod"}
        if v not in valid:
            msg = f"Environment must be one of: {', '.join(sorted(valid))}"
            raise ValueError(msg)
        return v

    @field_validator("priority")  # type: ignore[untyped-decorator]
    @classmethod
    def validate_priority(cls, v: int) -> int:
        """Ensure priority is non-negative."""
        if v < 0:
            msg = "Priority must be non-negative"
            raise ValueError(msg)
        return v


class Config(BaseModel):  # type: ignore[misc]
    """ytrix configuration.

    Supports both legacy single-project and multi-project modes.
    If 'projects' list is provided, multi-project mode is enabled.
    Otherwise, 'oauth' section is used for legacy single-project mode.
    """

    channel_id: str
    oauth: OAuthConfig | None = None
    projects: list[ProjectConfig] | None = None

    def get_project(self, name: str | None = None) -> ProjectConfig:
        """Get a project configuration by name.

        Args:
            name: Project name. If None, returns first available project.

        Returns:
            ProjectConfig for the requested project.

        Raises:
            ValueError: If project not found or no projects configured.
        """
        if self.projects:
            if name is None:
                return self.projects[0]
            for project in self.projects:
                if project.name == name:
                    return project
            available = ", ".join(p.name for p in self.projects)
            msg = f"Project '{name}' not found. Available: {available}"
            raise ValueError(msg)

        # Legacy mode: convert oauth to project
        if self.oauth:
            return ProjectConfig(
                name="default",
                client_id=self.oauth.client_id,
                client_secret=self.oauth.client_secret,
            )

        msg = "No projects or oauth configured"
        raise ValueError(msg)

    def get_project_names(self) -> list[str]:
        """Get list of all project names."""
        if self.projects:
            return [p.name for p in self.projects]
        if self.oauth:
            return ["default"]
        return []

    @property
    def is_multi_project(self) -> bool:
        """Check if multi-project mode is enabled."""
        return bool(self.projects and len(self.projects) > 1)

    def get_projects_by_quota_group(self, quota_group: str) -> list[ProjectConfig]:
        """Get all projects in a quota group, sorted by priority.

        Args:
            quota_group: The quota group name to filter by.

        Returns:
            List of ProjectConfig objects in the group, sorted by priority.
        """
        if not self.projects:
            if self.oauth:
                # Legacy mode: return default project if group matches
                default = ProjectConfig(
                    name="default",
                    client_id=self.oauth.client_id,
                    client_secret=self.oauth.client_secret,
                )
                if quota_group == "default":
                    return [default]
            return []

        matching = [p for p in self.projects if p.quota_group == quota_group]
        return sorted(matching, key=lambda p: p.priority)

    def get_quota_groups(self) -> list[str]:
        """Get list of unique quota groups."""
        if not self.projects:
            return ["default"] if self.oauth else []
        return sorted(set(p.quota_group for p in self.projects))


def get_config_dir() -> Path:
    """Get or create config directory."""
    config_dir = Path.home() / ".ytrix"
    config_dir.mkdir(exist_ok=True)
    return config_dir


def get_tokens_dir() -> Path:
    """Get or create tokens directory for multi-project mode."""
    tokens_dir = get_config_dir() / "tokens"
    tokens_dir.mkdir(exist_ok=True)
    return tokens_dir


def get_token_path(project_name: str | None = None) -> Path:
    """Get path for OAuth token cache.

    Args:
        project_name: Project name for multi-project mode.
                     If None, uses legacy single token location.

    Returns:
        Path to token JSON file.
    """
    if project_name is None or project_name == "default":
        return get_config_dir() / "token.json"
    return get_tokens_dir() / f"{project_name}.json"


def load_config() -> Config:
    """Load configuration from ~/.ytrix/config.toml."""
    config_path = get_config_dir() / "config.toml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            "Create it with:\n"
            "  channel_id = 'UCxxxxxxxxxx'\n"
            "  [oauth]\n"
            "  client_id = 'your-client-id'\n"
            "  client_secret = 'your-client-secret'\n\n"
            "Or for multi-project mode:\n"
            "  channel_id = 'UCxxxxxxxxxx'\n"
            "  [[projects]]\n"
            "  name = 'main'\n"
            "  client_id = 'your-client-id'\n"
            "  client_secret = 'your-client-secret'"
        )
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    config: Config = Config.model_validate(data)
    return config
