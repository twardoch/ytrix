"""Smoke tests for ytrix CLI commands."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ytrix import __version__
from ytrix.__main__ import YtrixCLI
from ytrix.models import Playlist, Video


class TestCLICommands:
    """Smoke tests for CLI command existence."""

    def test_all_commands_exist(self) -> None:
        """All expected commands exist on CLI class."""
        expected = [
            "version",
            "config",
            "ls",
            "plist2mlist",
            "plists2mlist",
            "plists2mlists",
            "plist2mlists",
            "mlists2yaml",
            "yaml2mlists",
            "mlist2yaml",
            "yaml2mlist",
            "cache_stats",
            "cache_clear",
            "journal_status",
        ]
        for cmd in expected:
            assert hasattr(YtrixCLI, cmd), f"Missing command: {cmd}"
            assert callable(getattr(YtrixCLI, cmd)), f"Not callable: {cmd}"

    def test_all_commands_have_docstrings(self) -> None:
        """All commands have docstrings for help text."""
        commands = [
            "version",
            "config",
            "ls",
            "plist2mlist",
            "plists2mlist",
            "plists2mlists",
            "plist2mlists",
            "mlists2yaml",
            "yaml2mlists",
            "mlist2yaml",
            "yaml2mlist",
            "cache_stats",
            "cache_clear",
            "journal_status",
        ]
        for cmd in commands:
            method = getattr(YtrixCLI, cmd)
            assert method.__doc__, f"Missing docstring: {cmd}"
            assert len(method.__doc__) > 10, f"Docstring too short: {cmd}"

    def test_cli_class_has_docstring(self) -> None:
        """CLI class has docstring for Fire main help."""
        assert YtrixCLI.__doc__, "CLI class missing docstring"
        assert "YouTube" in YtrixCLI.__doc__, "Docstring should mention YouTube"
        assert "playlist" in YtrixCLI.__doc__.lower(), "Docstring should mention playlist"

    def test_main_function_exists(self) -> None:
        """Entry point main function exists and is callable."""
        from ytrix.__main__ import main

        assert callable(main), "main() should be callable"


@pytest.fixture
def mock_config():
    """Mock config loading."""
    config = MagicMock()
    config.channel_id = "UCtest123"
    config.oauth.client_id = "test-id"
    config.oauth.client_secret = "test-secret"
    return config


@pytest.fixture
def mock_client():
    """Mock YouTube API client."""
    return MagicMock()


@pytest.fixture
def cli():
    """Create CLI instance without verbose."""
    with patch("ytrix.__main__.configure_logging"), patch("ytrix.__main__.api.set_throttle_delay"):
        return YtrixCLI(verbose=False)


@pytest.fixture
def cli_json():
    """Create CLI instance with JSON output."""
    with patch("ytrix.__main__.configure_logging"), patch("ytrix.__main__.api.set_throttle_delay"):
        return YtrixCLI(verbose=False, json_output=True)


class TestThrottleFlag:
    """Tests for --throttle CLI flag."""

    def test_throttle_default_value(self) -> None:
        """Default throttle is 200ms."""
        from ytrix import api

        original = api.get_throttle_delay()
        try:
            with patch("ytrix.__main__.configure_logging"):
                YtrixCLI(verbose=False)
            # Should have set to default 200
            assert api.get_throttle_delay() == 200
        finally:
            api.set_throttle_delay(original)

    def test_throttle_custom_value(self) -> None:
        """Custom throttle value is applied."""
        from ytrix import api

        original = api.get_throttle_delay()
        try:
            with patch("ytrix.__main__.configure_logging"):
                YtrixCLI(verbose=False, throttle=500)
            assert api.get_throttle_delay() == 500
        finally:
            api.set_throttle_delay(original)

    def test_throttle_zero_disables(self) -> None:
        """Throttle of 0 disables throttling."""
        from ytrix import api

        original = api.get_throttle_delay()
        try:
            with patch("ytrix.__main__.configure_logging"):
                YtrixCLI(verbose=False, throttle=0)
            assert api.get_throttle_delay() == 0
        finally:
            api.set_throttle_delay(original)


class TestVersion:
    """Tests for version command."""

    def test_version_prints_version(self, cli: YtrixCLI, capsys) -> None:
        """Version command prints version string."""
        cli.version()
        captured = capsys.readouterr()
        assert __version__ in captured.out

    def test_version_json_output(self, cli_json: YtrixCLI, capsys) -> None:
        """Version with JSON output returns dict."""
        import json as json_mod

        cli_json.version()
        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["version"] == __version__


class TestConfig:
    """Tests for config command."""

    def test_config_shows_paths(self, cli: YtrixCLI, capsys, tmp_path: Path) -> None:
        """Config command shows config and token paths."""
        with patch("ytrix.__main__.get_config_dir", return_value=tmp_path):
            cli.config()
        captured = capsys.readouterr()
        assert "Config path:" in captured.out
        assert "Token path:" in captured.out

    def test_config_shows_not_found_when_missing(
        self, cli: YtrixCLI, capsys, tmp_path: Path
    ) -> None:
        """Config command shows not found when config missing."""
        with patch("ytrix.__main__.get_config_dir", return_value=tmp_path):
            cli.config()
        captured = capsys.readouterr()
        assert "Config file not found" in captured.out
        assert "Setup guide:" in captured.out

    def test_config_shows_content_when_exists(self, cli: YtrixCLI, capsys, tmp_path: Path) -> None:
        """Config command shows content when config exists."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("channel_id = 'UCtest'\n[oauth]\nclient_id = 'id'\n")
        with patch("ytrix.__main__.get_config_dir", return_value=tmp_path):
            cli.config()
        captured = capsys.readouterr()
        assert "Config file exists" in captured.out
        assert "channel_id" in captured.out

    def test_config_masks_secrets(self, cli: YtrixCLI, capsys, tmp_path: Path) -> None:
        """Config command masks client_secret."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            "channel_id = 'UCtest'\n[oauth]\nclient_id = 'id'\nclient_secret = 'mysecret'\n"
        )
        with patch("ytrix.__main__.get_config_dir", return_value=tmp_path):
            cli.config()
        captured = capsys.readouterr()
        assert "mysecret" not in captured.out
        assert "<hidden>" in captured.out

    def test_config_json_output(self, cli_json: YtrixCLI, capsys, tmp_path: Path) -> None:
        """Config with JSON output returns dict."""
        import json as json_mod

        with patch("ytrix.__main__.get_config_dir", return_value=tmp_path):
            cli_json.config()
        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert "config_path" in parsed
        assert "config_exists" in parsed
        assert parsed["config_exists"] is False


class TestList:
    """Tests for list command."""

    def test_list_playlists(
        self, cli: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, capsys
    ) -> None:
        """List command shows playlists."""
        playlists = [
            Playlist(id="PL1", title="Playlist 1"),
            Playlist(id="PL2", title="Playlist 2", privacy="unlisted"),
        ]

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.api.list_my_playlists", return_value=playlists),
        ):
            cli.ls()

        captured = capsys.readouterr()
        assert "Playlist 1" in captured.out
        assert "Playlist 2" in captured.out
        assert "[unlisted]" in captured.out

    def test_list_json_output(
        self, cli_json: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, capsys
    ) -> None:
        """List with JSON output returns dict."""
        import json as json_mod

        playlists = [
            Playlist(id="PL1", title="Playlist 1"),
        ]

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.api.list_my_playlists", return_value=playlists),
        ):
            cli_json.ls()

        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["count"] == 1
        assert parsed["playlists"][0]["id"] == "PL1"

    def test_list_empty_shows_message(
        self, cli: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, capsys
    ) -> None:
        """List command shows message when no playlists."""
        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.api.list_my_playlists", return_value=[]),
        ):
            cli.ls()

        captured = capsys.readouterr()
        assert "No playlists found" in captured.out

    def test_list_empty_json_output(
        self, cli_json: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, capsys
    ) -> None:
        """List with JSON output returns empty list when no playlists."""
        import json as json_mod

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.api.list_my_playlists", return_value=[]),
        ):
            cli_json.ls()

        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["count"] == 0
        assert parsed["playlists"] == []

    def test_list_with_count(
        self, cli: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, capsys
    ) -> None:
        """List with --count shows video counts."""
        playlists = [Playlist(id="PL1", title="Playlist 1")]
        videos = [Video(id="v1", title="V1", channel="Ch", position=0)]

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.api.list_my_playlists", return_value=playlists),
            patch("ytrix.__main__.api.get_playlist_videos", return_value=videos),
        ):
            cli.ls(count=True)

        captured = capsys.readouterr()
        assert "1 videos" in captured.out

    def test_list_with_count_json(
        self, cli_json: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, capsys
    ) -> None:
        """List with --count and JSON includes video_count."""
        import json as json_mod

        playlists = [Playlist(id="PL1", title="Playlist 1")]
        videos = [
            Video(id="v1", title="V1", channel="Ch", position=0),
            Video(id="v2", title="V2", channel="Ch", position=1),
        ]

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.api.list_my_playlists", return_value=playlists),
            patch("ytrix.__main__.api.get_playlist_videos", return_value=videos),
        ):
            cli_json.ls(count=True)

        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["playlists"][0]["video_count"] == 2

    def test_list_user_playlists(self, cli: YtrixCLI, capsys) -> None:
        """List playlists from another user via yt-dlp."""
        playlists = [
            Playlist(id="PLuser1", title="User Playlist 1"),
            Playlist(id="PLuser2", title="User Playlist 2"),
        ]

        with patch("ytrix.__main__.extractor.extract_channel_playlists", return_value=playlists):
            cli.ls(user="@testchannel")

        captured = capsys.readouterr()
        assert "User Playlist 1" in captured.out
        assert "User Playlist 2" in captured.out
        assert "PLuser1" in captured.out

    def test_list_user_empty(self, cli: YtrixCLI, capsys) -> None:
        """List --user shows message when no playlists found."""
        with patch("ytrix.__main__.extractor.extract_channel_playlists", return_value=[]):
            cli.ls(user="@emptychannel")

        captured = capsys.readouterr()
        assert "No playlists found" in captured.out

    def test_list_user_json_output(self, cli_json: YtrixCLI, capsys) -> None:
        """List --user with JSON output returns dict."""
        import json as json_mod

        playlists = [Playlist(id="PLuser1", title="User Playlist 1")]

        with patch("ytrix.__main__.extractor.extract_channel_playlists", return_value=playlists):
            cli_json.ls(user="@testchannel")

        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["count"] == 1
        assert parsed["playlists"][0]["id"] == "PLuser1"

    def test_list_urls_output(
        self, cli: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, capsys
    ) -> None:
        """List --urls outputs only URLs, one per line."""
        playlists = [
            Playlist(id="PL1", title="Playlist 1"),
            Playlist(id="PL2", title="Playlist 2"),
        ]

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.api.list_my_playlists", return_value=playlists),
        ):
            result = cli.ls(urls=True)

        assert result is None  # No JSON return for urls mode
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 2
        assert "https://youtube.com/playlist?list=PL1" in lines[0]
        assert "https://youtube.com/playlist?list=PL2" in lines[1]
        # Should not have Rich formatting
        assert "[" not in captured.out or "list=" in captured.out

    def test_list_user_urls_output(self, cli: YtrixCLI, capsys) -> None:
        """List --user --urls outputs only URLs from another user's channel."""
        playlists = [
            Playlist(id="PLuser1", title="User Playlist 1"),
            Playlist(id="PLuser2", title="User Playlist 2"),
        ]

        with patch("ytrix.__main__.extractor.extract_channel_playlists", return_value=playlists):
            result = cli.ls(user="@testchannel", urls=True)

        assert result is None
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 2
        assert "https://youtube.com/playlist?list=PLuser1" in lines[0]
        assert "https://youtube.com/playlist?list=PLuser2" in lines[1]


