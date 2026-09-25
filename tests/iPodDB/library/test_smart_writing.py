"""Smart Playlist authoring against native boundaries and independent 1.0 bytes."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.parser.parser_definition import PARSER_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartRulesPayload,
)
from iPodDB.library import (
    IPodLibrary,
    Playlist,
    PlaylistKind,
    SmartField,
    SmartLocation,
    SmartMatch,
    SmartMediaKind,
    SmartOperator,
    SmartPlaylist,
    SmartPlaylistReference,
    SmartRule,
    SmartRuleGroup,
    SmartValueKind,
    smart_operators,
    smart_value_kind,
    validate_smart_playlist,
)
from iPodDB.library._smart_projection import project_smart
from iPodDB.library._smart_writing import smart_chunks
from iPodDB.shared.chunk_reader import parse_chunk_as


@pytest.mark.parametrize("field", tuple(SmartField))
def test_every_authorable_field_prepares_and_round_trips(field: SmartField) -> None:
    kind = smart_value_kind(field)
    value: str | int | SmartPlaylistReference | SmartMediaKind | SmartLocation
    if kind is SmartValueKind.TEXT:
        value = "Björk 🎵"
    elif kind is SmartValueKind.BOOLEAN:
        value = 0
    elif kind is SmartValueKind.DATE:
        value = 1_700_000_000
    elif kind is SmartValueKind.PLAYLIST:
        value = SmartPlaylistReference(10)
    elif field is SmartField.MEDIA_KIND:
        value = SmartMediaKind.MUSIC
    elif field is SmartField.LOCATION:
        value = SmartLocation.LOCAL
    else:
        value = 80
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            SmartMatch.ANY, (SmartRule(field, smart_operators(field)[0], value),)
        )
    )
    source = library(mirrored=True)
    desired = replace(
        source.snapshot,
        playlists=(
            *source.snapshot.playlists,
            Playlist(-1, "New smart", PlaylistKind.SMART, smart=smart),
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    checked = IPodLibrary.parse(result.prepared.itunes)
    assert checked.snapshot.playlists[-1].smart == smart


def test_original_nested_rules_and_relative_units_survive_preference_edit() -> None:
    fixture = json.loads(
        (
            Path(__file__).parents[2] / "fixtures/writing/original_smart_rules.json"
        ).read_text()
    )
    rows = tuple(
        parse_chunk_as(
            bytes.fromhex(fixture[name]), 0, MHOD, parser_definition=PARSER_DEFINITION
        )[0]
        for name in ("preferences", "rules")
    )
    smart = project_smart(rows)
    assert smart.editable
    nested = smart.rules.rules[0]
    assert isinstance(nested, SmartRuleGroup) and nested.match is SmartMatch.ANY
    assert nested.rules[0] == SmartRule(SmartField.ARTIST, SmartOperator.IS, "Björk")
    assert smart.rules.rules[1] == SmartRule(
        SmartField.DATE_ADDED, SmartOperator.IN_LAST, 604800
    )
    assert smart.rules.rules[2] == SmartRule(
        SmartField.COMPILATION, SmartOperator.IS_FALSE, 0
    )
    edited = smart_chunks(replace(smart, checked_only=True), rows)
    assert edited[1] == rows[1]
    # Alter one sibling; unchanged nested conditions keep their private headers.
    changed = replace(
        smart,
        rules=replace(
            smart.rules,
            rules=(
                *smart.rules.rules[:2],
                SmartRule(SmartField.COMPILATION, SmartOperator.IS_TRUE, 0),
            ),
        ),
    )
    encoded = smart_chunks(changed, rows)
    before, after = rows[1].payload, encoded[1].payload
    assert isinstance(before, MhodSmartRulesPayload) and isinstance(
        after, MhodSmartRulesPayload
    )
    assert after.rules[:2] == before.rules[:2]
    assert project_smart(encoded) == changed


@pytest.mark.parametrize("offset", (-18000, 19800))
def test_absolute_dates_use_device_timezone_and_relative_periods_do_not(
    offset: int,
) -> None:
    rules = SmartRuleGroup(
        rules=(
            SmartRule(SmartField.LAST_PLAYED, SmartOperator.BETWEEN, -1, 1_700_000_000),
            SmartRule(SmartField.DATE_ADDED, SmartOperator.NOT_IN_LAST, 86400),
        )
    )
    smart = SmartPlaylist(rules=rules)
    encoded = smart_chunks(smart, (), offset)
    assert project_smart(encoded, offset) == smart
    assert project_smart(encoded, 0) != smart


@pytest.mark.parametrize(
    "rule",
    (
        SmartRule(SmartField.RATING, SmartOperator.IS, 101),
        SmartRule(SmartField.PLAY_COUNT, SmartOperator.IS, 1 << 64),
        SmartRule(SmartField.DATE_ADDED, SmartOperator.IN_LAST, 0),
        SmartRule(SmartField.DATE_ADDED, SmartOperator.IN_LAST, 1 << 63),
        SmartRule(SmartField.CHECKED, SmartOperator.IS_TRUE, 1),
        SmartRule(SmartField.TITLE, SmartOperator.IS, "broken\ud800"),
        SmartRule(SmartField.YEAR, SmartOperator.IS, 2000, 2001),
    ),
)
def test_editor_validation_and_writer_both_reject_invalid_conditions(
    rule: SmartRule,
) -> None:
    smart = SmartPlaylist(rules=SmartRuleGroup(rules=(rule,)))
    with pytest.raises(ValueError):
        validate_smart_playlist(smart)
    with pytest.raises(ValueError):
        smart_chunks(smart, ())


def test_absolute_date_cannot_encode_as_the_native_missing_date_marker() -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(
                SmartRule(
                    SmartField.DATE_ADDED, SmartOperator.IS, -2_082_844_800 + 18000
                ),
            )
        )
    )
    with pytest.raises(ValueError, match="date"):
        smart_chunks(smart, (), -18000)


def test_native_missing_date_condition_is_preserved_as_read_only() -> None:
    from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
        MhodSmartNumericRuleData,
    )

    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.LAST_PLAYED, SmartOperator.IS, 1700000000),)
        )
    )
    prefs, row = smart_chunks(smart, ())
    payload = row.payload
    assert isinstance(payload, MhodSmartRulesPayload)
    rule = payload.rules[0]
    assert isinstance(rule.data, MhodSmartNumericRuleData)
    missing = replace(rule, data=replace(rule.data, from_value=0, to_value=0))
    native = replace(row, payload=replace(payload, rules=(missing,)))
    assert not project_smart((prefs, native)).editable


def test_new_playlist_rule_reference_is_remapped_to_the_allocated_native_id() -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(
                SmartRule(
                    SmartField.PLAYLIST,
                    SmartOperator.IS,
                    SmartPlaylistReference(-2),
                ),
            )
        )
    )
    encoded = smart_chunks(smart, (), playlist_ids={-2: 999})

    assert project_smart(encoded).rules.rules == (
        SmartRule(
            SmartField.PLAYLIST,
            SmartOperator.IS,
            SmartPlaylistReference(999),
        ),
    )


@pytest.mark.parametrize(
    "rule",
    (
        SmartRule(
            SmartField.PLAYLIST,
            SmartOperator.IS_NOT,
            SmartPlaylistReference(10),
        ),
        SmartRule(
            SmartField.MEDIA_KIND,
            SmartOperator.IS_NOT,
            SmartMediaKind.PODCAST,
        ),
        SmartRule(
            SmartField.LOCATION,
            SmartOperator.IS_NOT,
            SmartLocation.CLOUD,
        ),
        SmartRule(SmartField.PURCHASED, SmartOperator.IS_FALSE, 0),
    ),
)
def test_choice_and_reference_negations_round_trip(rule: SmartRule) -> None:
    smart = SmartPlaylist(rules=SmartRuleGroup(rules=(rule,)))

    assert project_smart(smart_chunks(smart, ())) == smart


def test_missing_playlist_rule_reference_blocks_preparation() -> None:
    source = library(mirrored=True)
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(
                SmartRule(
                    SmartField.PLAYLIST,
                    SmartOperator.IS,
                    SmartPlaylistReference(999),
                ),
            )
        )
    )
    desired = replace(
        source.snapshot,
        playlists=(
            *source.snapshot.playlists,
            Playlist(-1, "Broken", PlaylistKind.SMART, smart=smart),
        ),
    )

    plan = source.analyze(source.begin_draft(desired))

    assert plan.blocked
    assert "playlist.missing_rule_reference" in {issue.code for issue in plan.issues}
