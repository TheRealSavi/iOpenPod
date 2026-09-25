"""macOS Now Playing and remote-command integration through MediaPlayer."""

import logging
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from io import BytesIO
from types import ModuleType
from typing import Protocol, cast

from PIL import Image

from iOpenPod.app.playback.system_media.session import (
    SystemMediaArtwork,
    SystemMediaCommand,
    SystemMediaCommandHandler,
    SystemMediaCommandKind,
    SystemMediaSnapshot,
)

logger = logging.getLogger(__name__)


class _NowPlayingInfoCenter(Protocol):
    def setNowPlayingInfo_(self, value: dict[str, object] | None) -> None: ...

    def setPlaybackState_(self, value: int) -> None: ...


class _NowPlayingInfoCenterClass(Protocol):
    @staticmethod
    def defaultCenter() -> _NowPlayingInfoCenter: ...


class _RemoteCommand(Protocol):
    def addTargetWithHandler_(
        self,
        handler: Callable[[object], int],
    ) -> object: ...

    def removeTarget_(self, target: object) -> None: ...

    def setEnabled_(self, enabled: bool) -> None: ...


class _RemoteCommandCenter(Protocol):
    def playCommand(self) -> _RemoteCommand: ...

    def pauseCommand(self) -> _RemoteCommand: ...

    def togglePlayPauseCommand(self) -> _RemoteCommand: ...

    def nextTrackCommand(self) -> _RemoteCommand: ...

    def previousTrackCommand(self) -> _RemoteCommand: ...

    def changePlaybackPositionCommand(self) -> _RemoteCommand: ...


class _RemoteCommandCenterClass(Protocol):
    @staticmethod
    def sharedCommandCenter() -> _RemoteCommandCenter: ...


class _PlaybackPositionEvent(Protocol):
    def positionTime(self) -> float: ...


class _NSImage(Protocol):
    pass


class _NSImageAllocation(Protocol):
    def initWithData_(self, data: bytes) -> _NSImage | None: ...


class _NSImageClass(Protocol):
    @staticmethod
    def alloc() -> _NSImageAllocation: ...


class _MediaItemArtworkAllocation(Protocol):
    def initWithImage_(self, image: _NSImage) -> object | None: ...


class _MediaItemArtworkClass(Protocol):
    @staticmethod
    def alloc() -> _MediaItemArtworkAllocation: ...


@dataclass(frozen=True, slots=True)
class _MacOSBindings:
    info_center: _NowPlayingInfoCenter
    commands: Mapping[SystemMediaCommandKind, _RemoteCommand]
    title_key: str
    artist_key: str
    album_key: str
    genre_key: str
    track_number_key: str
    duration_key: str
    persistent_id_key: str
    elapsed_key: str
    playback_rate_key: str
    default_rate_key: str
    external_id_key: str
    exclude_suggestions_key: str | None
    artwork_key: str
    make_artwork: Callable[[SystemMediaArtwork], object]
    state_playing: int
    state_paused: int
    state_stopped: int
    status_success: int
    status_no_item: int
    status_failed: int


