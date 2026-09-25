# pyright: strict, reportPrivateUsage=false
"""Deterministic timing regressions for the real-time Synesthesia renderer."""

from dataclasses import replace
from itertools import pairwise
from typing import TYPE_CHECKING, cast

import pytest
from PySide6.QtWidgets import QApplication

from iOpenPod.GUI.synesthesia import renderer
from iOpenPod.GUI.synesthesia.conductor import ConductedField
from iOpenPod.GUI.synesthesia.persistent_world import FieldForcing, TransportState
from iOpenPod.GUI.synesthesia.scene_director import (
    CameraPose,
    VisualScene,
    idle_scene_moment,
)

if TYPE_CHECKING:
    from iOpenPod.app.synesthesia import TrackAnalysis
    from iOpenPod.GUI.synesthesia.conductor import FieldConductor


class _ConstantConductor:
    def __init__(self, _analysis: object = None) -> None:
        pass

    def advance(
        self,
        *,
        musical_time: float,
        delta_seconds: float,
        transport_state: TransportState,
        transport_epoch: int,
    ) -> ConductedField:
        del delta_seconds
        return ConductedField(
            musical_time=musical_time,
            transport_state=transport_state,
            transport_epoch=transport_epoch,
            forcing=FieldForcing(),
        )


def _renderer_with_constant_conductor() -> renderer.SynesthesiaRenderer:
    application = QApplication.instance()
    if not isinstance(application, QApplication):
        application = QApplication([])
    widget = renderer.SynesthesiaRenderer()
    widget._analysis = cast("TrackAnalysis", object())
    widget._conductor = cast("FieldConductor", _ConstantConductor())
    return widget


def test_playing_frames_advance_between_sparse_decoder_position_reports() -> None:
    """A 144 Hz view must not hold and jump on coarse media-clock signals."""

    widget = _renderer_with_constant_conductor()
    widget.set_position_ms(12_000)
    widget.set_playing(True)

    musical_times: list[float] = []
    for _index in range(8):
        widget._advance_field(1.0 / 144.0)
        musical_times.append(widget.latest_frame.musical_time)

    frame_steps = [later - earlier for earlier, later in pairwise(musical_times)]
    assert all(step > 0.0 for step in frame_steps)
    assert frame_steps == pytest.approx([1.0 / 144.0] * 7)
    widget.close()


def test_decoder_clock_error_is_corrected_gradually_at_a_bounded_rate() -> None:
    widget = _renderer_with_constant_conductor()
    frame_seconds = 1.0 / 144.0
    widget.set_position_ms(12_000)
    widget.set_playing(True)
    widget._advance_field(frame_seconds)
    before_report = widget.latest_frame.musical_time

    widget.set_position_ms(12_100)
    widget._advance_field(frame_seconds)
    corrected_step = widget.latest_frame.musical_time - before_report

    assert corrected_step > frame_seconds
    assert corrected_step <= frame_seconds * (
        1.0 + renderer._MAX_PLAYBACK_RATE_CORRECTION
    )
    assert widget.latest_frame.musical_time < 12.1
    widget.close()


def test_small_backward_decoder_jitter_never_regresses_musical_time() -> None:
    widget = _renderer_with_constant_conductor()
    frame_seconds = 1.0 / 144.0
    widget.set_position_ms(5_000)
    widget.set_playing(True)
    widget._advance_field(frame_seconds)
    widget._advance_field(frame_seconds)
    before_report = widget.latest_frame.musical_time

    widget.set_position_ms(5_005)
    widget._advance_field(frame_seconds)
    after_report = widget.latest_frame.musical_time

    assert after_report > before_report
    assert after_report - before_report < frame_seconds
    widget.close()


def test_pause_freezes_clock_without_accumulating_elapsed_time() -> None:
    widget = _renderer_with_constant_conductor()
    frame_seconds = 1.0 / 144.0
    widget.set_position_ms(3_000)
    widget.set_playing(True)
    widget._advance_field(frame_seconds)
    widget._advance_field(frame_seconds)
    paused_at = widget.latest_frame.musical_time
    paused_phases = widget._motion_phases.uniform_values()

    widget.set_playing(False)
    for _index in range(20):
        widget._advance_field(frame_seconds)

    assert widget.latest_frame.musical_time == pytest.approx(paused_at)
    assert widget._motion_phases.uniform_values() == paused_phases
    widget.set_playing(True)
    widget._advance_field(frame_seconds)
    assert widget.latest_frame.musical_time == pytest.approx(paused_at)
    widget._advance_field(frame_seconds)
    assert widget.latest_frame.musical_time == pytest.approx(paused_at + frame_seconds)
    widget.close()


