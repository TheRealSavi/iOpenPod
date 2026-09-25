"""Contract tests for backend-independent Host media integration."""

from collections.abc import Callable
from time import monotonic

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tests.iOpenPod.playback_test_support import FakePlaybackBackend

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iOpenPod.app.playback.system_media import (
    SystemMediaArtwork,
    SystemMediaBridge,
    SystemMediaCommand,
    SystemMediaCommandHandler,
    SystemMediaCommandKind,
    SystemMediaSnapshot,
)
from iOpenPod.app.playback_controller import PlaybackController
from iPodDB.library import Track


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


class _FakeSystemMediaSession:
    def __init__(self) -> None:
        self.handler: SystemMediaCommandHandler | None = None
        self.published: list[SystemMediaSnapshot | None] = []
        self.seek_positions: list[int] = []
        self.closed = False

    def set_command_handler(
        self,
        handler: SystemMediaCommandHandler | None,
    ) -> None:
        self.handler = handler

    def publish(self, snapshot: SystemMediaSnapshot | None) -> None:
        self.published.append(snapshot)

    def close(self) -> None:
        self.closed = True

    def seeked(self, position_ms: int) -> None:
        self.seek_positions.append(position_ms)

    def send(self, command: SystemMediaCommand) -> None:
        if self.handler is None:
            raise AssertionError("The fake system-media session has no command handler")
        self.handler(command)
        APPLICATION.processEvents()


class _FailingSystemMediaSession(_FakeSystemMediaSession):
    def publish(self, snapshot: SystemMediaSnapshot | None) -> None:
        del snapshot
        raise RuntimeError("Native media service unavailable")


class _ArtworkLoader:
    def __init__(self) -> None:
        self.requests: list[ArtworkRequest] = []

    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage:
        self.requests.append(request)
        return ArtworkImage(
            cache_key=f"device:{request.artwork_id}:1061",
            artwork_id=request.artwork_id,
            format_id=1061,
            width=2,
            height=2,
            rgb888=bytes((10, 20, 30)) * 4,
        )


def test_bridge_publishes_controller_owned_track_and_transport_state() -> None:
    backend = FakePlaybackBackend()
    controller = PlaybackController(backend)
    session = _FakeSystemMediaSession()
    bridge = SystemMediaBridge(controller, session)
    track = Track(
        7,
        "Flamingo",
        "Token",
        "Between Somewhere",
        231_000,
        genre="Alternative",
        track_number=4,
    )

    controller.enqueue(track)

    snapshot = session.published[-1]
    assert snapshot == SystemMediaSnapshot(
        entry_id=1,
        track_id=7,
        title="Flamingo",
        artist="Token",
        album="Between Somewhere",
        genre="Alternative",
        track_number=4,
        duration_ms=231_000,
        position_ms=0,
        playing=True,
        can_play=False,
        can_pause=True,
        can_next=True,
        can_previous=True,
        can_seek=True,
        volume_percent=64,
    )

    controller.pause()
    paused = session.published[-1]
    assert paused is not None
    assert not paused.playing
    assert paused.can_play
    assert not paused.can_pause

    bridge.close()


def test_bridge_routes_host_commands_to_controller_transport_policy() -> None:
    backend = FakePlaybackBackend()
    controller = PlaybackController(backend)
    session = _FakeSystemMediaSession()
    bridge = SystemMediaBridge(controller, session)
    first = Track(1, "First", "Artist", "Album", 180_000)
    second = Track(2, "Second", "Artist", "Album", 180_000)
    controller.enqueue(first)
    controller.enqueue(second)

    session.send(SystemMediaCommand(SystemMediaCommandKind.PAUSE))
    assert not controller.playing
    session.send(SystemMediaCommand(SystemMediaCommandKind.PLAY))
    assert controller.playing
    session.send(SystemMediaCommand(SystemMediaCommandKind.SEEK, 42_000))
    assert controller.position_ms == 42_000
    assert backend.seeks[-1] == 42_000
    assert session.seek_positions[-1] == 42_000
    session.send(
        SystemMediaCommand(SystemMediaCommandKind.SET_VOLUME, volume_percent=38)
    )
    assert controller.volume_percent == 38
    session.send(SystemMediaCommand(SystemMediaCommandKind.NEXT))
    assert controller.current_track == second
    session.send(SystemMediaCommand(SystemMediaCommandKind.PREVIOUS))
    assert controller.current_track == first

    bridge.close()


