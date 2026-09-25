# pyright: strict, reportPrivateUsage=false
# These white-box tests intentionally verify deterministic direction internals.

import math

import pytest

from iOpenPod.app.synesthesia import EventKind, MusicalEvent
from iOpenPod.GUI.synesthesia.scene_director import (
    CameraPose,
    CameraShotKind,
    MoodSignature,
    SceneDirector,
    SceneMotion,
    VisualScene,
    _plan_camera_sequence,
    choose_scene,
    plan_scene_motion,
)


@pytest.mark.parametrize(
    ("mood", "expected"),
    [
        (
            MoodSignature(0.58, 0.28, 0.34, 0.36, 0.94, 0.72, 0.20),
            VisualScene.MAGNETOSPHERE,
        ),
        (
            MoodSignature(0.48, 0.62, 0.96, 0.12, 0.22, 0.82, 0.14),
            VisualScene.RIBBON_CASCADE,
        ),
        (
            MoodSignature(0.97, 0.91, 0.18, 0.96, 0.38, 0.35, 0.70),
            VisualScene.WARP_TUNNEL,
        ),
        (
            MoodSignature(0.38, 0.42, 0.76, 0.92, 0.25, 0.58, 0.16),
            VisualScene.MIRROR_WAVE,
        ),
        (
            MoodSignature(0.44, 0.98, 0.88, 0.18, 0.12, 0.92, 0.12),
            VisualScene.PRISMATIC_VEIL,
        ),
        (
            MoodSignature(0.18, 0.26, 0.91, 0.42, 0.16, 0.24, 0.03),
            VisualScene.LATTICE_CATHEDRAL,
        ),
        (
            MoodSignature(0.96, 0.16, 0.44, 0.48, 0.98, 0.40, 0.24),
            VisualScene.SOLAR_BLOOM,
        ),
        (
            MoodSignature(0.08, 0.76, 0.34, 0.10, 0.08, 0.88, 0.08),
            VisualScene.STAR_CHAMBER,
        ),
        (
            MoodSignature(0.24, 0.25, 0.45, 0.15, 0.40, 0.65, 0.65),
            VisualScene.CONTOUR_DRIFT,
        ),
        (
            MoodSignature(0.70, 0.92, 0.25, 0.36, 0.30, 0.88, 0.80),
            VisualScene.CRYSTAL_SHOAL,
        ),
        (
            MoodSignature(0.72, 0.38, 0.86, 0.45, 0.88, 0.90, 0.16),
            VisualScene.BRAIDED_CURRENT,
        ),
        (
            MoodSignature(0.64, 0.90, 0.22, 0.88, 0.20, 0.30, 0.20),
            VisualScene.SIGNAL_RAIN,
        ),
    ],
)
def test_archetypal_moods_select_distinct_visual_scenes(
    mood: MoodSignature,
    expected: VisualScene,
) -> None:
    assert choose_scene(mood) is expected


def test_scene_director_never_repeats_the_immediately_previous_scene() -> None:
    director = object.__new__(SceneDirector)
    director._experience_seed = 19
    mood = MoodSignature(0.96, 0.16, 0.44, 0.48, 0.98, 0.40, 0.24)

    selected = director._choose_varied_scene(
        mood,
        cue_identity="chorus:1",
        recent=(VisualScene.SOLAR_BLOOM,),
        usage=dict.fromkeys(VisualScene, 0),
    )

    assert selected is not VisualScene.SOLAR_BLOOM


