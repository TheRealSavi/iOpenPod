"""Tests for the Windows System Media Transport Controls adapter."""

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from typing import cast

import pytest

from iOpenPod.app.playback.system_media import (
    SystemMediaArtwork,
    SystemMediaCommand,
    SystemMediaCommandKind,
    SystemMediaSnapshot,
    factory,
)
from iOpenPod.app.playback.system_media.windows import (
    WindowsSystemMediaSession,
    _Controls,  # pyright: ignore[reportPrivateUsage]
    _load_bindings,  # pyright: ignore[reportPrivateUsage]
    _NativeArtwork,  # pyright: ignore[reportPrivateUsage]
    _PendingArtwork,  # pyright: ignore[reportPrivateUsage]
    _WindowsBindings,  # pyright: ignore[reportPrivateUsage]
)


class _FakeMusic:
    def __init__(self) -> None:
        self.title = ""
        self.artist = ""
        self.album_title = ""
        self.album_artist = ""
        self.genres: list[str] = []
        self.track_number = 0


class _FakeUpdater:
    def __init__(self) -> None:
        self.type: object | None = None
        self.music_properties = _FakeMusic()
        self.thumbnail: object | None = None
        self.clear_count = 0
        self.update_count = 0

    def clear_all(self) -> None:
        self.clear_count += 1
        self.thumbnail = None

    def update(self) -> None:
        self.update_count += 1


class _FakeTimeline:
    def __init__(self) -> None:
        self.start_time: object | None = None
        self.end_time: object | None = None
        self.min_seek_time: object | None = None
        self.max_seek_time: object | None = None
        self.position: object | None = None


class _ButtonArgs:
    def __init__(self, button: object) -> None:
        self.button = button


class _FakeAsyncOperation:
    def __init__(self, *, complete_on_assignment: bool = False) -> None:
        self._completed: Callable[[object, object], None] | None = None
        self._finished = False
        self._complete_on_assignment = complete_on_assignment

    @property
    def completed(self) -> Callable[[object, object], None] | None:
        return self._completed

    @completed.setter
    def completed(self, value: Callable[[object, object], None] | None) -> None:
        # WinRT IAsyncOperation does not allow clearing Completed after it fires.
        if self._finished and value is None:
            raise OSError("A delegate was assigned when not allowed")
        self._completed = value
        if value is not None and self._complete_on_assignment:
            self.complete()

    def complete(self) -> None:
        callback = self._completed
        self._finished = True
        if callback is not None:
            callback(self, 1)


class _FakeStream:
    def seek(self, position: int) -> None:
        del position
        return


class _FakeWriter:
    def detach_stream(self) -> object:
        return object()


class _FakeReferenceClass:
    @staticmethod
    def create_from_stream(stream: object) -> object:
        del stream
        return "completed-reference"


class _FakeControls:
    def __init__(self) -> None:
        self.is_enabled = False
        self.is_play_enabled = False
        self.is_pause_enabled = False
        self.is_next_enabled = False
        self.is_previous_enabled = False
        self.is_fast_forward_enabled = False
        self.is_rewind_enabled = False
        self.playback_status: object | None = None
        self.display_updater = _FakeUpdater()
        self.timeline_updates: list[_FakeTimeline] = []
        self.handler: Callable[[object, _ButtonArgs], None] | None = None
        self.removed_tokens: list[object] = []

    def add_button_pressed(
        self,
        handler: Callable[[object, _ButtonArgs], None],
    ) -> object:
        self.handler = handler
        return "button-token"

    def remove_button_pressed(self, token: object) -> None:
        self.removed_tokens.append(token)

    def update_timeline_properties(self, value: object) -> None:
        assert isinstance(value, _FakeTimeline)
        self.timeline_updates.append(value)

    def send(self, button: object) -> None:
        if self.handler is None:
            raise AssertionError("No Windows button handler registered")
        self.handler(self, _ButtonArgs(button))