class TestPlist2mlist:
    """Tests for plist2mlist command."""

    def test_copies_playlist(
        self, cli: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock
    ) -> None:
        """Copies playlist to user's channel."""
        source_playlist = Playlist(
            id="PLsource",
            title="Source Playlist",
            description="Description",
            videos=[
                Video(id="vid1", title="Video 1", channel="Ch", position=0),
                Video(id="vid2", title="Video 2", channel="Ch", position=1),
            ],
        )
        mock_client.playlists().insert().execute.return_value = {"id": "PLnew123"}

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.extractor.extract_playlist", return_value=source_playlist),
            patch("ytrix.__main__.api.create_playlist", return_value="PLnew123"),
            patch("ytrix.__main__.api.add_video_to_playlist"),
        ):
            result = cli.plist2mlist("PLsource")

        assert "PLnew123" in result

    def test_dry_run_does_not_create(self, cli: YtrixCLI) -> None:
        """Dry run extracts but doesn't create playlist."""
        source_playlist = Playlist(
            id="PLsource",
            title="Source Playlist",
            description="Description",
            videos=[
                Video(id="vid1", title="Video 1", channel="Ch", position=0),
            ],
        )

        with (
            patch("ytrix.__main__.extractor.extract_playlist", return_value=source_playlist),
            patch("ytrix.__main__.api.create_playlist") as mock_create,
        ):
            result = cli.plist2mlist("PLsource", dry_run=True)

        mock_create.assert_not_called()
        assert result is None


