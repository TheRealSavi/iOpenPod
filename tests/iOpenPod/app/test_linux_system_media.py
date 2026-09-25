"""Tests for the Linux MPRIS system-media adapter."""

import subprocess
import sys
import textwrap
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import QDir, QUrl
from PySide6.QtDBus import QDBusConnection, QDBusMessage
from PySide6.QtTest import QSignalSpy

from iOpenPod.app.playback.system_media import (
    SystemMediaArtwork,
    SystemMediaCommand,
    SystemMediaCommandKind,
    SystemMediaSnapshot,
    factory,
)
from iOpenPod.app.playback.system_media.linux import (
    _PROPERTIES_INTERFACE,  # pyright: ignore[reportPrivateUsage]
    LinuxSystemMediaSession,
    _MprisState,  # pyright: ignore[reportPrivateUsage]
    _QtMprisObject,  # pyright: ignore[reportPrivateUsage]
)


class _FakeTransport:
    def __init__(self) -> None:
        self.handler: Callable[[str, tuple[object, ...]], None] | None = None
        self.published: list[_MprisState | None] = []
        self.seek_positions: list[int] = []
        self.close_count = 0

    def set_command_handler(
        self,
        handler: Callable[[str, tuple[object, ...]], None] | None,
    ) -> None:
        self.handler = handler

    def publish(self, state: _MprisState | None) -> None:
        self.published.append(state)

    def seeked(self, position_us: int) -> None:
        self.seek_positions.append(position_us)

    def close(self) -> None:
        self.close_count += 1

    def send(self, method: str, *arguments: object) -> None:
        if self.handler is None:
            raise AssertionError("The fake MPRIS transport has no command handler")
        self.handler(method, arguments)


class _FakeConnection:
    def __init__(self) -> None:
        self.messages: list[QDBusMessage] = []

    def send(self, message: QDBusMessage) -> bool:
        self.messages.append(message)
        return True


class _FakeElapsedClock:
    def __init__(self) -> None:
        self.valid = False
        self.elapsed_ns = 0

    def start(self) -> None:
        self.valid = True
        self.elapsed_ns = 0

    def invalidate(self) -> None:
        self.valid = False

    def isValid(self) -> bool:
        return self.valid

    def nsecsElapsed(self) -> int:
        return self.elapsed_ns


def _snapshot(
    *,
    playing: bool = True,
    position_ms: int = 42_500,
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
        position_ms=position_ms,
        playing=playing,
        can_play=not playing,
        can_pause=playing,
        can_next=True,
        can_previous=True,
        can_seek=True,
        volume_percent=64,
        artwork=artwork,
    )


def test_linux_session_publishes_mpris_metadata_timeline_and_capabilities() -> None:
    transport = _FakeTransport()
    session = LinuxSystemMediaSession(transport)

    session.publish(_snapshot())

    state = transport.published[-1]
    assert state == _MprisState(
        track_path="/org/mpris/MediaPlayer2/Track/entry_12",
        playback_status="Playing",
        metadata={
            "mpris:trackid": "/org/mpris/MediaPlayer2/Track/entry_12",
            "mpris:length": 231_000_000,
            "xesam:title": "Flamingo",
            "xesam:artist": ["Token"],
            "xesam:album": "Between Somewhere",
            "xesam:genre": ["Alternative"],
            "xesam:trackNumber": 4,
        },
        duration_us=231_000_000,
        position_us=42_500_000,
        volume=0.64,
        can_play=True,
        can_pause=True,
        can_next=True,
        can_previous=True,
        can_seek=True,
    )


def test_linux_session_routes_mpris_transport_seek_and_volume_commands() -> None:
    transport = _FakeTransport()
    session = LinuxSystemMediaSession(transport)
    received: list[SystemMediaCommand] = []
    session.set_command_handler(received.append)
    session.publish(_snapshot(position_ms=5_000))

    for method, kind in (
        ("Pause", SystemMediaCommandKind.PAUSE),
        ("Next", SystemMediaCommandKind.NEXT),
        ("Previous", SystemMediaCommandKind.PREVIOUS),
    ):
        transport.send(method)
        assert received[-1] == SystemMediaCommand(kind)

    transport.send("Seek", 10_250_000)
    transport.send(
        "SetPosition",
        "/org/mpris/MediaPlayer2/Track/entry_12",
        42_125_000,
    )
    transport.send("SetVolume", 0.375)
    assert received[-3:] == [
        SystemMediaCommand(SystemMediaCommandKind.SEEK, 15_250),
        SystemMediaCommand(SystemMediaCommandKind.SEEK, 42_125),
        SystemMediaCommand(SystemMediaCommandKind.SET_VOLUME, volume_percent=38),
    ]

    before = len(received)
    transport.send(
        "SetPosition",
        "/org/mpris/MediaPlayer2/Track/entry_99",
        1_000_000,
    )
    assert len(received) == before


