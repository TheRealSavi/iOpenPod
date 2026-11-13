"""Standalone comparison results executed by every studied dated-alarm image."""

import json
from pathlib import Path

from iPodDB.library._alarm_collation import compare_alarm_names


def test_native_mode_1b_vectors() -> None:
    fixture = Path(__file__).parents[2] / "fixtures/alarms/native_name_comparisons.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    assert len(data["cases"]) == 403
    for case in data["cases"]:
        assert compare_alarm_names(case["left"], case["right"]) == case["result"], case
