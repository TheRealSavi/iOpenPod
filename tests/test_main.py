"""Command-line contract for the iOpenPod entry point."""

import argparse
import logging
import runpy
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

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
