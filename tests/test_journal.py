"""Tests for ytrix.journal module."""

from pathlib import Path
from unittest.mock import patch

import pytest

from ytrix.journal import (
    Journal,
    Task,
    TaskStatus,
    clear_journal,
    create_journal,
    get_journal_summary,
    get_pending_tasks,
    load_journal,
    save_journal,
    update_task,
)


@pytest.fixture
def temp_journal_dir(tmp_path: Path):
    """Use a temporary directory for journal during tests."""
    with patch("ytrix.journal.get_config_dir", return_value=tmp_path):
        yield tmp_path


class TestTaskStatus:
    """Tests for TaskStatus enum."""

    def test_values(self) -> None:
        """Enum has expected values."""
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.IN_PROGRESS.value == "in_progress"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.SKIPPED.value == "skipped"


class TestTask:
    """Tests for Task dataclass."""

    def test_default_values(self) -> None:
        """Has correct default values."""
        task = Task(source_playlist_id="PL1", source_title="Test")
        assert task.target_playlist_id is None
        assert task.status == TaskStatus.PENDING
        assert task.error is None
        assert task.retry_count == 0
        assert task.videos_added == 0

    def test_to_dict(self) -> None:
        """Serializes to dict correctly."""
        task = Task(
            source_playlist_id="PL1",
            source_title="Test Playlist",
            target_playlist_id="PL2",
            status=TaskStatus.COMPLETED,
            videos_added=5,
        )
        d = task.to_dict()
        assert d["source_playlist_id"] == "PL1"
        assert d["source_title"] == "Test Playlist"
        assert d["target_playlist_id"] == "PL2"
        assert d["status"] == "completed"
        assert d["videos_added"] == 5

    def test_from_dict(self) -> None:
        """Deserializes from dict correctly."""
        d = {
            "source_playlist_id": "PL1",
            "source_title": "Test",
            "target_playlist_id": "PL2",
            "status": "completed",
            "error": None,
            "retry_count": 2,
            "videos_added": 10,
            "last_updated": "2024-01-01T12:00:00",
            "match_type": "exact",
            "match_playlist_id": "PLexisting",
        }
        task = Task.from_dict(d)
        assert task.source_playlist_id == "PL1"
        assert task.status == TaskStatus.COMPLETED
        assert task.retry_count == 2
        assert task.match_type == "exact"


class TestJournal:
    """Tests for Journal dataclass."""

    def test_to_dict(self) -> None:
        """Serializes to dict correctly."""
        journal = Journal(
            batch_id="batch_123",
            created_at="2024-01-01T12:00:00",
            tasks=[Task(source_playlist_id="PL1", source_title="Test")],
        )
        d = journal.to_dict()
        assert d["batch_id"] == "batch_123"
        assert d["created_at"] == "2024-01-01T12:00:00"
        assert len(d["tasks"]) == 1
        assert d["tasks"][0]["source_playlist_id"] == "PL1"

    def test_from_dict(self) -> None:
        """Deserializes from dict correctly."""
        d = {
            "batch_id": "batch_456",
            "created_at": "2024-01-02T00:00:00",
            "tasks": [
                {"source_playlist_id": "PL1", "source_title": "Test 1"},
                {"source_playlist_id": "PL2", "source_title": "Test 2"},
            ],
        }
        journal = Journal.from_dict(d)
        assert journal.batch_id == "batch_456"
        assert len(journal.tasks) == 2


class TestJournalPersistence:
    """Tests for journal save/load functions."""

    def test_save_and_load(self, temp_journal_dir: Path) -> None:
        """Can save and load journal."""
        journal = Journal(
            batch_id="test_batch",
            created_at="2024-01-01",
            tasks=[Task(source_playlist_id="PL1", source_title="Test")],
        )
        save_journal(journal)

        loaded = load_journal()
        assert loaded is not None
        assert loaded.batch_id == "test_batch"
        assert len(loaded.tasks) == 1

    def test_load_returns_none_when_missing(self, temp_journal_dir: Path) -> None:
        """Returns None when journal file doesn't exist."""
        assert load_journal() is None

    def test_load_returns_none_on_invalid_json(self, temp_journal_dir: Path) -> None:
        """Returns None on corrupted journal file."""
        journal_path = temp_journal_dir / "journal.json"
        journal_path.write_text("not valid json")
        assert load_journal() is None

    def test_clear_journal(self, temp_journal_dir: Path) -> None:
        """Clears journal file."""
        journal = Journal(batch_id="test", created_at="2024", tasks=[])
        save_journal(journal)
        assert (temp_journal_dir / "journal.json").exists()

        clear_journal()
        assert not (temp_journal_dir / "journal.json").exists()

    def test_clear_journal_when_missing(self, temp_journal_dir: Path) -> None:
        """Clear doesn't fail when file missing."""
        clear_journal()  # Should not raise


