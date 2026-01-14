"""Tests for dashboard.py.

this_file: tests/test_dashboard.py
"""

from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ytrix import dashboard


class TestGetTimeUntilReset:
    """Tests for get_time_until_reset()."""

    def test_returns_string_format(self):
        """Result is in 'Xh Ym' format."""
        result = dashboard.get_time_until_reset()
        assert "h" in result
        assert "m" in result

    def test_time_is_positive(self):
        """Time until reset is always positive (same day or next day)."""
        result = dashboard.get_time_until_reset()
        # Parse the result
        parts = result.replace("h", "").replace("m", "").split()
        hours = int(parts[0])
        minutes = int(parts[1])
        # Should be less than 24 hours
        assert 0 <= hours <= 23
        assert 0 <= minutes <= 59

    def test_returns_time_until_midnight_pt(self):
        """Verify calculation against expected midnight PT."""
        pacific = ZoneInfo("America/Los_Angeles")
        now = datetime.now(pacific)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        expected_delta = midnight - now
        expected_hours = int(expected_delta.total_seconds()) // 3600

        result = dashboard.get_time_until_reset()
        result_hours = int(result.split("h")[0])
        # Allow 1 minute tolerance for test execution time
        assert abs(result_hours - expected_hours) <= 1


class TestCreateQuotaDashboard:
    """Tests for create_quota_dashboard()."""

    def test_returns_panel(self):
        """Returns a Rich Panel."""
        result = dashboard.create_quota_dashboard(
            project_name="test",
            quota_group="personal",
            used=1000,
            limit=10000,
        )
        assert isinstance(result, Panel)

    def test_panel_contains_project_name(self):
        """Panel content includes project name."""
        result = dashboard.create_quota_dashboard(
            project_name="my-project",
            quota_group="work",
            used=500,
            limit=10000,
        )
        # Render to string to check content
        console = Console(file=StringIO(), force_terminal=True)
        console.print(result)
        output = console.file.getvalue()
        assert "my-project" in output

    def test_green_status_under_80_percent(self):
        """Status is green when usage < 80%."""
        result = dashboard.create_quota_dashboard(
            project_name="test",
            quota_group="personal",
            used=7000,  # 70%
            limit=10000,
        )
        console = Console(file=StringIO(), force_terminal=True)
        console.print(result)
        output = console.file.getvalue()
        assert "ACTIVE" in output

    def test_yellow_status_80_to_95_percent(self):
        """Status is yellow when 80% <= usage < 95%."""
        result = dashboard.create_quota_dashboard(
            project_name="test",
            quota_group="personal",
            used=8500,  # 85%
            limit=10000,
        )
        console = Console(file=StringIO(), force_terminal=True)
        console.print(result)
        output = console.file.getvalue()
        assert "WARNING" in output

    def test_red_status_at_95_percent(self):
        """Status is red when usage >= 95%."""
        result = dashboard.create_quota_dashboard(
            project_name="test",
            quota_group="personal",
            used=9600,  # 96%
            limit=10000,
        )
        console = Console(file=StringIO(), force_terminal=True)
        console.print(result)
        output = console.file.getvalue()
        assert "CRITICAL" in output

    def test_shows_remaining_capacity(self):
        """Shows remaining playlist creates and video operations."""
        result = dashboard.create_quota_dashboard(
            project_name="test",
            quota_group="personal",
            used=5000,
            limit=10000,
        )
        console = Console(file=StringIO(), force_terminal=True)
        console.print(result)
        output = console.file.getvalue()
        # 5000 remaining / 50 = 100 operations
        assert "100 playlist creates" in output
        assert "100 video operations" in output

    def test_quota_exhausted_message(self):
        """Shows exhausted message when remaining is 0 or negative."""
        result = dashboard.create_quota_dashboard(
            project_name="test",
            quota_group="personal",
            used=10000,
            limit=10000,
        )
        console = Console(file=StringIO(), force_terminal=True)
        console.print(result)
        output = console.file.getvalue()
        assert "exhausted" in output.lower()

    def test_handles_zero_limit(self):
        """Handles edge case of zero limit without division error."""
        # Should not raise ZeroDivisionError
        result = dashboard.create_quota_dashboard(
            project_name="test",
            quota_group="personal",
            used=0,
            limit=0,
        )
        assert isinstance(result, Panel)

    def test_shows_percentage(self):
        """Shows usage percentage in output."""
        result = dashboard.create_quota_dashboard(
            project_name="test",
            quota_group="personal",
            used=3000,
            limit=10000,
        )
        console = Console(file=StringIO(), force_terminal=True)
        console.print(result)
        output = console.file.getvalue()
        assert "30.0%" in output


