from __future__ import annotations

import ast
from pathlib import Path

from PyQt6.QtWidgets import QSpinBox

from iopenpod.gui.widgets.formatters import format_smart_rule
from iopenpod.gui.widgets.playlistEditor import SmartRuleRow
from iopenpod.itunesdb_parser.mhod_parser import _parse_mhod51
from iopenpod.itunesdb_shared.mhod_defs import (
    MHOD_HEADER_SIZE,
    SPL_FIELD_MAP,
    SPL_FIELD_TYPE_MAP,
    SPLFT_BINARY_AND,
    SPLFT_BOOLEAN,
    SPLFT_INT,
    SPLFT_STRING,
)
from iopenpod.itunesdb_writer.mhod_spl_writer import rules_from_parsed, write_mhod51


def _last_played_relative_row(qtbot) -> SmartRuleRow:
    row = SmartRuleRow()
    qtbot.addWidget(row)
    row.field_combo.setCurrentIndex(row.field_combo.findData(0x17))
    row.action_combo.setCurrentIndex(row.action_combo.findData(0x00000200))
    return row


def test_relative_date_rule_survives_writer_parser_editor_round_trip(qtbot) -> None:
    row = _last_played_relative_row(qtbot)
    spin = row._find_widget(QSpinBox)
    assert isinstance(spin, QSpinBox)
    spin.setValue(1)

    rule_data = row.get_rule_data()

    assert rule_data["from_value"] == 0
    assert rule_data["from_date"] == -1
    assert rule_data["from_units"] == 86400

    blob = write_mhod51(
        rules_from_parsed({"conjunction": "AND", "rules": [rule_data]})
    )
    parsed = _parse_mhod51(blob, MHOD_HEADER_SIZE, len(blob) - MHOD_HEADER_SIZE)
    parsed_rule = parsed["rules"][0]

    assert parsed_rule["from_value"] == 0
    assert parsed_rule["from_date"] == -1

    reloaded = SmartRuleRow()
    qtbot.addWidget(reloaded)
    reloaded.set_rule_data(parsed_rule)
    reloaded_spin = reloaded._find_widget(QSpinBox)
    assert isinstance(reloaded_spin, QSpinBox)
    assert reloaded_spin.value() == 1


def test_legacy_negative_relative_date_from_value_is_normalized() -> None:
    legacy_rule = {
        "field_id": 0x17,
        "action_id": 0x00000200,
        "from_value": -1,
        "from_date": -1,
        "from_units": 86400,
    }

    blob = write_mhod51(
        rules_from_parsed({"conjunction": "AND", "rules": [legacy_rule]})
    )
    parsed = _parse_mhod51(blob, MHOD_HEADER_SIZE, len(blob) - MHOD_HEADER_SIZE)

    assert parsed["rules"][0]["from_value"] == 0
    assert parsed["rules"][0]["from_date"] == -1


def test_legacy_unsigned_relative_date_formats_from_from_date() -> None:
    rule = {
        "field_id": 0x17,
        "action_id": 0x00000200,
        "from_value": 0xFFFFFFFFFFFFFFFF,
        "from_date": -1,
        "from_units": 86400,
    }

    assert format_smart_rule(rule) == "Last Played is in the last 1 days"


def test_legacy_seconds_relative_date_value_is_converted_to_units() -> None:
    legacy_rule = {
        "field_id": 0x17,
        "action_id": 0x00000200,
        "from_value": 86400,
        "from_date": 0,
        "from_units": 86400,
    }

    assert format_smart_rule(legacy_rule) == "Last Played is in the last 1 days"

    blob = write_mhod51(
        rules_from_parsed({"conjunction": "AND", "rules": [legacy_rule]})
    )
    parsed = _parse_mhod51(blob, MHOD_HEADER_SIZE, len(blob) - MHOD_HEADER_SIZE)

    assert parsed["rules"][0]["from_value"] == 0
    assert parsed["rules"][0]["from_date"] == -1


def test_unknown_string_rule_does_not_read_next_rule_as_numeric_payload() -> None:
    blob = write_mhod51(
        rules_from_parsed(
            {
                "conjunction": "AND",
                "rules": [
                    {
                        "field_id": 0x59,
                        "action_id": 0x01000002,
                        "string_value": "",
                    },
                    {
                        "field_id": 0x07,
                        "action_id": 0x00000001,
                        "from_value": 2026,
                        "from_units": 1,
                        "to_value": 2026,
                        "to_units": 1,
                    },
                ],
            }
        )
    )

    parsed = _parse_mhod51(blob, MHOD_HEADER_SIZE, len(blob) - MHOD_HEADER_SIZE)

    assert parsed["rules"][0] == {
        "field_id": 0x59,
        "action_id": 0x01000002,
        "data_length": 0,
        "string_value": "",
    }
    assert parsed["rules"][1]["from_value"] == 2026


