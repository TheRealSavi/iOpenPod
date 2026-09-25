# pyright: strict, reportPrivateUsage=false
# Advance the real renderer deterministically between Player transport events.

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QSlider, QWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.playback_test_support import FakePlaybackBackend

from iOpenPod.app.playback_controller import PlaybackController
from iOpenPod.GUI.pages import synesthesia_page as page_module
from iOpenPod.GUI.synesthesia.persistent_world import TransportState
from iPodDB.library import Track

if TYPE_CHECKING:
    from pytest import MonkeyPatch

    from iOpenPod.app.models.playback_models import PlaybackEntry
    from iOpenPod.app.playback.backend import PlaybackAttemptId
    from iOpenPod.app.synesthesia import (
        AnalysisRequest,
        SynesthesiaController,
        TrackAnalysis,
    )


class _AnalysisController(QObject):
    analysisChanged = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.track: Track | None = None
        self.analyzed: list[Track] = []
        self.analyzed_entry_ids: list[int | None] = []
        self.prepared: list[PlaybackEntry | None] = []
        self.clear_count = 0

    def analyze(
        self,
        track: Track,
        request: AnalysisRequest | None = None,
        *,
        entry_id: int | None = None,
    ) -> bool:
        del request
        self.track = track
        self.analyzed.append(track)
        self.analyzed_entry_ids.append(entry_id)
        self.analysisChanged.emit(None)
        return True

    def prepare_next(self, entry: PlaybackEntry | None) -> None:
        self.prepared.append(entry)

    def clear(self) -> None:
        self.track = None
        self.clear_count += 1
        self.analysisChanged.emit(None)


class _Renderer(QWidget):
    failure = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.calls: list[tuple[object, ...]] = []

    def set_analysis(self, analysis: TrackAnalysis | None) -> None:
        self.calls.append(("analysis", analysis))

    def set_preview(self, seed: int, duration_seconds: float | None) -> None:
        self.calls.append(("preview", seed, duration_seconds))

    def set_position_ms(self, position_ms: int) -> None:
        self.calls.append(("position", position_ms))

    def set_playing(self, playing: bool) -> None:
        self.calls.append(("playing", playing))

    def relocate(self, position_ms: int, transport_epoch: int) -> None:
        self.calls.append(("relocate", position_ms, transport_epoch))


class _DelayedPlaybackBackend(FakePlaybackBackend):
    """Allow a rendered frame before the decoder reports playing."""

    def start(self, attempt_id: PlaybackAttemptId, track: Track) -> None:
        self.current_attempt_id = attempt_id
        self.current_track = track
        self.started_attempt_ids.append(attempt_id)
        self.started.append(track)


def _track(track_id: int, *, title: str | None = None) -> Track:
    return Track(
        track_id=track_id,
        title=title or f"Track {track_id}",
        artist="Artist",
        album="Album",
        length_ms=180_000,
    )


def _page(
    monkeypatch: MonkeyPatch,
) -> tuple[
    page_module.SynesthesiaPage,
    _AnalysisController,
    PlaybackController,
    FakePlaybackBackend,
]:
    monkeypatch.setattr(page_module, "SynesthesiaRenderer", _Renderer)
    analysis = _AnalysisController()
    backend = FakePlaybackBackend()
    playback = PlaybackController(backend)
    page = page_module.SynesthesiaPage(
        cast("SynesthesiaController", analysis),
        playback,
    )
    return page, analysis, playback, backend


def test_page_contains_only_graphics_and_catches_up_when_analysis_finishes(
    monkeypatch: MonkeyPatch,
) -> None:
    page, analysis, playback, backend = _page(monkeypatch)
    analysis_result = cast("TrackAnalysis", object())
    playback.enqueue(_track(1))
    page.show()
    APPLICATION.processEvents()

    assert page.activate_current()
    renderer = page.renderer
    assert isinstance(renderer, _Renderer)
    assert ("preview", 1, 180.0) in renderer.calls
    renderer.calls.clear()
    analysis.analysisChanged.emit(None)
    assert renderer.calls == []

    backend.emit_position(47_000)
    analysis.analysisChanged.emit(analysis_result)

    assert renderer.calls[-3] == ("analysis", analysis_result)
    assert renderer.calls[-2] == ("position", 47_000)
    assert renderer.calls[-1] == ("playing", True)
    assert page.findChildren(QLabel) == []
    assert page.findChildren(QPushButton) == []
    assert page.findChildren(QSlider) == []
    assert page.findChildren(QProgressBar) == []

    page.deactivate()
    APPLICATION.processEvents()
    assert playback.playing
    assert analysis.track is None
    playback.shutdown()


def test_page_follows_new_entries_but_not_same_entry_metadata(
    monkeypatch: MonkeyPatch,
) -> None:
    page, analysis, playback, _backend = _page(monkeypatch)
    first = _track(1)
    playback.enqueue(first)
    page.show()
    APPLICATION.processEvents()
    assert page.activate_current()
    assert analysis.analyzed == [first]

    page.hide()
    page.show()
    APPLICATION.processEvents()
    assert analysis.track == first

    updated = replace(first, title="Updated")
    playback.reconcile_library((updated,))
    assert analysis.analyzed == [first]

    second = _track(2)
    playback.play_now((second,))
    assert analysis.analyzed == [first, second]
    assert analysis.track == second
    assert playback.playing

    page.deactivate()
    page.hide()
    playback.shutdown()


