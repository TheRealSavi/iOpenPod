"""Saved timer inspection cannot imply arming or import another model's store."""

import pytest
from whenever import PlainDateTime

from iPodDB.alarms.timer import (
    COUNTDOWN_TIMER_SOUNDS,
    CountdownTimerChanges,
    parse_countdown_timer,
    patch_countdown_timer,
)
from iPodDB.preferences.definitions import NamedPreferencesProfile
from iPodDB.shared.errors import iPodDBWriteError

N6 = NamedPreferencesProfile.NANO_6_1_2
N7 = NamedPreferencesProfile.NANO_7_1_0_4
REFRESH = NamedPreferencesProfile.NANO_UPDATER_39_1_1_2


def _xml(fields: str) -> bytes:
    return (
        f'<iPodSettings version="1.0"><Timer>{fields}</Timer></iPodSettings>'.encode()
    )


@pytest.mark.parametrize("profile", (N6, N7, REFRESH))
def test_saved_duration_and_civil_deadline_are_independent(
    profile: NamedPreferencesProfile,
) -> None:
    duration = "<Hours>2</Hours><Minutes>30</Minutes>"
    state = (
        "<DateTime>20261101013000</DateTime><SleepiPod>1</SleepiPod>"
        "<SoundIndex>24</SoundIndex><Unknown>retain me</Unknown>"
    )
    ordinary = _xml(duration if profile is N6 else duration + state)
    timer = _xml(state) if profile is N6 else None
    result = parse_countdown_timer(ordinary, profile=profile, timer_settings=timer)
    assert result.saved_hours == 2
    assert result.saved_minutes == 30
    assert result.raw_deadline == "20261101013000"
    assert result.deadline == PlainDateTime(2026, 11, 1, 1, 30)
    assert result.sleep_ipod is True
    assert result.sound_index == 24
    assert result.issues == ()


def test_nano6_does_not_read_running_state_from_ordinary_settings() -> None:
    source = _xml("<Hours>1</Hours><DateTime>20260101020000</DateTime>")
    result = parse_countdown_timer(source, profile=N6)
    assert result.saved_hours == 1
    assert result.deadline is None and result.raw_deadline is None
    result = parse_countdown_timer(None, profile=N6, timer_settings=source)
    assert result.saved_hours is None
    assert result.deadline == PlainDateTime(2026, 1, 1, 2)


@pytest.mark.parametrize("profile", (N7, REFRESH))
def test_nano7_never_imports_the_nano6_store(profile: NamedPreferencesProfile) -> None:
    result = parse_countdown_timer(
        None,
        profile=profile,
        timer_settings=_xml("<DateTime>20260101020000</DateTime>"),
    )
    assert result.deadline is None and result.raw_deadline is None
    assert result.issues == ()


@pytest.mark.parametrize("text", ("", "<DateTime/>", "<DateTime></DateTime>"))
def test_missing_and_empty_deadlines_never_invent_a_running_status(text: str) -> None:
    result = parse_countdown_timer(_xml(text), profile=N7)
    assert result.deadline is None
    assert result.raw_deadline == (None if text == "" else "")
    assert result.issues == ()


@pytest.mark.parametrize(
    "text",
    ("20260230010000", "20260308023000Z", " 20260101000000", "9" * 1000),
)
def test_unrecognized_deadline_is_retained_without_blocking_other_fields(
    text: str,
) -> None:
    source = _xml(f"<DateTime>{text}</DateTime><Minutes>15</Minutes>")
    result = parse_countdown_timer(source, profile=N7)
    assert result.raw_deadline == text
    assert result.deadline is None
    assert result.saved_minutes == 15 and result.issues


@pytest.mark.parametrize(
    "fields",
    (
        "<Hours>24</Hours><Minutes>60</Minutes><SoundIndex>25</SoundIndex>",
        "<Hours>-1</Hours><Minutes>999999999999999</Minutes><SoundIndex>4294967295</SoundIndex>",
        "<Hours>&#49;</Hours><Minutes>x</Minutes><SoundIndex>x</SoundIndex>",
    ),
)
def test_unknown_numbers_are_not_defaults_or_normalized_values(fields: str) -> None:
    result = parse_countdown_timer(
        _xml(fields + "<SleepiPod>2</SleepiPod>"), profile=N7
    )
    assert result.saved_hours is None and result.saved_minutes is None
    assert result.sound_index is None and result.sleep_ipod is None
    assert len(result.issues) == 4


