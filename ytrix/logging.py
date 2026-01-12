"""Logging configuration for ytrix."""

import sys

from loguru import logger

# Remove default handler
logger.remove()

# Default: only warnings and above to stderr
_default_format = "<level>{level}</level> | {message}"


def configure_logging(verbose: bool = False) -> None:
    """Configure logging based on verbosity."""
    logger.remove()
    if verbose:
        logger.add(
            sys.stderr,
            format="<dim>{time:HH:mm:ss}</dim> | <level>{level: <8}</level> | {message}",
            level="DEBUG",
        )
    else:
        logger.add(sys.stderr, format=_default_format, level="WARNING")


# Export logger for use in other modules
__all__ = ["logger", "configure_logging"]
