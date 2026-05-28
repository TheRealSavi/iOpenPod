from __future__ import annotations

from PyQt6.QtWidgets import QSpinBox

from GUI.widgets.formatters import format_smart_rule
from GUI.widgets.playlistEditor import SmartRuleRow
from iTunesDB_Parser.mhod_parser import _parse_mhod51
from iTunesDB_Shared.mhod_defs import MHOD_HEADER_SIZE
from iTunesDB_Writer.mhod_spl_writer import rules_from_parsed, write_mhod51


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
