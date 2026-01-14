"""Tests for the info module (subtitle extraction and transcript conversion)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytrix import info


class TestFormatDuration:
    """Tests for format_duration function."""

    def test_formats_seconds_only(self) -> None:
        assert info.format_duration(45) == "0:45"

    def test_formats_minutes_seconds(self) -> None:
        assert info.format_duration(125) == "2:05"

    def test_formats_hours_minutes_seconds(self) -> None:
        assert info.format_duration(3725) == "1:02:05"

    def test_handles_zero(self) -> None:
        assert info.format_duration(0) == "0:00"

    def test_handles_negative(self) -> None:
        assert info.format_duration(-10) == "0:00"

    def test_formats_exact_hour(self) -> None:
        assert info.format_duration(3600) == "1:00:00"

    def test_formats_large_duration(self) -> None:
        # 10 hours, 30 minutes, 15 seconds
        assert info.format_duration(37815) == "10:30:15"


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

    def test_skips_header_metadata(self) -> None:
        """Skips metadata lines between WEBVTT and first cue."""
        vtt = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000
Hello.
"""
        result = info.vtt_to_transcript(vtt)
        assert "Kind:" not in result
        assert "Language:" not in result
        assert "Hello." in result


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

    def test_webvtt_extension(self) -> None:
        """Handles webvtt extension."""
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello."
        result = info.subtitle_to_transcript(vtt, "webvtt")
        assert "Hello." in result

    def test_unknown_extension_with_arrow(self) -> None:
        """Detects format from content when extension unknown."""
        srt = "1\n00:00:00,000 --> 00:00:02,000\nHello SRT."
        result = info.subtitle_to_transcript(srt, "txt")
        assert "Hello SRT." in result

    def test_unknown_extension_with_webvtt_header(self) -> None:
        """Detects VTT from WEBVTT header when extension unknown."""
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello VTT."
        result = info.subtitle_to_transcript(vtt, "txt")
        assert "Hello VTT." in result

    def test_unknown_format_returns_as_is(self) -> None:
        """Returns unknown format content unchanged."""
        content = "Plain text without timestamps"
        result = info.subtitle_to_transcript(content, "unknown")
        assert result == content

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
        assert d["duration_formatted"] == "2:00"
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
        assert d["total_duration"] == 60
        assert d["total_duration_formatted"] == "1:00"
        assert "001_Video 1" in d["videos"]

    def test_to_dict_multiple_videos_sums_duration(self) -> None:
        playlist = info.PlaylistInfo(
            id="PLxxx",
            title="Test Playlist",
            description="Desc",
            channel="Channel",
            videos=[
                info.VideoInfo(
                    id="v1", title="Video 1", description="", channel="Ch", duration=60, position=0
                ),
                info.VideoInfo(
                    id="v2", title="Video 2", description="", channel="Ch", duration=120, position=1
                ),
                info.VideoInfo(
                    id="v3",
                    title="Video 3",
                    description="",
                    channel="Ch",
                    duration=3600,
                    position=2,
                ),
            ],
        )
        d = playlist.to_dict()
        assert d["video_count"] == 3
        assert d["total_duration"] == 3780  # 60 + 120 + 3600
        assert d["total_duration_formatted"] == "1:03:00"

    def test_to_dict_empty_playlist(self) -> None:
        playlist = info.PlaylistInfo(
            id="PLxxx",
            title="Empty Playlist",
            description="",
            channel="Channel",
            videos=[],
        )
        d = playlist.to_dict()
        assert d["video_count"] == 0
        assert d["total_duration"] == 0
        assert d["total_duration_formatted"] == "0:00"


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

    def test_returns_none_for_no_video_id(self) -> None:
        sub = info.SubtitleInfo(lang="en", source="manual", ext="srt", url=None)
        assert info.download_subtitle(sub) is None
        assert info.download_subtitle(sub, video_id=None) is None

    @patch("ytrix.info.YoutubeDL")
    def test_downloads_content_via_ytdlp(self, mock_ydl_class: MagicMock) -> None:
        throttler = info.Throttler(delay_ms=0)
        original_throttler = info._subtitle_throttler
        info._subtitle_throttler = throttler

        # Capture the outtmpl to write subtitle file to the correct temp directory
        captured_opts: dict = {}

        def capture_opts(opts: dict) -> MagicMock:
            captured_opts.update(opts)
            mock_ydl = MagicMock()

            def mock_download(_urls: list[str]) -> None:
                # Write subtitle file to the temp directory specified in outtmpl
                tmpdir = Path(captured_opts["outtmpl"]).parent
                sub_file = tmpdir / "test123.en.srt"
                sub_file.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello", encoding="utf-8")

            mock_ydl.download.side_effect = mock_download
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=mock_ydl)
            mock_context.__exit__ = MagicMock(return_value=False)
            return mock_context

        mock_ydl_class.side_effect = capture_opts

        try:
            sub = info.SubtitleInfo(lang="en", source="manual", ext="srt")
            result = info.download_subtitle(sub, video_id="test123")

            assert result == "1\n00:00:00,000 --> 00:00:02,000\nHello"
        finally:
            info._subtitle_throttler = original_throttler

    @patch("ytrix.info.random.uniform", return_value=0)
    @patch("ytrix.info.time.sleep")
    @patch("ytrix.info.YoutubeDL")
    def test_retries_on_rate_limit_error(
        self,
        mock_ydl_class: MagicMock,
        mock_sleep: MagicMock,
        _mock_uniform: MagicMock,
    ) -> None:
        throttler = info.Throttler(delay_ms=0)
        original_throttler = info._subtitle_throttler
        info._subtitle_throttler = throttler

        mock_ydl = MagicMock()
        # Simulate rate limit error
        mock_ydl.download.side_effect = Exception("HTTP Error 429: Too Many Requests")

        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_ydl)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_ydl_class.return_value = mock_context

        try:
            sub = info.SubtitleInfo(lang="en", source="manual", ext="srt")
            result = info.download_subtitle(sub, video_id="test123", max_retries=2)

            assert result is None
            assert mock_ydl.download.call_count == 2
            assert mock_sleep.called  # Should have slept between retries
        finally:
            info._subtitle_throttler = original_throttler


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