class TestPlist2mlistFlags:
    """Tests for plist2mlist --title and --privacy flags."""

    def test_custom_title_dry_run(self, cli: YtrixCLI, capsys) -> None:
        """--title flag shows custom title in dry run."""
        source_playlist = Playlist(
            id="PLsource",
            title="Original Title",
            description="Desc",
            videos=[Video(id="v1", title="V1", channel="Ch", position=0)],
        )

        with patch("ytrix.__main__.extractor.extract_playlist", return_value=source_playlist):
            cli.plist2mlist("PLsource", dry_run=True, title="My Custom Title")

        captured = capsys.readouterr()
        assert "My Custom Title" in captured.out
        # The "Title:" line should show custom title, not original
        assert "Title: My Custom Title" in captured.out

    def test_custom_title_json_dry_run(self, cli_json: YtrixCLI, capsys) -> None:
        """--title flag with JSON output in dry run."""
        import json as json_mod

        source_playlist = Playlist(
            id="PLsource",
            title="Original Title",
            description="Desc",
            videos=[Video(id="v1", title="V1", channel="Ch", position=0)],
        )

        with patch("ytrix.__main__.extractor.extract_playlist", return_value=source_playlist):
            cli_json.plist2mlist("PLsource", dry_run=True, title="Custom Title")

        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["title"] == "Custom Title"

    def test_privacy_dry_run(self, cli: YtrixCLI, capsys) -> None:
        """--privacy flag shows in dry run."""
        source_playlist = Playlist(
            id="PLsource",
            title="Title",
            description="Desc",
            videos=[Video(id="v1", title="V1", channel="Ch", position=0)],
        )

        with patch("ytrix.__main__.extractor.extract_playlist", return_value=source_playlist):
            cli.plist2mlist("PLsource", dry_run=True, privacy="unlisted")

        captured = capsys.readouterr()
        assert "unlisted" in captured.out

    def test_privacy_json_dry_run(self, cli_json: YtrixCLI, capsys) -> None:
        """--privacy flag with JSON output in dry run."""
        import json as json_mod

        source_playlist = Playlist(
            id="PLsource",
            title="Title",
            description="Desc",
            videos=[Video(id="v1", title="V1", channel="Ch", position=0)],
        )

        with patch("ytrix.__main__.extractor.extract_playlist", return_value=source_playlist):
            cli_json.plist2mlist("PLsource", dry_run=True, privacy="private")

        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["privacy"] == "private"

    def test_invalid_privacy_raises(self, cli: YtrixCLI) -> None:
        """Invalid --privacy value raises ValueError."""
        with pytest.raises(ValueError, match="--privacy must be"):
            cli.plist2mlist("PLtest", privacy="invalid")

    def test_title_and_privacy_create(
        self, cli_json: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, capsys
    ) -> None:
        """--title and --privacy are used when creating playlist."""
        import json as json_mod

        source_playlist = Playlist(
            id="PLsource",
            title="Original",
            description="Desc",
            videos=[Video(id="v1", title="V1", channel="Ch", position=0)],
        )

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.extractor.extract_playlist", return_value=source_playlist),
            patch("ytrix.__main__.api.create_playlist", return_value="PLnew") as mock_create,
            patch("ytrix.__main__.api.add_video_to_playlist"),
        ):
            cli_json.plist2mlist("PLsource", title="Custom", privacy="unlisted")

        # Verify create_playlist was called with custom title and privacy
        mock_create.assert_called_once_with(mock_client, "Custom", "Desc", "unlisted")

        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["title"] == "Custom"
        assert parsed["privacy"] == "unlisted"


class TestPlists2mlistFlags:
    """Tests for plists2mlist --privacy flag."""

    def test_privacy_dry_run(self, cli: YtrixCLI, capsys, tmp_path: Path) -> None:
        """--privacy flag shows in dry run."""
        input_file = tmp_path / "playlists.txt"
        input_file.write_text("PLtest\n")

        playlist = Playlist(
            id="PLtest",
            title="Test",
            videos=[Video(id="v1", title="V1", channel="Ch", position=0)],
        )

        with patch("ytrix.__main__.extractor.extract_playlist", return_value=playlist):
            cli.plists2mlist(str(input_file), dry_run=True, privacy="unlisted")

        captured = capsys.readouterr()
        assert "Privacy: unlisted" in captured.out

    def test_privacy_json_dry_run(self, cli_json: YtrixCLI, capsys, tmp_path: Path) -> None:
        """--privacy flag with JSON output in dry run."""
        import json as json_mod

        input_file = tmp_path / "playlists.txt"
        input_file.write_text("PLtest\n")

        playlist = Playlist(
            id="PLtest",
            title="Test",
            videos=[Video(id="v1", title="V1", channel="Ch", position=0)],
        )

        with patch("ytrix.__main__.extractor.extract_playlist", return_value=playlist):
            cli_json.plists2mlist(str(input_file), dry_run=True, privacy="private")

        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["privacy"] == "private"

    def test_invalid_privacy_raises(self, cli: YtrixCLI, tmp_path: Path) -> None:
        """Invalid --privacy value raises ValueError."""
        input_file = tmp_path / "playlists.txt"
        input_file.write_text("PLtest\n")

        with pytest.raises(ValueError, match="--privacy must be"):
            cli.plists2mlist(str(input_file), privacy="invalid")

    def test_privacy_used_in_create(
        self, cli_json: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """--privacy is passed to create_playlist."""
        input_file = tmp_path / "playlists.txt"
        input_file.write_text("PLtest\n")

        playlist = Playlist(
            id="PLtest",
            title="Test",
            videos=[Video(id="v1", title="V1", channel="Ch", position=0)],
        )

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.extractor.extract_playlist", return_value=playlist),
            patch("ytrix.__main__.api.create_playlist", return_value="PLnew") as mock_create,
            patch("ytrix.__main__.api.add_video_to_playlist"),
        ):
            cli_json.plists2mlist(str(input_file), title="Merged", privacy="unlisted")

        # Verify create_playlist was called with privacy
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        assert call_args.kwargs.get("privacy") == "unlisted"


