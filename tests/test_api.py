"""Tests for ytrix.api with mocked YouTube API client."""

from unittest.mock import MagicMock

import pytest

from ytrix.api import (
    PlaylistItem,
    add_video_to_playlist,
    create_playlist,
    get_playlist_items,
    get_playlist_videos,
    get_playlist_with_videos,
    list_my_playlists,
    remove_video_from_playlist,
    reorder_playlist_videos,
    update_playlist,
    update_playlist_item_position,
)


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock YouTube API client."""
    return MagicMock()


class TestCreatePlaylist:
    """Tests for create_playlist function."""

    def test_creates_playlist_with_defaults(self, mock_client: MagicMock) -> None:
        """Creates playlist with default privacy."""
        mock_client.playlists().insert().execute.return_value = {"id": "PLnew123"}

        result = create_playlist(mock_client, "Test Playlist")

        assert result == "PLnew123"
        mock_client.playlists().insert.assert_called()

    def test_creates_playlist_with_description(self, mock_client: MagicMock) -> None:
        """Creates playlist with description."""
        mock_client.playlists().insert().execute.return_value = {"id": "PLnew"}

        create_playlist(mock_client, "Test", description="My description")

        call_kwargs = mock_client.playlists().insert.call_args
        body = call_kwargs.kwargs.get("body", call_kwargs[1].get("body", {}))
        assert body["snippet"]["description"] == "My description"

    def test_creates_unlisted_playlist(self, mock_client: MagicMock) -> None:
        """Creates unlisted playlist."""
        mock_client.playlists().insert().execute.return_value = {"id": "PLnew"}

        create_playlist(mock_client, "Test", privacy="unlisted")

        call_kwargs = mock_client.playlists().insert.call_args
        body = call_kwargs.kwargs.get("body", call_kwargs[1].get("body", {}))
        assert body["status"]["privacyStatus"] == "unlisted"


class TestUpdatePlaylist:
    """Tests for update_playlist function."""

    def test_updates_title(self, mock_client: MagicMock) -> None:
        """Updates playlist title."""
        mock_client.playlists().list().execute.return_value = {
            "items": [
                {
                    "id": "PL123",
                    "snippet": {"title": "Old Title", "description": ""},
                    "status": {"privacyStatus": "public"},
                }
            ]
        }

        update_playlist(mock_client, "PL123", title="New Title")

        mock_client.playlists().update.assert_called()

    def test_raises_when_playlist_not_found(self, mock_client: MagicMock) -> None:
        """Raises ValueError when playlist not found."""
        mock_client.playlists().list().execute.return_value = {"items": []}

        with pytest.raises(ValueError, match="Playlist not found"):
            update_playlist(mock_client, "PLbad", title="New")


class TestAddVideoToPlaylist:
    """Tests for add_video_to_playlist function."""

    def test_adds_video_returns_item_id(self, mock_client: MagicMock) -> None:
        """Adds video and returns playlistItem ID."""
        mock_client.playlistItems().insert().execute.return_value = {"id": "item123"}

        result = add_video_to_playlist(mock_client, "PL123", "vid456")

        assert result == "item123"


class TestRemoveVideoFromPlaylist:
    """Tests for remove_video_from_playlist function."""

    def test_removes_video(self, mock_client: MagicMock) -> None:
        """Removes video by item ID."""
        remove_video_from_playlist(mock_client, "item123")

        mock_client.playlistItems().delete.assert_called_with(id="item123")


class TestListMyPlaylists:
    """Tests for list_my_playlists function."""

    def test_returns_playlists(self, mock_client: MagicMock) -> None:
        """Returns list of playlists."""
        mock_client.playlists().list().execute.return_value = {
            "items": [
                {
                    "id": "PL1",
                    "snippet": {"title": "Playlist 1", "description": "Desc 1"},
                    "status": {"privacyStatus": "public"},
                },
                {
                    "id": "PL2",
                    "snippet": {"title": "Playlist 2"},
                    "status": {"privacyStatus": "unlisted"},
                },
            ]
        }

        result = list_my_playlists(mock_client, "UC123")

        assert len(result) == 2
        assert result[0].id == "PL1"
        assert result[0].title == "Playlist 1"
        assert result[1].privacy == "unlisted"

    def test_handles_pagination(self, mock_client: MagicMock) -> None:
        """Handles paginated results."""
        mock_client.playlists().list().execute.side_effect = [
            {
                "items": [
                    {"id": "PL1", "snippet": {"title": "P1"}, "status": {"privacyStatus": "public"}}
                ],
                "nextPageToken": "token123",
            },
            {
                "items": [
                    {"id": "PL2", "snippet": {"title": "P2"}, "status": {"privacyStatus": "public"}}
                ],
            },
        ]

        result = list_my_playlists(mock_client, "UC123")

        assert len(result) == 2


class TestGetPlaylistItems:
    """Tests for get_playlist_items function."""

    def test_returns_items_with_ids(self, mock_client: MagicMock) -> None:
        """Returns PlaylistItem objects with item IDs."""
        mock_client.playlistItems().list().execute.return_value = {
            "items": [
                {
                    "id": "itemA",
                    "snippet": {
                        "resourceId": {"videoId": "vid1"},
                        "title": "Video 1",
                        "videoOwnerChannelTitle": "Channel",
                    },
                },
                {
                    "id": "itemB",
                    "snippet": {
                        "resourceId": {"videoId": "vid2"},
                        "title": "Video 2",
                    },
                },
            ]
        }

        result = get_playlist_items(mock_client, "PL123")

        assert len(result) == 2
        assert isinstance(result[0], PlaylistItem)
        assert result[0].item_id == "itemA"
        assert result[0].video_id == "vid1"
        assert result[0].position == 0
        assert result[1].position == 1


class TestGetPlaylistVideos:
    """Tests for get_playlist_videos function."""

    def test_returns_videos(self, mock_client: MagicMock) -> None:
        """Returns Video objects."""
        mock_client.playlistItems().list().execute.return_value = {
            "items": [
                {
                    "id": "item1",
                    "snippet": {
                        "resourceId": {"videoId": "vid1"},
                        "title": "Video 1",
                        "videoOwnerChannelTitle": "Ch",
                    },
                }
            ]
        }

        result = get_playlist_videos(mock_client, "PL123")

        assert len(result) == 1
        assert result[0].id == "vid1"
        assert result[0].title == "Video 1"


class TestGetPlaylistWithVideos:
    """Tests for get_playlist_with_videos function."""

    def test_returns_playlist_with_videos(self, mock_client: MagicMock) -> None:
        """Returns complete playlist with videos."""
        mock_client.playlists().list().execute.return_value = {
            "items": [
                {
                    "id": "PL123",
                    "snippet": {"title": "My Playlist", "description": "Desc"},
                    "status": {"privacyStatus": "public"},
                }
            ]
        }
        mock_client.playlistItems().list().execute.return_value = {
            "items": [
                {
                    "id": "item1",
                    "snippet": {
                        "resourceId": {"videoId": "vid1"},
                        "title": "V1",
                    },
                }
            ]
        }

        result = get_playlist_with_videos(mock_client, "PL123")

        assert result.id == "PL123"
        assert result.title == "My Playlist"
        assert len(result.videos) == 1

    def test_raises_when_not_found(self, mock_client: MagicMock) -> None:
        """Raises ValueError when playlist not found."""
        mock_client.playlists().list().execute.return_value = {"items": []}

        with pytest.raises(ValueError, match="Playlist not found"):
            get_playlist_with_videos(mock_client, "PLbad")


class TestUpdatePlaylistItemPosition:
    """Tests for update_playlist_item_position function."""

    def test_updates_position(self, mock_client: MagicMock) -> None:
        """Updates item position via API."""
        update_playlist_item_position(mock_client, "PL123", "itemA", "vid1", 5)

        mock_client.playlistItems().update.assert_called()
        call_kwargs = mock_client.playlistItems().update.call_args
        body = call_kwargs.kwargs.get("body", call_kwargs[1].get("body", {}))
        assert body["snippet"]["position"] == 5


class TestReorderPlaylistVideos:
    """Tests for reorder_playlist_videos function."""

    def test_reorders_videos(self, mock_client: MagicMock) -> None:
        """Reorders videos to match new order."""
        # Current order: vid1 (pos 0), vid2 (pos 1)
        mock_client.playlistItems().list().execute.return_value = {
            "items": [
                {"id": "itemA", "snippet": {"resourceId": {"videoId": "vid1"}, "title": "V1"}},
                {"id": "itemB", "snippet": {"resourceId": {"videoId": "vid2"}, "title": "V2"}},
            ]
        }

        # New order: vid2, vid1
        reorder_playlist_videos(mock_client, "PL123", ["vid2", "vid1"])

        # Should have called update to move vid2 to position 0
        mock_client.playlistItems().update.assert_called()

    def test_skips_videos_not_in_playlist(self, mock_client: MagicMock) -> None:
        """Skips videos not found in playlist."""
        mock_client.playlistItems().list().execute.return_value = {
            "items": [
                {"id": "itemA", "snippet": {"resourceId": {"videoId": "vid1"}, "title": "V1"}},
            ]
        }

        # vid2 not in playlist - should not raise
        reorder_playlist_videos(mock_client, "PL123", ["vid2", "vid1"])
