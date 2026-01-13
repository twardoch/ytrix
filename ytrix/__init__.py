"""ytrix - YouTube playlist management CLI."""

from ytrix.info import format_duration
from ytrix.models import InvalidPlaylistError, Playlist, Video

try:
    from ytrix._version import __version__
except ImportError:
    __version__ = "0.0.0.dev0"

__all__ = ["InvalidPlaylistError", "Playlist", "Video", "format_duration", "__version__"]
