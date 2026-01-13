"""Tests for ytrix.config."""

import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from ytrix.config import (
    Config,
    OAuthConfig,
    ProjectConfig,
    get_config_dir,
    get_token_path,
    get_tokens_dir,
    load_config,
)


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
        assert config.oauth is not None
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
        assert config.oauth is not None
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
            assert config.oauth is not None
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

    def test_config_without_oauth_or_projects_is_valid(self, tmp_path: Path) -> None:
        """Config with only channel_id is valid (projects accessed lazily)."""
        config_dir = tmp_path / ".ytrix"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text('channel_id = "UC123"')

        with patch("ytrix.config.Path.home", return_value=tmp_path):
            config = load_config()
            assert config.channel_id == "UC123"
            # But accessing projects raises
            with pytest.raises(ValueError, match="No projects or oauth"):
                config.get_project()

    def test_loads_multi_project_config(self, tmp_path: Path) -> None:
        """Loads config with multiple projects."""
        config_dir = tmp_path / ".ytrix"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text(
            """
channel_id = "UCtest123"

[[projects]]
name = "main"
client_id = "id1"
client_secret = "secret1"

[[projects]]
name = "backup"
client_id = "id2"
client_secret = "secret2"
"""
        )

        with patch("ytrix.config.Path.home", return_value=tmp_path):
            config = load_config()
            assert config.channel_id == "UCtest123"
            assert config.is_multi_project
            assert config.projects is not None
            assert len(config.projects) == 2
            assert config.get_project_names() == ["main", "backup"]
            assert config.get_project("main").client_id == "id1"
            assert config.get_project("backup").client_id == "id2"


class TestProjectConfig:
    """Tests for ProjectConfig model."""

    def test_valid_project_config(self) -> None:
        """ProjectConfig accepts valid data."""
        project = ProjectConfig(name="test", client_id="id", client_secret="secret")
        assert project.name == "test"
        assert project.client_id == "id"

    def test_name_with_dashes_and_underscores(self) -> None:
        """ProjectConfig allows dashes and underscores in name."""
        project = ProjectConfig(name="my-project_1", client_id="id", client_secret="s")
        assert project.name == "my-project_1"

    def test_invalid_name_raises(self) -> None:
        """ProjectConfig rejects names with special chars."""
        with pytest.raises(ValueError, match="alphanumeric"):
            ProjectConfig(name="my project!", client_id="id", client_secret="s")


class TestConfigGetProject:
    """Tests for Config.get_project method."""

    def test_get_first_project_when_name_is_none(self) -> None:
        """Returns first project when name not specified."""
        config = Config(
            channel_id="UC123",
            projects=[
                ProjectConfig(name="first", client_id="id1", client_secret="s1"),
                ProjectConfig(name="second", client_id="id2", client_secret="s2"),
            ],
        )
        project = config.get_project()
        assert project.name == "first"

    def test_get_project_by_name(self) -> None:
        """Returns specific project by name."""
        config = Config(
            channel_id="UC123",
            projects=[
                ProjectConfig(name="first", client_id="id1", client_secret="s1"),
                ProjectConfig(name="second", client_id="id2", client_secret="s2"),
            ],
        )
        project = config.get_project("second")
        assert project.name == "second"

    def test_get_project_from_legacy_oauth(self) -> None:
        """Converts legacy oauth to project named 'default'."""
        config = Config(
            channel_id="UC123",
            oauth=OAuthConfig(client_id="legacy-id", client_secret="legacy-secret"),
        )
        project = config.get_project()
        assert project.name == "default"
        assert project.client_id == "legacy-id"

    def test_get_project_not_found_raises(self) -> None:
        """Raises when project name not found."""
        config = Config(
            channel_id="UC123",
            projects=[ProjectConfig(name="only", client_id="id", client_secret="s")],
        )
        with pytest.raises(ValueError, match="not found"):
            config.get_project("missing")


class TestGetTokensDir:
    """Tests for get_tokens_dir function."""

    def test_returns_tokens_dir_in_config(self, tmp_path: Path) -> None:
        """Returns ~/.ytrix/tokens directory."""
        with patch("ytrix.config.Path.home", return_value=tmp_path):
            result = get_tokens_dir()
            assert result == tmp_path / ".ytrix" / "tokens"
            assert result.exists()


class TestGetTokenPathMultiProject:
    """Tests for get_token_path with project names."""

    def test_default_project_uses_legacy_path(self, tmp_path: Path) -> None:
        """Default/None project uses token.json directly."""
        with patch("ytrix.config.Path.home", return_value=tmp_path):
            result = get_token_path(None)
            assert result == tmp_path / ".ytrix" / "token.json"
            result = get_token_path("default")
            assert result == tmp_path / ".ytrix" / "token.json"

    def test_named_project_uses_tokens_subdir(self, tmp_path: Path) -> None:
        """Named project uses tokens/{name}.json."""
        with patch("ytrix.config.Path.home", return_value=tmp_path):
            result = get_token_path("my-project")
            assert result == tmp_path / ".ytrix" / "tokens" / "my-project.json"
