"""Tests for ytrix.projects module."""

import json
from pathlib import Path
from typing import Generator
from unittest.mock import patch

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

    def test_select_project(
        self, multi_project_config: Config, tmp_path: Path
    ) -> None:
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

    def test_record_quota(
        self, multi_project_config: Config, tmp_path: Path
    ) -> None:
        """Records quota usage for current project."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            manager.record_quota(50)
            assert manager.current_state.quota_used == 50
            manager.record_quota(100)
            assert manager.current_state.quota_used == 150

    def test_mark_exhausted(
        self, multi_project_config: Config, tmp_path: Path
    ) -> None:
        """Marks current project as quota-exhausted."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            manager.mark_exhausted("daily quota exceeded")
            assert manager.current_state.is_exhausted
            assert manager.current_state.last_error == "daily quota exceeded"

    def test_rotate_on_quota_exceeded(
        self, multi_project_config: Config, tmp_path: Path
    ) -> None:
        """Rotates to next project when quota exceeded."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            assert manager.current_project.name == "main"
            success = manager.rotate_on_quota_exceeded()
            assert success is True
            assert manager.current_project.name == "backup"

    def test_rotate_fails_when_all_exhausted(
        self, multi_project_config: Config, tmp_path: Path
    ) -> None:
        """Returns False when all projects exhausted."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            # Exhaust first
            manager.rotate_on_quota_exceeded()
            # Now second is current, exhaust it too
            success = manager.rotate_on_quota_exceeded()
            # Both exhausted, should fail
            assert success is False

    def test_state_persisted_to_disk(
        self, multi_project_config: Config, tmp_path: Path
    ) -> None:
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

    def test_state_restored_from_disk(
        self, multi_project_config: Config, tmp_path: Path
    ) -> None:
        """Quota state is restored on init (same day, no reset)."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        # Use today's date so quota isn't reset
        today = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
        state_path = tmp_path / "quota_state.json"
        state_path.write_text(json.dumps({
            "current_index": 1,
            "projects": [
                {"name": "main", "quota_used": 5000, "last_reset_date": today},
                {"name": "backup", "quota_used": 3000, "last_reset_date": today},
            ],
        }))

        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            assert manager._current_index == 1
            assert manager.current_project.name == "backup"
            assert manager.get_state("main").quota_used == 5000
            assert manager.get_state("backup").quota_used == 3000

    def test_quota_resets_on_new_day(
        self, multi_project_config: Config, tmp_path: Path
    ) -> None:
        """Quota resets when date changes (midnight PT)."""
        state_path = tmp_path / "quota_state.json"
        state_path.write_text(json.dumps({
            "current_index": 0,
            "projects": [
                {"name": "main", "quota_used": 5000, "last_reset_date": "2020-01-01"},
                {"name": "backup", "quota_used": 3000, "last_reset_date": "2020-01-01"},
            ],
        }))

        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(multi_project_config)
            # Old date should trigger reset
            assert manager.get_state("main").quota_used == 0
            assert manager.get_state("backup").quota_used == 0

    def test_legacy_config_works(
        self, legacy_config: Config, tmp_path: Path
    ) -> None:
        """Works with legacy single-project config."""
        with patch("ytrix.projects.get_config_dir", return_value=tmp_path):
            manager = ProjectManager(legacy_config)
            assert manager.project_names == ["default"]
            assert manager.current_project.name == "default"
            assert manager.current_project.client_id == "legacy-id"

    def test_status_summary(
        self, multi_project_config: Config, tmp_path: Path
    ) -> None:
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