def test_linux_session_bounds_relative_seek_and_maps_stop_to_pause() -> None:
    transport = _FakeTransport()
    session = LinuxSystemMediaSession(transport)
    received: list[SystemMediaCommand] = []
    session.set_command_handler(received.append)
    session.publish(_snapshot(position_ms=230_000))

    transport.send("Seek", 10_000_000)
    transport.send("Stop")

    assert received == [
        SystemMediaCommand(SystemMediaCommandKind.SEEK, 231_000),
        SystemMediaCommand(SystemMediaCommandKind.PAUSE),
    ]


def test_linux_session_encodes_and_reuses_bounded_artwork_as_a_file_url() -> None:
    transport = _FakeTransport()
    session = LinuxSystemMediaSession(transport)
    artwork = SystemMediaArtwork(
        cache_key="device:64:1061",
        artwork_id=64,
        width=1,
        height=1,
        rgb888=bytes((10, 20, 30)),
    )

    session.publish(_snapshot(artwork=artwork))
    first = transport.published[-1]
    session.publish(_snapshot(playing=False, artwork=artwork))
    second = transport.published[-1]

    assert first is not None and second is not None
    first_url = first.metadata["mpris:artUrl"]
    assert isinstance(first_url, str)
    assert first_url.startswith("file:")
    assert second.metadata["mpris:artUrl"] == first_url
    artwork_path = Path(QUrl(first_url).toLocalFile())
    assert artwork_path.is_absolute()
    assert artwork_path.resolve().is_relative_to(Path(QDir.tempPath()).resolve())
    assert artwork_path.is_file()

    session.close()
    assert not artwork_path.exists()


def test_linux_session_forwards_seeked_and_closes_idempotently() -> None:
    transport = _FakeTransport()
    session = LinuxSystemMediaSession(transport)
    session.publish(_snapshot())

    session.seeked(42_125)
    session.close()
    session.close()

    assert transport.seek_positions == [42_125_000]
    assert transport.published[-1] is None
    assert transport.handler is None
    assert transport.close_count == 1


def test_linux_factory_selects_adapter_and_falls_back_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iOpenPod.app.playback.system_media import linux

    transport = _FakeTransport()
    monkeypatch.setattr(
        linux,
        "LinuxSystemMediaSession",
        lambda: LinuxSystemMediaSession(transport),
    )
    session = factory.create_system_media_session(platform_name="linux")
    assert isinstance(session, LinuxSystemMediaSession)
    session.close()

    def fail() -> LinuxSystemMediaSession:
        raise RuntimeError("session bus unavailable")

    monkeypatch.setattr(linux, "LinuxSystemMediaSession", fail)
    unavailable = factory.create_system_media_session(platform_name="linux")
    assert unavailable.__class__.__name__ == "NullSystemMediaSession"


def test_linux_session_does_not_route_disabled_commands() -> None:
    transport = _FakeTransport()
    session = LinuxSystemMediaSession(transport)
    received: list[SystemMediaCommand] = []
    session.set_command_handler(received.append)
    session.publish(
        replace(
            _snapshot(playing=False),
            can_play=False,
            can_next=False,
            can_previous=False,
            can_seek=False,
        )
    )

    transport.send("Play")
    transport.send("Next")
    transport.send("Previous")
    transport.send("Seek", 10_000_000)

    assert received == []


def test_qt_mpris_object_emits_properties_and_seek_signals() -> None:
    connection = _FakeConnection()
    native = _QtMprisObject(cast("QDBusConnection", connection))
    seeked = QSignalSpy(native.player_adaptor.Seeked)
    state = _MprisState(
        track_path="/org/mpris/MediaPlayer2/Track/entry_12",
        playback_status="Playing",
        metadata={"mpris:trackid": "/org/mpris/MediaPlayer2/Track/entry_12"},
        duration_us=231_000_000,
        position_us=1_000_000,
        volume=0.64,
        can_play=False,
        can_pause=True,
        can_next=True,
        can_previous=True,
        can_seek=True,
    )

    native.publish(state)
    assert connection.messages[-1].interface() == _PROPERTIES_INTERFACE
    assert connection.messages[-1].member() == "PropertiesChanged"

    connection.messages.clear()
    native.publish(replace(state, position_us=2_000_000))
    assert connection.messages == []

    native.seeked(2_000_000)
    assert seeked.count() == 1
    assert seeked.at(0) == [2_000_000]


