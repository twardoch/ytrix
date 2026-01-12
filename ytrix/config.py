"""Configuration loading for ytrix."""

import tomllib
from pathlib import Path

from pydantic import BaseModel


class OAuthConfig(BaseModel):  # type: ignore[misc]
    """OAuth credentials."""

    client_id: str
    client_secret: str


class Config(BaseModel):  # type: ignore[misc]
    """ytrix configuration."""

    channel_id: str
    oauth: OAuthConfig


def get_config_dir() -> Path:
    """Get or create config directory."""
    config_dir = Path.home() / ".ytrix"
    config_dir.mkdir(exist_ok=True)
    return config_dir


def get_token_path() -> Path:
    """Get path for OAuth token cache."""
    return get_config_dir() / "token.json"


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
            "  client_secret = 'your-client-secret'"
        )
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    config: Config = Config.model_validate(data)
    return config
