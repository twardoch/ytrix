"""Tests for the info module (subtitle extraction and transcript conversion)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytrix import info


class TestSanitizeFilename:
    """Tests for _sanitize_filename function."""

    def test_removes_problematic_chars(self) -> None:
        assert info._sanitize_filename('Video: "Title" <test>') == "Video_ _Title_ _test_"

    def test_strips_dots_and_spaces(self) -> None:
        assert info._sanitize_filename("  ...Title...  ") == "Title"

    def test_truncates_long_names(self) -> None:
        long_name = "A" * 200
        result = info._sanitize_filename(long_name)
        assert len(result) <= 100

    def test_handles_empty_input(self) -> None:
        assert info._sanitize_filename("") == "untitled"
        assert info._sanitize_filename("...") == "untitled"

    def test_preserves_valid_chars(self) -> None:
        assert info._sanitize_filename("Valid-Title_123") == "Valid-Title_123"


class TestVideoFilename:
    """Tests for _video_filename function."""

    def test_formats_with_zero_padding(self) -> None:
        assert info._video_filename(0, "Test Video").startswith("001_")
        assert info._video_filename(9, "Test Video").startswith("010_")
        assert info._video_filename(99, "Test Video").startswith("100_")

    def test_sanitizes_title(self) -> None:
        result = info._video_filename(0, 'Title: "With" <Chars>')
        assert result == "001_Title_ _With_ _Chars_"


class TestSrtToTranscript:
    """Tests for srt_to_transcript function."""

    def test_removes_sequence_numbers_and_timestamps(self) -> None:
        srt = """1
00:00:00,000 --> 00:00:02,000
Hello world.

2
00:00:02,000 --> 00:00:04,000
This is a test.
"""
        result = info.srt_to_transcript(srt)
        assert "1\n" not in result
        assert "00:00:00" not in result
        assert "-->" not in result

    def test_extracts_text_content(self) -> None:
        srt = """1
00:00:00,000 --> 00:00:02,000
Hello world.

2
00:00:02,000 --> 00:00:04,000
This is a test.
"""
        result = info.srt_to_transcript(srt)
        assert "Hello world." in result
        assert "This is a test." in result

    def test_removes_html_tags(self) -> None:
        srt = """1
00:00:00,000 --> 00:00:02,000
<font color="#CCCCCC">Hello</font> world.
"""
        result = info.srt_to_transcript(srt)
        assert "<font" not in result
        assert "</font>" not in result
        assert "Hello" in result

    def test_joins_multiline_cues(self) -> None:
        srt = """1
00:00:00,000 --> 00:00:02,000
This is line one
and this is line two.
"""
        result = info.srt_to_transcript(srt)
        assert "This is line one and this is line two." in result


class TestVttToTranscript:
    """Tests for vtt_to_transcript function."""

    def test_skips_webvtt_header(self) -> None:
        vtt = """WEBVTT

00:00:00.000 --> 00:00:02.000
Hello world.
"""
        result = info.vtt_to_transcript(vtt)
        assert "WEBVTT" not in result
        assert "Hello world." in result

    def test_removes_cue_tags(self) -> None:
        vtt = """WEBVTT