@pytest.mark.parametrize(
    "source",
    (
        _xml("<Hours>1</Hours><Hours>2</Hours>"),
        _xml('<Hours unit="h">1</Hours>'),
        _xml("<Hours><x>1</x></Hours>"),
        b'<iPodSettings version="1.0"><Timer/><Timer><Hours>1</Hours></Timer></iPodSettings>',
        b"<!DOCTYPE x [<!ENTITY e '1'>]><iPodSettings version='1.0'><Timer/></iPodSettings>",
        b"not XML",
    ),
)
def test_ambiguous_or_unqualified_xml_does_not_select_a_winning_value(
    source: bytes,
) -> None:
    result = parse_countdown_timer(source, profile=N7)
    assert result.saved_hours is None and result.issues


def test_clickwheel_profile_cannot_claim_the_touch_timer_schema() -> None:
    result = parse_countdown_timer(
        _xml("<Hours>1</Hours>"), profile=NamedPreferencesProfile.NANO_5_1_0_2
    )
    assert result.saved_hours is None and result.issues


@pytest.mark.parametrize("profile", (N6, N7, REFRESH))
def test_preset_edit_changes_only_requested_scalars_and_native_sound_coupling(
    profile: NamedPreferencesProfile,
) -> None:
    duration = "<Hours>2</Hours><Minutes>30</Minutes>"
    state = (
        "<DateTime>unknown deadline</DateTime><SleepiPod>1</SleepiPod>"
        "<SoundIndex>4</SoundIndex><Unknown>retain me</Unknown>"
    )
    ordinary = _xml(duration if profile is N6 else duration + state)
    timer = _xml(state) if profile is N6 else None
    availability = parse_countdown_timer(
        ordinary, profile=profile, timer_settings=timer
    )
    assert availability.can_edit_duration
    assert availability.can_edit_sleep and availability.can_edit_sound
    result = patch_countdown_timer(
        ordinary,
        profile=profile,
        changes=CountdownTimerChanges(saved_hours=1, sound_index=24),
        timer_settings=timer,
    )
    expected_ordinary = ordinary.replace(b"<Hours>2", b"<Hours>1")
    if profile is N6:
        assert result.settings == expected_ordinary
        assert result.timer_settings == _xml(
            state.replace("<SleepiPod>1", "<SleepiPod>0").replace(
                "<SoundIndex>4", "<SoundIndex>24"
            )
        )
    else:
        assert result.settings == expected_ordinary.replace(
            b"<SleepiPod>1", b"<SleepiPod>0"
        ).replace(b"<SoundIndex>4", b"<SoundIndex>24")
        assert result.timer_settings is None


def test_sleep_choice_retains_last_sound_and_never_clears_deadline() -> None:
    source = _xml(
        "<DateTime>20261201013000</DateTime><SleepiPod>0</SleepiPod>"
        "<SoundIndex>24</SoundIndex>"
    )
    result = patch_countdown_timer(
        source, profile=N7, changes=CountdownTimerChanges(sleep_ipod=True)
    )
    assert result.settings == source.replace(b"<SleepiPod>0", b"<SleepiPod>1")


def test_unchanged_numeric_values_keep_their_original_spelling() -> None:
    source = _xml("<Hours> +02 </Hours><Minutes>0030</Minutes>")
    result = patch_countdown_timer(
        source,
        profile=N7,
        changes=CountdownTimerChanges(saved_hours=2, saved_minutes=30),
    )
    assert result.settings == source


@pytest.mark.parametrize(
    "change",
    (
        CountdownTimerChanges(saved_hours=24),
        CountdownTimerChanges(saved_minutes=-1),
        CountdownTimerChanges(sound_index=25),
        CountdownTimerChanges(sound_index=1, sleep_ipod=True),
        CountdownTimerChanges(saved_hours=True),
    ),
)
def test_invalid_or_conflicting_preset_changes_are_rejected(
    change: CountdownTimerChanges,
) -> None:
    source = _xml(
        "<Hours>2</Hours><Minutes>30</Minutes><SoundIndex>1</SoundIndex>"
        "<SleepiPod>0</SleepiPod>"
    )
    with pytest.raises(iPodDBWriteError):
        patch_countdown_timer(source, profile=N7, changes=change)


