"""Graphics-only Synesthesia page synchronized to Player-owned playback."""

# Hallmark · pre-emit critique: P5 H5 E5 S5 R5 V4

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtWidgets import QVBoxLayout, QWidget

from iOpenPod.GUI.synesthesia import SynesthesiaRenderer

if TYPE_CHECKING:
    from iOpenPod.app.playback_controller import PlaybackController
    from iOpenPod.app.synesthesia import SynesthesiaController, TrackAnalysis
    from iPodDB.library import Track


class SynesthesiaPage(QWidget):
    """Present only the visual field while observing authoritative Player state."""

    failure = Signal(str)

    def __init__(
        self,
        controller: SynesthesiaController,
        playback_controller: PlaybackController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("synesthesiaPage")
        self._controller = controller
        self._playback_controller = playback_controller
        self._active = False
        self._playback_entry_id = playback_controller.current_entry_id
        self._analysis_entry_id: int | None = None
        self._transport_epoch = 0
        self._prepare_timer = QTimer(self)
        self._prepare_timer.setSingleShot(True)
        self._prepare_timer.timeout.connect(self._prepare_next)

        self._renderer = SynesthesiaRenderer(self)
        self._renderer.failure.connect(self.failure.emit)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._renderer)

        controller.analysisChanged.connect(self._analysis_changed)
        playback_controller.currentTrackChanged.connect(self._current_track_changed)
        playback_controller.positionChanged.connect(self._position_changed)
        playback_controller.playingChanged.connect(self._playing_changed)
        playback_controller.seeked.connect(self._seeked)
        for model in (
            playback_controller.queue_model,
            playback_controller.history_model,
        ):
            model.rowsInserted.connect(self._schedule_prepare_next)
            model.rowsRemoved.connect(self._schedule_prepare_next)
            model.rowsMoved.connect(self._schedule_prepare_next)
            model.modelReset.connect(self._schedule_prepare_next)
            model.dataChanged.connect(self._schedule_prepare_next)
        self._renderer.set_playing(playback_controller.playing)
        self._renderer.set_position_ms(playback_controller.position_ms)

    @property
    def renderer(self) -> SynesthesiaRenderer:
        return self._renderer

    def activate_current(self) -> bool:
        """Start fresh analysis for the current Playback Entry."""

        track = self._playback_controller.current_track
        entry_id = self._playback_controller.current_entry_id
        if track is None or entry_id is None:
            self._active = False
            self._analysis_entry_id = None
            self._prepare_timer.stop()
            self._controller.clear()
            return False
        if entry_id != self._playback_entry_id:
            self._playback_entry_id = entry_id
            self._transport_epoch += 1
        self._active = True
        return self._start_analysis(track, entry_id)

    def deactivate(self) -> None:
        """Release graphics state when application navigation leaves this page."""

        self._active = False
        self._analysis_entry_id = None
        self._prepare_timer.stop()
        self._controller.clear()

    def _start_analysis(self, track: Track, entry_id: int) -> bool:
        self._analysis_entry_id = entry_id
        self._renderer.set_preview(
            track.track_id,
            track.length_ms / 1_000.0 if track.length_ms > 0 else None,
        )
        self._renderer.relocate(
            self._playback_controller.position_ms,
            self._transport_epoch,
        )
        self._renderer.set_playing(self._playback_controller.playing)
        started = self._controller.analyze(track, entry_id=entry_id)
        if not started:
            self._analysis_entry_id = None
        else:
            self._schedule_prepare_next()
        return started

    @Slot()
    def _schedule_prepare_next(self) -> None:
        if self._active:
            # Queue removal precedes currentTrackChanged. Observe the settled
            # state so consuming the next entry can promote its preparation.
            self._prepare_timer.start(0)

    @Slot()
    def _prepare_next(self) -> None:
        if self._active:
            self._controller.prepare_next(self._playback_controller.next_entry)

    @Slot(object)
    def _analysis_changed(self, value: object) -> None:
        if value is None:
            if self._analysis_entry_id is None:
                self._renderer.set_analysis(None)
            return
        if (
            not self._active
            or self._analysis_entry_id is None
            or self._analysis_entry_id != self._playback_controller.current_entry_id
        ):
            return
        self._renderer.set_analysis(cast("TrackAnalysis", value))
        self._renderer.set_position_ms(self._playback_controller.position_ms)
        self._renderer.set_playing(self._playback_controller.playing)

    @Slot(object)
    def _current_track_changed(self, _value: object) -> None:
        entry_id = self._playback_controller.current_entry_id
        if entry_id == self._playback_entry_id:
            return
        self._playback_entry_id = entry_id
        self._analysis_entry_id = None
        self._transport_epoch += 1
        track = self._playback_controller.current_track
        if self._active and track is not None and entry_id is not None:
            self._start_analysis(track, entry_id)
        else:
            self._prepare_timer.stop()
            self._controller.clear()

    @Slot(int)
    def _position_changed(self, position_ms: int) -> None:
        if self._active:
            self._renderer.set_position_ms(position_ms)

    @Slot(bool)
    def _playing_changed(self, playing: bool) -> None:
        if self._active:
            self._renderer.set_playing(playing)

    @Slot(int)
    def _seeked(self, position_ms: int) -> None:
        if not self._active:
            return
        self._transport_epoch += 1
        self._renderer.relocate(position_ms, self._transport_epoch)


__all__ = ["SynesthesiaPage"]