class TestPlists2mlist:
    """Tests for plists2mlist command."""

    def test_merges_playlists_from_file(
        self, cli: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Merges multiple playlists from file."""
        input_file = tmp_path / "playlists.txt"
        input_file.write_text("PLlist1\nPLlist2\n")

        playlist1 = Playlist(
            id="PLlist1",
            title="List 1",
            videos=[Video(id="v1", title="V1", channel="Ch", position=0)],
        )
        playlist2 = Playlist(
            id="PLlist2",
            title="List 2",
            videos=[Video(id="v2", title="V2", channel="Ch", position=0)],
        )

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.extractor.extract_playlist", side_effect=[playlist1, playlist2]),
            patch("ytrix.__main__.api.create_playlist", return_value="PLmerged"),
            patch("ytrix.__main__.api.add_video_to_playlist"),
        ):
            result = cli.plists2mlist(str(input_file))

        assert result is not None
        assert "PLmerged" in result

    def test_deduplicates_videos(
        self, cli_json: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Skips duplicate videos when merging."""
        input_file = tmp_path / "playlists.txt"
        input_file.write_text("PLlist1\nPLlist2\n")

        # Both playlists have video "v1"
        playlist1 = Playlist(
            id="PLlist1",
            title="List 1",
            videos=[Video(id="v1", title="V1", channel="Ch", position=0)],
        )
        playlist2 = Playlist(
            id="PLlist2",
            title="List 2",
            videos=[
                Video(id="v1", title="V1", channel="Ch", position=0),  # duplicate
                Video(id="v2", title="V2", channel="Ch", position=1),
            ],
        )

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.extractor.extract_playlist", side_effect=[playlist1, playlist2]),
            patch("ytrix.__main__.api.create_playlist", return_value="PLmerged"),
            patch("ytrix.__main__.api.add_video_to_playlist") as mock_add,
        ):
            result = cli_json.plists2mlist(str(input_file))

        # Should only add 2 unique videos, not 3
        assert mock_add.call_count == 2
        assert result is not None
        assert result["duplicates_skipped"] == 1


class TestPlist2mlists:
    """Tests for plist2mlists command."""

    def test_splits_by_channel(
        self, cli: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock
    ) -> None:
        """Splits playlist by channel."""
        source = Playlist(
            id="PLsource",
            title="Mixed",
            videos=[
                Video(id="v1", title="V1", channel="Channel A", position=0),
                Video(id="v2", title="V2", channel="Channel B", position=1),
            ],
        )

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.extractor.extract_playlist", return_value=source),
            patch("ytrix.__main__.api.create_playlist", side_effect=["PL1", "PL2"]),
            patch("ytrix.__main__.api.add_video_to_playlist"),
        ):
            result = cli.plist2mlists("PLsource", by="channel")

        assert result is not None and len(result) == 2

    def test_splits_by_year(
        self, cli: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock
    ) -> None:
        """Splits playlist by year."""
        source = Playlist(
            id="PLsource",
            title="Mixed Years",
            videos=[
                Video(id="v1", title="V1", channel="Ch", position=0, upload_date="20230115"),
                Video(id="v2", title="V2", channel="Ch", position=1, upload_date="20240320"),
            ],
        )

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.extractor.extract_playlist", return_value=source),
            patch("ytrix.__main__.api.create_playlist", side_effect=["PL2023", "PL2024"]),
            patch("ytrix.__main__.api.add_video_to_playlist"),
        ):
            result = cli.plist2mlists("PLsource", by="year")

        assert result is not None and len(result) == 2

    def test_json_output(
        self, cli_json: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, capsys
    ) -> None:
        """JSON output returns structured data."""
        import json as json_mod

        source = Playlist(
            id="PLsource",
            title="Mixed",
            videos=[
                Video(id="v1", title="V1", channel="Channel A", position=0),
                Video(id="v2", title="V2", channel="Channel B", position=1),
            ],
        )

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.extractor.extract_playlist", return_value=source),
            patch("ytrix.__main__.api.create_playlist", side_effect=["PL1", "PL2"]),
            patch("ytrix.__main__.api.add_video_to_playlist"),
        ):
            cli_json.plist2mlists("PLsource", by="channel")

        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["source_title"] == "Mixed"
        assert parsed["split_by"] == "channel"
        assert parsed["playlists_created"] == 2
        assert len(parsed["playlists"]) == 2

    def test_dry_run_shows_preview(self, cli: YtrixCLI, capsys) -> None:
        """Dry run shows what would be created without making changes."""
        source = Playlist(
            id="PLsource",
            title="Mixed",
            videos=[
                Video(id="v1", title="V1", channel="Channel A", position=0),
                Video(id="v2", title="V2", channel="Channel B", position=1),
            ],
        )

        with patch("ytrix.__main__.extractor.extract_playlist", return_value=source):
            result = cli.plist2mlists("PLsource", by="channel", dry_run=True)

        assert result is None  # No playlists created
        captured = capsys.readouterr()
        assert "Dry run" in captured.out
        assert "Channel A" in captured.out
        assert "Channel B" in captured.out

    def test_dry_run_json_output(self, cli_json: YtrixCLI, capsys) -> None:
        """Dry run with JSON returns planned playlists."""
        import json as json_mod

        source = Playlist(
            id="PLsource",
            title="Mixed",
            videos=[
                Video(id="v1", title="V1", channel="Channel A", position=0),
                Video(id="v2", title="V2", channel="Channel B", position=1),
            ],
        )

        with patch("ytrix.__main__.extractor.extract_playlist", return_value=source):
            cli_json.plist2mlists("PLsource", by="channel", dry_run=True)

        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["dry_run"] is True
        assert parsed["playlists_planned"] == 2
        assert len(parsed["playlists"]) == 2


