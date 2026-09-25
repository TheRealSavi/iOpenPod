"""Motion must respond to rates without rewriting already travelled distance."""

from dataclasses import replace

import pytest

from iOpenPod.GUI.synesthesia.motion_phases import MotionPhases
from iOpenPod.GUI.synesthesia.persistent_world import FieldForcing
from iOpenPod.GUI.synesthesia.scene_director import idle_scene_moment


@pytest.mark.parametrize("age_seconds", [0.0, 300.0, 3600.0])
def test_new_motion_does_not_depend_on_how_long_the_field_has_run(
    age_seconds: float,
) -> None:
    motion = idle_scene_moment().motion
    forcing = FieldForcing(activity=0.8, fine_excitation=0.7)
    phases = MotionPhases()
    phases.advance(age_seconds, motion, forcing)
    before = phases.uniform_values()

    changed_motion = replace(
        motion,
        direction_x=-motion.direction_x,
        direction_y=-motion.direction_y,
        travel_rate=motion.travel_rate * 0.5,
        orbit_rate=-motion.orbit_rate,
        depth_rate=motion.depth_rate * 0.5,
    )
    quieter = replace(forcing, activity=0.2, fine_excitation=0.1)
    phases.advance(1.0 / 60.0, changed_motion, quieter)
    just_started = MotionPhases()
    just_started.advance(1.0 / 60.0, changed_motion, quieter)

    increments = tuple(
        after - previous
        for after, previous in zip(phases.uniform_values(), before, strict=True)
    )
    assert increments == pytest.approx(just_started.uniform_values(), abs=1e-10)
    assert max(abs(increment) for increment in increments) < 0.05


@pytest.mark.parametrize("frames_per_second", [30, 60, 144])
def test_constant_motion_covers_the_same_distance_at_different_frame_rates(
    frames_per_second: int,
) -> None:
    motion = idle_scene_moment().motion
    forcing = FieldForcing(activity=0.6, harmonic_layer=0.7, vocal_layer=0.5)
    reference = MotionPhases()
    reference.advance(10.0, motion, forcing)
    sampled = MotionPhases()
    for _ in range(10 * frames_per_second):
        sampled.advance(1.0 / frames_per_second, motion, forcing)
    assert sampled.uniform_values() == pytest.approx(reference.uniform_values())


def test_falling_energy_slows_forward_motion_without_reversing_it() -> None:
    motion = idle_scene_moment().motion
    phases = MotionPhases()
    phases.advance(300.0, motion, FieldForcing(activity=0.9))
    before = phases.energy_journey
    phases.advance(1.0 / 60.0, motion, FieldForcing(activity=0.9))
    fast_step = phases.energy_journey - before
    before = phases.energy_journey
    phases.advance(1.0 / 60.0, motion, FieldForcing(activity=0.1))
    slow_step = phases.energy_journey - before
    assert 0.0 < slow_step < fast_step