def test_qt_mpris_position_advances_while_playing_and_freezes_while_paused() -> None:
    connection = _FakeConnection()
    clock = _FakeElapsedClock()
    native = _QtMprisObject(
        cast("QDBusConnection", connection),
        elapsed_clock=clock,
    )
    state = _MprisState(
        track_path="/org/mpris/MediaPlayer2/Track/entry_12",
        playback_status="Playing",
        metadata={"mpris:trackid": "/org/mpris/MediaPlayer2/Track/entry_12"},
        duration_us=10_000_000,
        position_us=1_000_000,
        volume=0.64,
        can_play=True,
        can_pause=True,
        can_next=True,
        can_previous=True,
        can_seek=True,
    )

    native.publish(state)
    clock.elapsed_ns = 2_500_000_000
    assert native.player_properties()["Position"] == 3_500_000

    native.publish(replace(state, playback_status="Paused", position_us=4_000_000))
    clock.elapsed_ns = 5_000_000_000
    assert native.player_properties()["Position"] == 4_000_000

    native.publish(replace(state, position_us=9_000_000))
    clock.elapsed_ns = 5_000_000_000
    assert native.player_properties()["Position"] == 10_000_000


def test_qt_mpris_arguments_can_be_marshaled_without_native_abort() -> None:
    probe = textwrap.dedent(
        """
        from iOpenPod.app.playback.system_media.linux import (
            _metadata_map,
            _string_list,
            _variant_map,
        )

        metadata = _metadata_map(
            {
                "mpris:trackid": "/org/mpris/MediaPlayer2/Track/entry_12",
                "mpris:length": 231_000_000,
                "xesam:artist": ["Token"],
            }
        )
        _variant_map({"Metadata": metadata, "CanPlay": True})
        _string_list(("file",))
        """
    )

    completed = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", probe],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "QDBusMarshaller" not in completed.stderr


def test_qt_mpris_object_routes_methods_and_writable_volume_property() -> None:
    connection = _FakeConnection()
    native = _QtMprisObject(cast("QDBusConnection", connection))
    received: list[tuple[str, tuple[object, ...]]] = []
    native.set_command_handler(
        lambda method, arguments: received.append((method, arguments))
    )

    native.player_adaptor.Seek(1_500_000)
    native.player_adaptor.Volume = 0.25  # type: ignore[assignment]

    assert received == [
        ("Seek", (1_500_000,)),
        ("SetVolume", (0.25,)),
    ]


def test_qt_mpris_adaptor_declares_exact_property_and_method_types() -> None:
    connection = _FakeConnection()
    native = _QtMprisObject(cast("QDBusConnection", connection))
    meta = native.player_adaptor.metaObject()

    position = meta.property(meta.indexOfProperty("Position"))
    metadata = meta.property(meta.indexOfProperty("Metadata"))
    seek = meta.method(meta.indexOfMethod("Seek(qlonglong)"))
    set_position = meta.method(
        meta.indexOfMethod("SetPosition(QDBusObjectPath,qlonglong)")
    )

    assert cast("str", position.typeName()) == "qlonglong"
    assert cast("str", metadata.typeName()) == "QVariantMap"
    assert seek.methodSignature().data() == b"Seek(qlonglong)"
    assert set_position.methodSignature().data() == (
        b"SetPosition(QDBusObjectPath,qlonglong)"
    )


def test_qt_mpris_introspection_exposes_both_required_interfaces() -> None:
    connection = _FakeConnection()
    native = _QtMprisObject(cast("QDBusConnection", connection))
    root_meta = native.root_adaptor.metaObject()
    player_meta = native.player_adaptor.metaObject()

    root_info = root_meta.classInfo(root_meta.indexOfClassInfo("D-Bus Interface"))
    player_info = player_meta.classInfo(player_meta.indexOfClassInfo("D-Bus Interface"))

    assert cast("str", root_info.value()) == "org.mpris.MediaPlayer2"
    assert cast("str", player_info.value()) == "org.mpris.MediaPlayer2.Player"
