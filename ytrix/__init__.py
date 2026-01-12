"""ytrix - YouTube playlist management CLI."""

from ytrix.models import InvalidPlaylistError, Playlist, Video

try:
    from ytrix._version import __version__
except ImportError:
    __version__ = "0.0.0.dev0"

__all__ = ["InvalidPlaylistError", "Playlist", "Video", "__version__"]
