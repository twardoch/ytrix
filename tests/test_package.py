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
    # Remove ytrix modules from cache to force reimport
    modules_to_remove = [k for k in sys.modules if k.startswith("ytrix")]
    for mod in modules_to_remove:
        del sys.modules[mod]

    # Mock _version import to raise ImportError
    with patch.dict(sys.modules, {"ytrix._version": None}):
        # Force reimport by reloading
        import importlib

        import ytrix

        importlib.reload(ytrix)

        # Should fall back to dev version
        assert ytrix.__version__ == "0.0.0.dev0"

    # Restore normal state
    for mod in modules_to_remove:
        if mod in sys.modules:
            del sys.modules[mod]


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
