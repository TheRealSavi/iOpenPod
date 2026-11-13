"""Native Nano 5 instruction fixtures drive complete SQLite catalog checks."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from iPodDB.SQLiteDB.alarm_playlists import project_sqlite_alarm_playlists
from iPodDB.SQLiteDB.schema import DYNAMIC_SCHEMA, LIBRARY_SCHEMA


def _catalog(rows: list[dict[str, int]], primary: int) -> tuple[int, ...]:
    with (
        closing(sqlite3.connect(":memory:")) as library,
        closing(sqlite3.connect(":memory:")) as dynamic,
    ):
        library.executescript(LIBRARY_SCHEMA)
        dynamic.executescript(DYNAMIC_SCHEMA)
        library.execute(
            "INSERT INTO db_info(pid,primary_container_pid) VALUES(1,?)", (primary,)
        )
        for index, row in enumerate(rows):
            library.execute(
                "INSERT INTO container(pid,name,name_order,distinguished_kind,media_kinds,is_hidden,smart_is_folder) VALUES(?,?,?,?,?,?,?)",
                (
                    row["pid"],
                    f"Playlist {index}",
                    index,
                    row["kind"],
                    row["media"],
                    row["hidden"],
                    row["folder"],
                ),
            )
            dynamic.execute(
                "INSERT INTO container_ui(container_pid) VALUES(?)", (row["pid"],)
            )
        library.commit()
        dynamic.commit()
        result = project_sqlite_alarm_playlists(
            library.serialize(), dynamic.serialize()
        )
        assert result.complete, result.issues
        return tuple(row.playlist_id for row in result.playlists)


def test_original_filter_and_complete_vector_order() -> None:
    fixture = json.loads(
        (
            Path(__file__).parents[1] / "fixtures/alarms/native_nano5_playlists.json"
        ).read_text(encoding="utf-8")
    )
    for case in fixture["filter_cases"]:
        assert bool(_catalog([case["row"]], 999)) is case["eligible"], case
    for case in fixture["order_cases"]:
        assert _catalog(case["rows"], case["primary"]) == tuple(case["pids"]), case


def test_original_media_conversion_eligibility() -> None:
    fixture = json.loads(
        (
            Path(__file__).parents[1] / "fixtures/alarms/native_nano5_playlists.json"
        ).read_text(encoding="utf-8")
    )
    for case in fixture["media_cases"]:
        row = {"pid": 1, "kind": 0, "hidden": 0, "media": case["input"], "folder": 0}
        expected = case["output"] == 0 or bool(case["output"] & 0x20015D)
        assert bool(_catalog([row], 999)) is expected, case