@pytest.mark.parametrize(
    "mood",
    [
        MoodSignature(0.96, 0.16, 0.44, 0.48, 0.98, 0.40, 0.24),
        MoodSignature(0.97, 0.91, 0.18, 0.96, 0.38, 0.35, 0.70),
        MoodSignature(0.18, 0.26, 0.91, 0.42, 0.16, 0.24, 0.03),
        MoodSignature(0.48, 0.62, 0.96, 0.12, 0.22, 0.82, 0.14),
    ],
)
@pytest.mark.parametrize("seed", [7, 19, 83])
def test_sustained_moods_do_not_cycle_between_a_few_favorite_scenes(
    mood: MoodSignature,
    seed: int,
) -> None:
    director = object.__new__(SceneDirector)
    director._experience_seed = seed

    def sequence() -> list[VisualScene]:
        history: list[VisualScene] = []
        usage = dict.fromkeys(VisualScene, 0)
        for index in range(30):
            scene = director._choose_varied_scene(
                mood,
                cue_identity=f"sustained:{index}",
                recent=tuple(history[-5:]),
                usage=usage,
            )
            assert scene not in history[-3:]
            radial = {
                VisualScene.SOLAR_BLOOM,
                VisualScene.MAGNETOSPHERE,
                VisualScene.WARP_TUNNEL,
            }
            if history and history[-1] in radial:
                assert scene not in radial
            if scene is VisualScene.SOLAR_BLOOM:
                assert scene not in history[-5:]
            history.append(scene)
            usage[scene] += 1
        return history

    first = sequence()
    assert first == sequence()
    assert len(set(first[:14])) >= 5
    assert first.count(VisualScene.SOLAR_BLOOM) <= 5


def test_every_scene_has_distinct_directional_waveform_choreography() -> None:
    mood = MoodSignature(0.72, 0.61, 0.54, 0.78, 0.66, 0.58, 0.31)
    motions = [
        plan_scene_motion(
            scene,
            mood,
            experience_seed=41,
            cue_identity=f"movement:{int(scene)}",
        )
        for scene in VisualScene
    ]

    for motion in motions:
        assert isinstance(motion, SceneMotion)
        assert math.hypot(motion.direction_x, motion.direction_y) == pytest.approx(1.0)
        assert (
            max(
                motion.travel_rate,
                abs(motion.orbit_rate),
                motion.depth_rate,
            )
            >= 0.20
        )
        assert motion.waveform_gain >= 0.30
        assert motion.parallax >= 0.20
        assert motion.world_scale > 0.0

    signatures = {
        (
            round(motion.travel_rate, 3),
            round(motion.orbit_rate, 3),
            round(motion.depth_rate, 3),
            round(motion.waveform_gain, 3),
            round(motion.parallax, 3),
            round(motion.world_scale, 3),
        )
        for motion in motions
    }
    assert len(signatures) == len(VisualScene)


def test_scene_motion_intensifies_with_musical_activity() -> None:
    calm = MoodSignature(0.08, 0.34, 0.28, 0.06, 0.12, 0.30, 0.05)
    active = MoodSignature(0.96, 0.78, 0.82, 0.94, 0.88, 0.86, 0.62)

    calm_motion = plan_scene_motion(
        VisualScene.WARP_TUNNEL,
        calm,
        experience_seed=8,
        cue_identity="bridge:0",
    )
    active_motion = plan_scene_motion(
        VisualScene.WARP_TUNNEL,
        active,
        experience_seed=8,
        cue_identity="bridge:0",
    )

    assert active_motion.travel_rate > calm_motion.travel_rate
    assert active_motion.depth_rate > calm_motion.depth_rate
    assert active_motion.waveform_gain > calm_motion.waveform_gain
    assert active_motion.parallax > calm_motion.parallax


def test_antipodal_scene_directions_take_one_continuous_shortest_arc() -> None:
    outgoing = SceneMotion(1.0, 0.0, 0.4, 0.1, 0.5, 0.8, 0.7, 0.9)
    incoming = SceneMotion(-1.0, 0.0, 0.8, -0.2, 0.9, 1.1, 1.0, 0.8)

    before = outgoing.interpolated(incoming, 0.49)
    midpoint = outgoing.interpolated(incoming, 0.50)
    after = outgoing.interpolated(incoming, 0.51)

    assert midpoint.direction_x == pytest.approx(0.0, abs=1e-12)
    assert midpoint.direction_y == pytest.approx(1.0)
    assert math.acos(
        min(
            1.0,
            max(
                -1.0,
                before.direction_x * after.direction_x
                + before.direction_y * after.direction_y,
            ),
        )
    ) < math.radians(5.0)


