"""Tests for logging configuration."""

import sys
from io import StringIO
from unittest.mock import patch

from ytrix.logging import configure_logging, logger


class TestConfigureLogging:
    """Tests for configure_logging function."""

    def test_verbose_false_filters_debug(self) -> None:
        """Non-verbose mode filters DEBUG messages."""
        configure_logging(verbose=False)

        stderr = StringIO()
        with patch.object(sys, "stderr", stderr):
            # Reconfigure to use our mock stderr
            configure_logging(verbose=False)
            logger.debug("debug message")
            logger.warning("warning message")

        output = stderr.getvalue()
        assert "debug message" not in output
        assert "warning message" in output

    def test_verbose_true_shows_debug(self) -> None:
        """Verbose mode shows DEBUG messages."""
        stderr = StringIO()
        with patch.object(sys, "stderr", stderr):
            configure_logging(verbose=True)
            logger.debug("debug message")

        output = stderr.getvalue()
        assert "debug message" in output

    def test_verbose_true_shows_timestamps(self) -> None:
        """Verbose mode includes timestamps in format."""
        stderr = StringIO()
        with patch.object(sys, "stderr", stderr):
            configure_logging(verbose=True)
            logger.info("test message")

        output = stderr.getvalue()
        # Timestamp format is HH:mm:ss, so expect colons
        assert ":" in output

    def test_logger_exported(self) -> None:
        """Logger is accessible from module."""
        from ytrix.logging import logger as imported_logger

        assert imported_logger is not None
        assert hasattr(imported_logger, "debug")
        assert hasattr(imported_logger, "info")
        assert hasattr(imported_logger, "warning")
        assert hasattr(imported_logger, "error")
