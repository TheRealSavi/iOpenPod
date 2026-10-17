"""Command-line contract for the iOpenPod entry point."""

import argparse
import json
import logging
import runpy
import struct
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

import iopenpod_launcher
from tests.iPodDB.binary_fixtures import (
    dataset,
    itunes_database,
    length_chunk,
    list_chunk,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _build_parser() -> argparse.ArgumentParser:
    entrypoint = runpy.run_path(str(Path(__file__).parents[1] / "main.py"))
    launcher_globals = entrypoint["run_with_crash_logging"].__globals__
    factory = cast(
        "Callable[[], argparse.ArgumentParser]",
        launcher_globals["build_parser"],
    )
    return factory()


def test_gui_no_longer_accepts_a_host_itunesdb_launch_argument() -> None:
    with pytest.raises(SystemExit) as error:
        _build_parser().parse_args(["--itunesdb", "Library-iTunesDB"])

    assert error.value.code == 2


def test_json_from_itdb_exports_original_smart_playlist_rules(tmp_path: Path) -> None:
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures/writing/original_smart_rules.json"
        ).read_text(encoding="utf-8")
    )
    playlist = length_chunk(
        b"mhyp",
        108,
        bytes.fromhex(fixture["preferences"]) + bytes.fromhex(fixture["rules"]),
        fields=struct.pack("<II", 2, 0),
    )
    source_bytes = itunes_database(dataset(2, list_chunk(b"mhlp", playlist)))
    source = tmp_path / "iTunesDB"
    source.write_bytes(source_bytes)
    output = tmp_path / "export" / "iTunesDB.json"
    args = _build_parser().parse_args(["--json-from-itdb", str(source), str(output)])

    assert iopenpod_launcher.run_cli(args)

    document = json.loads(output.read_text(encoding="utf-8"))
    exported_playlist = document["children"][0]["children"][0]["children"][0]
    group, relative_date, _compilation = exported_playlist["children"][1]["payload"][
        "rules"
    ]
    artist, rating = group["data"]["rules"]
    assert group["header_data"] == bytes(range(40)).hex()
    assert group["data"]["conjunction"] == 1
    assert artist["data"]["value"] == "Björk"
    assert artist["data"]["raw_data"] == "Björk".encode("utf-16-be").hex()
    assert rating["data"]["from_value"] == 80
    assert relative_date["data"]["from_date"] == -7
    assert relative_date["data"]["from_units"] == 86400
    assert source.read_bytes() == source_bytes


def test_uncaught_exception_is_logged_as_a_crash(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entrypoint = runpy.run_path(str(Path(__file__).parents[1] / "main.py"))
    run_with_crash_logging = cast(
        "Callable[[], int]",
        entrypoint["run_with_crash_logging"],
    )

    def crash() -> int:
        raise RuntimeError("unexpected failure")

    monkeypatch.setitem(run_with_crash_logging.__globals__, "main", crash)

    with (
        caplog.at_level(logging.CRITICAL),
        pytest.raises(RuntimeError, match="unexpected failure"),
    ):
        run_with_crash_logging()

    crash_records = [
        record for record in caplog.records if "iOpenPod crashed" in record.getMessage()
    ]
    assert len(crash_records) == 1
    assert crash_records[0].levelno == logging.CRITICAL
    assert crash_records[0].exc_info is not None