def test_relocate_resets_clock_exactly_and_starts_the_new_epoch() -> None:
    widget = _renderer_with_constant_conductor()
    frame_seconds = 1.0 / 144.0
    widget.set_position_ms(12_000)
    widget.set_playing(True)
    widget._advance_field(frame_seconds)
    phases_before_seek = widget._motion_phases.uniform_values()

    widget.relocate(2_000, 1)
    widget._advance_field(0.0)

    assert widget.latest_frame.musical_time == pytest.approx(2.0)
    assert widget.latest_frame.transport_epoch == 1
    assert widget._motion_phases.uniform_values() == phases_before_seek
    widget._advance_field(frame_seconds)
    assert widget.latest_frame.musical_time == pytest.approx(2.0 + frame_seconds)
    widget.close()


def test_clock_reset_discards_correction_and_clamps_to_track_duration() -> None:
    clock = renderer._PlaybackClock()
    clock.reset(9.0, duration_seconds=10.0)
    clock.set_playing(True)
    clock.observe(9.5)
    clock.reset(9.99, duration_seconds=10.0)

    assert clock.advance(0.0) == pytest.approx(9.99)
    assert clock.advance(1.0 / 30.0) == pytest.approx(10.0)
    clock.observe(12.0)
    assert clock.advance(1.0) == pytest.approx(10.0)


def test_preview_starts_without_analysis_and_follows_player_pause_and_seek() -> None:
    widget = renderer.SynesthesiaRenderer()
    widget.set_preview(17, None)
    widget.relocate(12_000, 1)
    widget.set_playing(True)
    widget._advance_field(1.0 / 60.0)
    widget._advance_field(1.0 / 60.0)

    assert widget.latest_frame.musical_time > 12.0
    assert widget.latest_frame.forcing.activity > FieldForcing().activity
    assert widget._analysis is None
    assert widget._world.genesis.experience_seed == 17

    widget.set_playing(False)
    paused_time = widget.latest_frame.musical_time
    widget._advance_field(1.0)
    assert widget.latest_frame.musical_time == paused_time

    widget.relocate(42_000, 2)
    widget._advance_field(0.0)
    assert widget.latest_frame.musical_time == pytest.approx(42.0)
    widget.close()


def test_analysis_handoff_preserves_field_and_blends_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Metadata:
        duration_seconds = 10.0

    class _Analysis:
        metadata = _Metadata()

    class _Director:
        def __init__(self, _analysis: object, *, experience_seed: int) -> None:
            assert experience_seed == 17

        def sample(self, _seconds: float) -> object:
            return idle_scene_moment()

    monkeypatch.setattr(renderer, "FieldConductor", _ConstantConductor)
    monkeypatch.setattr(renderer, "SceneDirector", _Director)
    widget = renderer.SynesthesiaRenderer()
    widget.set_preview(17, 180.0)
    widget.set_playing(True)
    widget.relocate(12_000, 1)
    widget._advance_field(1.0 / 60.0)
    world = widget._world
    phases = widget._motion_phases
    revision = widget.latest_frame.revision
    widget._particle_reset_pending = False
    widget._history_needs_clear = False

    widget.set_analysis(cast("TrackAnalysis", _Analysis()))
    widget.set_position_ms(12_000)
    assert widget._world is world
    assert widget._motion_phases is phases
    assert widget.latest_frame.revision == revision
    assert not widget._particle_reset_pending
    assert not widget._history_needs_clear

    widget._advance_field(0.1)
    assert widget.latest_frame.revision > revision
    assert widget.latest_frame.musical_time > 12.0
    assert widget._handoff_seconds == pytest.approx(0.1)
    assert widget.latest_frame.forcing.activity > FieldForcing().activity
    assert not widget.latest_frame.forcing.impulses

    widget.set_playing(False)
    widget._advance_field(1.0)
    assert widget._handoff_seconds == pytest.approx(0.1)
    widget.set_playing(True)
    for _ in range(24):
        widget._advance_field(0.1)
    assert widget._preview is None
    assert widget._world is world
    assert widget.latest_frame.transport_epoch == 1
    assert widget._motion_phases is phases
    assert phases.travel > 0.0
    widget.set_preview(23, 180.0)
    assert widget._motion_phases.uniform_values() == (0.0,) * 16
    widget.close()


def test_analysis_handoff_blends_scene_and_camera_before_reaching_target() -> None:
    preview = idle_scene_moment()
    analyzed = replace(
        preview,
        primary=VisualScene.SOLAR_BLOOM,
        secondary=VisualScene.SOLAR_BLOOM,
        camera_pose=CameraPose((2.0, 1.0, 3.0), (0.0, 0.0, 0.0), 0.2, 50.0),
    )

    start = renderer._blend_preview_scene(preview, analyzed, 0.0)
    middle = renderer._blend_preview_scene(preview, analyzed, 0.5)
    end = renderer._blend_preview_scene(preview, analyzed, 1.0)

    assert start.blend == 0.0
    assert middle.primary is preview.primary
    assert middle.secondary is analyzed.primary
    assert middle.blend == pytest.approx(0.5)
    assert middle.camera_pose != preview.camera_pose
    assert middle.camera_pose != analyzed.camera_pose
    assert end == analyzed