def test_each_scene_residence_is_composed_as_multiple_genuine_camera_shots() -> None:
    mood = MoodSignature(0.72, 0.61, 0.54, 0.78, 0.66, 0.58, 0.31)

    for scene in VisualScene:
        sequence = _plan_camera_sequence(
            scene,
            mood,
            experience_seed=41,
            cue_identity=f"camera:{int(scene)}",
            start_seconds=0.0,
            duration_seconds=18.0,
        )

        assert len(sequence.shots) >= 3
        assert sequence.shots[0].start_seconds == pytest.approx(0.0)
        assert sequence.shots[-1].end_seconds == pytest.approx(18.0)
        assert len({shot.kind for shot in sequence.shots}) >= 2
        assert any(
            shot.kind
            in {
                CameraShotKind.INSPECTION,
                CameraShotKind.ORBIT,
                CameraShotKind.TRACK,
                CameraShotKind.FLY_THROUGH,
            }
            for shot in sequence.shots
        )

        poses = [
            sequence.sample(18.0 * progress) for progress in (0.04, 0.34, 0.66, 0.96)
        ]
        positions = {
            tuple(round(value, 3) for value in pose.position) for pose in poses
        }
        targets = {tuple(round(value, 3) for value in pose.target) for pose in poses}
        fields_of_view = {round(pose.field_of_view_degrees, 2) for pose in poses}

        assert len(positions) >= 3
        assert len(targets) >= 2
        assert len(fields_of_view) >= 2
        assert (
            max(pose.position[2] for pose in poses)
            - min(pose.position[2] for pose in poses)
            >= 0.65
        )
        assert (
            max(pose.field_of_view_degrees for pose in poses)
            - min(pose.field_of_view_degrees for pose in poses)
            >= 6.0
        )


def test_camera_sequence_is_continuous_at_edits() -> None:
    mood = MoodSignature(0.62, 0.57, 0.71, 0.42, 0.34, 0.79, 0.16)
    sequence = _plan_camera_sequence(
        VisualScene.PRISMATIC_VEIL,
        mood,
        experience_seed=73,
        cue_identity="verse:2",
        start_seconds=11.0,
        duration_seconds=18.0,
    )

    for first, second in zip(sequence.shots, sequence.shots[1:], strict=False):
        assert first.end_seconds == pytest.approx(second.start_seconds)
        before = sequence.sample(first.end_seconds - 1e-5)
        after = sequence.sample(first.end_seconds + 1e-5)
        assert math.dist(before.position, after.position) < 1e-3
        assert math.dist(before.target, after.target) < 1e-3
        assert abs(before.field_of_view_degrees - after.field_of_view_degrees) < 1e-3


def test_camera_edits_snap_to_salient_punctuation_but_ignore_weak_events() -> None:
    mood = MoodSignature(0.70, 0.52, 0.54, 0.68, 0.61, 0.44, 0.20)
    strong_downbeat = MusicalEvent(
        "downbeat:5.62",
        EventKind.DOWNBEAT,
        5.62,
        0.88,
        0.92,
    )
    weak_beat = MusicalEvent(
        "beat:11.70",
        EventKind.BEAT,
        11.70,
        0.42,
        0.38,
    )
    sequence = _plan_camera_sequence(
        VisualScene.WARP_TUNNEL,
        mood,
        experience_seed=12,
        cue_identity="chorus:0",
        start_seconds=0.0,
        duration_seconds=18.0,
        events=(strong_downbeat, weak_beat),
    )

    assert sequence.shots[0].end_seconds == pytest.approx(5.62)
    assert sequence.shots[1].end_seconds == pytest.approx(12.0)


def test_camera_direction_changes_with_experience_seed_without_losing_grammar() -> None:
    mood = MoodSignature(0.48, 0.66, 0.82, 0.24, 0.22, 0.77, 0.11)
    first = _plan_camera_sequence(
        VisualScene.RIBBON_CASCADE,
        mood,
        experience_seed=5,
        cue_identity="bridge:1",
        start_seconds=0.0,
        duration_seconds=18.0,
    )
    repeated = _plan_camera_sequence(
        VisualScene.RIBBON_CASCADE,
        mood,
        experience_seed=5,
        cue_identity="bridge:1",
        start_seconds=0.0,
        duration_seconds=18.0,
    )
    alternate = _plan_camera_sequence(
        VisualScene.RIBBON_CASCADE,
        mood,
        experience_seed=6,
        cue_identity="bridge:1",
        start_seconds=0.0,
        duration_seconds=18.0,
    )

    assert first == repeated
    assert [shot.kind for shot in first.shots] == [
        shot.kind for shot in alternate.shots
    ]
    assert first.sample(7.5).position != alternate.sample(7.5).position


