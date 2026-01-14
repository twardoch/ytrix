"""Journal for tracking batch operations across sessions."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ytrix.config import get_config_dir
from ytrix.logging import logger


class TaskStatus(str, Enum):
    """Status of a batch task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"  # Skipped due to deduplication


@dataclass
class Task:
    """A single batch operation task."""

    source_playlist_id: str
    source_title: str
    target_playlist_id: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    error: str | None = None
    error_category: str | None = None  # ErrorCategory name from api.py
    retry_count: int = 0
    videos_added: int = 0
    last_updated: str = ""
    match_type: str | None = None  # "exact", "partial", "none"
    match_playlist_id: str | None = None  # ID of matching target playlist

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "source_playlist_id": self.source_playlist_id,
            "source_title": self.source_title,
            "target_playlist_id": self.target_playlist_id,
            "status": self.status.value,
            "error": self.error,
            "error_category": self.error_category,
            "retry_count": self.retry_count,
            "videos_added": self.videos_added,
            "last_updated": self.last_updated,
            "match_type": self.match_type,
            "match_playlist_id": self.match_playlist_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """Deserialize from dict."""
        return cls(
            source_playlist_id=data["source_playlist_id"],
            source_title=data["source_title"],
            target_playlist_id=data.get("target_playlist_id"),
            status=TaskStatus(data.get("status", "pending")),
            error=data.get("error"),
            error_category=data.get("error_category"),
            retry_count=data.get("retry_count", 0),
            videos_added=data.get("videos_added", 0),
            last_updated=data.get("last_updated", ""),
            match_type=data.get("match_type"),
            match_playlist_id=data.get("match_playlist_id"),
        )


@dataclass
class Journal:
    """Batch operation journal with persistence."""

    batch_id: str
    created_at: str
    tasks: list[Task] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "batch_id": self.batch_id,
            "created_at": self.created_at,
            "tasks": [t.to_dict() for t in self.tasks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Journal":
        """Deserialize from dict."""
        return cls(
            batch_id=data["batch_id"],
            created_at=data["created_at"],
            tasks=[Task.from_dict(t) for t in data.get("tasks", [])],
        )


def get_journal_path() -> Path:
    """Get path to journal file."""
    return get_config_dir() / "journal.json"


def load_journal() -> Journal | None:
    """Load journal from disk, returns None if not found."""
    path = get_journal_path()
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        journal = Journal.from_dict(data)
        logger.debug("Loaded journal with {} tasks", len(journal.tasks))
        return journal
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to load journal: {}", e)
        return None


def save_journal(journal: Journal) -> None:
    """Save journal to disk."""
    path = get_journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(journal.to_dict(), f, indent=2)
    path.chmod(0o600)  # Restrict permissions
    logger.debug("Saved journal to {}", path)


def clear_journal() -> None:
    """Delete journal file."""
    path = get_journal_path()
    if path.exists():
        path.unlink()
        logger.debug("Cleared journal")


def create_journal(source_playlists: list[tuple[str, str]]) -> Journal:
    """Create a new journal for batch operations.

    Args:
        source_playlists: List of (playlist_id, title) tuples
    """
    now = datetime.now().isoformat()
    batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    tasks = [
        Task(
            source_playlist_id=pid,
            source_title=title,
            last_updated=now,
        )
        for pid, title in source_playlists
    ]
    journal = Journal(batch_id=batch_id, created_at=now, tasks=tasks)
    save_journal(journal)
    return journal


def update_task(
    journal: Journal,
    source_playlist_id: str,
    status: TaskStatus | None = None,
    target_playlist_id: str | None = None,
    error: str | None = None,
    error_category: str | None = None,
    videos_added: int | None = None,
    match_type: str | None = None,
    match_playlist_id: str | None = None,
    increment_retry: bool = False,
) -> None:
    """Update a task in the journal and save."""
    for task in journal.tasks:
        if task.source_playlist_id == source_playlist_id:
            if status is not None:
                task.status = status
            if target_playlist_id is not None:
                task.target_playlist_id = target_playlist_id
            if error is not None:
                task.error = error
            if error_category is not None:
                task.error_category = error_category
            if videos_added is not None:
                task.videos_added = videos_added
            if match_type is not None:
                task.match_type = match_type
            if match_playlist_id is not None:
                task.match_playlist_id = match_playlist_id
            if increment_retry:
                task.retry_count += 1
            task.last_updated = datetime.now().isoformat()
            break
    save_journal(journal)


def get_pending_tasks(journal: Journal) -> list[Task]:
    """Get tasks that need processing (pending or failed with retries left)."""
    max_retries = 3
    return [
        t
        for t in journal.tasks
        if t.status == TaskStatus.PENDING
        or (t.status == TaskStatus.FAILED and t.retry_count < max_retries)
    ]


def get_journal_summary(journal: Journal) -> dict[str, int]:
    """Get summary counts by status."""
    summary: dict[str, int] = {
        "total": len(journal.tasks),
        "pending": 0,
        "in_progress": 0,
        "completed": 0,
        "failed": 0,
        "skipped": 0,
    }
    for task in journal.tasks:
        summary[task.status.value] += 1
    return summary