def test_ipod_video_55_every_rule_sample_field_labels() -> None:
    assert {
        field_id: SPL_FIELD_MAP[field_id]
        for field_id in (0x1D, 0x25, 0x59, 0x85, 0x86, 0x9A, 0x9C, 0x9F, 0xA0, 0xA1)
    } == {
        0x1D: "Checked",
        0x25: "Album Artwork",
        0x59: "Video Rating",
        0x85: "Location",
        0x86: "Cloud Status",
        0x9A: "Favorite / Suggest Less",
        0x9C: "Album Favorite / Suggest Less",
        0x9F: "Work",
        0xA0: "Movement Name",
        0xA1: "Movement Number",
    }
    assert {
        field_id
        for field_id, field_type in SPL_FIELD_TYPE_MAP.items()
        if field_type == SPLFT_BOOLEAN
    } == {0x1D, 0x25, 0x1F, 0x29}
    assert SPL_FIELD_TYPE_MAP[0x1D] == SPLFT_BOOLEAN
    assert SPL_FIELD_TYPE_MAP[0x25] == SPLFT_BOOLEAN
    assert SPL_FIELD_TYPE_MAP[0x1F] == SPLFT_BOOLEAN
    assert SPL_FIELD_TYPE_MAP[0x29] == SPLFT_BOOLEAN
    assert SPL_FIELD_TYPE_MAP[0x59] == SPLFT_STRING
    assert SPL_FIELD_TYPE_MAP[0x85] == SPLFT_BINARY_AND
    assert SPL_FIELD_TYPE_MAP[0x3C] == SPLFT_INT
    assert SPL_FIELD_TYPE_MAP[0x86] == SPLFT_INT
    assert SPL_FIELD_TYPE_MAP[0x9A] == SPLFT_INT
    assert SPL_FIELD_TYPE_MAP[0x9C] == SPLFT_INT
    assert SPL_FIELD_TYPE_MAP[0x9F] == SPLFT_STRING
    assert SPL_FIELD_TYPE_MAP[0xA0] == SPLFT_STRING
    assert SPL_FIELD_TYPE_MAP[0xA1] == SPLFT_INT


def test_ipod_video_55_every_rule_sample_field_formatting() -> None:
    assert format_smart_rule({
        "field_id": 0x9F,
        "action_id": 0x01000002,
        "string_value": "Suite",
    }) == 'Work contains "Suite"'
    assert format_smart_rule({
        "field_id": 0x02,
        "action_id": 0x01000004,
        "string_value": "Intro",
    }) == 'Song Name begins with "Intro"'
    assert format_smart_rule({
        "field_id": 0xA1,
        "action_id": 0x00000001,
        "from_value": 2,
    }) == "Movement Number is 2"


def test_boolean_rules_format_as_true_false() -> None:
    assert format_smart_rule({
        "field_id": 0x25,
        "action_id": 0x00000001,
    }) == "Album Artwork is true"
    assert format_smart_rule({
        "field_id": 0x1D,
        "action_id": 0x02000001,
    }) == "Checked is false"


def test_choice_rules_format_as_menu_values() -> None:
    assert format_smart_rule({
        "field_id": 0x9A,
        "action_id": 0x00000001,
        "from_value": 2,
    }) == "Favorite / Suggest Less is Favorite"
    assert format_smart_rule({
        "field_id": 0x86,
        "action_id": 0x02000001,
        "from_value": 2,
    }) == "Cloud Status is not Matched"
    assert format_smart_rule({
        "field_id": 0x85,
        "action_id": 0x00000400,
        "from_value": 1,
    }) == "Location is on this computer"
    assert format_smart_rule({
        "field_id": 0x3C,
        "action_id": 0x00000001,
        "from_value": 0x20,
    }) == "Media Kind is Music Video"


def test_integer_rules_format_user_units() -> None:
    assert format_smart_rule({
        "field_id": 0x19,
        "action_id": 0x00000100,
        "from_value": 100,
        "to_value": 109,
    }) == "Rating is in the range 5 stars - 5 stars"
    assert format_smart_rule({
        "field_id": 0x0C,
        "action_id": 0x00000001,
        "from_value": 1024 * 1024,
    }) == "Size is 1 MB"
    assert format_smart_rule({
        "field_id": 0x16,
        "action_id": 0x00000001,
        "from_value": 0,
    }) == "Plays is 0"


def test_date_rules_format_absolute_and_relative_values() -> None:
    assert format_smart_rule({
        "field_id": 0x10,
        "action_id": 0x00000100,
        "from_value": 3864067200,
        "to_value": 3864153599,
    }) == "Date Added is in the range 2026-06-12 - 2026-06-12"
    assert format_smart_rule({
        "field_id": 0x17,
        "action_id": 0x00000200,
        "from_date": -2,
        "from_units": 604800,
    }) == "Last Played is in the last 2 weeks"


def test_editor_field_policy_marks_unproven_fields_unsupported() -> None:
    source = Path("src/iopenpod/gui/widgets/playlistEditor.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    field_ids: tuple[int, ...] | None = None
    unsupported_ids: frozenset[int] | None = None

    def _literal_frozenset(node: ast.AST) -> frozenset[int]:
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "frozenset"
            and node.args
        ):
            return frozenset(ast.literal_eval(node.args[0]))
        value = ast.literal_eval(node)
        return frozenset(value)

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "_FIELD_OPTION_IDS":
                field_ids = ast.literal_eval(node.value)
            if isinstance(target, ast.Name) and target.id == "_UNSUPPORTED_FIELD_IDS":
                unsupported_ids = _literal_frozenset(node.value)

    assert field_ids is not None
    assert unsupported_ids is not None
    assert {0x4E, 0x4F, 0x50, 0x51, 0x52, 0x53}.issubset(field_ids)
    assert {0x39, 0x3E, 0x3F}.issubset(field_ids)
    assert unsupported_ids == frozenset({0x39, 0x3E, 0x3F})


def test_editor_preserves_non_default_string_action(qtbot) -> None:
    row = SmartRuleRow()
    qtbot.addWidget(row)

    row.set_rule_data({
        "field_id": 0x02,
        "action_id": 0x03000004,
        "string_value": "Intro",
    })

    assert row.action_combo.currentData() == 0x03000004
    assert row.get_rule_data()["action_id"] == 0x03000004