class TestSetSubtitleThrottleDelay:
    """Tests for set_subtitle_throttle_delay function."""

    def test_sets_delay(self) -> None:
        original = info._subtitle_throttler._delay_ms
        info.set_subtitle_throttle_delay(2000)
        assert info._subtitle_throttler._delay_ms == 2000
        assert info._subtitle_throttler._base_delay_ms == 2000
        # Restore
        info.set_subtitle_throttle_delay(original)


class TestSubtitleToTranscriptFormats:
    """Tests for subtitle_to_transcript format detection."""

    def test_srt_format(self) -> None:
        """Uses SRT parser for .srt extension."""
        srt = "1\n00:00:01,000 --> 00:00:02,000\nHello\n"
        result = info.subtitle_to_transcript(srt, "srt")
        assert "Hello" in result

    def test_vtt_format(self) -> None:
        """Uses VTT parser for .vtt extension."""
        vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nWorld\n"
        result = info.subtitle_to_transcript(vtt, "vtt")
        assert "World" in result

    def test_webvtt_format(self) -> None:
        """Uses VTT parser for .webvtt extension."""
        vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nTest\n"
        result = info.subtitle_to_transcript(vtt, "webvtt")
        assert "Test" in result

    def test_unknown_format_with_vtt_header(self) -> None:
        """Detects VTT by header for unknown extensions."""
        vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nAuto VTT\n"
        result = info.subtitle_to_transcript(vtt, "txt")
        assert "Auto VTT" in result

    def test_unknown_format_with_timestamps(self) -> None:
        """Falls back to SRT parser for unknown format with timestamps."""
        srt = "1\n00:00:01,000 --> 00:00:02,000\nAuto SRT\n"
        result = info.subtitle_to_transcript(srt, "unknown")
        assert "Auto SRT" in result

    def test_unknown_format_returns_as_is(self) -> None:
        """Returns content unchanged for unknown format without timestamps."""
        content = "Just plain text without any timestamps"
        result = info.subtitle_to_transcript(content, "xyz")
        assert result == content


class TestVttToTranscriptHeader:
    """Tests for vtt_to_transcript header handling."""

    def test_skips_vtt_header_lines(self) -> None:
        """Skips metadata lines after WEBVTT header."""
        vtt = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:02.000