class TestMlists2yaml:
    """Tests for mlists2yaml command."""

    def test_exports_playlists(
        self, cli: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Exports all playlists to YAML."""
        playlists = [
            Playlist(id="PL1", title="Playlist 1"),
            Playlist(id="PL2", title="Playlist 2"),
        ]
        output_path = tmp_path / "playlists.yaml"

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.api.list_my_playlists", return_value=playlists),
        ):
            result = cli.mlists2yaml(str(output_path), details=False)

        assert result == str(output_path)
        assert output_path.exists()
        content = output_path.read_text()
        assert "PL1" in content
        assert "PL2" in content

    def test_json_output_returns_dict(
        self, cli_json: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, capsys
    ) -> None:
        """JSON output returns dict and prints JSON."""
        import json as json_mod

        playlists = [
            Playlist(id="PL1", title="Playlist 1"),
            Playlist(id="PL2", title="Playlist 2"),
        ]

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.api.list_my_playlists", return_value=playlists),
        ):
            result = cli_json.mlists2yaml(details=False)

        assert isinstance(result, dict)
        assert result["count"] == 2
        assert len(result["playlists"]) == 2

        # Verify JSON was printed
        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["count"] == 2


class TestYaml2mlists:
    """Tests for yaml2mlists command."""

    def test_applies_changes_dry_run(
        self, cli: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Dry run shows changes without applying."""
        yaml_file = tmp_path / "playlists.yaml"
        yaml_file.write_text(
            """
playlists:
  - id: PL123
    title: New Title
    description: New Desc
    privacy: public
"""
        )

        current = Playlist(id="PL123", title="Old Title", description="Old Desc")
        mock_client.playlists().list().execute.return_value = {
            "items": [
                {
                    "id": "PL123",
                    "snippet": {"title": "Old Title", "description": "Old Desc"},
                    "status": {"privacyStatus": "public"},
                }
            ]
        }
        mock_client.playlistItems().list().execute.return_value = {"items": []}

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.api.get_playlist_with_videos", return_value=current),
            patch("ytrix.__main__.api.update_playlist") as mock_update,
        ):
            cli.yaml2mlists(str(yaml_file), dry_run=True)

        mock_update.assert_not_called()

    def test_json_output(
        self,
        cli_json: YtrixCLI,
        mock_config: MagicMock,
        mock_client: MagicMock,
        tmp_path: Path,
        capsys,
    ) -> None:
        """JSON output returns structured diff data."""
        import json as json_mod

        yaml_file = tmp_path / "playlists.yaml"
        yaml_file.write_text(
            """
playlists:
  - id: PL123
    title: New Title
    description: Desc
    privacy: public
"""
        )

        current = Playlist(id="PL123", title="Old Title", description="Desc")

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.api.get_playlist_with_videos", return_value=current),
        ):
            cli_json.yaml2mlists(str(yaml_file), dry_run=True)

        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["dry_run"] is True
        assert parsed["playlists_processed"] == 1
        assert parsed["playlists"][0]["playlist_id"] == "PL123"
        assert "title" in parsed["playlists"][0]["changes"]


class TestMlist2yaml:
    """Tests for mlist2yaml command."""

    def test_exports_single_playlist(
        self, cli: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Exports single playlist to YAML using yt-dlp for videos."""
        videos = [Video(id="v1", title="V1", channel="Ch", position=0)]
        extracted_playlist = Playlist(
            id="PLsingle",
            title="Single Playlist",
            videos=videos,
        )
        output_path = tmp_path / "single.yaml"

        # Mock the API metadata response
        mock_client.playlists.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "snippet": {"title": "Single Playlist", "description": "Test desc"},
                    "status": {"privacyStatus": "public"},
                }
            ]
        }

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.extractor.extract_playlist", return_value=extracted_playlist),
        ):
            result = cli.mlist2yaml("PLsingle", output=str(output_path))

        assert result == str(output_path)
        assert output_path.exists()
        assert "PLsingle" in output_path.read_text()

    def test_json_output(
        self, cli_json: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, capsys
    ) -> None:
        """JSON output returns playlist data."""
        import json as json_mod

        videos = [Video(id="v1", title="V1", channel="Ch", position=0)]
        extracted_playlist = Playlist(
            id="PLsingle",
            title="Single Playlist",
            videos=videos,
        )

        # Mock the API metadata response
        mock_client.playlists.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "snippet": {"title": "Single Playlist", "description": ""},
                    "status": {"privacyStatus": "public"},
                }
            ]
        }

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.extractor.extract_playlist", return_value=extracted_playlist),
        ):
            cli_json.mlist2yaml("PLsingle")

        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["playlist"]["id"] == "PLsingle"
        assert parsed["playlist"]["title"] == "Single Playlist"
        assert len(parsed["playlist"]["videos"]) == 1

    def test_falls_back_to_api_for_private_playlist(
        self, cli: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Falls back to API when yt-dlp fails (e.g., private playlist)."""
        videos = [Video(id="v1", title="V1", channel="Ch", position=0)]
        output_path = tmp_path / "private.yaml"

        # Mock the API metadata response
        mock_client.playlists.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "snippet": {"title": "Private Playlist", "description": ""},
                    "status": {"privacyStatus": "private"},
                }
            ]
        }

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.extractor.extract_playlist", side_effect=Exception("Private")),
            patch("ytrix.__main__.api.get_playlist_videos", return_value=videos),
        ):
            result = cli.mlist2yaml("PLprivate", output=str(output_path))

        assert result == str(output_path)
        assert output_path.exists()
        content = output_path.read_text()
        assert "PLprivate" in content
        assert "private" in content