def test_page_prepares_only_the_next_entry_while_active_and_tracks_queue_edits(
    monkeypatch: MonkeyPatch,
) -> None:
    page, analysis, playback, _backend = _page(monkeypatch)
    first, second, third = _track(1), _track(2), _track(3)
    playback.play_now((first, second, third))
    APPLICATION.processEvents()
    assert analysis.prepared == []

    try:
        assert page.activate_current()
        APPLICATION.processEvents()
        assert analysis.prepared == [playback.queue_model.entries[0]]
        assert analysis.analyzed == [first]

        assert playback.move_queue_entry(1, 0)
        APPLICATION.processEvents()
        reordered = analysis.prepared[-1]
        assert reordered is not None
        assert reordered == playback.queue_model.entries[0]
        assert reordered.track == third

        playback.remove_queue_entry(playback.queue_model.entries[0].entry_id)
        APPLICATION.processEvents()
        remaining = analysis.prepared[-1]
        assert remaining is not None
        assert remaining == playback.queue_model.entries[0]
        assert remaining.track == second

        playback.clear_queue()
        APPLICATION.processEvents()
        assert analysis.prepared[-1] is None

        # Leaving before the deferred update must not start another Job.
        count = len(analysis.prepared)
        playback.enqueue(third)
        page.deactivate()
        APPLICATION.processEvents()
        assert len(analysis.prepared) == count
        playback.enqueue(second)
        APPLICATION.processEvents()
        assert len(analysis.prepared) == count
    finally:
        page.deactivate()
        page.close()
        playback.shutdown()


def test_page_promotes_consumed_entry_before_preparing_its_successor(
    monkeypatch: MonkeyPatch,
) -> None:
    page, analysis, playback, backend = _page(monkeypatch)
    first, second, third = _track(1), _track(2), _track(3)
    playback.play_now((first, second, third))
    assert page.activate_current()
    APPLICATION.processEvents()
    prepared = playback.next_entry
    clears_before = analysis.clear_count

    try:
        backend.finish()
        # Consuming the queue emits model changes before currentTrackChanged.
        assert analysis.prepared == [prepared]
        assert analysis.analyzed == [first, second]
        assert analysis.analyzed_entry_ids[-1] == playback.current_entry_id
        assert analysis.clear_count == clears_before
        APPLICATION.processEvents()
        assert analysis.prepared[-1] == playback.next_entry
        assert playback.next_entry is not None
        assert playback.next_entry.track == third

        playback.previous()
        APPLICATION.processEvents()
        # Forward history, rather than the queue head, is now next.
        assert analysis.prepared[-1] == prepared

        playback.clear_session()
        APPLICATION.processEvents()
        assert analysis.track is None
        assert analysis.clear_count > clears_before
        assert analysis.prepared[-1] is None
    finally:
        page.deactivate()
        page.close()
        playback.shutdown()


def test_player_seek_relocates_but_position_updates_preserve_the_field(
    monkeypatch: MonkeyPatch,
) -> None:
    page, _analysis, playback, backend = _page(monkeypatch)
    playback.enqueue(_track(1))
    page.show()
    APPLICATION.processEvents()
    assert page.activate_current()
    renderer = page.renderer
    assert isinstance(renderer, _Renderer)
    renderer.calls.clear()

    backend.emit_position(1_250)
    playback.seek(5_000)
    playback.seek(9_000)

    assert renderer.calls[0:2] == [
        ("position", 1_250),
        ("position", 5_000),
    ]
    assert renderer.calls[2][:2] == ("relocate", 5_000)
    assert renderer.calls[3] == ("position", 9_000)
    assert renderer.calls[4][:2] == ("relocate", 9_000)
    first_epoch = renderer.calls[2][2]
    second_epoch = renderer.calls[4][2]
    assert isinstance(first_epoch, int)
    assert second_epoch == first_epoch + 1

    page.deactivate()
    page.hide()
    playback.shutdown()


@pytest.mark.parametrize("stopped_before_finish", (False, True))
def test_visualizer_advances_new_track_after_delayed_decoder_start(
    stopped_before_finish: bool,
) -> None:
    analysis = _AnalysisController()
    backend = _DelayedPlaybackBackend()
    playback = PlaybackController(backend)
    page = page_module.SynesthesiaPage(
        cast("SynesthesiaController", analysis), playback
    )
    first, second = _track(17), _track(18)
    playback.play_now((first, second))
    backend.emit_playing(True)
    backend.emit_position(first.length_ms - 100)
    assert page.activate_current()
    renderer = page.renderer
    frame_seconds = 1.0 / 60.0

    try:
        renderer._advance_field(frame_seconds)
        previous_epoch = renderer.latest_frame.transport_epoch
        backend.emit_position(first.length_ms)
        if stopped_before_finish:
            backend.emit_playing(False)
        backend.finish()

        # QRhi can render the new preview while its decoder is still starting.
        renderer._advance_field(frame_seconds)
        waiting_frame = renderer.latest_frame
        backend.emit_playing(True)
        renderer._advance_field(frame_seconds)
        renderer._advance_field(frame_seconds)

        assert analysis.analyzed == [first, second]
        assert waiting_frame.experience_seed == second.track_id
        assert waiting_frame.transport_state is TransportState.PAUSED
        assert waiting_frame.musical_time == 0.0
        assert renderer.latest_frame.transport_epoch > previous_epoch
        assert renderer.latest_frame.musical_time == pytest.approx(frame_seconds)
        assert renderer.latest_frame.transport_state is TransportState.PLAYING
    finally:
        page.deactivate()
        page.close()
        playback.shutdown()
