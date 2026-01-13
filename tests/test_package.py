"""Tests for ytrix package exports."""

import sys
from unittest.mock import patch


def test_version_exported() -> None:
    """Package exports __version__."""
    from ytrix import __version__

    assert __version__
    assert isinstance(__version__, str)


def test_version_fallback_on_import_error() -> None:
    """Falls back to dev version when _version module unavailable."""
    # Save original module references
    original_modules = {k: v for k, v in sys.modules.items() if k.startswith("ytrix")}

    # Remove ytrix modules from cache to force reimport
    for mod in list(original_modules.keys()):
        del sys.modules[mod]

    try:
        # Mock _version import to raise ImportError
        with patch.dict(sys.modules, {"ytrix._version": None}):
            # Force reimport by reloading
            import importlib

            import ytrix

            importlib.reload(ytrix)

            # Should fall back to dev version
            assert ytrix.__version__ == "0.0.0.dev0"
    finally:
        # Clean up any newly imported modules
        for mod in list(sys.modules.keys()):
            if mod.startswith("ytrix"):
                del sys.modules[mod]

        # Restore original modules to maintain consistent state
        sys.modules.update(original_modules)


def test_models_exported() -> None:
    """Package exports key models."""
    from ytrix import InvalidPlaylistError, Playlist, Video

    # Can instantiate
    video = Video(id="v1", title="Test", channel="Ch", position=0)
    playlist = Playlist(id="PL1", title="Test")

    assert video.id == "v1"
    assert playlist.id == "PL1"

    # Exception is raisable
    try:
        raise InvalidPlaylistError("test error")
    except InvalidPlaylistError as e:
        assert "test error" in str(e)


def test_format_duration_exported() -> None:
    """Package exports format_duration utility."""
    from ytrix import format_duration

    # Basic formatting
    assert format_duration(0) == "0:00"
    assert format_duration(65) == "1:05"
    assert format_duration(3661) == "1:01:01"
