"""Logging configuration for ytrix."""

import sys

from loguru import logger

# Remove default handler
logger.remove()

# Format strings for different log levels
_info_format = "<level>{level: <7}</level> | {message}"
_debug_format = "<dim>{time:HH:mm:ss}</dim> | <level>{level: <7}</level> | {message}"


def configure_logging(verbose: bool = False) -> None:
    """Configure logging based on verbosity.

    Args:
        verbose: If True, show DEBUG level with timestamps. If False, show INFO and above.
    """
    logger.remove()
    if verbose:
        logger.add(
            sys.stderr,
            format=_debug_format,
            level="DEBUG",
        )
    else:
        # Default: INFO and above (shows file saves, progress, warnings, errors)
        logger.add(sys.stderr, format=_info_format, level="INFO")


# Export logger for use in other modules
__all__ = ["logger", "configure_logging"]
