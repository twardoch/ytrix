"""Tests for ytrix.config."""

import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from ytrix.config import Config, OAuthConfig, get_config_dir, get_token_path, load_config


class TestOAuthConfig:
    """Tests for OAuthConfig model."""

    def test_valid_oauth_config(self) -> None:
        """OAuthConfig accepts valid credentials."""
        config = OAuthConfig(client_id="test-id", client_secret="test-secret")
        assert config.client_id == "test-id"
        assert config.client_secret == "test-secret"

    def test_missing_client_id_raises(self) -> None:
        """OAuthConfig requires client_id."""
        with pytest.raises(ValueError):
            OAuthConfig(client_secret="test-secret")  # type: ignore[call-arg]

    def test_missing_client_secret_raises(self) -> None:
        """OAuthConfig requires client_secret."""
        with pytest.raises(ValueError):
            OAuthConfig(client_id="test-id")  # type: ignore[call-arg]


class TestConfig:
    """Tests for Config model."""

    def test_valid_config(self) -> None:
        """Config accepts valid data."""
        config = Config(
            channel_id="UC123",
            oauth=OAuthConfig(client_id="id", client_secret="secret"),
        )
        assert config.channel_id == "UC123"
        assert config.oauth.client_id == "id"

    def test_missing_channel_id_raises(self) -> None:
        """Config requires channel_id."""
        with pytest.raises(ValueError):
            Config(oauth=OAuthConfig(client_id="id", client_secret="secret"))  # type: ignore[call-arg]

    def test_from_dict(self) -> None:
        """Config validates from dict (like TOML)."""
        data = {
            "channel_id": "UC456",
            "oauth": {"client_id": "my-id", "client_secret": "my-secret"},
        }
        config = Config.model_validate(data)
        assert config.channel_id == "UC456"
        assert config.oauth.client_id == "my-id"


class TestGetConfigDir:
    """Tests for get_config_dir function."""

    def test_returns_ytrix_dir_in_home(self, tmp_path: Path) -> None:
        """Returns ~/.ytrix directory."""
        with patch("ytrix.config.Path.home", return_value=tmp_path):
            result = get_config_dir()
            assert result == tmp_path / ".ytrix"

    def test_creates_directory_if_missing(self, tmp_path: Path) -> None:
        """Creates directory if it doesn't exist."""
        with patch("ytrix.config.Path.home", return_value=tmp_path):
            result = get_config_dir()
            assert result.exists()
            assert result.is_dir()


class TestGetTokenPath:
    """Tests for get_token_path function."""

    def test_returns_token_json_in_config_dir(self, tmp_path: Path) -> None:
        """Returns token.json path in config directory."""
        with patch("ytrix.config.Path.home", return_value=tmp_path):
            result = get_token_path()
            assert result == tmp_path / ".ytrix" / "token.json"


class TestLoadConfig:
    """Tests for load_config function."""

    def test_loads_valid_config(self, tmp_path: Path) -> None:
        """Loads config from TOML file."""
        config_dir = tmp_path / ".ytrix"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text(
            """
channel_id = "UCtest123"

[oauth]
client_id = "test-client-id"
client_secret = "test-client-secret"
"""
        )

        with patch("ytrix.config.Path.home", return_value=tmp_path):
            config = load_config()
            assert config.channel_id == "UCtest123"
            assert config.oauth.client_id == "test-client-id"
            assert config.oauth.client_secret == "test-client-secret"

    def test_raises_when_file_missing(self, tmp_path: Path) -> None:
        """Raises FileNotFoundError when config file missing."""
        config_dir = tmp_path / ".ytrix"
        config_dir.mkdir()

        with patch("ytrix.config.Path.home", return_value=tmp_path):
            with pytest.raises(FileNotFoundError) as exc_info:
                load_config()
            assert "config.toml" in str(exc_info.value)

    def test_raises_on_invalid_toml(self, tmp_path: Path) -> None:
        """Raises on malformed TOML."""
        config_dir = tmp_path / ".ytrix"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text("not valid [ toml")

        with (
            patch("ytrix.config.Path.home", return_value=tmp_path),
            pytest.raises(tomllib.TOMLDecodeError),
        ):
            load_config()

    def test_raises_on_missing_required_fields(self, tmp_path: Path) -> None:
        """Raises when required fields missing from TOML."""
        config_dir = tmp_path / ".ytrix"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text('channel_id = "UC123"')  # Missing oauth section

        with (
            patch("ytrix.config.Path.home", return_value=tmp_path),
            pytest.raises(ValueError),
        ):
            load_config()