@pytest.mark.parametrize(
    "source",
    (
        None,
        _xml(""),
        _xml("<Hours/>"),
        _xml("<Hours>1</Hours><Hours>2</Hours>"),
        _xml('<Hours mode="unknown">1</Hours>'),
        _xml("<Hours><![CDATA[1]]></Hours>"),
    ),
)
def test_writer_never_invents_or_selects_an_ambiguous_field(
    source: bytes | None,
) -> None:
    result = parse_countdown_timer(source, profile=N7)
    assert not result.can_edit_duration
    with pytest.raises(iPodDBWriteError):
        patch_countdown_timer(
            source, profile=N7, changes=CountdownTimerChanges(saved_hours=1)
        )


def test_sound_edit_requires_both_coupled_fields() -> None:
    source = _xml("<SoundIndex>5</SoundIndex>")
    assert not parse_countdown_timer(source, profile=N7).can_edit_sound
    with pytest.raises(iPodDBWriteError):
        patch_countdown_timer(
            source, profile=N7, changes=CountdownTimerChanges(sound_index=1)
        )


def test_nano6_does_not_require_an_unrelated_store_for_single_file_edits() -> None:
    ordinary = _xml("<Hours>2</Hours><Minutes>30</Minutes>")
    result = patch_countdown_timer(
        ordinary, profile=N6, changes=CountdownTimerChanges(saved_minutes=15)
    )
    assert result.settings == ordinary.replace(b"<Minutes>30", b"<Minutes>15")
    assert result.timer_settings is None
    timer = _xml("<SleepiPod>0</SleepiPod>")
    result = patch_countdown_timer(
        None,
        profile=N6,
        changes=CountdownTimerChanges(sleep_ipod=True),
        timer_settings=timer,
    )
    assert result.settings is None
    assert result.timer_settings == timer.replace(b"<SleepiPod>0", b"<SleepiPod>1")


def test_explicit_repair_does_not_normalize_other_unknown_settings() -> None:
    source = _xml("<Hours>unknown</Hours><Minutes>unknown</Minutes>")
    result = patch_countdown_timer(
        source, profile=N7, changes=CountdownTimerChanges(saved_hours=1)
    )
    assert result.settings == source.replace(b"<Hours>unknown", b"<Hours>1")


def test_native_sound_catalog_preserves_index_order() -> None:
    assert len(COUNTDOWN_TIMER_SOUNDS) == 25
    assert COUNTDOWN_TIMER_SOUNDS[0] == "Marimba"
    assert COUNTDOWN_TIMER_SOUNDS[4] == "Bell Tower"
    assert COUNTDOWN_TIMER_SOUNDS[24] == "Xylophone"


def test_writer_rejects_an_unqualified_profile_even_for_unchanged_values() -> None:
    source = _xml("<Hours>1</Hours><Minutes>15</Minutes>")
    profile = NamedPreferencesProfile.NANO_5_1_0_2
    observed = parse_countdown_timer(source, profile=profile)
    assert not observed.can_edit_duration
    assert not observed.can_edit_sleep and not observed.can_edit_sound
    with pytest.raises(iPodDBWriteError):
        patch_countdown_timer(
            source, profile=profile, changes=CountdownTimerChanges(saved_hours=1)
        )


@pytest.mark.parametrize(
    "source",
    (
        b'<iPodSettings version="2.0"><Timer><Hours>1</Hours><Minutes>15</Minutes></Timer></iPodSettings>',
        b'<iPodTimerSettings version="1.0"><Timer><Hours>1</Hours><Minutes>15</Minutes></Timer></iPodTimerSettings>',
    ),
)
def test_writer_requires_the_qualified_xml_envelope(source: bytes) -> None:
    assert not parse_countdown_timer(source, profile=N7).can_edit_duration
    with pytest.raises(iPodDBWriteError):
        patch_countdown_timer(
            source, profile=N7, changes=CountdownTimerChanges(saved_minutes=20)
        )