Hello
"""
        result = info.vtt_to_transcript(vtt)
        assert "Hello" in result
        assert "Kind" not in result
        assert "Language" not in result


class TestExtractVideoInfoRetry:
    """Tests for extract_video_info retry logic."""

    def test_retries_on_rate_limit(self) -> None:
        """Retries with backoff on rate limit errors."""
        call_count = 0

        def mock_extract(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("HTTP Error 429: Too Many Requests")
            return {
                "id": "test123",
                "title": "Test",
                "description": "Desc",
                "duration": 100,
                "channel": "Ch",
                "view_count": 1,
                "like_count": 0,
                "upload_date": "20240101",
                "subtitles": {},
                "automatic_captions": {},
            }

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info = mock_extract

        with (
            patch("ytrix.info.YoutubeDL", return_value=mock_ydl),
            patch("ytrix.info.time.sleep"),  # Skip actual sleep
        ):
            result = info.extract_video_info("test123", max_retries=3)

        assert call_count == 2
        assert result.id == "test123"

    def test_raises_after_max_retries(self) -> None:
        """Raises on non-rate-limit error without retry."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.side_effect = Exception("Video unavailable")

        with (
            patch("ytrix.info.YoutubeDL", return_value=mock_ydl),
            pytest.raises(Exception, match="Video unavailable"),
        ):
            info.extract_video_info("test123", max_retries=3)


