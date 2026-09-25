"""Tests for the macOS MediaPlayer system-media adapter."""

from collections.abc import Callable

from iOpenPod.app.playback.system_media.macos import (
    MacOSSystemMediaSession,
    _MacOSBindings,  # pyright: ignore[reportPrivateUsage]
)
from iOpenPod.app.playback.system_media.session import (
    SystemMediaArtwork,
    SystemMediaCommand,
    SystemMediaCommandKind,
    SystemMediaSnapshot,
)


class _FakeInfoCenter:
    def __init__(self) -> None:
        self.info: dict[str, object] | None = None
        self.playback_state = -1

    def setNowPlayingInfo_(self, value: dict[str, object] | None) -> None:
        self.info = value

    def setPlaybackState_(self, value: int) -> None:
        self.playback_state = value


class _FakeCommand:
    def __init__(self) -> None:
        self.enabled = False
        self.handler: Callable[[object], int] | None = None
        self.removed_targets: list[object] = []

    def addTargetWithHandler_(
        self,
        handler: Callable[[object], int],
    ) -> object:
        self.handler = handler
        return handler

    def removeTarget_(self, target: object) -> None:
        self.removed_targets.append(target)

    def setEnabled_(self, enabled: bool) -> None:
        self.enabled = enabled

    def send(self, event: object | None = None) -> int:
        if self.handler is None:
            raise AssertionError("The fake native command has no handler")
        return self.handler(object() if event is None else event)


class _PositionEvent:
    def __init__(self, seconds: float) -> None:
        self._seconds = seconds

    def positionTime(self) -> float:
        return self._seconds


def test_macos_session_publishes_metadata_state_and_capabilities() -> None:
    info_center = _FakeInfoCenter()
    commands = _commands()
    session = MacOSSystemMediaSession(_bindings(info_center, commands))
    snapshot = _snapshot(playing=True)

    session.publish(snapshot)

    assert info_center.info == {
        "title": "Flamingo",
        "artist": "Token",
        "album": "Between Somewhere",
        "genre": "Alternative",
        "trackNumber": 4,
        "duration": 231.0,
        "elapsed": 42.5,
        "rate": 1.0,
        "defaultRate": 1.0,
        "externalId": "iopenpod:entry:12",
        "persistentId": 7,
        "excludeSuggestions": True,
    }
    assert info_center.playback_state == 1
    assert not commands[SystemMediaCommandKind.PLAY].enabled
    assert commands[SystemMediaCommandKind.PAUSE].enabled
    assert commands[SystemMediaCommandKind.TOGGLE_PLAY_PAUSE].enabled
    assert commands[SystemMediaCommandKind.NEXT].enabled
    assert commands[SystemMediaCommandKind.PREVIOUS].enabled
    assert commands[SystemMediaCommandKind.SEEK].enabled

    session.publish(_snapshot(playing=False))
    assert info_center.playback_state == 2
    assert commands[SystemMediaCommandKind.PLAY].enabled
    assert not commands[SystemMediaCommandKind.PAUSE].enabled


def test_macos_session_translates_remote_commands_and_seek_seconds() -> None:
    info_center = _FakeInfoCenter()
    commands = _commands()
    session = MacOSSystemMediaSession(_bindings(info_center, commands))
    received: list[SystemMediaCommand] = []
    session.set_command_handler(received.append)
    session.publish(_snapshot(playing=False))

    assert commands[SystemMediaCommandKind.PLAY].send() == 0
    assert commands[SystemMediaCommandKind.SEEK].send(_PositionEvent(12.345)) == 0

    assert received == [
        SystemMediaCommand(SystemMediaCommandKind.PLAY),
        SystemMediaCommand(SystemMediaCommandKind.SEEK, 12_345),
    ]


