"""Tests for ytrix.projects module."""

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytrix.config import Config, OAuthConfig, ProjectConfig
from ytrix.projects import ProjectManager, ProjectState, get_project_manager, reset_project_manager


@pytest.fixture(autouse=True)
def reset_manager_between_tests() -> Generator[None, None, None]:
    """Reset the global project manager before and after each test."""
    reset_project_manager()
    yield
    reset_project_manager()


class TestProjectState:
    """Tests for ProjectState dataclass."""

    def test_to_dict(self) -> None:
        """Serializes to dict correctly."""
        state = ProjectState(
            name="test",
            quota_used=1000,
            last_reset_date="2025-01-13",
            is_exhausted=True,
            last_error="quota exceeded",
        )
        d = state.to_dict()
        assert d["name"] == "test"
        assert d["quota_used"] == 1000
        assert d["last_reset_date"] == "2025-01-13"
        assert d["is_exhausted"] is True
        assert d["last_error"] == "quota exceeded"

    def test_from_dict(self) -> None:
        """Deserializes from dict correctly."""
        d = {
            "name": "test",
            "quota_used": 500,
            "last_reset_date": "2025-01-12",
            "is_exhausted": False,
            "last_error": None,
        }
        state = ProjectState.from_dict(d)
        assert state.name == "test"
        assert state.quota_used == 500
        assert state.last_reset_date == "2025-01-12"
        assert state.is_exhausted is False
        assert state.last_error is None

    def test_from_dict_with_missing_fields(self) -> None:
        """Handles missing fields with defaults."""
        d = {"name": "minimal"}
        state = ProjectState.from_dict(d)
        assert state.name == "minimal"
        assert state.quota_used == 0
        assert state.is_exhausted is False