00:00:00.000 --> 00:00:02.000
<c.colorE5E5E5>Hello</c> world.
"""
        result = info.vtt_to_transcript(vtt)
        assert "<c." not in result
        assert "</c>" not in result


class TestSubtitleToTranscript:
    """Tests for subtitle_to_transcript function."""

    def test_detects_srt_format(self) -> None:
        srt = "1\n00:00:00,000 --> 00:00:02,000\nHello."
        result = info.subtitle_to_transcript(srt, "srt")
        assert "Hello." in result

    def test_detects_vtt_format(self) -> None:
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello."
        result = info.subtitle_to_transcript(vtt, "vtt")
        assert "Hello." in result

    def test_auto_detects_format_from_content(self) -> None:
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello."
        result = info.subtitle_to_transcript(vtt, "unknown")
        assert "Hello." in result


class TestCreateVideoMarkdown:
    """Tests for create_video_markdown function."""

    def test_creates_yaml_frontmatter(self) -> None:
        video = info.VideoInfo(
            id="abc123",
            title="Test Video",
            description="A test video",
            channel="Test Channel",
            duration=125,  # 2:05
            upload_date="20240115",
        )
        result = info.create_video_markdown(video, "en", "Transcript content.")

        assert result.startswith("---\n")
        assert "---\n\n" in result
        assert "id: abc123" in result
        assert "title: Test Video" in result
        assert "channel: Test Channel" in result
        assert "language: en" in result
        assert "'2:05'" in result  # YAML quotes strings with colons
        assert "upload_date: '2024-01-15'" in result

    def test_formats_hours_duration(self) -> None:
        video = info.VideoInfo(
            id="abc123",
            title="Long Video",
            description="",
            channel="Test",
            duration=3725,  # 1:02:05
        )
        result = info.create_video_markdown(video, "en", "Content.")
        assert "'1:02:05'" in result  # YAML quotes strings with colons

    def test_truncates_long_description(self) -> None:
        long_desc = "A" * 600
        video = info.VideoInfo(
            id="abc123",
            title="Video",
            description=long_desc,
            channel="Test",
            duration=60,
        )
        result = info.create_video_markdown(video, "en", "Content.")
        assert "..." in result
        # Description should be truncated to ~500 chars plus "..."
        assert "AAAAAAA" in result

    def test_includes_transcript(self) -> None:
        video = info.VideoInfo(
            id="abc123",
            title="Video",
            description="",
            channel="Test",
            duration=60,
        )
        result = info.create_video_markdown(video, "en", "This is the transcript content.")
        assert "This is the transcript content." in result


class TestSubtitleInfo:
    """Tests for SubtitleInfo dataclass."""

    def test_creation(self) -> None:
        sub = info.SubtitleInfo(lang="en", source="manual", ext="srt", url="https://example.com")
        assert sub.lang == "en"
        assert sub.source == "manual"
        assert sub.ext == "srt"
        assert sub.url == "https://example.com"


class TestVideoInfo:
    """Tests for VideoInfo dataclass."""

    def test_to_dict(self) -> None:
        video = info.VideoInfo(
            id="abc123",
            title="Test",
            description="Desc",
            channel="Channel",
            duration=120,
            upload_date="20240101",
            view_count=1000,
            like_count=50,
            subtitles=[
                info.SubtitleInfo(lang="en", source="manual", ext="srt"),
            ],
        )
        d = video.to_dict()
        assert d["id"] == "abc123"
        assert d["title"] == "Test"
        assert d["duration"] == 120
        assert d["view_count"] == 1000
        assert len(d["subtitles"]) == 1


class TestPlaylistInfo:
    """Tests for PlaylistInfo dataclass."""

    def test_to_dict(self) -> None:
        playlist = info.PlaylistInfo(
            id="PLxxx",
            title="Test Playlist",
            description="Desc",
            channel="Channel",
            videos=[
                info.VideoInfo(
                    id="v1",
                    title="Video 1",
                    description="",
                    channel="Channel",
                    duration=60,
                    position=0,
                ),
            ],
        )
        d = playlist.to_dict()
        assert d["id"] == "PLxxx"
        assert d["title"] == "Test Playlist"
        assert d["video_count"] == 1
        assert "001_Video 1" in d["videos"]


class TestExtractVideoInfo:
    """Tests for extract_video_info function."""

    @patch("ytrix.info.YoutubeDL")
    def test_extracts_video_metadata(self, mock_ydl_class: MagicMock) -> None:
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            "title": "Test Video",
            "description": "Video description",
            "channel": "Test Channel",
            "duration": 180,
            "upload_date": "20240101",
            "view_count": 5000,
            "like_count": 200,
            "subtitles": {
                "en": [{"ext": "srt", "url": "https://example.com/en.srt"}],
            },
            "automatic_captions": {
                "de": [{"ext": "vtt", "url": "https://example.com/de.vtt"}],
            },
        }

        result = info.extract_video_info("abc123")

        assert result.title == "Test Video"
        assert result.channel == "Test Channel"
        assert result.duration == 180
        assert len(result.subtitles) == 2

        # Check manual subtitle
        en_sub = next(s for s in result.subtitles if s.lang == "en")
        assert en_sub.source == "manual"
        assert en_sub.ext == "srt"

        # Check auto subtitle
        de_sub = next(s for s in result.subtitles if s.lang == "de")
        assert de_sub.source == "automatic"

    @patch("ytrix.info.YoutubeDL")
    def test_handles_no_info(self, mock_ydl_class: MagicMock) -> None:
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = None

        with pytest.raises(RuntimeError, match="yt-dlp returned no info"):
            info.extract_video_info("abc123")


class TestExtractPlaylistInfo:
    """Tests for extract_playlist_info function."""

    @patch("ytrix.info.YoutubeDL")
    def test_extracts_playlist_metadata(self, mock_ydl_class: MagicMock) -> None:
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {
            "title": "Test Playlist",
            "description": "Playlist description",
            "channel": "Test Channel",
            "entries": [
                {"id": "v1", "title": "Video 1", "channel": "Ch1", "duration": 60},
                {"id": "v2", "title": "Video 2", "channel": "Ch2", "duration": 120},
                None,  # Deleted video
            ],
        }

        result = info.extract_playlist_info("PLxxx")

        assert result.title == "Test Playlist"
        assert result.channel == "Test Channel"
        assert len(result.videos) == 2  # Skips None entry
        assert result.videos[0].id == "v1"
        assert result.videos[1].id == "v2"


class TestDownloadSubtitle:
    """Tests for download_subtitle function."""

    def test_returns_none_for_no_url(self) -> None:
        sub = info.SubtitleInfo(lang="en", source="manual", ext="srt", url=None)
        assert info.download_subtitle(sub) is None

    @patch("ytrix.info.httpx.Client")
    def test_downloads_content(self, mock_client_class: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = "1\n00:00:00,000 --> 00:00:02,000\nHello"
        mock_client.get.return_value = mock_response

        sub = info.SubtitleInfo(lang="en", source="manual", ext="srt", url="https://example.com")
        result = info.download_subtitle(sub)

        assert result == "1\n00:00:00,000 --> 00:00:02,000\nHello"


class TestExtractAndSavePlaylistInfo:
    """Tests for extract_and_save_playlist_info function."""

    @patch("ytrix.info.download_subtitle")
    @patch("ytrix.info.extract_video_info")
    @patch("ytrix.info.extract_playlist_info")
    def test_creates_folder_structure(
        self,
        mock_extract_playlist: MagicMock,
        mock_extract_video: MagicMock,
        mock_download_sub: MagicMock,
        tmp_path: Path,
    ) -> None:
        # Mock playlist extraction
        mock_extract_playlist.return_value = info.PlaylistInfo(
            id="PLxxx",
            title="Test Playlist",
            description="Desc",
            channel="Channel",
            videos=[
                info.VideoInfo(
                    id="v1",
                    title="Video 1",
                    description="",
                    channel="Channel",
                    duration=60,
                    position=0,
                ),
            ],
        )

        # Mock video extraction
        mock_extract_video.return_value = info.VideoInfo(
            id="v1",
            title="Video 1",
            description="Full description",
            channel="Channel",
            duration=60,
            subtitles=[
                info.SubtitleInfo(lang="en", source="manual", ext="srt", url="https://example.com"),
            ],
        )

        # Mock subtitle download
        mock_download_sub.return_value = "1\n00:00:00,000 --> 00:00:02,000\nHello world."

        # Run the function
        info.extract_and_save_playlist_info("PLxxx", tmp_path)

        # Check folder was created
        playlist_folder = tmp_path / "Test Playlist"
        assert playlist_folder.exists()

        # Check files were created
        assert (playlist_folder / "playlist.yaml").exists()
        assert (playlist_folder / "001_Video 1.en.srt").exists()
        assert (playlist_folder / "001_Video 1.en.md").exists()

        # Check subtitle content
        srt_content = (playlist_folder / "001_Video 1.en.srt").read_text()
        assert "Hello world." in srt_content

        # Check markdown content
        md_content = (playlist_folder / "001_Video 1.en.md").read_text()
        assert "id: v1" in md_content
        assert "Hello world." in md_content


class TestThrottler:
    """Tests for Throttler class."""

    def test_initial_delay(self) -> None:
        throttler = info.Throttler(delay_ms=100)
        assert throttler.delay_ms == 100

    def test_on_success_resets_errors(self) -> None:
        throttler = info.Throttler(delay_ms=100)
        throttler._consecutive_errors = 5
        throttler.on_success()
        assert throttler._consecutive_errors == 0

    def test_on_success_reduces_delay_toward_base(self) -> None:
        throttler = info.Throttler(delay_ms=100)
        throttler._delay_ms = 1000
        throttler.on_success()
        assert throttler._delay_ms == 900  # 1000 * 0.9

    def test_on_success_does_not_go_below_base(self) -> None:
        throttler = info.Throttler(delay_ms=100)
        throttler._delay_ms = 100
        throttler.on_success()
        assert throttler._delay_ms == 100

    def test_on_error_increases_delay_modest(self) -> None:
        throttler = info.Throttler(delay_ms=100)
        throttler.on_error(is_rate_limit=False)
        assert throttler._delay_ms == 150  # 100 * 1.5
        assert throttler._consecutive_errors == 1

    def test_on_error_rate_limit_aggressive_backoff(self) -> None:
        throttler = info.Throttler(delay_ms=100)
        throttler.on_error(is_rate_limit=True)
        # 100 * 2 + 1000 = 1200
        assert throttler._delay_ms == 1200
        assert throttler._consecutive_errors == 1

    def test_on_error_caps_at_max(self) -> None:
        throttler = info.Throttler(delay_ms=100)
        throttler._delay_ms = 29000
        throttler.on_error(is_rate_limit=True)
        assert throttler._delay_ms == 30000  # Capped

    def test_get_retry_delay_exponential(self) -> None:
        throttler = info.Throttler(delay_ms=100)
        # Base delays: 2^0=1? No, 2^attempt, so 2, 4, 8, 16, 32, 60
        d0 = throttler.get_retry_delay(0)
        d1 = throttler.get_retry_delay(1)
        d2 = throttler.get_retry_delay(2)
        # Base is 2^attempt, min 60
        assert 1 <= d0 <= 2  # 2^0=1 + jitter (up to 0.5)
        assert 2 <= d1 <= 4  # 2^1=2 + jitter (up to 1)
        assert 4 <= d2 <= 8  # 2^2=4 + jitter (up to 2)

    def test_get_retry_delay_caps_at_60(self) -> None:
        throttler = info.Throttler(delay_ms=100)
        d10 = throttler.get_retry_delay(10)  # 2^10=1024 -> capped at 60
        assert 60 <= d10 <= 90  # 60 + up to 30 jitter


class TestIsRateLimitError:
    """Tests for _is_rate_limit_error helper."""

    def test_detects_429(self) -> None:
        exc = Exception("HTTP Error 429: Too Many Requests")
        assert info._is_rate_limit_error(exc) is True

    def test_detects_rate_limit_text(self) -> None:
        exc = Exception("RATE_LIMIT_EXCEEDED error")
        assert info._is_rate_limit_error(exc) is True

    def test_detects_too_many(self) -> None:
        exc = Exception("too many requests please slow down")
        assert info._is_rate_limit_error(exc) is True

    def test_ignores_other_errors(self) -> None:
        exc = Exception("Network connection failed")
        assert info._is_rate_limit_error(exc) is False


class TestSetYtdlpThrottleDelay:
    """Tests for set_ytdlp_throttle_delay function."""

    def test_sets_delay(self) -> None:
        original = info._ytdlp_throttler._delay_ms
        info.set_ytdlp_throttle_delay(1000)
        assert info._ytdlp_throttler._delay_ms == 1000
        assert info._ytdlp_throttler._base_delay_ms == 1000
        # Restore
        info.set_ytdlp_throttle_delay(original)