class TestCreateOperationsTable:
    """Tests for create_operations_table()."""

    def test_returns_table(self):
        """Returns a Rich Table."""
        result = dashboard.create_operations_table({})
        assert isinstance(result, Table)

    def test_table_has_correct_columns(self):
        """Table has Operation, Count, Units, Note columns."""
        result = dashboard.create_operations_table({})
        column_names = [col.header for col in result.columns]
        assert "Operation" in column_names
        assert "Count" in column_names
        assert "Units" in column_names
        assert "Note" in column_names

    def test_adds_rows_for_operations(self):
        """Adds a row for each operation."""
        operations = {
            "Playlist Create": (5, 250),
            "Video Add": (50, 2500),
        }
        result = dashboard.create_operations_table(operations)
        assert result.row_count == 2

    def test_free_note_for_ytdlp_reads(self):
        """Shows FREE note for yt-dlp read operations."""
        operations = {
            "Read (yt-dlp)": (100, 0),
        }
        result = dashboard.create_operations_table(operations)
        console = Console(file=StringIO(), force_terminal=True)
        console.print(result)
        output = console.file.getvalue()
        assert "FREE" in output


class TestShowQuotaWarning:
    """Tests for show_quota_warning()."""

    def test_critical_warning_at_95_percent(self, capsys):
        """Shows critical panel at 95%+ usage."""
        with patch("ytrix.dashboard.Console") as mock_console_class:
            mock_console = mock_console_class.return_value
            dashboard.show_quota_warning(96.0, 400)
            # Should have called print with a Panel
            assert mock_console.print.called
            call_args = mock_console.print.call_args[0][0]
            assert isinstance(call_args, Panel)

    def test_warning_at_80_percent(self, capsys):
        """Shows yellow warning at 80-95% usage."""
        with patch("ytrix.dashboard.Console") as mock_console_class:
            mock_console = mock_console_class.return_value
            dashboard.show_quota_warning(85.0, 1500)
            assert mock_console.print.called

    def test_no_warning_under_80_percent(self, capsys):
        """No warning when under 80%."""
        with patch("ytrix.dashboard.Console") as mock_console_class:
            mock_console = mock_console_class.return_value
            dashboard.show_quota_warning(70.0, 3000)
            assert not mock_console.print.called


class TestShowRateLimitFeedback:
    """Tests for show_rate_limit_feedback()."""

    def test_shows_wait_time_and_attempt(self):
        """Shows wait time and attempt number."""
        with patch("ytrix.dashboard.Console") as mock_console_class:
            mock_console = mock_console_class.return_value
            dashboard.show_rate_limit_feedback(30.0, 2, 5)
            mock_console.print.assert_called_once()
            call_str = str(mock_console.print.call_args)
            assert "30" in call_str
            assert "2/5" in call_str


class TestShowSessionSummary:
    """Tests for show_session_summary()."""

    def test_shows_duration(self):
        """Shows session duration."""
        with patch("ytrix.dashboard.Console") as mock_console_class:
            mock_console = mock_console_class.return_value
            started = datetime.now() - timedelta(minutes=30)
            dashboard.show_session_summary(
                started=started,
                operations={"Create": 5},
                quota_consumed=250,
            )
            assert mock_console.print.called

    def test_shows_quota_consumed(self):
        """Shows quota consumed in summary."""
        with patch("ytrix.dashboard.Console") as mock_console_class:
            mock_console = mock_console_class.return_value
            started = datetime.now()
            dashboard.show_session_summary(
                started=started,
                operations={},
                quota_consumed=5000,
            )
            # Verify print was called with a table
            assert mock_console.print.called
            first_call = mock_console.print.call_args_list[0]
            assert isinstance(first_call[0][0], Table)

    def test_shows_errors_count(self):
        """Shows error count in summary."""
        with patch("ytrix.dashboard.Console") as mock_console_class:
            mock_console = mock_console_class.return_value
            started = datetime.now()
            dashboard.show_session_summary(
                started=started,
                operations={},
                quota_consumed=100,
                errors=["Error 1", "Error 2"],
            )
            # Should show errors list after table
            assert mock_console.print.call_count >= 2

    def test_truncates_long_error_list(self):
        """Shows only first 5 errors with count of remaining."""
        with patch("ytrix.dashboard.Console") as mock_console_class:
            mock_console = mock_console_class.return_value
            started = datetime.now()
            errors = [f"Error {i}" for i in range(10)]
            dashboard.show_session_summary(
                started=started,
                operations={},
                quota_consumed=100,
                errors=errors,
            )
            # Verify '... and X more' message is shown
            calls = [str(c) for c in mock_console.print.call_args_list]
            assert any("5 more" in c for c in calls)

    def test_handles_none_errors(self):
        """Handles None errors list gracefully."""
        with patch("ytrix.dashboard.Console") as mock_console_class:
            mock_console = mock_console_class.return_value
            started = datetime.now()
            # Should not raise
            dashboard.show_session_summary(
                started=started,
                operations={},
                quota_consumed=0,
                errors=None,
            )
            assert mock_console.print.called