class TestProjectManager:
    """Tests for ProjectManager class."""

    @pytest.fixture
    def multi_project_config(self) -> Config:
        """Create a multi-project config."""
        return Config(
            channel_id="UC123",
            projects=[
                ProjectConfig(name="main", client_id="id1", client_secret="s1"),
                ProjectConfig(name="backup", client_id="id2", client_secret="s2"),
            ],
        )

    @pytest.fixture
    def legacy_config(self) -> Config:
        """Create a legacy single-project config."""
        return Config(
            channel_id="UC123",
            oauth=OAuthConfig(client_id="legacy-id", client_secret="legacy-s"),
        )

    def test_current_project_returns_first(
        self, multi_project_config: Config, tmp_path: Path
    ) -> None:
        """Returns first project by default."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            assert manager.current_project.name == "main"

    def test_project_names(self, multi_project_config: Config, tmp_path: Path) -> None:
        """Lists all project names."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            assert manager.project_names == ["main", "backup"]

    def test_select_project(self, multi_project_config: Config, tmp_path: Path) -> None:
        """Manually selects a project."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            manager.select_project("backup")
            assert manager.current_project.name == "backup"

    def test_select_invalid_project_raises(
        self, multi_project_config: Config, tmp_path: Path
    ) -> None:
        """Raises when selecting non-existent project."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            with pytest.raises(ValueError, match="not found"):
                manager.select_project("nonexistent")

    def test_record_quota(self, multi_project_config: Config, tmp_path: Path) -> None:
        """Records quota usage for current project."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            manager.record_quota(50)
            assert manager.current_state.quota_used == 50
            manager.record_quota(100)
            assert manager.current_state.quota_used == 150

    def test_mark_exhausted(self, multi_project_config: Config, tmp_path: Path) -> None:
        """Marks current project as quota-exhausted."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            manager.mark_exhausted("daily quota exceeded")
            assert manager.current_state.is_exhausted
            assert manager.current_state.last_error == "daily quota exceeded"

    def test_context_switch_on_quota_exceeded(
        self, multi_project_config: Config, tmp_path: Path
    ) -> None:
        """Switches to next project when quota exceeded."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            assert manager.current_project.name == "main"
            success = manager.handle_quota_exhausted()
            assert success is True
            assert manager.current_project.name == "backup"

    def test_context_switch_fails_when_all_exhausted(
        self, multi_project_config: Config, tmp_path: Path
    ) -> None:
        """Returns False when all projects exhausted."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            # Exhaust first
            manager.handle_quota_exhausted()
            # Now second is current, exhaust it too
            success = manager.handle_quota_exhausted()
            # Both exhausted, should fail
            assert success is False

    def test_state_persisted_to_disk(self, multi_project_config: Config, tmp_path: Path) -> None:
        """Quota state is saved to disk."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            manager.record_quota(1000)

            # Check file was created
            state_path = tmp_path / "quota_state.json"
            assert state_path.exists()

            # Verify content
            with open(state_path) as f:
                data = json.load(f)
            assert data["current_index"] == 0
            main_state = next(p for p in data["projects"] if p["name"] == "main")
            assert main_state["quota_used"] == 1000

    def test_state_restored_from_disk(self, multi_project_config: Config, tmp_path: Path) -> None:
        """Quota state is restored on init (same day, no reset)."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        # Use today's date so quota isn't reset
        today = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
        state_path = tmp_path / "quota_state.json"
        state_path.write_text(
            json.dumps(
                {
                    "current_index": 1,
                    "projects": [
                        {"name": "main", "quota_used": 5000, "last_reset_date": today},
                        {"name": "backup", "quota_used": 3000, "last_reset_date": today},
                    ],
                }
            )
        )

        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            assert manager._current_index == 1
            assert manager.current_project.name == "backup"
            assert manager.get_state("main").quota_used == 5000
            assert manager.get_state("backup").quota_used == 3000

    def test_quota_resets_on_new_day(self, multi_project_config: Config, tmp_path: Path) -> None:
        """Quota resets when date changes (midnight PT)."""
        state_path = tmp_path / "quota_state.json"
        state_path.write_text(
            json.dumps(
                {
                    "current_index": 0,
                    "projects": [
                        {"name": "main", "quota_used": 5000, "last_reset_date": "2020-01-01"},
                        {"name": "backup", "quota_used": 3000, "last_reset_date": "2020-01-01"},
                    ],
                }
            )
        )

        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            # Old date should trigger reset
            assert manager.get_state("main").quota_used == 0
            assert manager.get_state("backup").quota_used == 0

    def test_legacy_config_works(self, legacy_config: Config, tmp_path: Path) -> None:
        """Works with legacy single-project config."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(legacy_config)
            assert manager.project_names == ["default"]
            assert manager.current_project.name == "default"
            assert manager.current_project.client_id == "legacy-id"

    def test_status_summary(self, multi_project_config: Config, tmp_path: Path) -> None:
        """Returns status for all projects."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            manager.record_quota(2000)
            summary = manager.status_summary()
            assert len(summary) == 2
            main = next(s for s in summary if s["name"] == "main")
            assert main["current"] is True
            assert main["quota_used"] == 2000
            assert main["quota_remaining"] == 8000


