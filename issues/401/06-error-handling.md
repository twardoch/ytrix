# Part 6: Enhanced Error Handling

## Error Type Distinction

The current implementation conflates different error types. We must handle them distinctly:

| HTTP Code | Error Type | Retryable? | Action |
|-----------|-----------|------------|--------|
| 429 | RATE_LIMIT_EXCEEDED | Yes | Backoff and retry |
| 403 (quotaExceeded) | Daily quota exceeded | **No** | Stop, report reset time |
| 403 (accessDenied) | Permission issue | No | Report, suggest fix |
| 5xx | Server error | Yes | Backoff and retry |
| 400 | Bad request | No | Report error details |

## Current Problem

```python
# Current behavior treats 403 quota as retryable - WRONG
_is_retryable_error() returns True for some 403 errors
```

## Improved Error Detection

```python
# api.py

from enum import Enum
from dataclasses import dataclass


class ErrorCategory(Enum):
    """Categories of YouTube API errors."""
    RATE_LIMITED = "rate_limited"        # 429 - retry with backoff
    QUOTA_EXCEEDED = "quota_exceeded"    # 403 quotaExceeded - stop, wait for reset
    PERMISSION_DENIED = "permission"     # 403 other - check credentials
    NOT_FOUND = "not_found"              # 404 - resource doesn't exist
    INVALID_REQUEST = "invalid"          # 400 - fix request
    SERVER_ERROR = "server"              # 5xx - retry with backoff
    NETWORK_ERROR = "network"            # Connection issues
    UNKNOWN = "unknown"


@dataclass
class APIError:
    """Structured API error with actionable guidance."""
    category: ErrorCategory
    message: str
    http_status: int | None
    retryable: bool
    user_action: str
    technical_details: str | None = None


def classify_error(exc: BaseException) -> APIError:
    """Classify an exception into actionable error category."""

    if isinstance(exc, HttpError):
        status = exc.resp.status
        content = _parse_error_content(exc)

        # 429 Rate Limit
        if status == 429:
            return APIError(
                category=ErrorCategory.RATE_LIMITED,
                message="API rate limit exceeded",
                http_status=429,
                retryable=True,
                user_action="Automatically retrying with backoff. If persistent, try --throttle 500",
            )

        # 403 - Multiple causes
        if status == 403:
            reason = content.get("reason", "")

            if reason == "quotaExceeded":
                reset_time = get_time_until_reset()
                return APIError(
                    category=ErrorCategory.QUOTA_EXCEEDED,
                    message=f"Daily quota exceeded. Resets in {reset_time} (midnight PT)",
                    http_status=403,
                    retryable=False,
                    user_action=(
                        "Options:\n"
                        "1. Wait for quota reset at midnight Pacific Time\n"
                        "2. Use --resume to continue tomorrow\n"
                        "3. Request quota increase: https://support.google.com/youtube/contact/yt_api_form"
                    ),
                )

            return APIError(
                category=ErrorCategory.PERMISSION_DENIED,
                message=f"Access denied: {content.get('message', 'Unknown')}",
                http_status=403,
                retryable=False,
                user_action="Check OAuth credentials. Run: ytrix projects_auth <project>",
                technical_details=str(content),
            )

        # 404 Not Found
        if status == 404:
            return APIError(
                category=ErrorCategory.NOT_FOUND,
                message="Resource not found",
                http_status=404,
                retryable=False,
                user_action="Verify the playlist/video ID is correct",
            )

        # 400 Bad Request
        if status == 400:
            return APIError(
                category=ErrorCategory.INVALID_REQUEST,
                message=f"Invalid request: {content.get('message', 'Unknown')}",
                http_status=400,
                retryable=False,
                user_action="Check input parameters",
                technical_details=str(content),
            )

        # 5xx Server Error
        if status >= 500:
            return APIError(
                category=ErrorCategory.SERVER_ERROR,
                message="YouTube API server error",
                http_status=status,
                retryable=True,
                user_action="Automatically retrying. If persistent, check YouTube status.",
            )

    # Network errors
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return APIError(
            category=ErrorCategory.NETWORK_ERROR,
            message="Network connection failed",
            http_status=None,
            retryable=True,
            user_action="Check internet connection",
        )

    # Unknown
    return APIError(
        category=ErrorCategory.UNKNOWN,
        message=str(exc),
        http_status=None,
        retryable=False,
        user_action="Check logs for details",
        technical_details=str(exc),
    )


def _parse_error_content(exc: HttpError) -> dict:
    """Parse error response content."""
    try:
        content = json.loads(exc.content.decode("utf-8"))
        errors = content.get("error", {}).get("errors", [])
        if errors:
            return errors[0]
        return content.get("error", {})
    except (json.JSONDecodeError, AttributeError):
        return {}
```