def test_bridge_loads_artwork_and_ignores_later_lower_resolution_results() -> None:
    loader = _ArtworkLoader()
    artwork_controller = ArtworkController(loader)
    controller = PlaybackController(FakePlaybackBackend())
    session = _FakeSystemMediaSession()
    bridge = SystemMediaBridge(
        controller,
        session,
        artwork_controller=artwork_controller,
    )

    try:
        controller.enqueue(Track(7, "Track", "Artist", "Album", 60_000, artwork_id=64))
        _wait_until(
            lambda: (
                session.published[-1] is not None
                and session.published[-1].artwork is not None
            )
        )

        snapshot = session.published[-1]
        assert snapshot is not None
        assert snapshot.artwork == SystemMediaArtwork(
            cache_key="device:64:1061",
            artwork_id=64,
            width=2,
            height=2,
            rgb888=bytes((10, 20, 30)) * 4,
        )
        assert loader.requests == [ArtworkRequest(64, 512)]

        published_count = len(session.published)
        artwork_controller.artworkReady.emit(
            ArtworkImage(
                cache_key="device:64:small-card",
                artwork_id=64,
                format_id=1061,
                width=1,
                height=1,
                rgb888=bytes((30, 20, 10)),
            )
        )
        APPLICATION.processEvents()

        assert len(session.published) == published_count
        assert session.published[-1] == snapshot
    finally:
        bridge.close()
        artwork_controller.shutdown()


def test_bridge_close_clears_host_state_and_detaches_commands() -> None:
    controller = PlaybackController(FakePlaybackBackend())
    session = _FakeSystemMediaSession()
    bridge = SystemMediaBridge(controller, session)
    controller.enqueue(Track(1, "Track", "Artist", "Album", 60_000))

    bridge.close()
    bridge.close()

    assert session.published[-1] is None
    assert session.handler is None
    assert session.closed


def test_bridge_disables_a_failed_native_session_without_breaking_playback() -> None:
    backend = FakePlaybackBackend()
    controller = PlaybackController(backend)
    session = _FailingSystemMediaSession()
    bridge = SystemMediaBridge(controller, session)

    controller.enqueue(Track(1, "Track", "Artist", "Album", 60_000))

    assert controller.playing
    assert session.closed
    bridge.close()


def test_system_media_commands_validate_their_typed_values() -> None:
    try:
        SystemMediaCommand(SystemMediaCommandKind.SEEK)
    except ValueError as error:
        assert "requires a position" in str(error)
    else:
        raise AssertionError("Expected a missing seek position to be rejected")

    try:
        SystemMediaCommand(SystemMediaCommandKind.PLAY, 1)
    except ValueError as error:
        assert "Only seek and volume" in str(error)
    else:
        raise AssertionError("Expected a play position to be rejected")

    try:
        SystemMediaCommand(SystemMediaCommandKind.SET_VOLUME, volume_percent=101)
    except ValueError as error:
        assert "between 0 and 100" in str(error)
    else:
        raise AssertionError("Expected an out-of-range volume to be rejected")


def _wait_until(predicate: Callable[[], bool], timeout_ms: int = 3000) -> None:
    deadline = monotonic() + timeout_ms / 1000
    while not predicate() and monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(10)
    APPLICATION.processEvents()
    assert predicate(), "Timed out waiting for system-media artwork"
