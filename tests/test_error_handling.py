"""Tests for error handling and BatchOperationHandler.

Tests error classification, retry behavior, and batch operation handling.
"""

# this_file: tests/test_error_handling.py

from googleapiclient.errors import HttpError

from ytrix.api import (
    APIError,
    BatchAction,
    BatchOperationHandler,
    ErrorCategory,
    classify_error,
    display_error,
)

# Import fixtures from conftest
from .conftest import make_http_error


class TestClassifyError:
    """Tests for the classify_error function."""

    def test_classify_429_as_rate_limited(self, rate_limit_error: HttpError) -> None:
        """429 errors should be classified as RATE_LIMITED and retryable."""
        result = classify_error(rate_limit_error)

        assert result.category == ErrorCategory.RATE_LIMITED
        assert result.retryable is True
        assert result.status_code == 429
        assert "rate limit" in result.message.lower()

    def test_classify_403_quota_as_not_retryable(self, quota_exceeded_error: HttpError) -> None:
        """403 quotaExceeded errors should NOT be retryable."""
        result = classify_error(quota_exceeded_error)

        assert result.category == ErrorCategory.QUOTA_EXCEEDED
        assert result.retryable is False
        assert result.status_code == 403
        assert "quota" in result.message.lower()
        assert result.reason == "quotaExceeded"

    def test_classify_403_permission_denied(self) -> None:
        """403 non-quota errors should be PERMISSION_DENIED."""
        error = make_http_error(403, "forbidden")
        result = classify_error(error)

        assert result.category == ErrorCategory.PERMISSION_DENIED
        assert result.retryable is False
        assert result.status_code == 403

    def test_classify_404_as_not_found(self, not_found_error: HttpError) -> None:
        """404 errors should be classified as NOT_FOUND."""
        result = classify_error(not_found_error)

        assert result.category == ErrorCategory.NOT_FOUND
        assert result.retryable is False
        assert result.status_code == 404
        assert "not found" in result.message.lower()

    def test_classify_400_as_invalid_request(self, bad_request_error: HttpError) -> None:
        """400 errors should be classified as INVALID_REQUEST."""
        result = classify_error(bad_request_error)

        assert result.category == ErrorCategory.INVALID_REQUEST
        assert result.retryable is False
        assert result.status_code == 400

    def test_classify_5xx_as_server_error(self, server_error: HttpError) -> None:
        """5xx errors should be classified as SERVER_ERROR and retryable."""
        result = classify_error(server_error)

        assert result.category == ErrorCategory.SERVER_ERROR
        assert result.retryable is True
        assert result.status_code == 500

    def test_classify_502_as_server_error(self) -> None:
        """502 Bad Gateway should be SERVER_ERROR."""
        error = make_http_error(502, "badGateway")
        result = classify_error(error)

        assert result.category == ErrorCategory.SERVER_ERROR
        assert result.retryable is True
        assert result.status_code == 502

    def test_classify_connection_error(self) -> None:
        """Connection errors should be NETWORK_ERROR and retryable."""
        error = ConnectionError("Network is unreachable")
        result = classify_error(error)

        assert result.category == ErrorCategory.NETWORK_ERROR
        assert result.retryable is True
        assert "network" in result.message.lower()

    def test_classify_timeout_error(self) -> None:
        """Timeout errors should be NETWORK_ERROR and retryable."""
        error = TimeoutError("Connection timed out")
        result = classify_error(error)

        assert result.category == ErrorCategory.NETWORK_ERROR
        assert result.retryable is True

    def test_classify_unknown_error(self) -> None:
        """Unknown exceptions should be UNKNOWN and not retryable."""
        error = ValueError("Something unexpected")
        result = classify_error(error)

        assert result.category == ErrorCategory.UNKNOWN
        assert result.retryable is False


class TestAPIError:
    """Tests for APIError dataclass."""

    def test_api_error_str(self) -> None:
        """APIError should have a readable string representation."""
        error = APIError(
            category=ErrorCategory.QUOTA_EXCEEDED,
            message="Daily quota exceeded",
            retryable=False,
            user_action="Wait until midnight PT",
            status_code=403,
            reason="quotaExceeded",
        )

        assert "QUOTA_EXCEEDED" in str(error)
        assert "Daily quota exceeded" in str(error)