class TestCreateJournal:
    """Tests for create_journal function."""

    def test_creates_journal_with_tasks(self, temp_journal_dir: Path) -> None:
        """Creates journal with tasks from source playlists."""
        sources = [("PL1", "Playlist 1"), ("PL2", "Playlist 2"), ("PL3", "Playlist 3")]
        journal = create_journal(sources)

        assert journal.batch_id.startswith("batch_")
        assert len(journal.tasks) == 3
        assert journal.tasks[0].source_playlist_id == "PL1"
        assert journal.tasks[0].source_title == "Playlist 1"
        assert journal.tasks[0].status == TaskStatus.PENDING


class TestUpdateTask:
    """Tests for update_task function."""

    def test_updates_status(self, temp_journal_dir: Path) -> None:
        """Updates task status."""
        journal = create_journal([("PL1", "Test")])
        update_task(journal, "PL1", status=TaskStatus.COMPLETED)

        assert journal.tasks[0].status == TaskStatus.COMPLETED

    def test_updates_target_playlist(self, temp_journal_dir: Path) -> None:
        """Updates target playlist ID."""
        journal = create_journal([("PL1", "Test")])
        update_task(journal, "PL1", target_playlist_id="PLnew")

        assert journal.tasks[0].target_playlist_id == "PLnew"

    def test_increments_retry(self, temp_journal_dir: Path) -> None:
        """Increments retry count."""
        journal = create_journal([("PL1", "Test")])
        update_task(journal, "PL1", increment_retry=True)
        update_task(journal, "PL1", increment_retry=True)

        assert journal.tasks[0].retry_count == 2

    def test_saves_after_update(self, temp_journal_dir: Path) -> None:
        """Saves journal after each update."""
        journal = create_journal([("PL1", "Test")])
        update_task(journal, "PL1", videos_added=5)

        # Load fresh from disk
        loaded = load_journal()
        assert loaded is not None
        assert loaded.tasks[0].videos_added == 5


class TestGetPendingTasks:
    """Tests for get_pending_tasks function."""

    def test_returns_pending_tasks(self, temp_journal_dir: Path) -> None:
        """Returns tasks with pending status."""
        journal = create_journal([("PL1", "T1"), ("PL2", "T2"), ("PL3", "T3")])
        update_task(journal, "PL2", status=TaskStatus.COMPLETED)

        pending = get_pending_tasks(journal)
        assert len(pending) == 2
        assert {t.source_playlist_id for t in pending} == {"PL1", "PL3"}

    def test_returns_failed_with_retries(self, temp_journal_dir: Path) -> None:
        """Returns failed tasks that can be retried."""
        journal = create_journal([("PL1", "T1")])
        update_task(journal, "PL1", status=TaskStatus.FAILED)

        pending = get_pending_tasks(journal)
        assert len(pending) == 1

    def test_excludes_failed_max_retries(self, temp_journal_dir: Path) -> None:
        """Excludes failed tasks that have maxed retries."""
        journal = create_journal([("PL1", "T1")])
        update_task(journal, "PL1", status=TaskStatus.FAILED)
        # Max retries is 3
        for _ in range(3):
            update_task(journal, "PL1", increment_retry=True)

        pending = get_pending_tasks(journal)
        assert len(pending) == 0


class TestGetJournalSummary:
    """Tests for get_journal_summary function."""

    def test_counts_by_status(self, temp_journal_dir: Path) -> None:
        """Returns correct counts by status."""
        journal = create_journal(
            [
                ("PL1", "T1"),
                ("PL2", "T2"),
                ("PL3", "T3"),
                ("PL4", "T4"),
            ]
        )
        update_task(journal, "PL1", status=TaskStatus.COMPLETED)
        update_task(journal, "PL2", status=TaskStatus.FAILED)
        update_task(journal, "PL3", status=TaskStatus.SKIPPED)

        summary = get_journal_summary(journal)

        assert summary["total"] == 4
        assert summary["pending"] == 1
        assert summary["completed"] == 1
        assert summary["failed"] == 1
        assert summary["skipped"] == 1