def _bindings(controls: _FakeControls) -> _WindowsBindings:
    def get_for_window(_window_id: int) -> _Controls:
        return cast("_Controls", controls)

    return _WindowsBindings(
        get_for_window=get_for_window,
        media_type_music="music",
        status_playing="playing",
        status_paused="paused",
        status_stopped="stopped",
        button_play="play",
        button_pause="pause",
        button_next="next",
        button_previous="previous",
        button_fast_forward="fast-forward",
        button_rewind="rewind",
        make_timeline=_FakeTimeline,
        make_time_span=lambda milliseconds: milliseconds * 10_000,
        make_artwork=lambda artwork: _NativeArtwork(
            reference=("thumbnail", artwork.cache_key),
            stream=("stream", artwork.cache_key),
        ),
    )


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
        artwork=artwork,
    )


def test_windows_session_publishes_metadata_capabilities_and_timeline() -> None:
    controls = _FakeControls()
    session = WindowsSystemMediaSession(42, _bindings(controls))

    session.publish(_snapshot())

    music = controls.display_updater.music_properties
    assert controls.is_enabled
    assert controls.display_updater.type == "music"
    assert (music.title, music.artist, music.album_title) == (
        "Flamingo",
        "Token",
        "Between Somewhere",
    )
    assert (music.genres, music.track_number) == (["Alternative"], 4)
    assert controls.playback_status == "playing"
    assert not controls.is_play_enabled
    assert controls.is_pause_enabled
    assert controls.is_next_enabled
    assert controls.is_previous_enabled
    assert controls.is_fast_forward_enabled
    assert controls.is_rewind_enabled

    timeline = controls.timeline_updates[-1]
    assert timeline.start_time == 0
    assert timeline.end_time == 231_000 * 10_000
    assert timeline.min_seek_time == 0
    assert timeline.max_seek_time == 231_000 * 10_000
    assert timeline.position == 42_500 * 10_000


def test_windows_session_routes_native_buttons_and_bounded_relative_seek() -> None:
    controls = _FakeControls()
    session = WindowsSystemMediaSession(42, _bindings(controls))
    received: list[SystemMediaCommand] = []
    session.set_command_handler(received.append)
    session.publish(_snapshot(position_ms=5_000))

    for button, kind in (
        ("play", SystemMediaCommandKind.PLAY),
        ("pause", SystemMediaCommandKind.PAUSE),
        ("next", SystemMediaCommandKind.NEXT),
        ("previous", SystemMediaCommandKind.PREVIOUS),
    ):
        controls.send(button)
        assert received[-1] == SystemMediaCommand(kind)

    controls.send("fast-forward")
    controls.send("rewind")
    assert received[-2:] == [
        SystemMediaCommand(SystemMediaCommandKind.SEEK, 15_000),
        SystemMediaCommand(SystemMediaCommandKind.SEEK, 0),
    ]

    session.publish(_snapshot(position_ms=230_000))
    controls.send("fast-forward")
    assert received[-1] == SystemMediaCommand(SystemMediaCommandKind.SEEK, 231_000)


def test_windows_session_caches_artwork_by_application_cache_key() -> None:
    controls = _FakeControls()
    conversions: list[SystemMediaArtwork] = []
    bindings = _bindings(controls)

    def make_artwork(artwork: SystemMediaArtwork) -> _NativeArtwork:
        conversions.append(artwork)
        return _NativeArtwork("reference", "stream")

    bindings = replace(bindings, make_artwork=make_artwork)
    session = WindowsSystemMediaSession(42, bindings)
    artwork = SystemMediaArtwork(
        cache_key="device:64:1061",
        artwork_id=64,
        width=1,
        height=1,
        rgb888=bytes((10, 20, 30)),
    )

    session.publish(_snapshot(artwork=artwork))
    session.publish(_snapshot(playing=False, artwork=artwork))

    assert conversions == [artwork]
    assert controls.display_updater.thumbnail == "reference"


def test_windows_session_publishes_artwork_after_async_stream_write() -> None:
    controls = _FakeControls()
    operation = _FakeAsyncOperation()
    pending = _PendingArtwork(
        operation=operation,  # type: ignore[arg-type]
        stream=_FakeStream(),
        writer=_FakeWriter(),  # type: ignore[arg-type]
        reference_class=_FakeReferenceClass(),
    )

    def make_artwork(_artwork: SystemMediaArtwork) -> _PendingArtwork:
        return pending

    bindings = replace(_bindings(controls), make_artwork=make_artwork)
    session = WindowsSystemMediaSession(42, bindings)
    artwork = SystemMediaArtwork(
        cache_key="device:64:1061",
        artwork_id=64,
        width=1,
        height=1,
        rgb888=bytes((10, 20, 30)),
    )

    session.publish(_snapshot(artwork=artwork))
    assert controls.display_updater.thumbnail is None

    operation.complete()

    assert controls.display_updater.thumbnail is not None
    assert controls.display_updater.thumbnail == "completed-reference"