class MacOSSystemMediaSession:
    """Publish PlaybackController state to the macOS system media surfaces."""

    def __init__(self, bindings: _MacOSBindings | None = None) -> None:
        self._bindings = bindings or _load_bindings()
        self._handler: SystemMediaCommandHandler | None = None
        self._targets: list[tuple[_RemoteCommand, object]] = []
        self._artwork_cache_key: str | None = None
        self._native_artwork: object | None = None
        self._closed = False
        try:
            self._register_commands()
            self.publish(None)
        except Exception:
            self._closed = True
            self._remove_targets()
            raise

    def set_command_handler(
        self,
        handler: SystemMediaCommandHandler | None,
    ) -> None:
        self._handler = handler

    def publish(self, snapshot: SystemMediaSnapshot | None) -> None:
        if self._closed:
            return
        bindings = self._bindings
        if snapshot is None:
            bindings.info_center.setNowPlayingInfo_(None)
            bindings.info_center.setPlaybackState_(bindings.state_stopped)
            self._set_command_capabilities(None)
            self._artwork_cache_key = None
            self._native_artwork = None
            return

        info: dict[str, object] = {
            bindings.title_key: snapshot.title,
            bindings.artist_key: snapshot.artist,
            bindings.album_key: snapshot.album,
            bindings.duration_key: snapshot.duration_ms / 1_000,
            bindings.elapsed_key: snapshot.position_ms / 1_000,
            bindings.playback_rate_key: 1.0 if snapshot.playing else 0.0,
            bindings.default_rate_key: 1.0,
            bindings.external_id_key: f"iopenpod:entry:{snapshot.entry_id}",
            bindings.persistent_id_key: snapshot.track_id,
        }
        if snapshot.genre:
            info[bindings.genre_key] = snapshot.genre
        if snapshot.track_number > 0:
            info[bindings.track_number_key] = snapshot.track_number
        if bindings.exclude_suggestions_key is not None:
            info[bindings.exclude_suggestions_key] = True
        native_artwork = self._native_artwork_for(snapshot.artwork)
        if native_artwork is not None:
            info[bindings.artwork_key] = native_artwork

        bindings.info_center.setNowPlayingInfo_(info)
        bindings.info_center.setPlaybackState_(
            bindings.state_playing if snapshot.playing else bindings.state_paused
        )
        self._set_command_capabilities(snapshot)

    def seeked(self, position_ms: int) -> None:
        del position_ms

    def _native_artwork_for(self, artwork: SystemMediaArtwork | None) -> object | None:
        if artwork is None:
            self._artwork_cache_key = None
            self._native_artwork = None
            return None
        if artwork.cache_key == self._artwork_cache_key:
            return self._native_artwork
        self._artwork_cache_key = artwork.cache_key
        try:
            self._native_artwork = self._bindings.make_artwork(artwork)
        except Exception:
            self._native_artwork = None
            logger.warning(
                "Could not convert album artwork for macOS Now Playing",
                exc_info=True,
            )
        return self._native_artwork

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.publish(None)
        except Exception:
            logger.warning(
                "Could not clear macOS Now Playing state",
                exc_info=True,
            )
        finally:
            self._closed = True
            self._handler = None
            self._remove_targets()

    def _remove_targets(self) -> None:
        for command, target in self._targets:
            try:
                command.removeTarget_(target)
            except Exception:
                logger.debug(
                    "Could not remove a macOS remote-command target",
                    exc_info=True,
                )
        self._targets.clear()

    def _register_commands(self) -> None:
        for kind, command in self._bindings.commands.items():
            handler = self._make_native_handler(kind)
            target = command.addTargetWithHandler_(handler)
            self._targets.append((command, target))

    def _make_native_handler(
        self,
        kind: SystemMediaCommandKind,
    ) -> Callable[[object], int]:
        def handle(event: object) -> int:
            handler = self._handler
            if self._closed or handler is None:
                return self._bindings.status_no_item
            try:
                position_ms: int | None = None
                if kind is SystemMediaCommandKind.SEEK:
                    position_seconds = cast(
                        "_PlaybackPositionEvent",
                        event,
                    ).positionTime()
                    if not math.isfinite(position_seconds):
                        return self._bindings.status_failed
                    position_ms = max(0, round(position_seconds * 1_000))
                handler(SystemMediaCommand(kind, position_ms))
            except Exception:
                logger.warning(
                    "Could not handle macOS system-media command %s",
                    kind.value,
                    exc_info=True,
                )
                return self._bindings.status_failed
            return self._bindings.status_success

        return handle

    def _set_command_capabilities(
        self,
        snapshot: SystemMediaSnapshot | None,
    ) -> None:
        enabled = {
            SystemMediaCommandKind.PLAY: snapshot is not None and snapshot.can_play,
            SystemMediaCommandKind.PAUSE: (snapshot is not None and snapshot.can_pause),
            SystemMediaCommandKind.TOGGLE_PLAY_PAUSE: snapshot is not None,
            SystemMediaCommandKind.NEXT: snapshot is not None and snapshot.can_next,
            SystemMediaCommandKind.PREVIOUS: (
                snapshot is not None and snapshot.can_previous
            ),
            SystemMediaCommandKind.SEEK: snapshot is not None and snapshot.can_seek,
        }
        for kind, command in self._bindings.commands.items():
            command.setEnabled_(enabled.get(kind, False))