def test_macos_session_converts_and_reuses_album_artwork_by_cache_key() -> None:
    info_center = _FakeInfoCenter()
    commands = _commands()
    converted: list[SystemMediaArtwork] = []

    def make_artwork(artwork: SystemMediaArtwork) -> object:
        converted.append(artwork)
        return (artwork.cache_key, artwork.width, artwork.height)

    session = MacOSSystemMediaSession(
        _bindings(info_center, commands, make_artwork=make_artwork)
    )
    artwork = SystemMediaArtwork(
        cache_key="device:64:1061",
        artwork_id=64,
        width=2,
        height=2,
        rgb888=bytes((10, 20, 30)) * 4,
    )

    session.publish(_snapshot(playing=True, artwork=artwork))
    session.publish(_snapshot(playing=False, artwork=artwork))

    assert info_center.info is not None
    assert info_center.info["artwork"] == ("device:64:1061", 2, 2)
    assert converted == [artwork]


def test_macos_session_keeps_metadata_when_artwork_conversion_fails() -> None:
    info_center = _FakeInfoCenter()
    commands = _commands()
    attempts = 0

    def reject_artwork(_artwork: SystemMediaArtwork) -> object:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("Native image conversion failed")

    session = MacOSSystemMediaSession(
        _bindings(info_center, commands, make_artwork=reject_artwork)
    )
    artwork = SystemMediaArtwork(
        cache_key="broken:64:1061",
        artwork_id=64,
        width=1,
        height=1,
        rgb888=bytes((10, 20, 30)),
    )

    session.publish(_snapshot(playing=True, artwork=artwork))
    session.publish(_snapshot(playing=False, artwork=artwork))

    assert info_center.info is not None
    assert info_center.info["title"] == "Flamingo"
    assert "artwork" not in info_center.info
    assert attempts == 1


def test_macos_session_close_clears_now_playing_and_native_targets() -> None:
    info_center = _FakeInfoCenter()
    commands = _commands()
    session = MacOSSystemMediaSession(_bindings(info_center, commands))
    session.publish(_snapshot(playing=True))

    session.close()
    session.close()

    assert info_center.info is None
    assert info_center.playback_state == 3
    assert all(not command.enabled for command in commands.values())
    assert all(len(command.removed_targets) == 1 for command in commands.values())
    assert commands[SystemMediaCommandKind.PLAY].send() == 110


def _commands() -> dict[SystemMediaCommandKind, _FakeCommand]:
    return {kind: _FakeCommand() for kind in SystemMediaCommandKind}


def _bindings(
    info_center: _FakeInfoCenter,
    commands: dict[SystemMediaCommandKind, _FakeCommand],
    *,
    make_artwork: Callable[[SystemMediaArtwork], object] | None = None,
) -> _MacOSBindings:
    return _MacOSBindings(
        info_center=info_center,
        commands=commands,
        title_key="title",
        artist_key="artist",
        album_key="album",
        genre_key="genre",
        track_number_key="trackNumber",
        duration_key="duration",
        persistent_id_key="persistentId",
        elapsed_key="elapsed",
        playback_rate_key="rate",
        default_rate_key="defaultRate",
        external_id_key="externalId",
        exclude_suggestions_key="excludeSuggestions",
        artwork_key="artwork",
        make_artwork=make_artwork or (lambda artwork: artwork.cache_key),
        state_playing=1,
        state_paused=2,
        state_stopped=3,
        status_success=0,
        status_no_item=110,
        status_failed=200,
    )


def _snapshot(
    *,
    playing: bool,
    artwork: SystemMediaArtwork | None = None,
) -> SystemMediaSnapshot:
    return SystemMediaSnapshot(
        entry_id=12,
        track_id=7,
        title="Flamingo",
        artist="Token",
        album="Between Somewhere",
        genre="Alternative",
        track_number=4,
        duration_ms=231_000,
        position_ms=42_500,
        playing=playing,
        can_play=not playing,
        can_pause=playing,
        can_next=True,
        can_previous=True,
        can_seek=True,
        artwork=artwork,
    )