## Improved Retry Decorator

```python
def _should_retry(exc: BaseException) -> bool:
    """Determine if exception should be retried."""
    error = classify_error(exc)
    return error.retryable


api_retry = retry(
    retry=retry_if_exception(_should_retry),
    stop=stop_after_attempt(10),
    wait=wait_exponential_jitter(initial=2, max=300, jitter=5),
    before_sleep=_log_retry_attempt,
    reraise=True,
)


def _log_retry_attempt(retry_state):
    """Log retry attempts with user-friendly messages."""
    exc = retry_state.outcome.exception()
    error = classify_error(exc)
    attempt = retry_state.attempt_number
    wait = retry_state.next_action.sleep

    if error.category == ErrorCategory.RATE_LIMITED:
        console.print(f"[yellow]Rate limited. Retrying in {wait:.0f}s (attempt {attempt}/10)[/yellow]")
    elif error.category == ErrorCategory.SERVER_ERROR:
        console.print(f"[yellow]Server error. Retrying in {wait:.0f}s (attempt {attempt}/10)[/yellow]")
```

## User-Friendly Error Display

```python
def display_error(error: APIError) -> None:
    """Display error with Rich formatting."""
    from rich.panel import Panel

    if error.category == ErrorCategory.QUOTA_EXCEEDED:
        console.print(Panel(
            f"[red bold]{error.message}[/red bold]\n\n"
            f"{error.user_action}",
            title="Quota Exhausted",
            border_style="red",
        ))
    elif error.category == ErrorCategory.RATE_LIMITED:
        console.print(f"[yellow]{error.message}[/yellow]")
        console.print(f"[dim]{error.user_action}[/dim]")
    elif error.category == ErrorCategory.PERMISSION_DENIED:
        console.print(Panel(
            f"[red]{error.message}[/red]\n\n"
            f"{error.user_action}",
            title="Permission Denied",
            border_style="red",
        ))
    else:
        console.print(f"[red]Error: {error.message}[/red]")
        console.print(f"[dim]{error.user_action}[/dim]")
        if error.technical_details:
            logger.debug("Technical details: {}", error.technical_details)
```

## Graceful Degradation for Batch Operations

```python
class BatchOperationHandler:
    """Handle errors during batch operations with graceful recovery."""

    def __init__(self, journal: Journal):
        self.journal = journal
        self.consecutive_errors = 0
        self.max_consecutive_errors = 3

    def handle_error(self, task_id: str, error: APIError) -> BatchAction:
        """Determine action for batch operation error.

        Returns:
            BatchAction indicating how to proceed
        """
        if error.category == ErrorCategory.QUOTA_EXCEEDED:
            # Stop batch, save state for resume
            self._pause_batch(error)
            return BatchAction.STOP_ALL

        if error.category == ErrorCategory.RATE_LIMITED:
            # Already retried - this shouldn't happen often
            self.consecutive_errors += 1
            if self.consecutive_errors >= self.max_consecutive_errors:
                self._pause_batch(error)
                return BatchAction.STOP_ALL
            return BatchAction.SKIP_CURRENT

        if error.category in (ErrorCategory.NOT_FOUND, ErrorCategory.INVALID_REQUEST):
            # Skip this item, continue batch
            self.journal.update_task(task_id, TaskStatus.FAILED, error.message)
            return BatchAction.SKIP_CURRENT

        # Server/network errors after retries exhausted
        self.consecutive_errors += 1
        if self.consecutive_errors >= self.max_consecutive_errors:
            self._pause_batch(error)
            return BatchAction.STOP_ALL

        return BatchAction.SKIP_CURRENT

    def _pause_batch(self, error: APIError) -> None:
        """Pause batch and notify user."""
        console.print(Panel(
            f"[yellow]Batch operation paused[/yellow]\n\n"
            f"Reason: {error.message}\n\n"
            f"To resume: ytrix plists2mlists <file> --resume",
            title="Operation Paused",
            border_style="yellow",
        ))


class BatchAction(Enum):
    CONTINUE = "continue"
    SKIP_CURRENT = "skip"
    STOP_ALL = "stop"
```

## Implementation Checklist

- [ ] Add `ErrorCategory` enum
- [ ] Add `APIError` dataclass
- [ ] Implement `classify_error()` function
- [ ] Update `_is_retryable_error()` to use classify_error
- [ ] Add retry logging with `_log_retry_attempt()`
- [ ] Implement `display_error()` with Rich panels
- [ ] Add `BatchOperationHandler` for batch error recovery
- [ ] Update all commands to use new error handling
- [ ] Add error category to journal entries
- [ ] Test all error paths with mock responses
