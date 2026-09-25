# pyright: strict, reportPrivateUsage=false
# These white-box tests intentionally verify SceneDirector calibration seams.

import math
from dataclasses import fields, replace
from itertools import pairwise
from typing import Any

import pytest

from iOpenPod.app.synesthesia import (
    EventKind,
    MusicalEvent,
    SectionProfile,
    SignalValidity,
    TrackAnalysis,
)
from iOpenPod.GUI.synesthesia.scene_director import (
    MoodSignature,
    SceneDirector,
    VisualScene,
    _scene_scores,
)


def test_dense_rhythmic_events_raise_scene_percussion_and_development(
    synthetic_analysis: TrackAnalysis,
) -> None:
    section = synthetic_analysis.sections[0]
    span = section.end_seconds - section.start_seconds
    events = tuple(
        MusicalEvent(
            event_id=f"dense-{index}",
            kind=EventKind.ONSET if index % 2 else EventKind.BEAT,
            seconds=section.start_seconds + span * (index + 1) / 25.0,
            strength=0.86,
            confidence=0.92,
        )
        for index in range(24)
    )
    quiet = replace(synthetic_analysis, events=())
    rhythmic = replace(synthetic_analysis, events=events)

    quiet_mood, quiet_development, _ = SceneDirector(
        quiet, experience_seed=7
    )._scene_evidence(section.start_seconds, section.end_seconds)
    rhythmic_mood, rhythmic_development, _ = SceneDirector(
        rhythmic, experience_seed=7
    )._scene_evidence(section.start_seconds, section.end_seconds)

    assert rhythmic_mood.percussion > quiet_mood.percussion + 0.20
    assert rhythmic_development > quiet_development + 0.04


def test_unavailable_evidence_is_not_reinvented_by_section_profiles(
    synthetic_analysis: TrackAnalysis,
) -> None:
    unavailable_groups = {
        name: _with_validity(
            getattr(synthetic_analysis.timeline, name), SignalValidity.UNAVAILABLE
        )
        for name in (
            "energy",
            "rhythm",
            "spectrum",
            "timbre",
            "harmony",
            "spatial",
            "layers",
            "structure",
        )
    }
    timeline = replace(synthetic_analysis.timeline, **unavailable_groups)
    sections = tuple(
        replace(section, profile=SectionProfile(1.0, 1.0, 1.0, 1.0))
        for section in synthetic_analysis.sections
    )
    unavailable = replace(
        synthetic_analysis,
        timeline=timeline,
        sections=sections,
        events=(),
    )

    mood = SceneDirector(unavailable, experience_seed=11).cues[0].mood

    assert mood.energy == pytest.approx(0.0)
    assert mood.brightness == pytest.approx(0.42)
    assert mood.harmony == pytest.approx(0.5)
    assert mood.percussion == pytest.approx(0.0)
    assert mood.bass == pytest.approx(0.0)
    assert mood.width == pytest.approx(0.5)
    assert mood.noise == pytest.approx(0.0)


def test_scene_variety_stays_within_a_musically_plausible_score_margin() -> None:
    director = object.__new__(SceneDirector)
    director._experience_seed = 83
    signature = MoodSignature(0.96, 0.16, 0.44, 0.48, 0.98, 0.40, 0.24)
    raw_scores = _scene_scores(signature)
    selected = director._choose_varied_scene(
        signature,
        cue_identity="plausibility:0",
        recent=(),
        usage=dict.fromkeys(raw_scores, 20),
    )

    assert raw_scores[selected] >= max(raw_scores.values()) - 0.50