class TestYaml2mlist:
    """Tests for yaml2mlist command."""

    def test_delegates_to_yaml2mlists(
        self, cli: YtrixCLI, mock_config: MagicMock, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Delegates to yaml2mlists for single playlist."""
        yaml_file = tmp_path / "playlist.yaml"
        yaml_file.write_text(
            """
playlists:
  - id: PL123
    title: Test
    description: Desc
    privacy: public
"""
        )

        current = Playlist(id="PL123", title="Test", description="Desc")

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.api.get_playlist_with_videos", return_value=current),
        ):
            # Should not raise
            cli.yaml2mlist(str(yaml_file), dry_run=True)

    def test_json_output_returns_result(
        self,
        cli_json: YtrixCLI,
        mock_config: MagicMock,
        mock_client: MagicMock,
        tmp_path: Path,
        capsys,
    ) -> None:
        """JSON output returns structured data."""
        import json as json_mod

        yaml_file = tmp_path / "playlist.yaml"
        yaml_file.write_text(
            """
playlists:
  - id: PL123
    title: Updated Title
    description: Desc
    privacy: public
"""
        )

        current = Playlist(id="PL123", title="Original", description="Desc")

        with (
            patch("ytrix.__main__.load_config", return_value=mock_config),
            patch("ytrix.__main__.api.get_youtube_client", return_value=mock_client),
            patch("ytrix.__main__.api.get_playlist_with_videos", return_value=current),
            patch("ytrix.__main__.api.update_playlist"),
        ):
            result = cli_json.yaml2mlist(str(yaml_file))

        assert result is not None
        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert "playlists_processed" in parsed
        assert parsed["playlists_processed"] == 1


class TestErrorCases:
    """Tests for error handling in CLI commands."""

    def test_extract_playlist_id_invalid_chars(self) -> None:
        """extract_playlist_id raises on invalid characters."""
        from ytrix.models import InvalidPlaylistError, extract_playlist_id

        with pytest.raises(InvalidPlaylistError, match="Invalid characters"):
            extract_playlist_id("PL@#$%invalid")

    def test_extract_playlist_id_empty(self) -> None:
        """extract_playlist_id raises on empty input."""
        from ytrix.models import InvalidPlaylistError, extract_playlist_id

        with pytest.raises(InvalidPlaylistError, match="Empty"):
            extract_playlist_id("")

    def test_extract_playlist_id_too_short(self) -> None:
        """extract_playlist_id raises on too-short input."""
        from ytrix.models import InvalidPlaylistError, extract_playlist_id

        with pytest.raises(InvalidPlaylistError, match="too short"):
            extract_playlist_id("P")

    def test_plist2mlists_invalid_by(self, cli: YtrixCLI) -> None:
        """plist2mlists raises on invalid --by value."""
        with pytest.raises(ValueError, match="--by must be"):
            cli.plist2mlists("PLtest", by="invalid")

    def test_plists2mlist_empty_file(self, cli: YtrixCLI, tmp_path: Path) -> None:
        """plists2mlist raises on empty file."""
        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("")

        with pytest.raises(ValueError, match="No playlist URLs found"):
            cli.plists2mlist(str(empty_file))

    def test_plists2mlist_comments_only(self, cli: YtrixCLI, tmp_path: Path) -> None:
        """plists2mlist raises when file has only comments."""
        comments_file = tmp_path / "comments.txt"
        comments_file.write_text("# comment 1\n# comment 2\n")

        with pytest.raises(ValueError, match="No playlist URLs found"):
            cli.plists2mlist(str(comments_file))

    def test_ls_missing_config(self, cli: YtrixCLI) -> None:
        """ls raises when config file is missing."""
        with (
            patch("ytrix.__main__.load_config", side_effect=FileNotFoundError("Config not found")),
            pytest.raises(FileNotFoundError, match="Config not found"),
        ):
            cli.ls()


class TestCacheCommands:
    """Tests for cache_stats and cache_clear commands."""

    def test_cache_stats_shows_info(self, cli: YtrixCLI, capsys) -> None:
        """cache_stats command shows cache statistics."""
        mock_stats = {
            "path": "/tmp/cache.db",
            "size_mb": 1.5,
            "playlists": {"valid": 5, "total": 10},
            "videos": {"valid": 100, "total": 150},
            "playlist_videos": {"valid": 50, "total": 75},
            "channel_playlists": {"valid": 2, "total": 3},
        }
        with patch("ytrix.__main__.cache.get_cache_stats", return_value=mock_stats):
            cli.cache_stats()

        captured = capsys.readouterr()
        assert "/tmp/cache.db" in captured.out
        assert "1.5 MB" in captured.out
        assert "playlists: 5 valid / 10 total" in captured.out
        assert "videos: 100 valid / 150 total" in captured.out

    def test_cache_stats_json_output(self, cli_json: YtrixCLI, capsys) -> None:
        """cache_stats with JSON output returns dict."""
        import json as json_mod

        mock_stats = {
            "path": "/tmp/cache.db",
            "size_mb": 1.5,
            "playlists": {"valid": 5, "total": 10},
            "videos": {"valid": 100, "total": 150},
            "playlist_videos": {"valid": 50, "total": 75},
            "channel_playlists": {"valid": 2, "total": 3},
        }
        with patch("ytrix.__main__.cache.get_cache_stats", return_value=mock_stats):
            cli_json.cache_stats()

        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["path"] == "/tmp/cache.db"
        assert parsed["size_mb"] == 1.5
        assert parsed["playlists"]["valid"] == 5

    def test_cache_stats_no_size(self, cli: YtrixCLI, capsys) -> None:
        """cache_stats handles missing size_mb gracefully."""
        mock_stats = {
            "path": "/tmp/cache.db",
            "playlists": {"valid": 0, "total": 0},
            "videos": {"valid": 0, "total": 0},
            "playlist_videos": {"valid": 0, "total": 0},
            "channel_playlists": {"valid": 0, "total": 0},
        }
        with patch("ytrix.__main__.cache.get_cache_stats", return_value=mock_stats):
            cli.cache_stats()

        captured = capsys.readouterr()
        assert "/tmp/cache.db" in captured.out
        assert "MB" not in captured.out  # No size_mb field

    def test_cache_clear_all(self, cli: YtrixCLI, capsys) -> None:
        """cache_clear clears all entries."""
        with patch("ytrix.__main__.cache.clear_cache", return_value=100) as mock_clear:
            cli.cache_clear()

        mock_clear.assert_called_once()
        captured = capsys.readouterr()
        assert "Cleared 100 cache entries" in captured.out

    def test_cache_clear_expired_only(self, cli: YtrixCLI, capsys) -> None:
        """cache_clear --expired-only clears only expired entries."""
        with patch("ytrix.__main__.cache.clear_expired", return_value=25) as mock_clear:
            cli.cache_clear(expired_only=True)

        mock_clear.assert_called_once()
        captured = capsys.readouterr()
        assert "Cleared 25 expired cache entries" in captured.out

    def test_cache_clear_json_output(self, cli_json: YtrixCLI, capsys) -> None:
        """cache_clear with JSON output returns dict."""
        import json as json_mod

        with patch("ytrix.__main__.cache.clear_cache", return_value=50):
            cli_json.cache_clear()

        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["deleted"] == 50
        assert parsed["expired_only"] is False

    def test_cache_clear_expired_json_output(self, cli_json: YtrixCLI, capsys) -> None:
        """cache_clear --expired-only with JSON output."""
        import json as json_mod

        with patch("ytrix.__main__.cache.clear_expired", return_value=10):
            cli_json.cache_clear(expired_only=True)

        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["deleted"] == 10
        assert parsed["expired_only"] is True


class TestConfigTokenStatus:
    """Tests for config command token status display."""

    def test_config_shows_token_exists(self, cli: YtrixCLI, capsys, tmp_path: Path) -> None:
        """Config shows green when OAuth token exists."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("channel_id = 'UCtest'\n[oauth]\nclient_id = 'id'\n")
        token_file = tmp_path / "token.json"
        token_file.write_text('{"access_token": "test"}')

        with patch("ytrix.__main__.get_config_dir", return_value=tmp_path):
            cli.config()

        captured = capsys.readouterr()
        assert "OAuth token cached" in captured.out

    def test_config_shows_no_token(self, cli: YtrixCLI, capsys, tmp_path: Path) -> None:
        """Config shows yellow when OAuth token missing."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("channel_id = 'UCtest'\n[oauth]\nclient_id = 'id'\n")
        # No token.json created

        with patch("ytrix.__main__.get_config_dir", return_value=tmp_path):
            cli.config()

        captured = capsys.readouterr()
        assert "No OAuth token yet" in captured.out


class TestListUserWithCount:
    """Tests for ls --user --count flag."""

    def test_list_user_with_count(self, cli: YtrixCLI, capsys) -> None:
        """List --user --count shows video counts via yt-dlp."""
        playlists = [
            Playlist(id="PLuser1", title="User Playlist 1"),
            Playlist(id="PLuser2", title="User Playlist 2"),
        ]

        with (
            patch("ytrix.__main__.extractor.extract_channel_playlists", return_value=playlists),
            patch("ytrix.__main__.extractor.get_video_count", side_effect=[10, 25]),
        ):
            cli.ls(user="@testchannel", count=True)

        captured = capsys.readouterr()
        assert "10 videos" in captured.out
        assert "25 videos" in captured.out

    def test_list_user_with_count_json(self, cli_json: YtrixCLI, capsys) -> None:
        """List --user --count with JSON includes video_count."""
        import json as json_mod

        playlists = [
            Playlist(id="PLuser1", title="User Playlist 1"),
        ]

        with (
            patch("ytrix.__main__.extractor.extract_channel_playlists", return_value=playlists),
            patch("ytrix.__main__.extractor.get_video_count", return_value=42),
        ):
            cli_json.ls(user="@testchannel", count=True)

        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["playlists"][0]["video_count"] == 42


class TestJournalStatus:
    """Tests for journal_status command."""

    def test_journal_status_no_journal(self, cli: YtrixCLI, capsys, tmp_path: Path) -> None:
        """Shows message when no journal exists."""
        with patch("ytrix.__main__.load_journal", return_value=None):
            cli.journal_status()
        captured = capsys.readouterr()
        assert "No journal found" in captured.out

    def test_journal_status_json_no_journal(self, cli_json: YtrixCLI, capsys) -> None:
        """JSON output when no journal exists."""
        import json as json_mod

        with patch("ytrix.__main__.load_journal", return_value=None):
            cli_json.journal_status()
        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["exists"] is False

    def test_journal_status_shows_summary(self, cli: YtrixCLI, capsys) -> None:
        """Shows journal summary when journal exists."""
        from ytrix.journal import Journal, Task, TaskStatus

        journal = Journal(
            batch_id="test_batch",
            created_at="2024-01-01T00:00:00",
            tasks=[
                Task(source_playlist_id="PL1", source_title="Test1", status=TaskStatus.COMPLETED),
                Task(source_playlist_id="PL2", source_title="Test2", status=TaskStatus.PENDING),
            ],
        )
        with patch("ytrix.__main__.load_journal", return_value=journal):
            cli.journal_status()
        captured = capsys.readouterr()
        assert "test_batch" in captured.out
        assert "Total: 2" in captured.out
        assert "Completed: 1" in captured.out
        assert "Pending: 1" in captured.out

    def test_journal_status_json(self, cli_json: YtrixCLI, capsys) -> None:
        """JSON output includes full journal data."""
        import json as json_mod

        from ytrix.journal import Journal, Task, TaskStatus

        journal = Journal(
            batch_id="test_batch",
            created_at="2024-01-01T00:00:00",
            tasks=[
                Task(source_playlist_id="PL1", source_title="Test1", status=TaskStatus.COMPLETED),
            ],
        )
        with patch("ytrix.__main__.load_journal", return_value=journal):
            cli_json.journal_status()
        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["batch_id"] == "test_batch"
        assert len(parsed["tasks"]) == 1
        assert parsed["summary"]["completed"] == 1

    def test_journal_status_clear(self, cli: YtrixCLI, capsys) -> None:
        """--clear flag clears the journal."""
        with patch("ytrix.__main__.clear_journal") as mock_clear:
            cli.journal_status(clear=True)
        mock_clear.assert_called_once()
        captured = capsys.readouterr()
        assert "Journal cleared" in captured.out

    def test_journal_status_clear_json(self, cli_json: YtrixCLI, capsys) -> None:
        """JSON output when clearing journal."""
        import json as json_mod

        with patch("ytrix.__main__.clear_journal"):
            cli_json.journal_status(clear=True)
        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["cleared"] is True

    def test_journal_status_shows_failed_tasks(self, cli: YtrixCLI, capsys) -> None:
        """Shows details of failed tasks."""
        from ytrix.journal import Journal, Task, TaskStatus

        journal = Journal(
            batch_id="test_batch",
            created_at="2024-01-01T00:00:00",
            tasks=[
                Task(
                    source_playlist_id="PL1",
                    source_title="Failed Task",
                    status=TaskStatus.FAILED,
                    error="API error",
                    retry_count=2,
                ),
            ],
        )
        with patch("ytrix.__main__.load_journal", return_value=journal):
            cli.journal_status()
        captured = capsys.readouterr()
        assert "Failed tasks:" in captured.out
        assert "Failed Task" in captured.out
        assert "API error" in captured.out
        assert "Retries: 2" in captured.out

    def test_journal_status_pending_only(self, cli: YtrixCLI, capsys) -> None:
        """--pending-only filters to incomplete tasks."""
        from ytrix.journal import Journal, Task, TaskStatus

        journal = Journal(
            batch_id="test_batch",
            created_at="2024-01-01T00:00:00",
            tasks=[
                Task(source_playlist_id="PL1", source_title="Done", status=TaskStatus.COMPLETED),
                Task(
                    source_playlist_id="PL2", source_title="Pending Task", status=TaskStatus.PENDING
                ),
                Task(
                    source_playlist_id="PL3", source_title="Failed Task", status=TaskStatus.FAILED
                ),
            ],
        )
        with patch("ytrix.__main__.load_journal", return_value=journal):
            cli.journal_status(pending_only=True)
        captured = capsys.readouterr()
        assert "Pending tasks:" in captured.out
        assert "Pending Task" in captured.out

    def test_journal_status_pending_only_json(self, cli_json: YtrixCLI, capsys) -> None:
        """JSON output with --pending-only filters tasks."""
        import json as json_mod

        from ytrix.journal import Journal, Task, TaskStatus

        journal = Journal(
            batch_id="test_batch",
            created_at="2024-01-01T00:00:00",
            tasks=[
                Task(source_playlist_id="PL1", source_title="Done", status=TaskStatus.COMPLETED),
                Task(source_playlist_id="PL2", source_title="Pending", status=TaskStatus.PENDING),
            ],
        )
        with patch("ytrix.__main__.load_journal", return_value=journal):
            cli_json.journal_status(pending_only=True)
        captured = capsys.readouterr()
        parsed = json_mod.loads(captured.out)
        assert parsed["pending_only"] is True
        assert len(parsed["tasks"]) == 1
        assert parsed["tasks"][0]["source_title"] == "Pending"


class TestProjectFlag:
    """Tests for --project CLI flag."""

    def test_project_flag_stores_value(self) -> None:
        """--project flag stores project name."""
        with (
            patch("ytrix.__main__.configure_logging"),
            patch("ytrix.__main__.api.set_throttle_delay"),
        ):
            cli = YtrixCLI(project="backup")
        assert cli._project == "backup"

    def test_project_flag_default_none(self) -> None:
        """--project defaults to None."""
        with (
            patch("ytrix.__main__.configure_logging"),
            patch("ytrix.__main__.api.set_throttle_delay"),
        ):
            cli = YtrixCLI()
        assert cli._project is None


class TestProjectCommands:
    """Tests for project management commands."""

    def test_projects_command_exists(self) -> None:
        """projects command exists."""
        assert hasattr(YtrixCLI, "projects")
        assert callable(YtrixCLI.projects)

    def test_projects_auth_command_exists(self) -> None:
        """projects_auth command exists."""
        assert hasattr(YtrixCLI, "projects_auth")
        assert callable(YtrixCLI.projects_auth)

    def test_projects_select_command_exists(self) -> None:
        """projects_select command exists."""
        assert hasattr(YtrixCLI, "projects_select")
        assert callable(YtrixCLI.projects_select)

    def test_projects_add_command_exists(self) -> None:
        """projects_add command exists."""
        assert hasattr(YtrixCLI, "projects_add")
        assert callable(YtrixCLI.projects_add)


class TestHelpCommand:
    """Tests for help command."""

    def test_help_command_exists(self) -> None:
        """help command exists."""
        assert hasattr(YtrixCLI, "help")
        assert callable(YtrixCLI.help)

    def test_help_command_runs(self, capsys: Any) -> None:
        """help command prints output."""
        with (
            patch("ytrix.__main__.configure_logging"),
            patch("ytrix.__main__.api.set_throttle_delay"),
        ):
            cli = YtrixCLI()
            cli.help()
        captured = capsys.readouterr()
        assert "ytrix" in captured.out
        assert "plist2mlist" in captured.out
        assert "--help" in captured.out


class TestGcpCommands:
    """Tests for GCP project management commands."""

    def test_gcp_clone_command_exists(self) -> None:
        """gcp_clone command exists."""
        assert hasattr(YtrixCLI, "gcp_clone")
        assert callable(YtrixCLI.gcp_clone)

    def test_gcp_inventory_command_exists(self) -> None:
        """gcp_inventory command exists."""
        assert hasattr(YtrixCLI, "gcp_inventory")
        assert callable(YtrixCLI.gcp_inventory)

    def test_gcp_clone_requires_gcloud(self) -> None:
        """gcp_clone fails gracefully when gcloud is not installed."""
        with (
            patch("ytrix.__main__.configure_logging"),
            patch("ytrix.__main__.api.set_throttle_delay"),
            patch("ytrix.gcptrix.check_gcloud_installed", return_value=False),
        ):
            cli = YtrixCLI()
            result = cli.gcp_clone("test-project", "2")
        assert result is None

    def test_gcp_inventory_requires_gcloud(self) -> None:
        """gcp_inventory fails gracefully when gcloud is not installed."""
        with (
            patch("ytrix.__main__.configure_logging"),
            patch("ytrix.__main__.api.set_throttle_delay"),
            patch("ytrix.gcptrix.check_gcloud_installed", return_value=False),
        ):
            cli = YtrixCLI()
            result = cli.gcp_inventory("test-project")
        assert result is None

    def test_gcp_clone_json_output_on_missing_gcloud(self) -> None:
        """gcp_clone returns JSON error when gcloud missing and --json-output."""
        with (
            patch("ytrix.__main__.configure_logging"),
            patch("ytrix.__main__.api.set_throttle_delay"),
            patch("ytrix.gcptrix.check_gcloud_installed", return_value=False),
        ):
            cli = YtrixCLI(json_output=True)
            result = cli.gcp_clone("test-project", "2")
        assert result is not None
        assert result["success"] is False
        assert "gcloud" in result["error"].lower()

    def test_gcp_inventory_json_output_on_missing_gcloud(self) -> None:
        """gcp_inventory returns JSON error when gcloud missing and --json-output."""
        with (
            patch("ytrix.__main__.configure_logging"),
            patch("ytrix.__main__.api.set_throttle_delay"),
            patch("ytrix.gcptrix.check_gcloud_installed", return_value=False),
        ):
            cli = YtrixCLI(json_output=True)
            result = cli.gcp_inventory("test-project")
        assert result is not None
        assert result["success"] is False
        assert "gcloud" in result["error"].lower()