def test_every_scene_transition_keeps_camera_slices_in_front_of_the_full_frustum() -> (
    None
):
    mood = MoodSignature(0.70, 0.62, 0.58, 0.66, 0.54, 0.72, 0.26)
    sequences = {
        scene: _plan_camera_sequence(
            scene,
            mood,
            experience_seed=37,
            cue_identity=f"transition:{int(scene)}",
            start_seconds=0.0,
            duration_seconds=18.0,
        )
        for scene in VisualScene
    }
    layer_offsets = (-1.8, -1.6, -0.85, -0.55, 0.0, 0.72, 0.85, 1.2, 2.4)

    for outgoing_scene, outgoing in sequences.items():
        for incoming_scene, incoming in sequences.items():
            if incoming_scene is outgoing_scene:
                continue
            bridged = incoming.bridged_from(outgoing.final_pose)
            first_shot = bridged.shots[0]
            transition_span = min(
                3.2,
                first_shot.end_seconds - first_shot.start_seconds,
            )
            previous_hits: dict[
                tuple[float, float, float],
                tuple[float, float],
            ] = {}
            for step in range(33):
                seconds = first_shot.start_seconds + transition_span * step / 32.0
                pose = bridged.sample(seconds)
                forward = _normalized(_difference(pose.target, pose.position))
                reference_up = (
                    (1.0, 0.0, 0.0)
                    if abs(_dot(forward, (0.0, 1.0, 0.0))) > 0.98
                    else (0.0, 1.0, 0.0)
                )
                unrolled_right = _normalized(_cross(forward, reference_up))
                unrolled_up = _normalized(_cross(unrolled_right, forward))
                sine = math.sin(pose.roll_radians)
                cosine = math.cos(pose.roll_radians)
                right = _sum(
                    _scaled(unrolled_right, cosine),
                    _scaled(unrolled_up, sine),
                )
                up = _difference(
                    _scaled(unrolled_up, cosine),
                    _scaled(unrolled_right, sine),
                )
                lens = math.tan(math.radians(pose.field_of_view_degrees) * 0.5)
                focus_distance = math.dist(pose.position, pose.target)

                for point_x in (-16.0 / 9.0, 0.0, 16.0 / 9.0):
                    for point_y in (-1.0, 0.0, 1.0):
                        ray = _normalized(
                            _sum(
                                forward,
                                _scaled(
                                    _sum(
                                        _scaled(right, point_x),
                                        _scaled(up, point_y),
                                    ),
                                    lens,
                                ),
                            )
                        )
                        denominator = _dot(ray, forward)
                        assert denominator > 0.10
                        for layer_offset in layer_offsets:
                            plane_distance = max(
                                0.35,
                                focus_distance + layer_offset,
                            )
                            intersection_distance = plane_distance / denominator
                            assert math.isfinite(intersection_distance)
                            assert intersection_distance > 0.0
                            hit = _sum(
                                pose.position,
                                _scaled(ray, intersection_distance),
                            )
                            assert max(abs(component) for component in hit) < 40.0
                            key = (point_x, point_y, layer_offset)
                            if previous_hit := previous_hits.get(key):
                                assert math.dist(previous_hit, hit[:2]) < 3.0
                            previous_hits[key] = hit[:2]


@pytest.mark.parametrize(
    "scene",
    (VisualScene.WARP_TUNNEL, VisualScene.LATTICE_CATHEDRAL),
)
def test_deep_scene_shots_keep_the_authoritative_field_in_view(
    scene: VisualScene,
) -> None:
    mood = MoodSignature(0.76, 0.58, 0.54, 0.72, 0.62, 0.68, 0.31)
    sequence = _plan_camera_sequence(
        scene,
        mood,
        experience_seed=29,
        cue_identity=f"field-anchor:{int(scene)}",
        start_seconds=0.0,
        duration_seconds=18.0,
    )

    for step in range(129):
        pose = sequence.sample(18.0 * step / 128.0)
        forward = _normalized(_difference(pose.target, pose.position))
        reference_up = (
            (1.0, 0.0, 0.0)
            if abs(_dot(forward, (0.0, 1.0, 0.0))) > 0.98
            else (0.0, 1.0, 0.0)
        )
        unrolled_right = _normalized(_cross(forward, reference_up))
        unrolled_up = _normalized(_cross(unrolled_right, forward))
        sine = math.sin(pose.roll_radians)
        cosine = math.cos(pose.roll_radians)
        right = _sum(
            _scaled(unrolled_right, cosine),
            _scaled(unrolled_up, sine),
        )
        up = _difference(
            _scaled(unrolled_up, cosine),
            _scaled(unrolled_right, sine),
        )
        camera_to_field = _difference((0.0, 0.0, 0.0), pose.position)
        depth = _dot(camera_to_field, forward)
        lens = math.tan(math.radians(pose.field_of_view_degrees) * 0.5)

        assert depth > 0.0, (step, pose)
        projected_x = _dot(camera_to_field, right) / (depth * lens)
        projected_y = _dot(camera_to_field, up) / (depth * lens)
        assert abs(projected_x) <= (16.0 / 9.0) * 1.2, (step, pose, projected_x)
        assert abs(projected_y) <= 1.2, (step, pose, projected_y)


