"""Linux MPRIS integration through Qt's D-Bus event-loop support."""

from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol, cast

from PySide6.QtCore import (
    ClassInfo,
    Property,
    QDir,
    QElapsedTimer,
    QFile,
    QIODevice,
    QMetaType,
    QObject,
    QSaveFile,
    QTemporaryDir,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtDBus import (
    QDBusAbstractAdaptor,
    QDBusArgument,
    QDBusConnection,
    QDBusMessage,
    QDBusObjectPath,
    QDBusVariant,
)

from iOpenPod.app.playback.system_media.session import (
    SystemMediaArtwork,
    SystemMediaCommand,
    SystemMediaCommandHandler,
    SystemMediaCommandKind,
    SystemMediaSnapshot,
)

logger = logging.getLogger(__name__)

_STRING_META_TYPE = QMetaType(QMetaType.Type.QString)
_DBUS_VARIANT_META_TYPE = QMetaType.fromName(b"QDBusVariant")
_BUS_NAME = "org.mpris.MediaPlayer2.iOpenPod"
_OBJECT_PATH = "/org/mpris/MediaPlayer2"
_ROOT_INTERFACE = "org.mpris.MediaPlayer2"
_PLAYER_INTERFACE = "org.mpris.MediaPlayer2.Player"
_PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"


@dataclass(frozen=True, slots=True)
class _MprisState:
    """MPRIS-shaped state kept independent of Qt's D-Bus value wrappers."""

    track_path: str
    playback_status: str
    metadata: Mapping[str, object]
    duration_us: int
    position_us: int
    volume: float
    can_play: bool
    can_pause: bool
    can_next: bool
    can_previous: bool
    can_seek: bool


_NativeCommandHandler = Callable[[str, tuple[object, ...]], None]


class _ElapsedClock(Protocol):
    """Monotonic elapsed clock used to project a live MPRIS position."""

    def start(self) -> None: ...

    def invalidate(self) -> None: ...

    def isValid(self) -> bool: ...

    def nsecsElapsed(self) -> int: ...


class _MprisTransport(Protocol):
    """Injectable D-Bus transport used by the platform-neutral adapter tests."""

    def set_command_handler(
        self,
        handler: _NativeCommandHandler | None,
    ) -> None: ...

    def publish(self, state: _MprisState | None) -> None: ...

    def seeked(self, position_us: int) -> None: ...

    def close(self) -> None: ...


class LinuxSystemMediaSession:
    """Publish controller snapshots through the desktop's MPRIS 2 session."""

    def __init__(self, transport: _MprisTransport | None = None) -> None:
        self._artwork_cache = _MprisArtworkCache()
        try:
            self._transport = transport or _QtMprisTransport()
        except Exception:
            self._artwork_cache.close()
            raise
        self._handler: SystemMediaCommandHandler | None = None
        self._latest_snapshot: SystemMediaSnapshot | None = None
        self._closed = False
        try:
            self._transport.set_command_handler(self._native_command)
            self.publish(None)
        except Exception:
            self._closed = True
            try:
                self._transport.set_command_handler(None)
            finally:
                try:
                    self._transport.close()
                finally:
                    self._artwork_cache.close()
            raise

    def set_command_handler(
        self,
        handler: SystemMediaCommandHandler | None,
    ) -> None:
        self._handler = handler

    def publish(self, snapshot: SystemMediaSnapshot | None) -> None:
        if self._closed:
            return
        self._latest_snapshot = snapshot
        if snapshot is None:
            self._artwork_cache.clear()
            self._transport.publish(None)
            return
        self._transport.publish(self._state_for(snapshot))

    def seeked(self, position_ms: int) -> None:
        if not self._closed:
            self._transport.seeked(max(0, position_ms) * 1_000)

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.publish(None)
        except Exception:
            logger.warning("Could not clear Linux MPRIS state", exc_info=True)
        finally:
            self._closed = True
            self._handler = None
            try:
                self._transport.set_command_handler(None)
            finally:
                try:
                    self._transport.close()
                finally:
                    self._artwork_cache.close()

    def _state_for(self, snapshot: SystemMediaSnapshot) -> _MprisState:
        track_path = _track_path(snapshot.entry_id)
        metadata: dict[str, object] = {
            "mpris:trackid": track_path,
            # Linux Now Playing clients use the advertised duration together with
            # Position and CanSeek to decide whether to expose a scrubber.
            "mpris:length": max(0, snapshot.duration_ms) * 1_000,
            "xesam:title": snapshot.title,
            "xesam:artist": [snapshot.artist] if snapshot.artist else [],
            "xesam:album": snapshot.album,
        }
        if snapshot.genre:
            metadata["xesam:genre"] = [snapshot.genre]
        if snapshot.track_number > 0:
            metadata["xesam:trackNumber"] = snapshot.track_number
        artwork_url = self._art_url_for(snapshot.artwork)
        if artwork_url is not None:
            metadata["mpris:artUrl"] = artwork_url
        return _MprisState(
            track_path=track_path,
            playback_status="Playing" if snapshot.playing else "Paused",
            metadata=metadata,
            duration_us=max(0, snapshot.duration_ms) * 1_000,
            position_us=min(
                max(0, snapshot.position_ms),
                max(0, snapshot.duration_ms),
            )
            * 1_000,
            volume=snapshot.volume_percent / 100,
            # MPRIS CanPlay is a player capability, not an enabled-state mirror.
            # Keep it true during active playback so Host clients retain the player.
            can_play=snapshot.can_play or snapshot.playing,
            can_pause=snapshot.can_pause,
            can_next=snapshot.can_next,
            can_previous=snapshot.can_previous,
            can_seek=snapshot.can_seek,
        )

    def _art_url_for(self, artwork: SystemMediaArtwork | None) -> str | None:
        return self._artwork_cache.url_for(artwork)

    def _native_command(self, method: str, arguments: tuple[object, ...]) -> None:
        if self._closed:
            return
        snapshot = self._latest_snapshot
        command: SystemMediaCommand | None = None
        if method == "Play" and snapshot is not None and snapshot.can_play:
            command = SystemMediaCommand(SystemMediaCommandKind.PLAY)
        elif method == "Pause" and snapshot is not None and snapshot.can_pause:
            command = SystemMediaCommand(SystemMediaCommandKind.PAUSE)
        elif method == "PlayPause" and snapshot is not None:
            command = SystemMediaCommand(SystemMediaCommandKind.TOGGLE_PLAY_PAUSE)
        elif method == "Stop" and snapshot is not None and snapshot.playing:
            # PlaybackController deliberately models current-item pause rather than
            # a separate stopped state, which is the closest supported MPRIS intent.
            command = SystemMediaCommand(SystemMediaCommandKind.PAUSE)
        elif method == "Next" and snapshot is not None and snapshot.can_next:
            command = SystemMediaCommand(SystemMediaCommandKind.NEXT)
        elif method == "Previous" and snapshot is not None and snapshot.can_previous:
            command = SystemMediaCommand(SystemMediaCommandKind.PREVIOUS)
        elif (
            method == "Seek"
            and snapshot is not None
            and snapshot.can_seek
            and len(arguments) == 1
        ):
            offset_us = _integer(arguments[0])
            if offset_us is not None:
                position_ms = min(
                    max(0, snapshot.position_ms + round(offset_us / 1_000)),
                    max(0, snapshot.duration_ms),
                )
                command = SystemMediaCommand(
                    SystemMediaCommandKind.SEEK,
                    position_ms,
                )
        elif (
            method == "SetPosition"
            and snapshot is not None
            and snapshot.can_seek
            and len(arguments) == 2
            and _object_path(arguments[0]) == _track_path(snapshot.entry_id)
        ):
            position_us = _integer(arguments[1])
            if position_us is not None:
                position_ms = min(
                    max(0, round(position_us / 1_000)),
                    max(0, snapshot.duration_ms),
                )
                command = SystemMediaCommand(
                    SystemMediaCommandKind.SEEK,
                    position_ms,
                )
        elif method == "SetVolume" and len(arguments) == 1:
            volume = _number(arguments[0])
            if volume is not None:
                command = SystemMediaCommand(
                    SystemMediaCommandKind.SET_VOLUME,
                    volume_percent=min(100, max(0, round(volume * 100))),
                )
        handler = self._handler
        if command is None or handler is None:
            return
        try:
            handler(command)
        except Exception:
            logger.warning(
                "Could not handle Linux MPRIS command %s",
                method,
                exc_info=True,
            )


class _QtMprisTransport:
    """Own the MPRIS well-known name and typed adaptors on Qt's session bus."""

    def __init__(self) -> None:
        self._connection = QDBusConnection.sessionBus()
        if not self._connection.isConnected():
            raise RuntimeError("The desktop D-Bus session bus is unavailable")
        self._object = _QtMprisObject(self._connection)
        self._closed = False
        if not self._connection.registerService(_BUS_NAME):
            raise RuntimeError(f"Could not register MPRIS service {_BUS_NAME}")
        if not self._connection.registerObject(
            _OBJECT_PATH,
            self._object,
            QDBusConnection.RegisterOption.ExportAdaptors,
        ):
            self._connection.unregisterService(_BUS_NAME)
            raise RuntimeError(f"Could not register MPRIS object {_OBJECT_PATH}")

    def set_command_handler(
        self,
        handler: _NativeCommandHandler | None,
    ) -> None:
        self._object.set_command_handler(handler)

    def publish(self, state: _MprisState | None) -> None:
        self._object.publish(state)

    def seeked(self, position_us: int) -> None:
        self._object.seeked(position_us)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._object.set_command_handler(None)
        self._connection.unregisterObject(_OBJECT_PATH)
        self._connection.unregisterService(_BUS_NAME)


class _MprisArtworkCache:
    """Keep at most one PNG available for MPRIS clients through a file URL."""

    def __init__(self) -> None:
        template = QDir(QDir.tempPath()).filePath("iopenpod-mpris-XXXXXX")
        self._directory = QTemporaryDir(template)
        if not self._directory.isValid():
            logger.warning(
                "Could not create the MPRIS artwork directory: %s",
                self._directory.errorString(),
            )
        self._cache_key: str | None = None
        self._path: str | None = None
        self._url: str | None = None

    def url_for(self, artwork: SystemMediaArtwork | None) -> str | None:
        if artwork is None:
            self.clear()
            return None
        if artwork.cache_key == self._cache_key:
            return self._url
        self._cache_key = artwork.cache_key
        if not self._directory.isValid():
            return None
        old_path = self._path
        self._path = None
        self._url = None
        try:
            from PIL import Image

            encoded = BytesIO()
            Image.frombytes(
                "RGB",
                (artwork.width, artwork.height),
                artwork.rgb888,
            ).save(encoded, format="PNG")
            digest = hashlib.sha256(artwork.cache_key.encode("utf-8")).hexdigest()[:16]
            path = self._directory.filePath(f"artwork-{digest}.png")
            output = QSaveFile(path)
            if not output.open(QIODevice.OpenModeFlag.WriteOnly):
                raise OSError(output.errorString())
            payload = encoded.getvalue()
            if output.write(payload) != len(payload) or not output.commit():
                output.cancelWriting()
                raise OSError(output.errorString())
            self._path = path
            self._url = QUrl.fromLocalFile(path).toString()
        except Exception:
            logger.warning(
                "Could not convert album artwork for Linux MPRIS",
                exc_info=True,
            )
        if old_path is not None and old_path != self._path:
            QFile.remove(old_path)
        return self._url

    def clear(self) -> None:
        path = self._path
        self._cache_key = None
        self._path = None
        self._url = None
        if path is not None:
            QFile.remove(path)

    def close(self) -> None:
        self.clear()
        self._directory.remove()


class _QtMprisObject(QObject):
    """Own typed root/player adaptors and their shared MPRIS state."""

    def __init__(
        self,
        connection: QDBusConnection,
        elapsed_clock: _ElapsedClock | None = None,
    ) -> None:
        super().__init__()
        self._connection = connection
        self._handler: _NativeCommandHandler | None = None
        self._state: _MprisState | None = None
        self._position_clock = elapsed_clock or QElapsedTimer()
        self.root_adaptor = _QtMprisRootAdaptor(self)
        self.player_adaptor = _QtMprisPlayerAdaptor(self)

    def set_command_handler(
        self,
        handler: _NativeCommandHandler | None,
    ) -> None:
        self._handler = handler

    def publish(self, state: _MprisState | None) -> None:
        before = self.player_properties()
        self._state = state
        if state is not None and state.playback_status == "Playing":
            self._position_clock.start()
        else:
            self._position_clock.invalidate()
        after = self.player_properties()
        changed = {
            name: value
            for name, value in after.items()
            if name != "Position" and before.get(name) != value
        }
        if changed:
            self._properties_changed(_PLAYER_INTERFACE, changed)

    def seeked(self, position_us: int) -> None:
        self.player_adaptor.Seeked.emit(max(0, position_us))

    def emit_command(self, method: str, arguments: tuple[object, ...]) -> None:
        handler = self._handler
        if handler is not None:
            handler(method, arguments)

    def player_properties(self) -> dict[str, object]:
        state = self._state
        return {
            "PlaybackStatus": "Stopped" if state is None else state.playback_status,
            "LoopStatus": "None",
            "Rate": 1.0,
            "Shuffle": False,
            "Metadata": {} if state is None else dict(state.metadata),
            "Volume": 1.0 if state is None else state.volume,
            "Position": self._current_position_us(),
            "MinimumRate": 1.0,
            "MaximumRate": 1.0,
            "CanGoNext": state is not None and state.can_next,
            "CanGoPrevious": state is not None and state.can_previous,
            "CanPlay": state is not None and state.can_play,
            "CanPause": state is not None and state.can_pause,
            "CanSeek": state is not None and state.can_seek,
            "CanControl": True,
        }

    def _current_position_us(self) -> int:
        state = self._state
        if state is None:
            return 0
        elapsed_us = 0
        if state.playback_status == "Playing" and self._position_clock.isValid():
            elapsed_us = max(0, self._position_clock.nsecsElapsed() // 1_000)
        return min(
            max(0, state.position_us) + elapsed_us,
            max(0, state.duration_us),
        )

    def _properties_changed(
        self,
        interface: str,
        changed: Mapping[str, object],
    ) -> None:
        signal = QDBusMessage.createSignal(
            _OBJECT_PATH,
            _PROPERTIES_INTERFACE,
            "PropertiesChanged",
        )
        signal.setArguments([interface, _variant_map(changed), _string_list(())])
        if not self._connection.send(signal):
            raise RuntimeError("Could not send MPRIS PropertiesChanged")


@ClassInfo(**{"D-Bus Interface": _ROOT_INTERFACE})  # type: ignore[arg-type]
class _QtMprisRootAdaptor(QDBusAbstractAdaptor):  # type: ignore[operator]
    """Export the MPRIS root interface with Qt-owned property replies."""

    def __init__(self, owner: _QtMprisObject) -> None:
        super().__init__(owner)

    CanQuit = Property(bool, lambda _self: False)
    Fullscreen = Property(bool, lambda _self: False)
    CanSetFullscreen = Property(bool, lambda _self: False)
    CanRaise = Property(bool, lambda _self: False)
    HasTrackList = Property(bool, lambda _self: False)
    Identity = Property(str, lambda _self: "iOpenPod")
    SupportedUriSchemes = Property(
        "QStringList",  # type: ignore[arg-type]
        lambda _self: [],
    )
    SupportedMimeTypes = Property(
        "QStringList",  # type: ignore[arg-type]
        lambda _self: [],
    )

    @Slot()
    def Raise(self) -> None:
        """MPRIS Raise is unavailable because CanRaise is false."""

    @Slot()
    def Quit(self) -> None:
        """MPRIS Quit is unavailable because CanQuit is false."""


@ClassInfo(**{"D-Bus Interface": _PLAYER_INTERFACE})  # type: ignore[arg-type]
class _QtMprisPlayerAdaptor(QDBusAbstractAdaptor):  # type: ignore[operator]
    """Export typed MPRIS player properties, commands, and signals."""

    Seeked = Signal("qlonglong")  # type: ignore[arg-type]

    def __init__(self, owner: _QtMprisObject) -> None:
        super().__init__(owner)
        self._owner = owner

    PlaybackStatus = Property(
        str,
        lambda self: cast("str", self._owner.player_properties()["PlaybackStatus"]),
    )
    LoopStatus = Property(str, lambda _self: "None")
    Rate = Property(float, lambda _self: 1.0)
    Shuffle = Property(bool, lambda _self: False)
    Metadata = Property(
        "QVariantMap",  # type: ignore[arg-type]
        lambda self: _qt_property_metadata(
            cast(
                "Mapping[str, object]",
                self._owner.player_properties()["Metadata"],
            )
        ),
    )
    Volume = Property(
        float,
        lambda self: cast("float", self._owner.player_properties()["Volume"]),
        lambda self, value: self._owner.emit_command("SetVolume", (value,)),
    )
    Position = Property(
        "qlonglong",  # type: ignore[arg-type]
        lambda self: cast("int", self._owner.player_properties()["Position"]),
    )
    MinimumRate = Property(float, lambda _self: 1.0)
    MaximumRate = Property(float, lambda _self: 1.0)
    CanGoNext = Property(
        bool,
        lambda self: cast("bool", self._owner.player_properties()["CanGoNext"]),
    )
    CanGoPrevious = Property(
        bool,
        lambda self: cast("bool", self._owner.player_properties()["CanGoPrevious"]),
    )
    CanPlay = Property(
        bool,
        lambda self: cast("bool", self._owner.player_properties()["CanPlay"]),
    )
    CanPause = Property(
        bool,
        lambda self: cast("bool", self._owner.player_properties()["CanPause"]),
    )
    CanSeek = Property(
        bool,
        lambda self: cast("bool", self._owner.player_properties()["CanSeek"]),
    )
    CanControl = Property(bool, lambda _self: True)

    @Slot()
    def Next(self) -> None:
        self._owner.emit_command("Next", ())

    @Slot()
    def Previous(self) -> None:
        self._owner.emit_command("Previous", ())

    @Slot()
    def Pause(self) -> None:
        self._owner.emit_command("Pause", ())

    @Slot()
    def PlayPause(self) -> None:
        self._owner.emit_command("PlayPause", ())

    @Slot()
    def Stop(self) -> None:
        self._owner.emit_command("Stop", ())

    @Slot()
    def Play(self) -> None:
        self._owner.emit_command("Play", ())

    @Slot("qlonglong")
    def Seek(self, offset_us: int) -> None:
        self._owner.emit_command("Seek", (offset_us,))

    @Slot(QDBusObjectPath, "qlonglong")
    def SetPosition(self, track_path: QDBusObjectPath, position_us: int) -> None:
        self._owner.emit_command("SetPosition", (track_path, position_us))

    @Slot(str)
    def OpenUri(self, _uri: str) -> None:
        """URI opening is unavailable because no URI schemes are advertised."""


def _variant_map(values: Mapping[str, object]) -> QDBusArgument:
    argument = QDBusArgument()
    argument.beginMap(_STRING_META_TYPE, _DBUS_VARIANT_META_TYPE)
    for name, value in values.items():
        argument.beginMapEntry()
        argument.appendVariant(name)
        argument.appendVariant(QDBusVariant(_dbus_value(name, value)))
        argument.endMapEntry()
    argument.endMap()
    return argument


def _dbus_value(name: str, value: object) -> object:
    if name == "Metadata" and isinstance(value, Mapping):
        return _metadata_map(cast("Mapping[object, object]", value))
    if name in {"SupportedUriSchemes", "SupportedMimeTypes"}:
        return _string_list(cast("list[str]", value))
    return value


def _metadata_value(name: str, value: object) -> object:
    if name == "mpris:trackid":
        return QDBusObjectPath(str(value))
    if name in {"xesam:artist", "xesam:genre"}:
        return _string_list(cast("list[str]", value))
    return value


def _qt_property_metadata(values: Mapping[str, object]) -> dict[str, object]:
    """Preserve D-Bus-only value types in Qt's exported QVariantMap."""
    return {
        name: QDBusObjectPath(str(value)) if name == "mpris:trackid" else value
        for name, value in values.items()
    }


def _metadata_map(values: Mapping[object, object]) -> QDBusArgument:
    normalized = {str(name): value for name, value in values.items()}
    argument = QDBusArgument()
    argument.beginMap(_STRING_META_TYPE, _DBUS_VARIANT_META_TYPE)
    for name, value in normalized.items():
        argument.beginMapEntry()
        argument.appendVariant(name)
        argument.appendVariant(QDBusVariant(_metadata_value(name, value)))
        argument.endMapEntry()
    argument.endMap()
    return argument


def _string_list(values: tuple[str, ...] | list[str]) -> QDBusArgument:
    argument = QDBusArgument()
    argument.beginArray(QMetaType.Type.QString)
    for value in values:
        argument.appendVariant(value)
    argument.endArray()
    return argument


def _track_path(entry_id: int) -> str:
    return f"{_OBJECT_PATH}/Track/entry_{max(0, entry_id)}"


def _object_path(value: object) -> str | None:
    if isinstance(value, QDBusObjectPath):
        return value.path()
    if isinstance(value, str):
        return value
    return None


def _unwrap_variant(value: object) -> object:
    return value.variant() if isinstance(value, QDBusVariant) else value


def _integer(value: object) -> int | None:
    value = _unwrap_variant(value)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _number(value: object) -> float | None:
    value = _unwrap_variant(value)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None


__all__ = ["LinuxSystemMediaSession"]
