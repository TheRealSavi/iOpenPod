"""Windows System Media Transport Controls integration through PyWinRT."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable, MutableSequence
    from types import ModuleType

from iOpenPod.app.playback.system_media.session import (
    SystemMediaArtwork,
    SystemMediaCommand,
    SystemMediaCommandHandler,
    SystemMediaCommandKind,
    SystemMediaSnapshot,
)

logger = logging.getLogger(__name__)

_SEEK_STEP_MS = 10_000


class _MusicProperties(Protocol):
    title: str
    artist: str
    album_title: str
    album_artist: str
    genres: MutableSequence[str]
    track_number: int


class _DisplayUpdater(Protocol):
    type: object
    music_properties: _MusicProperties
    thumbnail: object | None

    def clear_all(self) -> None: ...

    def update(self) -> None: ...


class _TimelineProperties(Protocol):
    start_time: object
    end_time: object
    min_seek_time: object
    max_seek_time: object
    position: object


class _MediaButtonEventArgs(Protocol):
    button: object


class _AsyncOperation(Protocol):
    completed: Callable[[object, object], None] | None

    def get(self) -> object: ...


class _RandomAccessStream(Protocol):
    def seek(self, position: int) -> None: ...


class _DataWriter(Protocol):
    def write_bytes(self, value: bytes) -> None: ...

    def store_async(self) -> _AsyncOperation: ...

    def detach_stream(self) -> object: ...


class _ReferenceClass(Protocol):
    @staticmethod
    def create_from_stream(stream: _RandomAccessStream) -> object: ...


class _Controls(Protocol):
    is_enabled: bool
    is_play_enabled: bool
    is_pause_enabled: bool
    is_next_enabled: bool
    is_previous_enabled: bool
    is_fast_forward_enabled: bool
    is_rewind_enabled: bool
    playback_status: object
    display_updater: _DisplayUpdater

    def add_button_pressed(
        self,
        handler: Callable[[object, _MediaButtonEventArgs], None],
    ) -> object: ...

    def remove_button_pressed(self, token: object) -> None: ...

    def update_timeline_properties(self, value: _TimelineProperties) -> None: ...


@dataclass(frozen=True, slots=True)
class _NativeArtwork:
    """Native thumbnail plus a stream keepalive for the WinRT reference."""

    reference: object
    stream: object


@dataclass(frozen=True, slots=True)
class _PendingArtwork:
    """Artwork whose WinRT stream write completes asynchronously on the GUI STA."""

    operation: _AsyncOperation
    stream: _RandomAccessStream
    writer: _DataWriter
    reference_class: _ReferenceClass


_ArtworkResult = _NativeArtwork | _PendingArtwork


@dataclass(frozen=True, slots=True)
class _WindowsBindings:
    """WinRT values and factories kept injectable for platform-neutral tests."""

    get_for_window: Callable[[int], _Controls]
    media_type_music: object
    status_playing: object
    status_paused: object
    status_stopped: object
    button_play: object
    button_pause: object
    button_next: object
    button_previous: object
    button_fast_forward: object
    button_rewind: object
    make_timeline: Callable[[], _TimelineProperties]
    make_time_span: Callable[[int], object]
    make_artwork: Callable[[SystemMediaArtwork], _ArtworkResult]


class WindowsSystemMediaSession:
    """Publish PlaybackController state to Windows system media controls."""

    def __init__(
        self,
        window_id: int,
        bindings: _WindowsBindings | None = None,
    ) -> None:
        if window_id <= 0:
            raise ValueError("Windows system-media integration requires a window ID")
        self._bindings = bindings or _load_bindings()
        self._controls = self._bindings.get_for_window(window_id)
        self._handler: SystemMediaCommandHandler | None = None
        self._button_token: object | None = None
        self._artwork_cache_key: str | None = None
        self._native_artwork: _NativeArtwork | None = None
        self._pending_artwork: _PendingArtwork | None = None
        self._latest_snapshot: SystemMediaSnapshot | None = None
        self._closed = False
        try:
            self._controls.is_enabled = True
            self._button_token = self._controls.add_button_pressed(self._button_pressed)
            self.publish(None)
        except Exception:
            self._closed = True
            self._remove_button_handler()
            raise

    def set_command_handler(
        self,
        handler: SystemMediaCommandHandler | None,
    ) -> None:
        self._handler = handler

    def publish(self, snapshot: SystemMediaSnapshot | None) -> None:
        if self._closed:
            return
        if snapshot is None:
            # Invalidate async artwork first so a completion racing the native
            # clear cannot repopulate the stopped session.
            self._latest_snapshot = None
            self._artwork_cache_key = None
            self._native_artwork = None
            self._cancel_pending_artwork()
            self._clear_native_state()
            return

        self._latest_snapshot = snapshot
        self._controls.is_enabled = True
        updater = self._controls.display_updater
        updater.clear_all()
        updater.type = self._bindings.media_type_music
        music = updater.music_properties
        music.title = snapshot.title
        music.artist = snapshot.artist
        music.album_title = snapshot.album
        music.album_artist = snapshot.artist
        genres = music.genres
        genres.clear()
        if snapshot.genre:
            genres.append(snapshot.genre)
        music.track_number = max(0, snapshot.track_number)

        native_artwork = self._native_artwork_for(snapshot.artwork)
        updater.thumbnail = (
            native_artwork.reference if native_artwork is not None else None
        )
        updater.update()
        self._controls.playback_status = (
            self._bindings.status_playing
            if snapshot.playing
            else self._bindings.status_paused
        )
        self._set_capabilities(snapshot)
        self._update_timeline(snapshot)

    def seeked(self, position_ms: int) -> None:
        del position_ms

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.publish(None)
        except Exception:
            logger.warning(
                "Could not clear Windows system-media state",
                exc_info=True,
            )
        finally:
            self._closed = True
            self._handler = None
            self._remove_button_handler()

    def _clear_native_state(self) -> None:
        updater = self._controls.display_updater
        updater.clear_all()
        # Disable the session while it has no item; otherwise Windows can keep
        # showing an executable/unknown-app entry after metadata is cleared.
        self._controls.is_enabled = False
        updater.update()
        self._controls.playback_status = self._bindings.status_stopped
        self._set_capabilities(None)
        timeline = self._bindings.make_timeline()
        zero = self._bindings.make_time_span(0)
        timeline.start_time = zero
        timeline.end_time = zero
        timeline.min_seek_time = zero
        timeline.max_seek_time = zero
        timeline.position = zero
        self._controls.update_timeline_properties(timeline)

    def _set_capabilities(self, snapshot: SystemMediaSnapshot | None) -> None:
        self._controls.is_play_enabled = snapshot is not None and snapshot.can_play
        self._controls.is_pause_enabled = snapshot is not None and snapshot.can_pause
        self._controls.is_next_enabled = snapshot is not None and snapshot.can_next
        self._controls.is_previous_enabled = (
            snapshot is not None and snapshot.can_previous
        )
        seek_enabled = snapshot is not None and snapshot.can_seek
        self._controls.is_fast_forward_enabled = seek_enabled
        self._controls.is_rewind_enabled = seek_enabled

    def _update_timeline(self, snapshot: SystemMediaSnapshot) -> None:
        duration_ms = max(0, snapshot.duration_ms)
        position_ms = min(max(0, snapshot.position_ms), duration_ms)
        timeline = self._bindings.make_timeline()
        start = self._bindings.make_time_span(0)
        end = self._bindings.make_time_span(duration_ms)
        timeline.start_time = start
        timeline.end_time = end
        timeline.min_seek_time = start
        timeline.max_seek_time = end
        timeline.position = self._bindings.make_time_span(position_ms)
        self._controls.update_timeline_properties(timeline)

    def _native_artwork_for(
        self,
        artwork: SystemMediaArtwork | None,
    ) -> _NativeArtwork | None:
        if artwork is None:
            self._artwork_cache_key = None
            self._native_artwork = None
            self._cancel_pending_artwork()
            return None
        if artwork.cache_key == self._artwork_cache_key:
            return self._native_artwork
        self._artwork_cache_key = artwork.cache_key
        try:
            self._cancel_pending_artwork()
            result = self._bindings.make_artwork(artwork)
            if isinstance(result, _PendingArtwork):
                self._pending_artwork = result
                self._native_artwork = None
                result.operation.completed = lambda _sender, _status: (
                    self._artwork_write_completed(
                        artwork.cache_key,
                        result,
                    )
                )
            else:
                self._native_artwork = result
        except Exception:
            self._native_artwork = None
            logger.warning(
                "Could not convert album artwork for Windows system media",
                exc_info=True,
            )
        return self._native_artwork

    def _artwork_write_completed(
        self,
        cache_key: str,
        pending: _PendingArtwork,
    ) -> None:
        if (
            self._closed
            or self._pending_artwork is not pending
            or self._artwork_cache_key != cache_key
        ):
            return
        self._pending_artwork = None
        # PyWinRT rejects assigning ``Completed`` after an IAsyncOperation has
        # already fired (WinError -2147483624).  The operation owns this
        # one-shot callback until it is released, so only detach it while a
        # write is still pending (see _cancel_pending_artwork).
        try:
            pending.writer.detach_stream()
            pending.stream.seek(0)
            self._native_artwork = _NativeArtwork(
                reference=pending.reference_class.create_from_stream(pending.stream),
                stream=pending.stream,
            )
        except Exception:
            self._native_artwork = None
            logger.warning(
                "Could not finalize album artwork for Windows system media",
                exc_info=True,
            )
            return

        snapshot = self._latest_snapshot
        if (
            snapshot is None
            or snapshot.artwork is None
            or snapshot.artwork.cache_key != cache_key
        ):
            return
        try:
            updater = self._controls.display_updater
            updater.thumbnail = self._native_artwork.reference
            updater.update()
        except Exception:
            logger.warning(
                "Could not publish album artwork for Windows system media",
                exc_info=True,
            )

    def _button_pressed(
        self,
        _sender: object,
        args: _MediaButtonEventArgs,
    ) -> None:
        if self._closed:
            return
        button = args.button
        command_kind: SystemMediaCommandKind | None = None
        position_ms: int | None = None
        if button == self._bindings.button_play:
            command_kind = SystemMediaCommandKind.PLAY
        elif button == self._bindings.button_pause:
            command_kind = SystemMediaCommandKind.PAUSE
        elif button == self._bindings.button_next:
            command_kind = SystemMediaCommandKind.NEXT
        elif button == self._bindings.button_previous:
            command_kind = SystemMediaCommandKind.PREVIOUS
        elif button in (
            self._bindings.button_fast_forward,
            self._bindings.button_rewind,
        ):
            snapshot = self._latest_snapshot
            if snapshot is None or not snapshot.can_seek:
                return
            delta = (
                _SEEK_STEP_MS
                if button == self._bindings.button_fast_forward
                else -_SEEK_STEP_MS
            )
            position_ms = min(
                max(0, snapshot.position_ms + delta),
                max(0, snapshot.duration_ms),
            )
            command_kind = SystemMediaCommandKind.SEEK
        if command_kind is None:
            return
        handler = self._handler
        if handler is None:
            return
        try:
            handler(SystemMediaCommand(command_kind, position_ms))
        except Exception:
            logger.warning(
                "Could not handle Windows system-media command",
                exc_info=True,
            )

    def _remove_button_handler(self) -> None:
        token = self._button_token
        if token is None:
            return
        self._button_token = None
        try:
            self._controls.remove_button_pressed(token)
        except Exception:
            logger.debug(
                "Could not remove Windows system-media button handler",
                exc_info=True,
            )

    def _cancel_pending_artwork(self) -> None:
        pending = self._pending_artwork
        self._pending_artwork = None
        if pending is not None:
            try:
                pending.operation.completed = None
            except Exception:
                # A completion can race cancellation on the GUI STA.  Once
                # completed, WinRT does not permit replacing its delegate;
                # dropping our reference is sufficient to ignore the result.
                logger.debug(
                    "Could not detach pending Windows artwork completion",
                    exc_info=True,
                )


def _load_bindings() -> _WindowsBindings:
    media = import_module("winrt.windows.media")
    interop = import_module("winrt.windows.media.interop")
    import_module("winrt.windows.foundation.collections")
    streams = import_module("winrt.windows.storage.streams")
    return _WindowsBindings(
        get_for_window=cast(
            "Callable[[int], _Controls]",
            _required_object(interop, "get_for_window"),
        ),
        media_type_music=_required_member(media, "MediaPlaybackType", "MUSIC"),
        status_playing=_required_member(media, "MediaPlaybackStatus", "PLAYING"),
        status_paused=_required_member(media, "MediaPlaybackStatus", "PAUSED"),
        status_stopped=_required_member(media, "MediaPlaybackStatus", "STOPPED"),
        button_play=_required_member(
            media,
            "SystemMediaTransportControlsButton",
            "PLAY",
        ),
        button_pause=_required_member(
            media,
            "SystemMediaTransportControlsButton",
            "PAUSE",
        ),
        button_next=_required_member(
            media,
            "SystemMediaTransportControlsButton",
            "NEXT",
        ),
        button_previous=_required_member(
            media,
            "SystemMediaTransportControlsButton",
            "PREVIOUS",
        ),
        button_fast_forward=_required_member(
            media,
            "SystemMediaTransportControlsButton",
            "FAST_FORWARD",
        ),
        button_rewind=_required_member(
            media,
            "SystemMediaTransportControlsButton",
            "REWIND",
        ),
        make_timeline=cast(
            "Callable[[], _TimelineProperties]",
            _required_object(media, "SystemMediaTransportControlsTimelineProperties"),
        ),
        make_time_span=cast(
            "Callable[[int], object]",
            _make_time_span,
        ),
        make_artwork=_artwork_factory(streams),
    )


def _artwork_factory(
    streams: ModuleType,
) -> Callable[[SystemMediaArtwork], _ArtworkResult]:
    stream_class = cast(
        "Callable[[], _RandomAccessStream]",
        _required_object(streams, "InMemoryRandomAccessStream"),
    )
    writer_class = cast(
        "Callable[[_RandomAccessStream], _DataWriter]",
        _required_object(streams, "DataWriter"),
    )
    reference_class = cast(
        "_ReferenceClass",
        _required_object(streams, "RandomAccessStreamReference"),
    )

    def make_artwork(artwork: SystemMediaArtwork) -> _PendingArtwork:
        from io import BytesIO

        from PIL import Image

        encoded = BytesIO()
        Image.frombytes(
            "RGB",
            (artwork.width, artwork.height),
            artwork.rgb888,
        ).save(encoded, format="PNG")
        stream = stream_class()
        writer = writer_class(stream)
        writer.write_bytes(encoded.getvalue())
        operation = writer.store_async()
        return _PendingArtwork(
            operation=operation,
            stream=stream,
            writer=writer,
            reference_class=reference_class,
        )

    return make_artwork


def _required_object(module: ModuleType, name: str) -> object:
    value = getattr(module, name, None)
    if value is None:
        raise RuntimeError(f"Windows WinRT media API does not provide {name}")
    return value


def _required_member(module: ModuleType, name: str, member: str) -> object:
    value = getattr(_required_object(module, name), member, None)
    if value is None:
        raise RuntimeError(f"Windows WinRT media API does not provide {name}.{member}")
    return value


def _make_time_span(milliseconds: int) -> object:
    return timedelta(milliseconds=milliseconds)


__all__ = ["WindowsSystemMediaSession"]