def test_long_bass_heavy_section_keeps_variety_when_planned_and_sought(
    synthetic_analysis: TrackAnalysis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = replace(
        synthetic_analysis,
        metadata=replace(synthetic_analysis.metadata, duration_seconds=300.0),
        sections=(
            replace(
                synthetic_analysis.sections[0], start_seconds=0.0, end_seconds=300.0
            ),
        ),
        events=(),
    )
    mood = MoodSignature(0.96, 0.16, 0.44, 0.48, 0.98, 0.40, 0.24)

    def fixed_scene_evidence(
        _director: SceneDirector,
        _start_seconds: float,
        _end_seconds: float,
    ) -> tuple[MoodSignature, float, float]:
        return mood, 0.5, 0.0

    monkeypatch.setattr(SceneDirector, "_scene_evidence", fixed_scene_evidence)

    director = SceneDirector(analysis, experience_seed=19)
    history = [cue.scene for cue in director.cues]

    assert len(set(history)) >= 5
    assert history.count(VisualScene.SOLAR_BLOOM) <= math.ceil(len(history) / 6)
    assert any(scene.value >= VisualScene.CONTOUR_DRIFT.value for scene in history)
    for index, cue in enumerate(director.cues):
        assert cue.scene not in history[max(0, index - 3) : index]
        if cue.scene is VisualScene.SOLAR_BLOOM:
            assert cue.scene not in history[max(0, index - 5) : index]
        midpoint = (cue.start_seconds + cue.end_seconds) * 0.5
        expected = director.sample(midpoint)
        director.sample(299.0)
        director.sample(0.0)
        assert director.sample(midpoint) == expected
        assert expected.primary is cue.scene


@pytest.mark.parametrize("boundary_shape", ("gap", "overlap"))
def test_tolerance_valid_section_boundaries_form_one_contiguous_scene_timeline(
    synthetic_analysis: TrackAnalysis,
    boundary_shape: str,
) -> None:
    first, second, third = synthetic_analysis.sections
    first = replace(first, start_seconds=0.0, end_seconds=30.0)
    second = replace(second, start_seconds=30.0, end_seconds=60.0)
    third = replace(third, start_seconds=60.0, end_seconds=90.0)
    boundary = (first.end_seconds + second.start_seconds) * 0.5
    half_difference = synthetic_analysis.timeline.window_seconds * 0.25
    direction = 1.0 if boundary_shape == "gap" else -1.0
    sections = (
        replace(first, end_seconds=boundary - direction * half_difference),
        replace(second, start_seconds=boundary + direction * half_difference),
        third,
    )
    analysis = replace(
        synthetic_analysis,
        metadata=replace(synthetic_analysis.metadata, duration_seconds=90.0),
        sections=sections,
    )

    director = SceneDirector(analysis, experience_seed=17)

    assert len(director.cues) >= 2
    for previous, following in zip(director.cues, director.cues[1:], strict=False):
        assert previous.end_seconds == pytest.approx(following.start_seconds)
        before = director.sample(previous.end_seconds - 1e-6).camera_pose
        after = director.sample(previous.end_seconds + 1e-6).camera_pose
        assert math.dist(before.position, after.position) < 1e-3
        assert math.dist(before.target, after.target) < 1e-3


def test_tolerance_valid_micro_sections_cannot_reverse_the_scene_timeline(
    synthetic_analysis: TrackAnalysis,
) -> None:
    first, second, third = synthetic_analysis.sections
    sections = (
        replace(first, start_seconds=0.0, end_seconds=0.12),
        replace(second, start_seconds=0.0, end_seconds=0.01),
        replace(third, start_seconds=0.0, end_seconds=18.0),
    )
    analysis = replace(synthetic_analysis, sections=sections)

    director = SceneDirector(analysis, experience_seed=23)

    assert director.cues[0].start_seconds == 0.0
    assert director.cues[-1].end_seconds == analysis.metadata.duration_seconds
    assert all(cue.end_seconds > cue.start_seconds for cue in director.cues)
    assert all(
        first_cue.end_seconds == pytest.approx(second_cue.start_seconds)
        for first_cue, second_cue in zip(
            director.cues,
            director.cues[1:],
            strict=False,
        )
    )


def test_scene_sampling_is_independent_of_seek_history(
    synthetic_analysis: TrackAnalysis,
) -> None:
    reference = SceneDirector(synthetic_analysis, experience_seed=31)
    seeking = SceneDirector(synthetic_analysis, experience_seed=31)

    for seconds in (17.8, 1.2, 12.1, 5.9, 9.4, 0.0, 18.0, 6.1):
        assert seeking.sample(seconds) == reference.sample(seconds)


@pytest.mark.parametrize(
    "duration", [1.0, 1.99, 2.0, 2.01, 3.0, 22.0, 23.0, 45.0, 65.0, 120.0, 300.0]
)
def test_short_analysis_sections_do_not_force_short_visual_residences(
    synthetic_analysis: TrackAnalysis,
    duration: float,
) -> None:
    template = synthetic_analysis.sections[0]
    sections = tuple(
        replace(
            template,
            section_id=f"fragment-{index}",
            start_seconds=index * 3.0,
            end_seconds=min(duration, (index + 1) * 3.0),
        )
        for index in range(math.ceil(duration / 3.0))
    )
    analysis = replace(
        synthetic_analysis,
        metadata=replace(synthetic_analysis.metadata, duration_seconds=duration),
        sections=sections,
        events=(),
    )

    director = SceneDirector(analysis, experience_seed=37)
    assert director.cues[0].start_seconds == 0.0
    assert director.cues[-1].end_seconds == duration
    for cue in director.cues:
        assert min(2.0, duration) <= cue.end_seconds - cue.start_seconds <= 22.0
    for previous, following in zip(director.cues, director.cues[1:], strict=False):
        assert previous.end_seconds == following.start_seconds
        before = director.sample(following.start_seconds - 1e-6)
        after = director.sample(following.start_seconds + 1e-6)
        assert math.dist(before.camera_pose.position, after.camera_pose.position) < 1e-3


@pytest.mark.parametrize(
    ("boundaries", "expected_starts"),
    [
        ((0.0, 1.5, 3.0, 6.0, 9.0, 12.0, 18.0), [0.0, 3.0, 6.0, 9.0, 12.0]),
        ((0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0), [0.0, 2.0, 4.0]),
        ((0.0, 2.0, 3.9, 4.5, 6.0), [0.0, 2.0]),
        ((0.0, 30.0, 60.0), [0.0, 15.0, 30.0, 45.0]),
    ],
)
def test_scene_residences_follow_musical_boundaries_after_a_two_second_hold(
    synthetic_analysis: TrackAnalysis,
    boundaries: tuple[float, ...],
    expected_starts: list[float],
) -> None:
    sections = tuple(
        replace(
            synthetic_analysis.sections[0],
            section_id=f"phrase-{index}",
            start_seconds=start,
            end_seconds=end,
        )
        for index, (start, end) in enumerate(pairwise(boundaries))
    )
    analysis = replace(
        synthetic_analysis,
        metadata=replace(synthetic_analysis.metadata, duration_seconds=boundaries[-1]),
        sections=sections,
        events=(),
    )
    director = SceneDirector(analysis, experience_seed=37)

    assert [cue.start_seconds for cue in director.cues] == expected_starts
    assert analysis.sections == sections


def _with_validity(group: Any, validity: SignalValidity) -> Any:
    return replace(
        group,
        **{
            field.name: replace(getattr(group, field.name), validity=validity)
            for field in fields(group)
        },
    )