class TestExtractPlaylistInfoRetry:
    """Tests for extract_playlist_info retry logic."""

    def test_retries_on_rate_limit(self) -> None:
        """Retries with backoff on rate limit errors."""
        call_count = 0

        def mock_extract(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("RATE_LIMIT_EXCEEDED")
            return {
                "id": "PLtest",
                "title": "Playlist",
                "description": "",
                "uploader": "Channel",
                "entries": [{"id": "v1", "title": "V1", "channel": "C", "duration": 60}],
            }

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info = mock_extract

        with (
            patch("ytrix.info.YoutubeDL", return_value=mock_ydl),
            patch("ytrix.info.time.sleep"),
        ):
            result = info.extract_playlist_info("PLtest", max_retries=3)

        assert call_count == 2
        assert result.id == "PLtest"

    def test_raises_when_no_data(self) -> None:
        """Raises RuntimeError when yt-dlp returns None."""
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = None

        with (
            patch("ytrix.info.YoutubeDL", return_value=mock_ydl),
            pytest.raises(RuntimeError, match="returned no info"),
        ):
            info.extract_playlist_info("PLtest", max_retries=1)


class TestYtdlpRateLimitConfig:
    """Tests for YtdlpRateLimitConfig class."""

    def test_default_values(self) -> None:
        """Default config has sensible values for rate limiting."""
        config = info.YtdlpRateLimitConfig()
        assert config.sleep_interval_requests == 5.0
        assert config.sleep_interval == 5.0
        assert config.max_sleep_interval == 10.0
        assert config.sleep_interval_subtitles == 10.0
        assert config.ratelimit is None

    def test_custom_values(self) -> None:
        """Can create config with custom values."""
        config = info.YtdlpRateLimitConfig(
            sleep_interval_requests=20.0,
            sleep_interval=10.0,
            max_sleep_interval=15.0,
            sleep_interval_subtitles=25.0,
            ratelimit=2_500_000,
        )
        assert config.sleep_interval_requests == 20.0
        assert config.sleep_interval == 10.0
        assert config.max_sleep_interval == 15.0
        assert config.sleep_interval_subtitles == 25.0
        assert config.ratelimit == 2_500_000

    def test_to_ytdlp_opts(self) -> None:
        """Converts to yt-dlp options dict."""
        config = info.YtdlpRateLimitConfig(
            sleep_interval_requests=5.0,
            sleep_interval=3.0,
            max_sleep_interval=6.0,
            sleep_interval_subtitles=8.0,
            ratelimit=1_000_000,
        )
        opts = config.to_ytdlp_opts()
        assert opts["sleep_interval_requests"] == 5.0
        assert opts["sleep_interval"] == 3.0
        assert opts["max_sleep_interval"] == 6.0
        assert opts["sleep_interval_subtitles"] == 8.0
        assert opts["ratelimit"] == 1_000_000

    def test_to_ytdlp_opts_excludes_zero_values(self) -> None:
        """Zero values are excluded from options."""
        config = info.YtdlpRateLimitConfig(
            sleep_interval_requests=0,
            sleep_interval=0,
            max_sleep_interval=0,
            sleep_interval_subtitles=0,
            ratelimit=None,
        )
        opts = config.to_ytdlp_opts()
        assert "sleep_interval_requests" not in opts
        assert "sleep_interval" not in opts
        assert "max_sleep_interval" not in opts
        assert "sleep_interval_subtitles" not in opts
        assert "ratelimit" not in opts


class TestConfigureYtdlpRateLimits:
    """Tests for configure_ytdlp_rate_limits function."""

    def test_configures_sleep_requests(self) -> None:
        """Can configure sleep_requests."""
        original = info._rate_limit_config.sleep_interval_requests
        info.configure_ytdlp_rate_limits(sleep_requests=15.0)
        assert info._rate_limit_config.sleep_interval_requests == 15.0
        # Restore
        info._rate_limit_config.sleep_interval_requests = original

    def test_configures_sleep_interval(self) -> None:
        """Can configure sleep_interval."""
        original = info._rate_limit_config.sleep_interval
        info.configure_ytdlp_rate_limits(sleep_interval=12.0)
        assert info._rate_limit_config.sleep_interval == 12.0
        info._rate_limit_config.sleep_interval = original

    def test_configures_max_sleep_interval(self) -> None:
        """Can configure max_sleep_interval."""
        original = info._rate_limit_config.max_sleep_interval
        info.configure_ytdlp_rate_limits(max_sleep_interval=20.0)
        assert info._rate_limit_config.max_sleep_interval == 20.0
        info._rate_limit_config.max_sleep_interval = original

    def test_configures_sleep_subtitles(self) -> None:
        """Can configure sleep_subtitles."""
        original = info._rate_limit_config.sleep_interval_subtitles
        info.configure_ytdlp_rate_limits(sleep_subtitles=18.0)
        assert info._rate_limit_config.sleep_interval_subtitles == 18.0
        info._rate_limit_config.sleep_interval_subtitles = original

    def test_configures_ratelimit(self) -> None:
        """Can configure ratelimit."""
        original = info._rate_limit_config.ratelimit
        info.configure_ytdlp_rate_limits(ratelimit=2_500_000)
        assert info._rate_limit_config.ratelimit == 2_500_000
        info._rate_limit_config.ratelimit = original


class TestGetYtdlpBaseOpts:
    """Tests for get_ytdlp_base_opts function."""

    def test_returns_quiet_by_default(self) -> None:
        """Returns quiet options by default."""
        opts = info.get_ytdlp_base_opts()
        assert opts["quiet"] is True
        assert opts["no_warnings"] is True

    def test_returns_skip_download_by_default(self) -> None:
        """Returns skip_download by default."""
        opts = info.get_ytdlp_base_opts()
        assert opts["skip_download"] is True

    def test_includes_extract_flat_when_requested(self) -> None:
        """Includes extract_flat when requested."""
        opts = info.get_ytdlp_base_opts(extract_flat=True)
        assert opts["extract_flat"] is True

    def test_excludes_extract_flat_by_default(self) -> None:
        """Does not include extract_flat by default."""
        opts = info.get_ytdlp_base_opts()
        assert "extract_flat" not in opts

    def test_includes_rate_limits_by_default(self) -> None:
        """Includes rate limiting options by default."""
        opts = info.get_ytdlp_base_opts()
        assert "sleep_interval_requests" in opts
        assert "sleep_interval" in opts
        assert "max_sleep_interval" in opts
        assert "sleep_interval_subtitles" in opts

    def test_excludes_rate_limits_when_disabled(self) -> None:
        """Can exclude rate limiting options."""
        opts = info.get_ytdlp_base_opts(include_rate_limits=False)
        assert "sleep_interval_requests" not in opts
        assert "sleep_interval" not in opts
        assert "max_sleep_interval" not in opts
        assert "sleep_interval_subtitles" not in opts

    def test_can_override_quiet(self) -> None:
        """Can override quiet setting."""
        opts = info.get_ytdlp_base_opts(quiet=False)
        assert opts["quiet"] is False
        assert opts["no_warnings"] is False

    def test_can_override_skip_download(self) -> None:
        """Can override skip_download setting."""
        opts = info.get_ytdlp_base_opts(skip_download=False)
        assert opts["skip_download"] is False