class TestProjectManagerEdgeCases:
    """Tests for ProjectManager edge cases and error handling."""

    def test_corrupted_state_file_reinitializes(self, tmp_path: Path) -> None:
        """Corrupted state file is handled gracefully."""
        config = Config(
            channel_id="UC123",
            projects=[ProjectConfig(name="main", client_id="id1", client_secret="s1")],
        )
        state_path = tmp_path / "quota_state.json"
        state_path.write_text("not valid json {{{")

        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(config)
            # Should initialize fresh state despite corruption
            assert manager.project_names == ["main"]
            assert manager.get_state("main").quota_used == 0

    def test_state_file_with_missing_keys(self, tmp_path: Path) -> None:
        """State file missing required keys is handled."""
        config = Config(
            channel_id="UC123",
            projects=[ProjectConfig(name="main", client_id="id1", client_secret="s1")],
        )
        state_path = tmp_path / "quota_state.json"
        # Missing "projects" key
        state_path.write_text('{"current_index": 0}')

        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(config)
            # Should handle gracefully
            assert manager.project_names == ["main"]

    def test_new_project_added_to_config(self, tmp_path: Path) -> None:
        """New project in config gets added to state."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
        state_path = tmp_path / "quota_state.json"
        # Only "main" in state file
        state_path.write_text(
            json.dumps(
                {
                    "current_index": 0,
                    "projects": [
                        {"name": "main", "quota_used": 1000, "last_reset_date": today},
                    ],
                }
            )
        )

        # Config has both main and backup
        config = Config(
            channel_id="UC123",
            projects=[
                ProjectConfig(name="main", client_id="id1", client_secret="s1"),
                ProjectConfig(name="backup", client_id="id2", client_secret="s2"),
            ],
        )

        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(config)
            # Main should have restored quota
            assert manager.get_state("main").quota_used == 1000
            # Backup should be initialized fresh
            assert manager.get_state("backup").quota_used == 0
            assert "backup" in manager.project_names

    def test_current_index_bounds_check(self, tmp_path: Path) -> None:
        """Index out of bounds is reset to 0."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
        state_path = tmp_path / "quota_state.json"
        # Index 5 is out of bounds for 2 projects
        state_path.write_text(
            json.dumps(
                {
                    "current_index": 5,
                    "projects": [
                        {"name": "main", "quota_used": 0, "last_reset_date": today},
                        {"name": "backup", "quota_used": 0, "last_reset_date": today},
                    ],
                }
            )
        )

        config = Config(
            channel_id="UC123",
            projects=[
                ProjectConfig(name="main", client_id="id1", client_secret="s1"),
                ProjectConfig(name="backup", client_id="id2", client_secret="s2"),
            ],
        )

        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(config)
            # Should reset to valid index
            assert manager.current_project.name in ["main", "backup"]

    def test_no_projects_configured_raises(self, tmp_path: Path) -> None:
        """Raises ValueError when no projects configured."""
        # Config with no projects and no oauth
        config = Config(channel_id="UC123")

        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(config)
            with pytest.raises(ValueError, match="No projects configured"):
                _ = manager.current_project


class TestGetProjectManager:
    """Tests for get_project_manager function."""

    def test_returns_singleton(self, tmp_path: Path) -> None:
        """Returns same instance on repeated calls."""
        config = Config(
            channel_id="UC123",
            oauth=OAuthConfig(client_id="id", client_secret="s"),
        )
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            reset_project_manager()
            m1 = get_project_manager(config)
            m2 = get_project_manager()
            assert m1 is m2

    def test_reset_clears_singleton(self, tmp_path: Path) -> None:
        """Reset clears the cached manager."""
        config = Config(
            channel_id="UC123",
            oauth=OAuthConfig(client_id="id", client_secret="s"),
        )
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            reset_project_manager()
            m1 = get_project_manager(config)
            reset_project_manager()
            m2 = get_project_manager(config)
            assert m1 is not m2

    def test_loads_config_when_not_provided(self, tmp_path: Path) -> None:
        """Loads config from disk when not provided."""
        config = Config(
            channel_id="UC123",
            oauth=OAuthConfig(client_id="id", client_secret="s"),
        )
        with (
            patch("ytrix.projects.get_config_dir", return_value=tmp_path),
            patch("ytrix.config.load_config", return_value=config) as mock_load,
        ):
            reset_project_manager()
            manager = get_project_manager()
            mock_load.assert_called_once()
            assert manager.project_names == ["default"]


