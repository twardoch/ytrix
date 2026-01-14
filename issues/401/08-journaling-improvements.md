# Part 8: Journaling & Resume Improvements

## Current State

The existing journaling system (`journal.py`) tracks batch operations for resume capability. Improvements needed:

1. **Better state persistence** - Track more context for debugging
2. **Error categorization** - Store error types, not just messages
3. **Progress estimation** - Provide ETA based on history
4. **Cleanup automation** - Remove stale entries

## Enhanced Journal Schema

### 8.1 Task Entry Schema

```python
# journal.py

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"  # New: intentionally skipped (e.g., duplicate)


class ErrorCategory(Enum):
    NONE = "none"
    QUOTA_EXCEEDED = "quota_exceeded"
    RATE_LIMITED = "rate_limited"
    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    NETWORK_ERROR = "network_error"
    INVALID_INPUT = "invalid_input"
    UNKNOWN = "unknown"


@dataclass
class JournalTask:
    """Enhanced task entry with full context."""

    # Identification
    task_id: str
    batch_id: str  # Groups related tasks
    command: str   # e.g., "plists2mlists"

    # Source and target
    source_id: str
    source_type: str  # "playlist", "video", "channel"
    target_id: str | None = None

    # Status tracking
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Error tracking
    error_category: ErrorCategory = ErrorCategory.NONE
    error_message: str | None = None
    retry_count: int = 0
    max_retries: int = 3

    # Quota tracking
    quota_consumed: int = 0
    project_used: str | None = None

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class JournalBatch:
    """Batch operation metadata."""

    batch_id: str
    command: str
    input_file: str | None = None

    # Progress
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    skipped_tasks: int = 0

    # Timing
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_resumed_at: datetime | None = None

    # Quota summary
    total_quota_consumed: int = 0

    # State
    is_complete: bool = False
    is_paused: bool = False
    pause_reason: str | None = None
```

### 8.2 Journal Manager

```python
class JournalManager:
    """Enhanced journal management with batch support."""

    def __init__(self, journal_path: Path = None):
        self.journal_path = journal_path or get_config_dir() / "journal.json"
        self._load()

    def create_batch(self, command: str, input_file: str | None = None) -> str:
        """Create new batch and return batch_id."""
        batch_id = f"{command}-{int(time.time())}"
        batch = JournalBatch(
            batch_id=batch_id,
            command=command,
            input_file=input_file,
        )
        self.batches[batch_id] = batch
        self._save()
        return batch_id

    def add_task(
        self,
        batch_id: str,
        source_id: str,
        source_type: str = "playlist",
        **kwargs,
    ) -> JournalTask:
        """Add task to batch."""
        task_id = f"{batch_id}-{len(self.tasks)}"
        task = JournalTask(
            task_id=task_id,
            batch_id=batch_id,
            command=self.batches[batch_id].command,
            source_id=source_id,
            source_type=source_type,
            **kwargs,
        )
        self.tasks[task_id] = task
        self.batches[batch_id].total_tasks += 1
        self._save()
        return task

    def update_task(
        self,
        task_id: str,
        status: TaskStatus,
        error_category: ErrorCategory = ErrorCategory.NONE,
        error_message: str | None = None,
        quota_consumed: int = 0,
        target_id: str | None = None,
        **kwargs,
    ) -> None:
        """Update task status and metadata."""
        task = self.tasks[task_id]
        task.status = status
        task.updated_at = datetime.utcnow()
        task.error_category = error_category
        task.error_message = error_message
        task.quota_consumed += quota_consumed

        if target_id:
            task.target_id = target_id

        if status == TaskStatus.IN_PROGRESS and not task.started_at:
            task.started_at = datetime.utcnow()
        elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED):
            task.completed_at = datetime.utcnow()

        # Update batch counters
        batch = self.batches[task.batch_id]
        if status == TaskStatus.COMPLETED:
            batch.completed_tasks += 1
            batch.total_quota_consumed += quota_consumed
        elif status == TaskStatus.FAILED:
            batch.failed_tasks += 1
        elif status == TaskStatus.SKIPPED:
            batch.skipped_tasks += 1

        # Check if batch is complete
        completed = batch.completed_tasks + batch.failed_tasks + batch.skipped_tasks
        if completed >= batch.total_tasks:
            batch.is_complete = True
            batch.completed_at = datetime.utcnow()

        self._save()

    def get_resumable_tasks(self, batch_id: str) -> list[JournalTask]:
        """Get tasks that can be resumed."""
        return [
            task for task in self.tasks.values()
            if task.batch_id == batch_id
            and task.status in (TaskStatus.PENDING, TaskStatus.FAILED)
            and task.retry_count < task.max_retries
        ]

    def pause_batch(self, batch_id: str, reason: str) -> None:
        """Pause batch operation."""
        batch = self.batches[batch_id]
        batch.is_paused = True
        batch.pause_reason = reason
        self._save()

    def resume_batch(self, batch_id: str) -> None:
        """Mark batch as resumed."""
        batch = self.batches[batch_id]
        batch.is_paused = False
        batch.pause_reason = None
        batch.last_resumed_at = datetime.utcnow()
        self._save()

    def get_batch_summary(self, batch_id: str) -> dict:
        """Get summary statistics for batch."""
        batch = self.batches[batch_id]
        tasks = [t for t in self.tasks.values() if t.batch_id == batch_id]

        # Calculate timing
        durations = [
            (t.completed_at - t.started_at).total_seconds()
            for t in tasks
            if t.started_at and t.completed_at
        ]
        avg_duration = sum(durations) / len(durations) if durations else 0

        remaining = batch.total_tasks - batch.completed_tasks - batch.failed_tasks - batch.skipped_tasks
        eta_seconds = remaining * avg_duration

        return {
            "batch_id": batch_id,
            "command": batch.command,
            "total": batch.total_tasks,
            "completed": batch.completed_tasks,
            "failed": batch.failed_tasks,
            "skipped": batch.skipped_tasks,
            "remaining": remaining,
            "quota_consumed": batch.total_quota_consumed,
            "is_complete": batch.is_complete,
            "is_paused": batch.is_paused,
            "pause_reason": batch.pause_reason,
            "avg_task_duration": avg_duration,
            "eta_seconds": eta_seconds,
            "error_summary": self._get_error_summary(batch_id),
        }

    def _get_error_summary(self, batch_id: str) -> dict[str, int]:
        """Count errors by category."""
        errors: dict[str, int] = {}
        for task in self.tasks.values():
            if task.batch_id == batch_id and task.error_category != ErrorCategory.NONE:
                key = task.error_category.value
                errors[key] = errors.get(key, 0) + 1
        return errors

    def cleanup_completed(self, max_age_days: int = 7) -> int:
        """Remove completed batches older than max_age_days."""
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        removed = 0

        for batch_id in list(self.batches.keys()):
            batch = self.batches[batch_id]
            if batch.is_complete and batch.completed_at and batch.completed_at < cutoff:
                # Remove batch and its tasks
                del self.batches[batch_id]
                self.tasks = {
                    tid: t for tid, t in self.tasks.items()
                    if t.batch_id != batch_id
                }
                removed += 1

        if removed:
            self._save()
        return removed
```