def test_camera_pacing_remains_cinematic_around_shot_count_thresholds() -> None:
    mood = MoodSignature(0.78, 0.65, 0.62, 0.74, 0.68, 0.72, 0.34)
    durations = (2.5, 5.99, 6.01, 11.99, 12.01, 17.99, 18.01, 22.0, 32.0, 44.0)

    for scene in VisualScene:
        for duration in durations:
            sequence = _plan_camera_sequence(
                scene,
                mood,
                experience_seed=53,
                cue_identity=f"pacing:{int(scene)}",
                start_seconds=0.0,
                duration_seconds=duration,
            )
            sample_count = max(2, math.ceil(duration / 0.025))
            previous_seconds = 0.0
            previous = sequence.sample(previous_seconds)
            for step in range(1, sample_count + 1):
                seconds = duration * step / sample_count
                pose = sequence.sample(seconds)
                delta = seconds - previous_seconds
                assert math.dist(previous.position, pose.position) / delta < 7.0
                assert math.dist(previous.target, pose.target) / delta < 7.0
                assert _pose_view_angle(previous, pose) / delta < math.radians(62.0)
                assert (
                    abs(previous.field_of_view_degrees - pose.field_of_view_degrees)
                    / delta
                    < 12.0
                )
                previous_seconds = seconds
                previous = pose

        for threshold in (6.0, 12.0, 18.0):
            shorter = _plan_camera_sequence(
                scene,
                mood,
                experience_seed=53,
                cue_identity=f"threshold:{int(scene)}",
                start_seconds=0.0,
                duration_seconds=threshold - 0.01,
            )
            longer = _plan_camera_sequence(
                scene,
                mood,
                experience_seed=53,
                cue_identity=f"threshold:{int(scene)}",
                start_seconds=0.0,
                duration_seconds=threshold + 0.01,
            )
            for fraction in (0.2, 0.4, 0.6, 0.8, 0.98):
                seconds = (threshold - 0.01) * fraction
                before = shorter.sample(seconds)
                after = longer.sample(seconds)
                context = (scene, threshold, fraction, before, after)
                assert math.dist(before.position, after.position) < 2.0, context
                assert math.dist(before.target, after.target) < 2.0, context
                assert (
                    abs(before.field_of_view_degrees - after.field_of_view_degrees)
                    < 6.0
                ), context


def _dot(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    return sum(a * b for a, b in zip(first, second, strict=True))


def _cross(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _normalized(
    value: tuple[float, float, float],
) -> tuple[float, float, float]:
    magnitude = math.sqrt(_dot(value, value))
    return tuple(component / magnitude for component in value)  # type: ignore[return-value]


def _sum(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(a + b for a, b in zip(first, second, strict=True))  # type: ignore[return-value]


def _difference(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(a - b for a, b in zip(first, second, strict=True))  # type: ignore[return-value]


def _scaled(
    value: tuple[float, float, float],
    scale: float,
) -> tuple[float, float, float]:
    return tuple(component * scale for component in value)  # type: ignore[return-value]


def _pose_view_angle(first: CameraPose, second: CameraPose) -> float:
    first_forward = _normalized(_difference(first.target, first.position))
    second_forward = _normalized(_difference(second.target, second.position))
    cosine = min(1.0, max(-1.0, _dot(first_forward, second_forward)))
    return math.acos(cosine)