class TestGetCredentials:
    """Tests for ProjectManager.get_credentials method."""

    def test_returns_cached_credentials(self, tmp_path: Path) -> None:
        """Returns cached credentials on second call."""
        config = Config(
            channel_id="UC123",
            oauth=OAuthConfig(client_id="id", client_secret="s"),
        )
        mock_creds = MagicMock()
        mock_creds.valid = True

        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(config)
            manager._credentials = mock_creds
            result = manager.get_credentials()
            assert result is mock_creds

    def test_loads_credentials_from_token_file(self, tmp_path: Path) -> None:
        """Loads credentials from existing token file."""
        config = Config(
            channel_id="UC123",
            projects=[ProjectConfig(name="main", client_id="id1", client_secret="s1")],
        )
        token_path = tmp_path / "tokens" / "main.json"
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text('{"token": "test", "refresh_token": "rt"}')

        mock_creds = MagicMock()
        mock_creds.valid = True

        with (
            patch("ytrix.projects.get_config_dir", return_value=tmp_path),
            patch("ytrix.projects.get_token_path", return_value=token_path),
            patch(
                "google.oauth2.credentials.Credentials.from_authorized_user_info",
                return_value=mock_creds,
            ),
        ):
            manager = ProjectManager(config)
            result = manager.get_credentials()
            assert result is mock_creds

    def test_refreshes_expired_credentials(self, tmp_path: Path) -> None:
        """Refreshes credentials when expired."""
        config = Config(
            channel_id="UC123",
            projects=[ProjectConfig(name="main", client_id="id1", client_secret="s1")],
        )
        token_path = tmp_path / "tokens" / "main.json"
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text('{"token": "test", "refresh_token": "rt"}')

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "rt"
        mock_creds.to_json.return_value = '{"token": "new"}'

        mock_request = MagicMock()

        with (
            patch("ytrix.projects.get_config_dir", return_value=tmp_path),
            patch("ytrix.projects.get_token_path", return_value=token_path),
            patch(
                "google.oauth2.credentials.Credentials.from_authorized_user_info",
                return_value=mock_creds,
            ),
            patch("google.auth.transport.requests.Request", return_value=mock_request),
        ):
            manager = ProjectManager(config)
            result = manager.get_credentials()
            mock_creds.refresh.assert_called_once_with(mock_request)
            assert result is mock_creds

    def test_raises_on_failed_credentials(self, tmp_path: Path) -> None:
        """Raises RuntimeError when credentials cannot be obtained."""
        config = Config(
            channel_id="UC123",
            projects=[ProjectConfig(name="main", client_id="id1", client_secret="s1")],
        )
        token_path = tmp_path / "tokens" / "main.json"
        # No token file exists

        # Mock the OAuth flow to return None (simulating failure)
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = None

        with (
            patch("ytrix.projects.get_config_dir", return_value=tmp_path),
            patch("ytrix.projects.get_token_path", return_value=token_path),
            patch(
                "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config",
                return_value=mock_flow,
            ),
        ):
            manager = ProjectManager(config)
            with pytest.raises(RuntimeError, match="Failed to obtain credentials"):
                manager.get_credentials()


class TestGetClient:
    """Tests for ProjectManager.get_client method."""

    def test_returns_cached_client(self, tmp_path: Path) -> None:
        """Returns cached client on second call."""
        config = Config(
            channel_id="UC123",
            oauth=OAuthConfig(client_id="id", client_secret="s"),
        )
        mock_client = MagicMock()

        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(config)
            manager._client = mock_client
            result = manager.get_client()
            assert result is mock_client

    def test_builds_client_with_credentials(self, tmp_path: Path) -> None:
        """Builds YouTube client with credentials."""
        config = Config(
            channel_id="UC123",
            oauth=OAuthConfig(client_id="id", client_secret="s"),
        )
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_client = MagicMock()

        with (
            patch("ytrix.projects.get_config_dir", return_value=tmp_path),
            patch.object(ProjectManager, "get_credentials", return_value=mock_creds),
            patch("googleapiclient.discovery.build", return_value=mock_client) as mock_build,
        ):
            manager = ProjectManager(config)
            result = manager.get_client()
            mock_build.assert_called_once_with("youtube", "v3", credentials=mock_creds)
            assert result is mock_client