### 8.3 Resume Command Enhancement

```python
# In cli.py

def plists2mlists(
    input_file: str,
    resume: bool = False,
    resume_batch: str | None = None,
    skip_failed: bool = False,
    **kwargs,
) -> int:
    """Batch copy playlists from file.

    Args:
        input_file: Path to file with playlist URLs (one per line)
        resume: Resume the most recent incomplete batch
        resume_batch: Resume a specific batch by ID
        skip_failed: Skip previously failed tasks instead of retrying
    """
    journal = JournalManager()

    if resume or resume_batch:
        # Find batch to resume
        if resume_batch:
            batch_id = resume_batch
        else:
            # Find most recent incomplete batch for this command
            candidates = [
                b for b in journal.batches.values()
                if b.command == "plists2mlists" and not b.is_complete
            ]
            if not candidates:
                console.print("[yellow]No incomplete batches to resume[/yellow]")
                return 1
            batch_id = max(candidates, key=lambda b: b.created_at).batch_id

        # Get resumable tasks
        tasks = journal.get_resumable_tasks(batch_id)
        if skip_failed:
            tasks = [t for t in tasks if t.status == TaskStatus.PENDING]

        if not tasks:
            console.print("[green]All tasks in batch are complete[/green]")
            return 0

        console.print(f"[bold]Resuming batch {batch_id}[/bold]")
        console.print(f"  {len(tasks)} tasks remaining")

        journal.resume_batch(batch_id)
        return _execute_batch(journal, batch_id, tasks, **kwargs)

    # Create new batch
    batch_id = journal.create_batch("plists2mlists", input_file)
    # ... rest of implementation
```

### 8.4 Journal Status Command

```bash
# New CLI command
ytrix journal_status [--batch BATCH_ID] [--verbose]

# Example output:
$ ytrix journal_status

Active Batches:
┌──────────────────────────┬─────────┬────────────┬──────────┬──────────────┐
│ Batch ID                 │ Command │ Progress   │ Status   │ Created      │
├──────────────────────────┼─────────┼────────────┼──────────┼──────────────┤
│ plists2mlists-1704672000 │ p2m     │ 45/100     │ PAUSED   │ 2h ago       │
│ plist2mlist-1704671000   │ p2m     │ COMPLETE   │ ✓        │ 3h ago       │
└──────────────────────────┴─────────┴────────────┴──────────┴──────────────┘

Paused batch reason: Quota exhausted (resets in 4h 12m)
Resume with: ytrix plists2mlists --resume
```

## Implementation Checklist

- [ ] Add `ErrorCategory` enum to journal.py
- [ ] Add `TaskStatus.SKIPPED` for dedup scenarios
- [ ] Create `JournalTask` dataclass with enhanced fields
- [ ] Create `JournalBatch` dataclass
- [ ] Implement `JournalManager` class
- [ ] Add `get_resumable_tasks()` method
- [ ] Add `pause_batch()` and `resume_batch()` methods
- [ ] Add `get_batch_summary()` with ETA calculation
- [ ] Add `cleanup_completed()` for stale entry removal
- [ ] Update `plists2mlists` with `--resume-batch` and `--skip-failed` flags
- [ ] Add `journal_status` CLI command
- [ ] Add `journal_cleanup` CLI command
- [ ] Migrate existing journal.json to new schema
- [ ] Test resume behavior across sessions
