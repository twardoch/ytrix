"""Tests for ytrix package exports."""


def test_version_exported() -> None:
    """Package exports __version__."""
    from ytrix import __version__

    assert __version__
    assert isinstance(__version__, str)


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