class TestQuotaGroupHandling:
    """Tests for quota_group-based context switching (ToS compliance)."""

    @pytest.fixture
    def multi_group_config(self) -> Config:
        """Create config with projects in multiple quota groups."""
        return Config(
            channel_id="UC123",
            projects=[
                ProjectConfig(
                    name="personal-1",
                    client_id="id1",
                    client_secret="s1",
                    quota_group="personal",
                    priority=0,
                ),
                ProjectConfig(
                    name="personal-2",
                    client_id="id2",
                    client_secret="s2",
                    quota_group="personal",
                    priority=1,
                ),
                ProjectConfig(
                    name="client-a",
                    client_id="id3",
                    client_secret="s3",
                    quota_group="client-a",
                    priority=0,
                ),
            ],
        )

    def test_handle_quota_exhausted_switches_within_same_group(
        self, multi_group_config: Config, tmp_path: Path
    ) -> None:
        """handle_quota_exhausted only switches within same quota_group."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_group_config)
            manager.select_project("personal-1")
            assert manager.current_project.name == "personal-1"

            success = manager.handle_quota_exhausted()
            assert success is True
            # Should switch to personal-2 (same group), NOT client-a
            assert manager.current_project.name == "personal-2"
            assert manager.current_project.quota_group == "personal"

    def test_handle_quota_exhausted_fails_when_all_in_group_exhausted(
        self, multi_group_config: Config, tmp_path: Path
    ) -> None:
        """Returns False when all projects in quota_group are exhausted."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_group_config)
            manager.select_project("personal-1")

            # Exhaust first
            manager.handle_quota_exhausted()
            # Now personal-2 is current
            assert manager.current_project.name == "personal-2"

            # Exhaust second in group
            success = manager.handle_quota_exhausted()
            # Should fail - all personal projects exhausted
            assert success is False

    def test_handle_quota_exhausted_does_not_cross_groups(
        self, multi_group_config: Config, tmp_path: Path
    ) -> None:
        """Does NOT failover to projects in different quota_group (ToS compliance)."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_group_config)
            manager.select_project("client-a")

            # client-a is alone in its group
            success = manager.handle_quota_exhausted()
            assert success is False
            # Should NOT switch to personal group projects

    def test_select_context_by_quota_group(
        self, multi_group_config: Config, tmp_path: Path
    ) -> None:
        """select_context filters by quota_group."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_group_config)

            project = manager.select_context(quota_group="client-a")
            assert project.name == "client-a"
            assert project.quota_group == "client-a"

    def test_select_context_respects_priority(
        self, multi_group_config: Config, tmp_path: Path
    ) -> None:
        """select_context selects by priority within group."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_group_config)

            # personal-1 has priority=0, personal-2 has priority=1
            project = manager.select_context(quota_group="personal")
            assert project.name == "personal-1"  # Lower priority = selected first

    def test_select_context_skips_exhausted(
        self, multi_group_config: Config, tmp_path: Path
    ) -> None:
        """select_context skips exhausted projects."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_group_config)

            # Exhaust personal-1
            manager.select_project("personal-1")
            manager.mark_exhausted()

            # Now select_context should skip personal-1
            project = manager.select_context(quota_group="personal")
            assert project.name == "personal-2"

    def test_select_context_force_project_overrides_filters(
        self, multi_group_config: Config, tmp_path: Path
    ) -> None:
        """force_project in select_context overrides all filters."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_group_config)

            # Force client-a even though we specify personal group
            project = manager.select_context(quota_group="personal", force_project="client-a")
            assert project.name == "client-a"

    def test_select_context_raises_when_no_match(
        self, multi_group_config: Config, tmp_path: Path
    ) -> None:
        """select_context raises when no projects match filters."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_group_config)

            with pytest.raises(ValueError, match="No available projects"):
                manager.select_context(quota_group="nonexistent")

    def test_status_summary_includes_quota_group(
        self, multi_group_config: Config, tmp_path: Path
    ) -> None:
        """status_summary includes quota_group, environment, priority."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_group_config)
            summary = manager.status_summary()

            # Check first project has new fields
            personal1 = next(s for s in summary if s["name"] == "personal-1")
            assert personal1["quota_group"] == "personal"
            assert personal1["priority"] == 0
            assert "environment" in personal1

    def test_backwards_compat_deprecated_rotate_method(
        self, multi_group_config: Config, tmp_path: Path
    ) -> None:
        """Deprecated rotate_on_quota_exceeded still works for backwards compat."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_group_config)
            manager.select_project("personal-1")

            # Old deprecated method should still work
            success = manager.rotate_on_quota_exceeded()
            assert success is True
            assert manager.current_project.name == "personal-2"