def _load_bindings() -> _MacOSBindings:
    media_player = import_module("MediaPlayer")
    appkit = import_module("AppKit")
    info_center_class = cast(
        "_NowPlayingInfoCenterClass",
        _required_object(media_player, "MPNowPlayingInfoCenter"),
    )
    command_center_class = cast(
        "_RemoteCommandCenterClass",
        _required_object(media_player, "MPRemoteCommandCenter"),
    )
    command_center = command_center_class.sharedCommandCenter()
    return _MacOSBindings(
        info_center=info_center_class.defaultCenter(),
        commands={
            SystemMediaCommandKind.PLAY: command_center.playCommand(),
            SystemMediaCommandKind.PAUSE: command_center.pauseCommand(),
            SystemMediaCommandKind.TOGGLE_PLAY_PAUSE: (
                command_center.togglePlayPauseCommand()
            ),
            SystemMediaCommandKind.NEXT: command_center.nextTrackCommand(),
            SystemMediaCommandKind.PREVIOUS: command_center.previousTrackCommand(),
            SystemMediaCommandKind.SEEK: (
                command_center.changePlaybackPositionCommand()
            ),
        },
        title_key=_required_string(media_player, "MPMediaItemPropertyTitle"),
        artist_key=_required_string(media_player, "MPMediaItemPropertyArtist"),
        album_key=_required_string(media_player, "MPMediaItemPropertyAlbumTitle"),
        genre_key=_required_string(media_player, "MPMediaItemPropertyGenre"),
        track_number_key=_required_string(
            media_player,
            "MPMediaItemPropertyAlbumTrackNumber",
        ),
        duration_key=_required_string(
            media_player,
            "MPMediaItemPropertyPlaybackDuration",
        ),
        persistent_id_key=_required_string(
            media_player,
            "MPMediaItemPropertyPersistentID",
        ),
        elapsed_key=_required_string(
            media_player,
            "MPNowPlayingInfoPropertyElapsedPlaybackTime",
        ),
        playback_rate_key=_required_string(
            media_player,
            "MPNowPlayingInfoPropertyPlaybackRate",
        ),
        default_rate_key=_required_string(
            media_player,
            "MPNowPlayingInfoPropertyDefaultPlaybackRate",
        ),
        external_id_key=_required_string(
            media_player,
            "MPNowPlayingInfoPropertyExternalContentIdentifier",
        ),
        exclude_suggestions_key=_optional_string(
            media_player,
            "MPNowPlayingInfoPropertyExcludeFromSuggestions",
        ),
        artwork_key=_required_string(media_player, "MPMediaItemPropertyArtwork"),
        make_artwork=_artwork_factory(media_player, appkit),
        state_playing=_required_int(
            media_player,
            "MPNowPlayingPlaybackStatePlaying",
        ),
        state_paused=_required_int(
            media_player,
            "MPNowPlayingPlaybackStatePaused",
        ),
        state_stopped=_required_int(
            media_player,
            "MPNowPlayingPlaybackStateStopped",
        ),
        status_success=_required_int(
            media_player,
            "MPRemoteCommandHandlerStatusSuccess",
        ),
        status_no_item=_required_int(
            media_player,
            "MPRemoteCommandHandlerStatusNoActionableNowPlayingItem",
        ),
        status_failed=_required_int(
            media_player,
            "MPRemoteCommandHandlerStatusCommandFailed",
        ),
    )


def _artwork_factory(
    media_player: ModuleType,
    appkit: ModuleType,
) -> Callable[[SystemMediaArtwork], object]:
    media_artwork_class = cast(
        "_MediaItemArtworkClass",
        _required_object(media_player, "MPMediaItemArtwork"),
    )
    image_class = cast(
        "_NSImageClass",
        _required_object(appkit, "NSImage"),
    )

    def make_artwork(artwork: SystemMediaArtwork) -> object:
        encoded = BytesIO()
        Image.frombytes(
            "RGB",
            (artwork.width, artwork.height),
            artwork.rgb888,
        ).save(encoded, format="PNG")
        native_image = image_class.alloc().initWithData_(encoded.getvalue())
        if native_image is None:
            raise RuntimeError("AppKit could not decode the album artwork")
        native_artwork = media_artwork_class.alloc().initWithImage_(native_image)
        if native_artwork is None:
            raise RuntimeError("MediaPlayer could not create album artwork")
        return native_artwork

    return make_artwork


def _required_string(module: ModuleType, name: str) -> str:
    value = getattr(module, name, None)
    if not isinstance(value, str):
        raise RuntimeError(f"macOS MediaPlayer does not provide {name}")
    return value


def _required_object(module: ModuleType, name: str) -> object:
    value = getattr(module, name, None)
    if value is None:
        raise RuntimeError(f"macOS MediaPlayer does not provide {name}")
    return value


def _optional_string(module: ModuleType, name: str) -> str | None:
    value = getattr(module, name, None)
    return value if isinstance(value, str) else None


def _required_int(module: ModuleType, name: str) -> int:
    value = getattr(module, name, None)
    if not isinstance(value, int):
        raise RuntimeError(f"macOS MediaPlayer does not provide {name}")
    return value


__all__ = ["MacOSSystemMediaSession"]
