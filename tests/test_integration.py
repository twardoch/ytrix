"""Integration tests that call real external services.

These tests are marked with @pytest.mark.integration and require:
- yt-dlp installed and in PATH
- Network access to YouTube

Run with: pytest -m integration
Skip with: pytest -m "not integration"
"""

import shutil

import pytest

from ytrix.extractor import extract_playlist

# Skip all tests if yt-dlp is not installed
pytestmark = pytest.mark.skipif(shutil.which("yt-dlp") is None, reason="yt-dlp not installed")


@pytest.mark.integration
class TestYtdlpIntegration:
    """Integration tests using real yt-dlp calls."""

    # YouTube's "Top Tracks - United States" tends to be stable for testing
    # Using a small educational playlist that's unlikely to change dramatically
    TEST_PLAYLIST_ID = "PLFs4vir_WsTyXrrpFstD64Qj95vpy-yo1"  # Python.org short demo playlist

    def test_extract_playlist_returns_valid_data(self) -> None:
        """extract_playlist returns Playlist with videos from real YouTube."""
        playlist = extract_playlist(self.TEST_PLAYLIST_ID)

        # Basic structure checks
        assert playlist.id == self.TEST_PLAYLIST_ID
        assert playlist.title  # Has a title
        assert isinstance(playlist.videos, list)
        # This playlist should have at least 1 video
        assert len(playlist.videos) >= 1

    def test_extract_playlist_from_url(self) -> None:
        """extract_playlist works with full URL."""
        url = f"https://www.youtube.com/playlist?list={self.TEST_PLAYLIST_ID}"
        playlist = extract_playlist(url)

        assert playlist.id == self.TEST_PLAYLIST_ID
        assert len(playlist.videos) >= 1

    def test_videos_have_metadata(self) -> None:
        """Extracted videos have expected metadata fields."""
        playlist = extract_playlist(self.TEST_PLAYLIST_ID)

        # Check first video has expected fields
        if playlist.videos:
            video = playlist.videos[0]
            assert video.id  # Has video ID
            assert video.title  # Has title
            assert video.position == 0  # Position is set

    def test_invalid_playlist_raises_error(self) -> None:
        """Invalid playlist ID raises RuntimeError."""
        with pytest.raises(RuntimeError, match="Failed to extract"):
            extract_playlist("PLthis_does_not_exist_xyz123")