class TestBatchOperationHandler:
    """Tests for BatchOperationHandler class."""

    def test_handle_quota_error_stops_batch(self, quota_exceeded_error: HttpError) -> None:
        """Quota exceeded should stop the entire batch."""
        handler = BatchOperationHandler()

        action = handler.handle_error("task1", quota_exceeded_error)

        assert action == BatchAction.STOP_ALL
        assert handler.total_errors == 1
        assert handler.last_error is not None
        assert handler.last_error.category == ErrorCategory.QUOTA_EXCEEDED

    def test_handle_not_found_skips_current(self, not_found_error: HttpError) -> None:
        """NOT_FOUND errors should skip the current item and continue."""
        handler = BatchOperationHandler()

        action = handler.handle_error("task1", not_found_error)

        assert action == BatchAction.SKIP_CURRENT
        assert handler.total_errors == 1

    def test_handle_invalid_request_skips_current(self, bad_request_error: HttpError) -> None:
        """INVALID_REQUEST errors should skip the current item."""
        handler = BatchOperationHandler()

        action = handler.handle_error("task1", bad_request_error)

        assert action == BatchAction.SKIP_CURRENT

    def test_handle_permission_denied_skips_current(self) -> None:
        """PERMISSION_DENIED errors should skip the current item."""
        handler = BatchOperationHandler()
        error = make_http_error(403, "forbidden")

        action = handler.handle_error("task1", error)

        assert action == BatchAction.SKIP_CURRENT

    def test_consecutive_errors_stop_batch(self, server_error: HttpError) -> None:
        """Too many consecutive errors should stop the batch."""
        handler = BatchOperationHandler(max_consecutive_errors=3)

        # First two errors skip
        action1 = handler.handle_error("task1", server_error)
        action2 = handler.handle_error("task2", server_error)

        assert action1 == BatchAction.SKIP_CURRENT
        assert action2 == BatchAction.SKIP_CURRENT
        assert handler.consecutive_errors == 2

        # Third consecutive error stops
        action3 = handler.handle_error("task3", server_error)
        assert action3 == BatchAction.STOP_ALL
        assert handler.consecutive_errors == 3

    def test_success_resets_consecutive_counter(self, server_error: HttpError) -> None:
        """Successful operations reset the consecutive error counter."""
        handler = BatchOperationHandler(max_consecutive_errors=3)

        # Two errors
        handler.handle_error("task1", server_error)
        handler.handle_error("task2", server_error)
        assert handler.consecutive_errors == 2

        # Success resets counter
        handler.on_success()
        assert handler.consecutive_errors == 0

        # Can now have more errors before stopping
        action = handler.handle_error("task3", server_error)
        assert action == BatchAction.SKIP_CURRENT
        assert handler.consecutive_errors == 1

    def test_rate_limit_behavior(self, rate_limit_error: HttpError) -> None:
        """Rate limit errors should behave appropriately."""
        handler = BatchOperationHandler(max_consecutive_errors=3)

        # First rate limit skips
        action1 = handler.handle_error("task1", rate_limit_error)
        assert action1 == BatchAction.SKIP_CURRENT

        # Repeated rate limits eventually stop
        handler.handle_error("task2", rate_limit_error)
        action3 = handler.handle_error("task3", rate_limit_error)
        assert action3 == BatchAction.STOP_ALL

    def test_get_summary(self, server_error: HttpError) -> None:
        """Summary should correctly report error counts."""
        handler = BatchOperationHandler()

        assert handler.get_summary() == "No errors"

        handler.handle_error("task1", server_error)
        handler.handle_error("task2", server_error)
        handler.on_success()
        handler.handle_error("task3", server_error)

        summary = handler.get_summary()
        assert "3 error(s)" in summary
        assert "1 consecutive" in summary


class TestDisplayError:
    """Tests for display_error function."""

    def test_display_error_no_crash(self, quota_exceeded_error: HttpError) -> None:
        """display_error should not crash for any error type."""
        api_error = classify_error(quota_exceeded_error)
        # Should not raise
        display_error(api_error)
        display_error(api_error, show_action=False)

    def test_display_error_with_various_categories(self) -> None:
        """display_error should handle all error categories."""
        errors = [
            make_http_error(429, "rateLimitExceeded"),
            make_http_error(403, "quotaExceeded"),
            make_http_error(404, "notFound"),
            make_http_error(400, "badRequest"),
            make_http_error(500, "internalError"),
        ]

        for http_error in errors:
            api_error = classify_error(http_error)
            # Should not raise
            display_error(api_error)
