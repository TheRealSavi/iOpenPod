"""Choose durable visual Scenes from complete-song musical evidence."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from enum import IntEnum
from itertools import pairwise
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from iOpenPod.app.synesthesia import (
        MusicalEvent,
        MusicFrame,
        MusicSection,
        SignalSample,
        TrackAnalysis,
        VectorSample,
    )

_MIN_SCENE_SECONDS: Final = 2.0
_MAX_SCENE_SECONDS: Final = 22.0
_TRANSITION_SECONDS: Final = 3.2
_CAMERA_SECONDS_PER_SHOT: Final = 6.0
_MIN_CAMERA_SHOT_SECONDS: Final = 0.10
_MAX_CAMERA_ENDPOINT_TRAVEL_PER_SECOND: Final = 1.9
_MAX_CAMERA_ENDPOINT_ANGLE_RADIANS_PER_SECOND: Final = math.radians(24.0)
_MAX_CAMERA_ENDPOINT_FOV_DEGREES_PER_SECOND: Final = 6.0
_MAX_CAMERA_ENDPOINT_ROLL_RADIANS_PER_SECOND: Final = 0.12


class VisualScene(IntEnum):
    """Renderer scene vocabulary, ordered to match the GPU uniform contract."""

    MAGNETOSPHERE = 0
    RIBBON_CASCADE = 1
    WARP_TUNNEL = 2
    MIRROR_WAVE = 3
    PRISMATIC_VEIL = 4
    LATTICE_CATHEDRAL = 5
    SOLAR_BLOOM = 6
    STAR_CHAMBER = 7
    CONTOUR_DRIFT = 8
    CRYSTAL_SHOAL = 9
    BRAIDED_CURRENT = 10
    SIGNAL_RAIN = 11


_RADIAL_SCENES: Final = frozenset(
    (VisualScene.MAGNETOSPHERE, VisualScene.WARP_TUNNEL, VisualScene.SOLAR_BLOOM)
)


class CameraShotKind(IntEnum):
    """Small editorial vocabulary used to compose one Scene residence."""

    ESTABLISHING = 0
    TRACK = 1
    ORBIT = 2
    INSPECTION = 3
    FLY_THROUGH = 4
    REVEAL = 5


@dataclass(frozen=True, slots=True)
class CameraPose:
    """One fully directed, renderer-ready camera pose."""

    position: tuple[float, float, float]
    target: tuple[float, float, float]
    roll_radians: float
    field_of_view_degrees: float

    def __post_init__(self) -> None:
        values = (*self.position, *self.target, self.roll_radians)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Camera pose values must be finite")
        if not 24.0 <= self.field_of_view_degrees <= 72.0:
            raise ValueError("Camera field of view must be in [24, 72] degrees")
        if math.dist(self.position, self.target) < 0.2:
            raise ValueError("Camera position must remain separate from its target")

    def interpolated(self, other: CameraPose, amount: float) -> CameraPose:
        bounded = _smootherstep(amount)
        return CameraPose(
            position=_mix_vector(self.position, other.position, bounded),
            target=_mix_vector(self.target, other.target, bounded),
            roll_radians=_mix(self.roll_radians, other.roll_radians, bounded),
            field_of_view_degrees=_mix(
                self.field_of_view_degrees,
                other.field_of_view_degrees,
                bounded,
            ),
        )


@dataclass(frozen=True, slots=True)
class CameraShot:
    """One bounded composition within a longer Scene residence."""

    identity: str
    kind: CameraShotKind
    start_seconds: float
    end_seconds: float

    def __post_init__(self) -> None:
        if not self.identity.strip():
            raise ValueError("A Camera Shot requires an identity")
        if (
            not math.isfinite(self.start_seconds)
            or not math.isfinite(self.end_seconds)
            or self.start_seconds < 0.0
            or self.end_seconds <= self.start_seconds
        ):
            raise ValueError("A Camera Shot requires a positive finite span")


@dataclass(frozen=True, slots=True)
class MoodSignature:
    """Presentation-owned mood axes derived from calibrated Musical Evidence."""

    energy: float
    brightness: float
    harmony: float
    percussion: float
    bass: float
    width: float
    noise: float

    def __post_init__(self) -> None:
        for name, value in (
            ("energy", self.energy),
            ("brightness", self.brightness),
            ("harmony", self.harmony),
            ("percussion", self.percussion),
            ("bass", self.bass),
            ("width", self.width),
            ("noise", self.noise),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"Mood {name} must be finite and in [0, 1]")


@dataclass(frozen=True, slots=True)
class SceneTuning:
    """Relative visibility of the shared field projections in one Scene."""

    particles: float
    comets: float
    filaments: float
    events: float

    def interpolated(self, other: SceneTuning, amount: float) -> SceneTuning:
        bounded = min(1.0, max(0.0, amount))
        return SceneTuning(
            particles=_mix(self.particles, other.particles, bounded),
            comets=_mix(self.comets, other.comets, bounded),
            filaments=_mix(self.filaments, other.filaments, bounded),
            events=_mix(self.events, other.events, bounded),
        )


@dataclass(frozen=True, slots=True)
class SceneMotion:
    """Continuous world and waveform choreography for one Scene residence."""

    direction_x: float
    direction_y: float
    travel_rate: float
    orbit_rate: float
    depth_rate: float
    waveform_gain: float
    parallax: float
    world_scale: float

    def __post_init__(self) -> None:
        values = (
            self.direction_x,
            self.direction_y,
            self.travel_rate,
            self.orbit_rate,
            self.depth_rate,
            self.waveform_gain,
            self.parallax,
            self.world_scale,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Scene motion values must be finite")
        if not math.isclose(
            math.hypot(self.direction_x, self.direction_y),
            1.0,
            rel_tol=1e-6,
            abs_tol=1e-6,
        ):
            raise ValueError("Scene motion direction must be normalized")
        if (
            min(
                self.travel_rate,
                self.depth_rate,
                self.waveform_gain,
                self.parallax,
            )
            < 0.0
        ):
            raise ValueError("Scene motion magnitudes must be non-negative")
        if self.world_scale <= 0.0:
            raise ValueError("Scene world scale must be positive")

    def interpolated(self, other: SceneMotion, amount: float) -> SceneMotion:
        bounded = min(1.0, max(0.0, amount))
        start_heading = math.atan2(self.direction_y, self.direction_x)
        end_heading = math.atan2(other.direction_y, other.direction_x)
        heading_delta = (end_heading - start_heading + math.pi) % math.tau - math.pi
        if math.isclose(abs(heading_delta), math.pi, abs_tol=1e-6):
            # Antipodal headings have two equally short routes. Always taking the
            # positive route prevents floating-point noise from changing the cut.
            heading_delta = math.pi
        heading = start_heading + heading_delta * bounded
        return SceneMotion(
            direction_x=math.cos(heading),
            direction_y=math.sin(heading),
            travel_rate=_mix(self.travel_rate, other.travel_rate, bounded),
            orbit_rate=_mix(self.orbit_rate, other.orbit_rate, bounded),
            depth_rate=_mix(self.depth_rate, other.depth_rate, bounded),
            waveform_gain=_mix(self.waveform_gain, other.waveform_gain, bounded),
            parallax=_mix(self.parallax, other.parallax, bounded),
            world_scale=_mix(self.world_scale, other.world_scale, bounded),
        )


@dataclass(frozen=True, slots=True)
class _PlannedCameraShot:
    shot: CameraShot
    start_pose: CameraPose
    end_pose: CameraPose
    position_arc: tuple[float, float, float]
    target_arc: tuple[float, float, float]

    def sample(self, seconds: float) -> CameraPose:
        progress = _unit(
            (seconds - self.shot.start_seconds)
            / (self.shot.end_seconds - self.shot.start_seconds)
        )
        eased = _smootherstep(progress)
        landing_arc = math.sin(math.pi * progress) ** 2
        position = _add_vector(
            _mix_vector(self.start_pose.position, self.end_pose.position, eased),
            _scale_vector(self.position_arc, landing_arc),
        )
        target = _add_vector(
            _mix_vector(self.start_pose.target, self.end_pose.target, eased),
            _scale_vector(self.target_arc, landing_arc),
        )
        return CameraPose(
            position=position,
            target=target,
            roll_radians=_mix(
                self.start_pose.roll_radians,
                self.end_pose.roll_radians,
                eased,
            ),
            field_of_view_degrees=_mix(
                self.start_pose.field_of_view_degrees,
                self.end_pose.field_of_view_degrees,
                eased,
            ),
        )


@dataclass(frozen=True, slots=True)
class _CameraSequence:
    planned_shots: tuple[_PlannedCameraShot, ...]

    def __post_init__(self) -> None:
        if not self.planned_shots:
            raise ValueError("A Camera Sequence requires at least one shot")
        for previous, following in zip(
            self.planned_shots,
            self.planned_shots[1:],
            strict=False,
        ):
            if not math.isclose(
                previous.shot.end_seconds,
                following.shot.start_seconds,
                abs_tol=1e-9,
            ):
                raise ValueError("Camera Shots must form a contiguous sequence")
            if previous.end_pose != following.start_pose:
                raise ValueError("Camera Shot poses must meet at every edit")

    @property
    def shots(self) -> tuple[CameraShot, ...]:
        return tuple(planned.shot for planned in self.planned_shots)

    @property
    def first_pose(self) -> CameraPose:
        return self.planned_shots[0].start_pose

    @property
    def final_pose(self) -> CameraPose:
        return self.planned_shots[-1].end_pose

    def sample(self, seconds: float) -> CameraPose:
        return self._planned_shot_at(seconds).sample(seconds)

    def moment(
        self,
        seconds: float,
    ) -> tuple[CameraShot, CameraPose, float, float]:
        planned = self._planned_shot_at(seconds)
        span = planned.shot.end_seconds - planned.shot.start_seconds
        progress = _unit((seconds - planned.shot.start_seconds) / span)
        travel = _distance(planned.start_pose.position, planned.end_pose.position)
        lens_change = abs(
            planned.end_pose.field_of_view_degrees
            - planned.start_pose.field_of_view_degrees
        )
        motion = _unit((travel / span) * 0.42 + (lens_change / span) * 0.035)
        motion *= math.sin(math.pi * progress) ** 2
        return planned.shot, planned.sample(seconds), progress, motion

    def bridged_from(self, pose: CameraPose) -> _CameraSequence:
        bridged: list[_PlannedCameraShot] = []
        start_pose = pose
        for planned in self.planned_shots:
            span = planned.shot.end_seconds - planned.shot.start_seconds
            end_pose = _limited_camera_destination(
                start_pose,
                planned.end_pose,
                span,
            )
            bridged.append(
                _PlannedCameraShot(
                    planned.shot,
                    start_pose,
                    end_pose,
                    planned.position_arc,
                    planned.target_arc,
                )
            )
            start_pose = end_pose
        return _CameraSequence(tuple(bridged))

    def _planned_shot_at(self, seconds: float) -> _PlannedCameraShot:
        if seconds <= self.planned_shots[0].shot.start_seconds:
            return self.planned_shots[0]
        if seconds >= self.planned_shots[-1].shot.end_seconds:
            return self.planned_shots[-1]
        return next(
            (
                planned
                for planned in self.planned_shots
                if planned.shot.start_seconds <= seconds < planned.shot.end_seconds
            ),
            self.planned_shots[-1],
        )


@dataclass(frozen=True, slots=True)
class SceneCue:
    """One bounded scene residence planned against the Track timeline."""

    start_seconds: float
    end_seconds: float
    scene: VisualScene
    mood: MoodSignature
    motion: SceneMotion
    development: float
    camera_sequence: _CameraSequence


@dataclass(frozen=True, slots=True)
class SceneMoment:
    """Two-scene crossfade and shared-system tuning for one rendered frame."""

    primary: VisualScene
    secondary: VisualScene
    blend: float
    transition_energy: float
    tuning: SceneTuning
    motion: SceneMotion
    camera_shot: CameraShot
    camera_pose: CameraPose
    camera_progress: float
    camera_motion: float

    def __post_init__(self) -> None:
        for name, value in (
            ("blend", self.blend),
            ("transition energy", self.transition_energy),
            ("camera progress", self.camera_progress),
            ("camera motion", self.camera_motion),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"Scene {name} must be finite and in [0, 1]")


@dataclass(frozen=True, slots=True)
class _MotionProfile:
    heading: float
    heading_jitter: float
    travel_rate: float
    orbit_rate: float
    depth_rate: float
    waveform_gain: float
    parallax: float
    world_scale: float


@dataclass(frozen=True, slots=True)
class _CameraGrammar:
    kinds: tuple[CameraShotKind, ...]
    poses: tuple[CameraPose, ...]
    position_arcs: tuple[tuple[float, float, float], ...]
    target_arcs: tuple[tuple[float, float, float], ...]


_SCENE_TUNING: Final = {
    VisualScene.MAGNETOSPHERE: SceneTuning(1.30, 0.62, 0.30, 1.28),
    VisualScene.RIBBON_CASCADE: SceneTuning(0.30, 0.42, 0.82, 0.92),
    VisualScene.WARP_TUNNEL: SceneTuning(1.18, 1.52, 0.12, 1.34),
    VisualScene.MIRROR_WAVE: SceneTuning(0.16, 0.18, 0.54, 1.00),
    VisualScene.PRISMATIC_VEIL: SceneTuning(0.22, 0.20, 0.92, 0.82),
    VisualScene.LATTICE_CATHEDRAL: SceneTuning(0.12, 0.08, 1.22, 0.72),
    VisualScene.SOLAR_BLOOM: SceneTuning(0.72, 0.56, 0.34, 1.58),
    VisualScene.STAR_CHAMBER: SceneTuning(0.88, 0.38, 0.12, 1.12),
    VisualScene.CONTOUR_DRIFT: SceneTuning(0.08, 0.0, 0.12, 0.48),
    VisualScene.CRYSTAL_SHOAL: SceneTuning(0.18, 0.12, 0.0, 0.62),
    VisualScene.BRAIDED_CURRENT: SceneTuning(0.14, 0.26, 0.18, 0.72),
    VisualScene.SIGNAL_RAIN: SceneTuning(0.06, 0.0, 0.0, 0.58),
}

_MOTION_PROFILES: Final = {
    VisualScene.MAGNETOSPHERE: _MotionProfile(
        1.57, 0.62, 0.18, 0.34, 0.42, 0.54, 0.82, 0.94
    ),
    VisualScene.RIBBON_CASCADE: _MotionProfile(
        0.00, 0.24, 0.82, 0.07, 0.26, 1.36, 0.58, 0.82
    ),
    VisualScene.WARP_TUNNEL: _MotionProfile(
        0.00, 3.14, 1.72, 0.22, 2.24, 0.68, 1.48, 0.78
    ),
    VisualScene.MIRROR_WAVE: _MotionProfile(
        1.57, 0.18, 0.44, -0.16, 0.28, 1.72, 0.42, 0.88
    ),
    VisualScene.PRISMATIC_VEIL: _MotionProfile(
        0.36, 0.42, 0.68, 0.12, 0.78, 1.18, 0.96, 0.76
    ),
    VisualScene.LATTICE_CATHEDRAL: _MotionProfile(
        -1.57, 0.15, 1.08, 0.04, 1.68, 0.62, 1.24, 0.84
    ),
    VisualScene.SOLAR_BLOOM: _MotionProfile(
        2.42, 0.48, 0.24, 0.46, 0.52, 0.92, 0.68, 1.04
    ),
    VisualScene.STAR_CHAMBER: _MotionProfile(
        0.18, 0.82, 0.94, 0.03, 1.18, 0.38, 1.74, 0.72
    ),
    VisualScene.CONTOUR_DRIFT: _MotionProfile(
        0.62, 0.28, 0.42, -0.05, 0.24, 0.86, 0.54, 0.92
    ),
    VisualScene.CRYSTAL_SHOAL: _MotionProfile(
        -0.48, 0.36, 0.76, 0.18, 0.92, 0.64, 1.32, 0.86
    ),
    VisualScene.BRAIDED_CURRENT: _MotionProfile(
        1.24, 0.20, 0.88, -0.12, 0.48, 1.48, 0.72, 0.90
    ),
    VisualScene.SIGNAL_RAIN: _MotionProfile(
        -1.57, 0.12, 1.36, 0.0, 0.62, 0.72, 1.12, 0.80
    ),
}


def _pose(
    position: tuple[float, float, float],
    target: tuple[float, float, float],
    field_of_view_degrees: float,
    roll_radians: float = 0.0,
) -> CameraPose:
    return CameraPose(position, target, roll_radians, field_of_view_degrees)


_CAMERA_GRAMMARS: Final = {
    VisualScene.MAGNETOSPHERE: _CameraGrammar(
        (
            CameraShotKind.ESTABLISHING,
            CameraShotKind.ORBIT,
            CameraShotKind.INSPECTION,
            CameraShotKind.REVEAL,
        ),
        (
            _pose((-5.8, 2.3, 8.4), (-0.5, 0.1, 0.0), 56.0),
            _pose((4.6, 1.4, 5.8), (0.4, 0.0, 0.1), 46.0, 0.04),
            _pose((1.3, 0.5, 3.0), (0.0, 0.3, 0.0), 34.0, -0.03),
            _pose((-3.8, -1.0, 5.5), (0.1, -0.1, 0.2), 43.0, -0.05),
            _pose((0.4, 3.2, 9.3), (0.0, 0.0, 0.0), 60.0),
        ),
        ((0.3, 1.1, -0.7), (-0.7, 0.5, -0.4), (0.4, -0.8, 0.2), (0.0, 0.9, 0.7)),
        ((0.2, 0.1, 0.0), (-0.2, 0.2, 0.1), (0.15, -0.1, 0.0), (0.0, 0.0, 0.0)),
    ),
    VisualScene.RIBBON_CASCADE: _CameraGrammar(
        (
            CameraShotKind.ESTABLISHING,
            CameraShotKind.TRACK,
            CameraShotKind.FLY_THROUGH,
            CameraShotKind.REVEAL,
        ),
        (
            _pose((-5.4, 3.0, 7.6), (-0.8, 0.0, 0.0), 54.0, -0.05),
            _pose((-2.8, 0.8, 4.7), (0.5, 0.1, -0.3), 43.0, 0.03),
            _pose((0.3, -0.1, 2.5), (2.1, 0.2, -1.0), 35.0, 0.06),
            _pose((3.5, 1.1, 3.8), (0.6, 0.4, -0.4), 42.0, -0.04),
            _pose((5.8, 3.7, 8.8), (0.0, 0.1, 0.0), 59.0),
        ),
        ((0.6, -0.5, -0.4), (0.3, 0.8, -0.6), (-0.5, -0.4, -0.8), (-0.7, 0.5, 0.6)),
        ((0.5, 0.2, -0.2), (0.7, 0.0, -0.4), (-0.5, 0.3, 0.0), (-0.2, 0.1, 0.0)),
    ),
    VisualScene.WARP_TUNNEL: _CameraGrammar(
        (
            CameraShotKind.ESTABLISHING,
            CameraShotKind.TRACK,
            CameraShotKind.FLY_THROUGH,
            CameraShotKind.REVEAL,
        ),
        (
            _pose((-3.8, 2.0, 8.8), (0.0, 0.0, -1.5), 58.0, -0.05),
            _pose((-1.2, 0.5, 4.6), (0.0, 0.0, -2.8), 45.0, 0.02),
            _pose((0.2, 0.1, 2.8), (0.0, 0.0, -1.8), 36.0),
            _pose((0.8, -0.4, 2.4), (-0.2, 0.2, -1.2), 49.0, 0.09),
            _pose((4.8, 2.6, 8.6), (0.0, 0.0, -1.2), 63.0, -0.07),
        ),
        ((0.7, 0.4, -0.8), (-0.5, 0.3, -0.6), (0.3, 0.2, -0.5), (1.0, -0.5, -0.4)),
        ((0.0, 0.0, -0.4), (0.0, 0.0, -0.4), (0.2, 0.1, -0.35), (-0.4, 0.2, -0.3)),
    ),
    VisualScene.MIRROR_WAVE: _CameraGrammar(
        (
            CameraShotKind.ESTABLISHING,
            CameraShotKind.TRACK,
            CameraShotKind.INSPECTION,
            CameraShotKind.REVEAL,
        ),
        (
            _pose((-5.7, 1.3, 7.2), (0.0, 0.0, 0.0), 53.0),
            _pose((-2.7, -1.0, 4.5), (0.5, 0.2, -0.2), 41.0, -0.04),
            _pose((0.1, 1.1, 3.0), (0.0, 0.0, -0.3), 32.0),
            _pose((3.4, -0.6, 4.2), (-0.4, 0.1, 0.0), 40.0, 0.05),
            _pose((5.6, 2.0, 7.8), (0.0, 0.0, 0.0), 57.0),
        ),
        ((0.4, -0.8, -0.4), (0.8, 0.5, -0.3), (-0.7, -0.5, 0.1), (-0.4, 0.9, 0.5)),
        ((0.4, 0.1, 0.0), (-0.2, 0.2, -0.2), (-0.4, 0.0, 0.1), (0.0, 0.0, 0.0)),
    ),
    VisualScene.PRISMATIC_VEIL: _CameraGrammar(
        (
            CameraShotKind.ESTABLISHING,
            CameraShotKind.FLY_THROUGH,
            CameraShotKind.INSPECTION,
            CameraShotKind.REVEAL,
        ),
        (
            _pose((-4.9, 3.4, 7.9), (-0.4, 0.2, 0.0), 55.0, -0.04),
            _pose((-2.0, 1.2, 4.6), (0.6, -0.1, -0.5), 44.0, 0.06),
            _pose((0.1, 0.0, 2.0), (1.3, 0.4, -1.6), 33.0, 0.08),
            _pose((2.9, -0.4, 3.5), (0.0, 0.3, -0.6), 39.0, -0.05),
            _pose((5.2, 2.8, 8.2), (0.0, 0.0, 0.0), 58.0),
        ),
        ((0.5, -0.6, -0.5), (-0.4, 0.8, -0.8), (0.6, -0.3, -0.5), (-0.8, 0.7, 0.8)),
        ((0.4, 0.0, -0.2), (0.5, 0.3, -0.4), (-0.4, 0.2, 0.0), (0.0, 0.0, 0.0)),
    ),
    VisualScene.LATTICE_CATHEDRAL: _CameraGrammar(
        (
            CameraShotKind.ESTABLISHING,
            CameraShotKind.TRACK,
            CameraShotKind.FLY_THROUGH,
            CameraShotKind.REVEAL,
        ),
        (
            _pose((-2.8, -2.0, 8.6), (0.0, 0.4, -1.0), 54.0),
            _pose((-1.5, -1.4, 5.2), (0.0, 0.6, -2.0), 42.0),
            _pose((0.0, -0.7, 2.6), (0.0, 0.5, -1.8), 34.0),
            _pose((1.4, 1.2, 1.4), (0.0, 0.4, -1.3), 43.0, 0.03),
            _pose((4.3, 4.0, 7.5), (0.0, 0.3, -1.0), 61.0, -0.04),
        ),
        ((0.6, 0.3, -0.7), (-0.4, 0.5, -0.6), (0.3, 0.4, -0.5), (0.8, 1.0, 0.6)),
        ((0.0, 0.4, -0.4), (0.0, 0.4, -0.4), (0.0, 0.2, -0.3), (0.0, 0.1, 0.0)),
    ),
    VisualScene.SOLAR_BLOOM: _CameraGrammar(
        (
            CameraShotKind.ESTABLISHING,
            CameraShotKind.ORBIT,
            CameraShotKind.INSPECTION,
            CameraShotKind.REVEAL,
        ),
        (
            _pose((-5.2, 2.4, 8.0), (0.0, 0.0, 0.0), 55.0),
            _pose((3.7, 1.0, 5.3), (0.1, 0.0, 0.0), 44.0, 0.05),
            _pose((1.8, -0.2, 3.8), (0.0, 0.2, 0.0), 36.0, -0.03),
            _pose((-3.0, -1.2, 4.6), (-0.1, 0.0, 0.0), 41.0, -0.06),
            _pose((0.0, 3.8, 9.7), (0.0, 0.0, 0.0), 62.0),
        ),
        ((0.4, 1.0, -0.8), (-0.8, 0.4, -0.5), (0.5, -0.6, 0.1), (0.2, 1.0, 0.8)),
        ((0.2, 0.1, 0.0), (-0.1, 0.2, 0.0), (-0.2, -0.1, 0.0), (0.0, 0.0, 0.0)),
    ),
    VisualScene.STAR_CHAMBER: _CameraGrammar(
        (
            CameraShotKind.ESTABLISHING,
            CameraShotKind.TRACK,
            CameraShotKind.FLY_THROUGH,
            CameraShotKind.REVEAL,
        ),
        (
            _pose((-6.4, 3.1, 9.2), (0.2, 0.0, -0.8), 57.0, -0.03),
            _pose((-3.1, 1.0, 5.5), (1.2, 0.2, -1.4), 45.0, 0.04),
            _pose((0.0, -0.2, 2.5), (1.7, 0.5, -3.6), 34.0, 0.07),
            _pose((3.0, 1.2, 1.0), (-0.3, 0.2, -4.8), 42.0, -0.05),
            _pose((6.7, 4.0, 9.8), (0.0, 0.0, -1.0), 61.0),
        ),
        ((0.8, -0.4, -0.5), (-0.3, 0.7, -0.9), (0.7, 0.3, -1.0), (-0.8, 0.9, 0.9)),
        ((0.6, 0.1, -0.3), (0.8, 0.2, -0.6), (-0.6, 0.3, -0.4), (0.0, 0.0, 0.0)),
    ),
    VisualScene.CONTOUR_DRIFT: _CameraGrammar(
        (
            CameraShotKind.ESTABLISHING,
            CameraShotKind.TRACK,
            CameraShotKind.INSPECTION,
            CameraShotKind.REVEAL,
        ),
        (
            _pose((-3.8, 3.2, 8.4), (-0.5, 0.2, 0.0), 57.0, -0.12),
            _pose((-1.8, 1.8, 6.2), (0.2, 0.3, 0.0), 48.0, -0.04),
            _pose((1.0, 1.0, 4.8), (0.5, 0.0, 0.0), 40.0, 0.08),
            _pose((3.2, -0.6, 6.0), (0.0, -0.3, 0.0), 47.0, 0.12),
            _pose((1.2, 3.0, 9.4), (0.0, 0.0, 0.0), 60.0),
        ),
        ((0.4, 0.3, 0.0), (0.5, -0.2, -0.3), (0.2, -0.4, 0.1), (-0.4, 0.5, 0.4)),
        ((0.2, 0.2, 0.0), (0.3, -0.1, 0.0), (-0.2, -0.2, 0.0), (0.0, 0.1, 0.0)),
    ),
    VisualScene.CRYSTAL_SHOAL: _CameraGrammar(
        (
            CameraShotKind.ESTABLISHING,
            CameraShotKind.FLY_THROUGH,
            CameraShotKind.INSPECTION,
            CameraShotKind.REVEAL,
        ),
        (
            _pose((-4.2, -1.2, 8.6), (-0.3, 0.0, 0.0), 58.0, 0.05),
            _pose((-1.6, 0.8, 5.2), (0.4, 0.3, -0.2), 47.0, -0.05),
            _pose((0.8, 1.2, 3.6), (0.2, 0.0, -0.4), 38.0, -0.08),
            _pose((3.4, -0.5, 5.1), (-0.4, 0.2, 0.0), 44.0, 0.04),
            _pose((0.8, -2.0, 9.0), (0.0, 0.0, 0.0), 61.0, 0.08),
        ),
        ((0.5, 0.6, -0.4), (0.3, -0.5, -0.4), (-0.4, 0.4, 0.1), (-0.6, -0.4, 0.6)),
        ((0.2, 0.2, -0.1), (0.2, -0.2, -0.1), (-0.3, 0.1, 0.0), (0.0, 0.0, 0.0)),
    ),
    VisualScene.BRAIDED_CURRENT: _CameraGrammar(
        (
            CameraShotKind.ESTABLISHING,
            CameraShotKind.TRACK,
            CameraShotKind.INSPECTION,
            CameraShotKind.REVEAL,
        ),
        (
            _pose((-3.0, -2.6, 8.0), (0.0, -0.4, 0.0), 54.0, -0.16),
            _pose((-1.4, -0.8, 5.6), (0.0, 0.2, 0.0), 44.0, -0.08),
            _pose((1.6, 0.8, 4.0), (0.0, 0.5, -0.2), 37.0, 0.04),
            _pose((2.8, 2.6, 5.8), (0.0, 0.6, 0.0), 46.0, 0.10),
            _pose((-1.0, 3.6, 9.0), (0.0, 0.0, 0.0), 59.0, -0.06),
        ),
        ((0.3, 0.4, -0.3), (-0.4, 0.4, -0.2), (0.3, 0.5, 0.0), (-0.5, 0.4, 0.6)),
        ((0.0, 0.3, 0.0), (0.1, 0.4, 0.0), (-0.1, 0.3, 0.0), (0.0, -0.2, 0.0)),
    ),
    VisualScene.SIGNAL_RAIN: _CameraGrammar(
        (
            CameraShotKind.ESTABLISHING,
            CameraShotKind.TRACK,
            CameraShotKind.FLY_THROUGH,
            CameraShotKind.REVEAL,
        ),
        (
            _pose((-4.0, 2.4, 8.4), (-0.3, 0.4, 0.0), 58.0),
            _pose((-1.5, 0.4, 5.8), (0.4, 0.0, -0.2), 46.0, 0.03),
            _pose((1.2, -1.4, 3.8), (0.2, -0.4, -0.5), 39.0, -0.04),
            _pose((3.2, -2.6, 5.4), (-0.2, -0.6, -0.2), 48.0, -0.06),
            _pose((0.6, 1.0, 9.2), (0.0, 0.0, 0.0), 62.0),
        ),
        ((0.4, -0.5, -0.2), (0.5, -0.4, -0.3), (-0.3, -0.5, 0.1), (-0.5, 0.4, 0.6)),
        ((0.2, -0.3, -0.1), (0.1, -0.3, -0.1), (-0.2, -0.2, 0.0), (0.0, 0.2, 0.0)),
    ),
}


def choose_scene(mood: MoodSignature) -> VisualScene:
    """Return the strongest visual grammar for one mood signature."""

    scores = _scene_scores(mood)
    return max(scores, key=scores.__getitem__)


def plan_scene_motion(
    scene: VisualScene,
    mood: MoodSignature,
    *,
    experience_seed: int,
    cue_identity: str,
) -> SceneMotion:
    """Give one Scene a stable direction and music-scaled movement character."""

    profile = _MOTION_PROFILES[scene]
    direction_variation = _stable_signed(
        experience_seed,
        cue_identity,
        scene.name,
        "direction",
    )
    angle = profile.heading + profile.heading_jitter * direction_variation
    energy_drive = 0.62 + mood.energy * 0.58 + mood.percussion * 0.18
    depth_drive = 0.58 + mood.energy * 0.64 + mood.bass * 0.22
    waveform_drive = (
        0.54 + mood.percussion * 0.48 + mood.harmony * 0.28 + mood.noise * 0.16
    )
    parallax_drive = 0.62 + mood.width * 0.52 + mood.brightness * 0.16
    return SceneMotion(
        direction_x=math.cos(angle),
        direction_y=math.sin(angle),
        travel_rate=profile.travel_rate * energy_drive,
        orbit_rate=profile.orbit_rate * (0.62 + mood.harmony * 0.46 + mood.bass * 0.18),
        depth_rate=profile.depth_rate * depth_drive,
        waveform_gain=profile.waveform_gain * waveform_drive,
        parallax=profile.parallax * parallax_drive,
        world_scale=profile.world_scale * (1.08 - mood.energy * 0.16),
    )


def _plan_camera_sequence(
    scene: VisualScene,
    mood: MoodSignature,
    *,
    experience_seed: int,
    cue_identity: str,
    start_seconds: float,
    duration_seconds: float,
    development: float = 0.5,
    attention_pan: float = 0.0,
    events: tuple[MusicalEvent, ...] = (),
) -> _CameraSequence:
    """Privately compose stable Camera Shots for one Scene residence."""

    if not math.isfinite(start_seconds) or start_seconds < 0.0:
        raise ValueError("Camera sequence start must be finite and non-negative")
    if not math.isfinite(duration_seconds) or duration_seconds <= 0.0:
        raise ValueError("Camera sequence duration must be positive and finite")
    grammar = _CAMERA_GRAMMARS[scene]
    shot_count = min(
        4,
        max(1, math.ceil(duration_seconds / _CAMERA_SECONDS_PER_SHOT)),
    )
    pose_indices = {
        1: (0, 1),
        2: (0, 1, 2),
        3: (0, 1, 2, 3),
        4: (0, 1, 2, 3, 4),
    }[shot_count]
    shot_indices = {
        1: (0,),
        2: (0, 1),
        3: (0, 1, 2),
        4: (0, 1, 2, 3),
    }[shot_count]
    poses = tuple(
        _direct_camera_pose(
            grammar.poses[index],
            mood=mood,
            development=development,
            attention_pan=attention_pan,
            experience_seed=experience_seed,
            cue_identity=cue_identity,
            pose_index=index,
            is_reveal=index == 4,
        )
        for index in pose_indices
    )
    boundaries = [start_seconds]
    for boundary_index in range(1, shot_count):
        ideal = start_seconds + _CAMERA_SECONDS_PER_SHOT * boundary_index
        lower = boundaries[-1] + _MIN_CAMERA_SHOT_SECONDS
        upper = (
            start_seconds
            + duration_seconds
            - _MIN_CAMERA_SHOT_SECONDS * (shot_count - boundary_index)
        )
        boundaries.append(
            _snap_camera_edit(
                ideal,
                lower=lower,
                upper=upper,
                events=events,
            )
        )
    boundaries.append(start_seconds + duration_seconds)
    arc_scale = 0.86 + mood.energy * 0.22 + mood.width * 0.10
    planned: list[_PlannedCameraShot] = []
    start_pose = poses[0]
    for offset, grammar_index in enumerate(shot_indices):
        start = boundaries[offset]
        end = boundaries[offset + 1]
        shot = CameraShot(
            identity=f"{cue_identity}:shot-{offset}:{grammar.kinds[grammar_index].name}",
            kind=grammar.kinds[grammar_index],
            start_seconds=start,
            end_seconds=end,
        )
        arc_variation = 1.0 + 0.12 * _stable_signed(
            experience_seed,
            cue_identity,
            str(offset),
            "arc",
        )
        shot_development = 1.0
        if shot_count > 1 and offset == shot_count - 1:
            shot_development = _smootherstep(
                (end - start - _MIN_CAMERA_SHOT_SECONDS)
                / (_CAMERA_SECONDS_PER_SHOT - _MIN_CAMERA_SHOT_SECONDS)
            )
        desired_end_pose = _camera_pose_toward(
            start_pose,
            poses[offset + 1],
            shot_development,
        )
        end_pose = _limited_camera_destination(
            start_pose,
            desired_end_pose,
            end - start,
        )
        arc_span_scale = min(1.0, (end - start) / 3.0) * shot_development
        planned.append(
            _PlannedCameraShot(
                shot=shot,
                start_pose=start_pose,
                end_pose=end_pose,
                position_arc=_scale_vector(
                    grammar.position_arcs[grammar_index],
                    arc_scale * arc_variation * arc_span_scale,
                ),
                target_arc=_scale_vector(
                    grammar.target_arcs[grammar_index],
                    (0.82 + mood.harmony * 0.18) * arc_span_scale,
                ),
            )
        )
        start_pose = end_pose
    return _CameraSequence(tuple(planned))


def _limited_camera_destination(
    start: CameraPose,
    desired: CameraPose,
    span_seconds: float,
) -> CameraPose:
    """Bound average displacement between consecutive editorial landings."""

    travel = max(
        _distance(start.position, desired.position),
        _distance(start.target, desired.target),
    )
    view_angle = _camera_view_angle(start, desired)
    field_of_view_change = abs(
        desired.field_of_view_degrees - start.field_of_view_degrees
    )
    roll_change = abs(desired.roll_radians - start.roll_radians)
    amount = min(
        1.0,
        _rate_limit_amount(
            travel,
            _MAX_CAMERA_ENDPOINT_TRAVEL_PER_SECOND * span_seconds,
        ),
        _rate_limit_amount(
            view_angle,
            _MAX_CAMERA_ENDPOINT_ANGLE_RADIANS_PER_SECOND * span_seconds,
        ),
        _rate_limit_amount(
            field_of_view_change,
            _MAX_CAMERA_ENDPOINT_FOV_DEGREES_PER_SECOND * span_seconds,
        ),
        _rate_limit_amount(
            roll_change,
            _MAX_CAMERA_ENDPOINT_ROLL_RADIANS_PER_SECOND * span_seconds,
        ),
    )
    return CameraPose(
        position=_mix_vector(start.position, desired.position, amount),
        target=_mix_vector(start.target, desired.target, amount),
        roll_radians=_mix(start.roll_radians, desired.roll_radians, amount),
        field_of_view_degrees=_mix(
            start.field_of_view_degrees,
            desired.field_of_view_degrees,
            amount,
        ),
    )


def _camera_pose_toward(
    start: CameraPose,
    desired: CameraPose,
    amount: float,
) -> CameraPose:
    bounded = _unit(amount)
    return CameraPose(
        position=_mix_vector(start.position, desired.position, bounded),
        target=_mix_vector(start.target, desired.target, bounded),
        roll_radians=_mix(start.roll_radians, desired.roll_radians, bounded),
        field_of_view_degrees=_mix(
            start.field_of_view_degrees,
            desired.field_of_view_degrees,
            bounded,
        ),
    )


def _rate_limit_amount(change: float, maximum_change: float) -> float:
    if change <= 1e-9:
        return 1.0
    return min(1.0, maximum_change / change)


def _camera_view_angle(first: CameraPose, second: CameraPose) -> float:
    first_forward = _normalized_vector(_subtract_vector(first.target, first.position))
    second_forward = _normalized_vector(
        _subtract_vector(second.target, second.position)
    )
    cosine = min(1.0, max(-1.0, _dot_vector(first_forward, second_forward)))
    return math.acos(cosine)


def _direct_camera_pose(
    pose: CameraPose,
    *,
    mood: MoodSignature,
    development: float,
    attention_pan: float,
    experience_seed: int,
    cue_identity: str,
    pose_index: int,
    is_reveal: bool,
) -> CameraPose:
    yaw = 0.10 * _stable_signed(experience_seed, cue_identity, "camera-yaw")
    distance_scale = 0.94 + mood.energy * 0.08
    if is_reveal:
        distance_scale *= 0.90 + _unit(development) * 0.22
    target_shift = (
        (mood.width - 0.5) * 0.24 + min(1.0, max(-1.0, attention_pan)) * 0.48,
        (mood.harmony - 0.5) * 0.22,
        (mood.bass - 0.5) * -0.18,
    )
    target = _add_vector(_yaw_vector(pose.target, yaw), target_shift)
    relative_position = _subtract_vector(pose.position, pose.target)
    relative_position = _scale_vector(
        _yaw_vector(relative_position, yaw), distance_scale
    )
    position = _add_vector(target, relative_position)
    pose_roll = 0.025 * _stable_signed(
        experience_seed,
        cue_identity,
        str(pose_index),
        "roll",
    )
    fov = pose.field_of_view_degrees + (mood.brightness - 0.5) * 2.4
    return CameraPose(
        position=position,
        target=target,
        roll_radians=pose.roll_radians + pose_roll,
        field_of_view_degrees=min(72.0, max(24.0, fov)),
    )


def _snap_camera_edit(
    ideal: float,
    *,
    lower: float,
    upper: float,
    events: tuple[MusicalEvent, ...],
) -> float:
    """Move an edit only to nearby, trustworthy musical punctuation."""

    window = min(0.80, max(0.0, (upper - lower) * 0.34))
    candidates: list[tuple[float, float, float]] = []
    for event in events:
        if not lower <= event.seconds <= upper or abs(event.seconds - ideal) > window:
            continue
        kind = getattr(event.kind, "value", str(event.kind))
        kind_weight = {
            "section-boundary": 1.00,
            "source-entrance": 0.92,
            "downbeat": 0.86,
            "beat": 0.48,
        }.get(kind, 0.0)
        minimum_confidence = 0.50 if kind == "beat" else 0.40
        minimum_strength = 0.62 if kind == "beat" else 0.35
        if (
            kind_weight <= 0.0
            or event.confidence < minimum_confidence
            or event.strength < minimum_strength
        ):
            continue
        salience = kind_weight * event.confidence * (0.55 + 0.45 * event.strength)
        proximity = 1.0 - abs(event.seconds - ideal) / max(window, 1e-6)
        candidates.append((salience + proximity * 0.28, proximity, event.seconds))
    if not candidates:
        return min(upper, max(lower, ideal))
    return max(candidates)[2]


def idle_scene_moment() -> SceneMoment:
    """Return a calm Scene for the field before a Track is available."""

    return _IDLE_SCENE_MOMENT


class SceneDirector:
    """Plan varied Scenes, then crossfade without changing analysis semantics."""

    def __init__(self, analysis: TrackAnalysis, *, experience_seed: int) -> None:
        self._analysis = analysis
        self._experience_seed = experience_seed
        self._cues = self._build_cues()

    @property
    def cues(self) -> tuple[SceneCue, ...]:
        return self._cues

    def sample(self, seconds: float) -> SceneMoment:
        bounded = min(
            self._analysis.metadata.duration_seconds,
            max(0.0, seconds),
        )
        cue_index = next(
            (
                index
                for index, cue in enumerate(self._cues)
                if cue.start_seconds <= bounded < cue.end_seconds
            ),
            len(self._cues) - 1,
        )
        cue = self._cues[cue_index]
        camera_shot, camera_pose, camera_progress, camera_motion = (
            cue.camera_sequence.moment(bounded)
        )
        if cue_index == 0:
            return _settled_moment(
                cue,
                camera_shot=camera_shot,
                camera_pose=camera_pose,
                camera_progress=camera_progress,
                camera_motion=camera_motion,
            )
        elapsed = bounded - cue.start_seconds
        transition_seconds = min(
            _TRANSITION_SECONDS,
            max(1.2, (cue.end_seconds - cue.start_seconds) * 0.24),
        )
        if elapsed >= transition_seconds:
            return _settled_moment(
                cue,
                camera_shot=camera_shot,
                camera_pose=camera_pose,
                camera_progress=camera_progress,
                camera_motion=camera_motion,
            )
        previous_cue = self._cues[cue_index - 1]
        previous = previous_cue.scene
        progress = min(1.0, max(0.0, elapsed / transition_seconds))
        blend = progress * progress * (3.0 - 2.0 * progress)
        tuning = _SCENE_TUNING[previous].interpolated(_SCENE_TUNING[cue.scene], blend)
        motion = previous_cue.motion.interpolated(cue.motion, blend)
        return SceneMoment(
            primary=previous,
            secondary=cue.scene,
            blend=blend,
            transition_energy=4.0 * blend * (1.0 - blend),
            tuning=tuning,
            motion=motion,
            camera_shot=camera_shot,
            camera_pose=camera_pose,
            camera_progress=camera_progress,
            camera_motion=camera_motion,
        )

    def _build_cues(self) -> tuple[SceneCue, ...]:
        cues: list[SceneCue] = []
        recent: list[VisualScene] = []
        usage = dict.fromkeys(VisualScene, 0)
        previous_camera_pose: CameraPose | None = None
        section_boundaries = _normalized_section_boundaries(
            self._analysis.sections,
            self._analysis.metadata.duration_seconds,
        )
        residences = _scene_residence_boundaries(section_boundaries)
        for cue_index, (start, end) in enumerate(pairwise(residences)):
            mood, development, attention_pan = self._scene_evidence(start, end)
            section = self._analysis.section_at(start)
            cue_identity = f"{section.section_id}:{cue_index}"
            scene = self._choose_varied_scene(
                mood,
                cue_identity=cue_identity,
                recent=tuple(recent[-5:]),
                usage=usage,
            )
            motion = plan_scene_motion(
                scene,
                mood,
                experience_seed=self._experience_seed,
                cue_identity=cue_identity,
            )
            camera_sequence = _plan_camera_sequence(
                scene,
                mood,
                experience_seed=self._experience_seed,
                cue_identity=cue_identity,
                start_seconds=start,
                duration_seconds=end - start,
                development=development,
                attention_pan=attention_pan,
                events=self._analysis.events_between(start, end),
            )
            if previous_camera_pose is not None:
                camera_sequence = camera_sequence.bridged_from(previous_camera_pose)
            cues.append(
                SceneCue(start, end, scene, mood, motion, development, camera_sequence)
            )
            previous_camera_pose = camera_sequence.final_pose
            recent.append(scene)
            usage[scene] += 1
        return tuple(cues)

    def _scene_evidence(
        self,
        start_seconds: float,
        end_seconds: float,
    ) -> tuple[MoodSignature, float, float]:
        """Calibrate a cue from interval evidence instead of one frozen midpoint."""

        span = end_seconds - start_seconds
        sample_spacing = max(
            self._analysis.timeline.grid.step_seconds * 2.0,
            0.12,
        )
        sample_count = min(128, max(9, math.ceil(span / sample_spacing)))
        frames = tuple(
            self._analysis.sample(
                start_seconds + span * (sample_index + 0.5) / sample_count
            )
            for sample_index in range(sample_count)
        )
        energy_samples = tuple(
            _reliable_value(frame.energy.relative, fallback=0.0) for frame in frames
        )
        brightness_samples = tuple(
            _perceptual_brightness(frame, fallback=0.42) for frame in frames
        )
        harmony_samples = tuple(
            _reliable_value(frame.harmony.coherence, fallback=0.5) for frame in frames
        )
        percussive_layer_samples = tuple(
            _reliable_value(frame.layers.percussive, fallback=0.0) for frame in frames
        )
        onset_samples = tuple(
            _reliable_value(frame.rhythm.onset_strength, fallback=0.0)
            for frame in frames
        )
        pulse_samples = tuple(
            _reliable_value(frame.rhythm.pulse, fallback=0.0) for frame in frames
        )
        bass_samples = tuple(
            _reliable_value(frame.layers.bass_register) for frame in frames
        )
        width_samples = tuple(
            _reliable_value(frame.spatial.width, fallback=0.5) for frame in frames
        )
        noise_samples = tuple(
            _unit(
                _reliable_value(frame.layers.noise) * 0.62
                + _reliable_value(frame.timbre.flatness) * 0.38
            )
            for frame in frames
        )
        pan_samples = tuple(
            _reliable_value(frame.spatial.pan, fallback=0.0) for frame in frames
        )
        novelty = max(
            _reliable_value(frame.section_novelty, fallback=0.0) for frame in frames
        )
        events = self._analysis.events_between(start_seconds, end_seconds)
        onset_density = sum(
            event.strength * event.confidence
            for event in events
            if event.kind.value == "onset"
        ) / max(span, 1e-6)
        beat_density = sum(
            event.strength * event.confidence
            for event in events
            if event.kind.value in {"beat", "downbeat"}
        ) / max(span, 1e-6)
        rhythmic_density = _unit(
            1.0 - math.exp(-(onset_density * 0.82 + beat_density * 0.26))
        )
        trend_width = max(1, len(frames) // 4)
        energy_trend = _mean(energy_samples[-trend_width:]) - _mean(
            energy_samples[:trend_width]
        )
        brightness_trend = _mean(brightness_samples[-trend_width:]) - _mean(
            brightness_samples[:trend_width]
        )
        development = _unit(
            0.42
            + energy_trend * 0.48
            + brightness_trend * 0.18
            + novelty * 0.24
            + rhythmic_density * 0.10
        )
        mood = MoodSignature(
            energy=_unit(
                _mean(energy_samples) * 0.72 + _upper_mean(energy_samples) * 0.28
            ),
            brightness=_unit(_mean(brightness_samples)),
            harmony=_unit(_mean(harmony_samples)),
            percussion=_unit(
                _mean(percussive_layer_samples) * 0.22
                + _upper_mean(percussive_layer_samples) * 0.10
                + _upper_mean(onset_samples) * 0.18
                + _mean(pulse_samples) * 0.14
                + rhythmic_density * 0.36
            ),
            bass=_unit(_mean(bass_samples)),
            width=_unit(_mean(width_samples)),
            noise=_unit(_mean(noise_samples)),
        )
        return mood, development, min(1.0, max(-1.0, _mean(pan_samples)))

    def _choose_varied_scene(
        self,
        mood: MoodSignature,
        *,
        cue_identity: str,
        recent: tuple[VisualScene, ...],
        usage: dict[VisualScene, int],
    ) -> VisualScene:
        raw_scores = _scene_scores(mood)
        best_score = max(raw_scores.values())
        # A narrow score gate stranded the diversity penalty inside a two-Scene
        # pool. Keep at least six musically ranked alternatives before cooldowns.
        ranked = sorted(VisualScene, key=raw_scores.__getitem__, reverse=True)
        candidates = set(ranked[:6]) | {
            scene for scene, score in raw_scores.items() if score >= best_score - 1.10
        }
        candidates.difference_update(recent[-3:])
        if VisualScene.SOLAR_BLOOM in recent[-5:]:
            candidates.discard(VisualScene.SOLAR_BLOOM)
        if recent and recent[-1] in _RADIAL_SCENES:
            candidates.difference_update(_RADIAL_SCENES)
        scores = {scene: raw_scores[scene] for scene in candidates}
        for scene in sorted(candidates):
            scores[scene] += 0.12 * _stable_signed(
                self._experience_seed, cue_identity, scene.name
            )
            scores[scene] -= usage[scene] * 0.32
            if scene in recent:
                scores[scene] -= 0.88 - recent[::-1].index(scene) * 0.18
        return max(sorted(scores), key=scores.__getitem__)


def _scene_scores(mood: MoodSignature) -> dict[VisualScene, float]:
    energy = mood.energy
    brightness = mood.brightness
    harmony = mood.harmony
    percussion = mood.percussion
    bass = mood.bass
    width = mood.width
    noise = mood.noise
    return {
        VisualScene.MAGNETOSPHERE: (
            2.4 * bass
            + 0.8 * width
            + 0.6 * (1.0 - harmony)
            + 0.3 * energy
            - 0.8 * brightness
            - 0.6 * percussion
        ),
        VisualScene.RIBBON_CASCADE: (
            2.0 * harmony
            + 1.2 * width
            + 0.8 * (1.0 - percussion)
            + 0.3 * brightness
            + 0.8 * (1.0 - brightness)
            - 0.8 * energy
        ),
        VisualScene.WARP_TUNNEL: (
            2.0 * energy + 1.4 * percussion + brightness + 0.8 * noise - 0.8 * harmony
        ),
        VisualScene.MIRROR_WAVE: (
            2.0 * percussion
            + harmony
            + 0.8 * (1.0 - energy)
            + 0.4 * width
            - 0.5 * brightness
            - 0.6 * noise
        ),
        VisualScene.PRISMATIC_VEIL: (
            1.8 * brightness
            + 1.5 * harmony
            + 0.9 * width
            + 0.6 * (1.0 - percussion)
            - 0.4 * energy
        ),
        VisualScene.LATTICE_CATHEDRAL: (
            1.8 * harmony
            + 1.4 * (1.0 - energy)
            + 1.1 * (1.0 - noise)
            + 0.2 * (1.0 - percussion)
            - 0.8 * brightness
            - 0.3 * width
        ),
        VisualScene.SOLAR_BLOOM: (
            2.0 * energy
            + 1.3 * bass
            + (1.0 - brightness)
            - 0.8 * width
            + 0.4 * (1.0 - percussion)
        ),
        VisualScene.STAR_CHAMBER: (
            2.0 * (1.0 - energy)
            + 1.2 * width
            + 0.9 * brightness
            + 0.8 * (1.0 - percussion)
            - 0.8 * bass
            - 0.6 * harmony
            + 0.2 * noise
        ),
        VisualScene.CONTOUR_DRIFT: (
            1.4 * (1.0 - energy)
            + 1.0 * (1.0 - brightness)
            + 1.0 * noise
            + 0.7 * bass
            + 0.6 * harmony
            + 0.4 * width
        ),
        VisualScene.CRYSTAL_SHOAL: (
            1.5 * brightness
            + 1.2 * noise
            + 0.8 * width
            + 0.7 * energy
            + 0.4 * (1.0 - harmony)
        ),
        VisualScene.BRAIDED_CURRENT: (
            1.4 * bass
            + 1.3 * harmony
            + 0.9 * width
            + 0.7 * energy
            + 0.3 * (1.0 - percussion)
            - 0.4 * (1.0 - harmony)
        ),
        VisualScene.SIGNAL_RAIN: (
            1.6 * percussion
            + 1.2 * brightness
            + 0.8 * (1.0 - harmony)
            + 0.5 * energy
            + 0.4 * (1.0 - width)
        ),
    }


def _scene_residence_boundaries(
    section_boundaries: tuple[float, ...],
) -> tuple[float, ...]:
    """Follow Section edits, suppressing changes less than two seconds apart."""

    duration = section_boundaries[-1]
    musical_boundaries = [0.0]
    for boundary in section_boundaries[1:-1]:
        if (
            boundary - musical_boundaries[-1] >= _MIN_SCENE_SECONDS
            and duration - boundary >= _MIN_SCENE_SECONDS
        ):
            musical_boundaries.append(boundary)
    musical_boundaries.append(duration)

    boundaries = [0.0]
    for start, end in pairwise(musical_boundaries):
        # Retain the existing long-Section subdivision without moving its edits.
        segment_count = max(1, math.ceil((end - start) / _MAX_SCENE_SECONDS))
        boundaries.extend(
            start + (end - start) * index / segment_count
            for index in range(1, segment_count)
        )
        boundaries.append(end)
    return tuple(boundaries)


def _normalized_section_boundaries(
    sections: tuple[MusicSection, ...],
    duration_seconds: float,
) -> tuple[float, ...]:
    """Turn tolerance-valid Section edges into one increasing partition."""

    minimum_span = min(
        _MIN_CAMERA_SHOT_SECONDS,
        duration_seconds / (len(sections) * 2.0),
    )
    boundaries = [0.0]
    interior = (
        (first.end_seconds + second.start_seconds) * 0.5
        for first, second in pairwise(sections)
    )
    for boundary_index, candidate in enumerate(interior, start=1):
        lower = boundaries[-1] + minimum_span
        remaining_sections = len(sections) - boundary_index
        upper = duration_seconds - minimum_span * remaining_sections
        boundaries.append(min(upper, max(lower, candidate)))
    boundaries.append(duration_seconds)
    return tuple(boundaries)


def _settled_moment(
    cue: SceneCue,
    *,
    camera_shot: CameraShot,
    camera_pose: CameraPose,
    camera_progress: float,
    camera_motion: float,
) -> SceneMoment:
    return SceneMoment(
        cue.scene,
        cue.scene,
        0.0,
        0.0,
        _SCENE_TUNING[cue.scene],
        cue.motion,
        camera_shot,
        camera_pose,
        camera_progress,
        camera_motion,
    )


def _stable_signed(experience_seed: int, *parts: str) -> float:
    digest = hashlib.blake2s(
        f"{experience_seed}:{':'.join(parts)}".encode(), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big") / float((1 << 64) - 1) * 2.0 - 1.0


def _mix(first: float, second: float, amount: float) -> float:
    return first + (second - first) * amount


def _mix_vector(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    amount: float,
) -> tuple[float, float, float]:
    return tuple(
        _mix(before, after, amount) for before, after in zip(first, second, strict=True)
    )  # type: ignore[return-value]


def _add_vector(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(before + after for before, after in zip(first, second, strict=True))  # type: ignore[return-value]


def _subtract_vector(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(before - after for before, after in zip(first, second, strict=True))  # type: ignore[return-value]


def _scale_vector(
    vector: tuple[float, float, float],
    scale: float,
) -> tuple[float, float, float]:
    return tuple(value * scale for value in vector)  # type: ignore[return-value]


def _dot_vector(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    return sum(before * after for before, after in zip(first, second, strict=True))


def _normalized_vector(
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    magnitude = math.sqrt(_dot_vector(vector, vector))
    if magnitude <= 1e-9:
        raise ValueError("Cannot normalize a zero-length vector")
    return tuple(value / magnitude for value in vector)  # type: ignore[return-value]


def _yaw_vector(
    vector: tuple[float, float, float],
    radians: float,
) -> tuple[float, float, float]:
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return (
        vector[0] * cosine + vector[2] * sine,
        vector[1],
        -vector[0] * sine + vector[2] * cosine,
    )


def _distance(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    return math.sqrt(
        sum((before - after) ** 2 for before, after in zip(first, second, strict=True))
    )


def _smootherstep(value: float) -> float:
    bounded = _unit(value)
    return bounded * bounded * bounded * (bounded * (bounded * 6.0 - 15.0) + 10.0)


def _mean(values: tuple[float, ...]) -> float:
    return sum(values) / len(values)


def _upper_mean(values: tuple[float, ...], *, fraction: float = 0.20) -> float:
    count = max(1, math.ceil(len(values) * fraction))
    return _mean(tuple(sorted(values, reverse=True)[:count]))


def _sample_reliability(sample: SignalSample | VectorSample | float) -> float:
    if isinstance(sample, float | int):
        return 1.0
    confidence = float(getattr(sample, "confidence", 1.0))
    validity = getattr(sample, "validity", None)
    validity_name = getattr(validity, "value", validity)
    if validity_name == "unavailable":
        return 0.0
    if validity_name == "limited":
        confidence *= 0.58
    return _unit(confidence)


def _reliable_value(sample: SignalSample | float, *, fallback: float = 0.0) -> float:
    if isinstance(sample, float | int):
        return float(sample)
    value = sample.value
    return _mix(fallback, value, _sample_reliability(sample))


def _perceptual_brightness(frame: MusicFrame, *, fallback: float) -> float:
    spectrum = frame.spectrum
    centroid = spectrum.centroid_hz
    centroid_value = max(80.0, centroid.value)
    centroid_unit = _unit(math.log2(centroid_value / 80.0) / math.log2(12_000.0 / 80.0))
    centroid_unit = _mix(fallback, centroid_unit, _sample_reliability(centroid))
    distribution = spectrum.band_distribution
    try:
        high_share = sum(
            distribution.component(name)
            for name in ("upper-mid", "presence", "brilliance")
        )
    except KeyError:
        high_share = fallback
    high_unit = _mix(
        fallback,
        _unit(math.sqrt(max(0.0, high_share))),
        _sample_reliability(distribution),
    )
    return _unit(centroid_unit * 0.72 + high_unit * 0.28)


def _unit(value: float) -> float:
    return min(1.0, max(0.0, value))


_IDLE_MOOD: Final = MoodSignature(0.14, 0.42, 0.38, 0.08, 0.12, 0.72, 0.16)
_IDLE_MOTION: Final = plan_scene_motion(
    VisualScene.STAR_CHAMBER,
    _IDLE_MOOD,
    experience_seed=0,
    cue_identity="idle",
)
_IDLE_CAMERA_SEQUENCE: Final = _plan_camera_sequence(
    VisualScene.STAR_CHAMBER,
    _IDLE_MOOD,
    experience_seed=0,
    cue_identity="idle",
    start_seconds=0.0,
    duration_seconds=18.0,
)
_IDLE_CAMERA_SHOT, _IDLE_CAMERA_POSE, _IDLE_CAMERA_PROGRESS, _ = (
    _IDLE_CAMERA_SEQUENCE.moment(2.4)
)
_IDLE_CUE: Final = SceneCue(
    0.0,
    18.0,
    VisualScene.STAR_CHAMBER,
    _IDLE_MOOD,
    _IDLE_MOTION,
    0.5,
    _IDLE_CAMERA_SEQUENCE,
)
_IDLE_SCENE_MOMENT: Final = _settled_moment(
    _IDLE_CUE,
    camera_shot=_IDLE_CAMERA_SHOT,
    camera_pose=_IDLE_CAMERA_POSE,
    camera_progress=_IDLE_CAMERA_PROGRESS,
    camera_motion=0.0,
)


__all__ = [
    "CameraPose",
    "CameraShot",
    "CameraShotKind",
    "MoodSignature",
    "SceneCue",
    "SceneDirector",
    "SceneMoment",
    "SceneMotion",
    "SceneTuning",
    "VisualScene",
    "choose_scene",
    "idle_scene_moment",
    "plan_scene_motion",
]