def test_windows_session_keeps_artwork_when_completion_is_synchronous() -> None:
    controls = _FakeControls()
    operation = _FakeAsyncOperation(complete_on_assignment=True)
    pending = _PendingArtwork(
        operation=operation,  # type: ignore[arg-type]
        stream=_FakeStream(),
        writer=_FakeWriter(),  # type: ignore[arg-type]
        reference_class=_FakeReferenceClass(),
    )

    def make_artwork(_artwork: SystemMediaArtwork) -> _PendingArtwork:
        return pending

    bindings = replace(
        _bindings(controls),
        make_artwork=make_artwork,
    )
    session = WindowsSystemMediaSession(42, bindings)
    artwork = SystemMediaArtwork(
        cache_key="device:64:1061",
        artwork_id=64,
        width=1,
        height=1,
        rgb888=bytes((10, 20, 30)),
    )

    session.publish(_snapshot(artwork=artwork))

    assert controls.display_updater.thumbnail == "completed-reference"


def test_windows_session_clears_state_and_close_is_idempotent() -> None:
    controls = _FakeControls()
    session = WindowsSystemMediaSession(42, _bindings(controls))
    session.publish(_snapshot())

    session.close()
    session.close()

    assert not controls.is_enabled
    assert controls.playback_status == "stopped"
    assert not controls.is_play_enabled
    assert not controls.is_pause_enabled
    assert not controls.is_next_enabled
    assert not controls.is_previous_enabled
    assert not controls.is_fast_forward_enabled
    assert not controls.is_rewind_enabled
    assert controls.display_updater.clear_count == 3
    assert controls.display_updater.update_count == 3
    assert controls.removed_tokens == ["button-token"]
    cleared_timeline = controls.timeline_updates[-1]
    assert (
        cleared_timeline.start_time,
        cleared_timeline.end_time,
        cleared_timeline.min_seek_time,
        cleared_timeline.max_seek_time,
        cleared_timeline.position,
    ) == (0, 0, 0, 0, 0)


def test_windows_session_ignores_buttons_without_a_command_handler() -> None:
    controls = _FakeControls()
    session = WindowsSystemMediaSession(42, _bindings(controls))
    session.publish(_snapshot())

    controls.send("play")
    controls.send("fast-forward")


def test_windows_factory_selects_adapter_and_falls_back_without_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iOpenPod.app.playback.system_media import windows

    controls = _FakeControls()
    monkeypatch.setattr(windows, "_load_bindings", lambda: _bindings(controls))

    session = factory.create_system_media_session(
        platform_name="win32",
        window_id=42,
    )
    assert isinstance(session, WindowsSystemMediaSession)
    session.close()

    missing = factory.create_system_media_session(
        platform_name="win32",
        window_id=None,
    )
    assert missing.__class__.__name__ == "NullSystemMediaSession"


def test_windows_factory_falls_back_when_native_adapter_initialization_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iOpenPod.app.playback.system_media import windows

    def fail(_window_id: int) -> WindowsSystemMediaSession:
        raise RuntimeError("native controls unavailable")

    monkeypatch.setattr(windows, "WindowsSystemMediaSession", fail)
    session = factory.create_system_media_session(
        platform_name="win32",
        window_id=42,
    )
    assert session.__class__.__name__ == "NullSystemMediaSession"


def test_windows_session_rejects_invalid_window_id() -> None:
    with pytest.raises(ValueError, match="window ID"):
        WindowsSystemMediaSession(0, _bindings(_FakeControls()))


def test_real_pywinrt_binding_uses_winrt_time_span_shape() -> None:
    bindings = _load_bindings()
    assert bindings.make_time_span(1_500) == timedelta(milliseconds=1_500)
