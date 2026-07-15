from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_iopenpod_namespace_exposes_application_modules() -> None:
    package = importlib.import_module("iopenpod")
    sync_session = importlib.import_module("iopenpod.application.sync_session")
    contracts = importlib.import_module("iopenpod.sync.contracts")

    assert package.__name__ == "iopenpod"
    assert sync_session.SyncSessionController.__name__ == "SyncSessionController"
    assert contracts.SyncPlan.__name__ == "SyncPlan"


def test_console_script_enters_through_package_main() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["scripts"]["iopenpod"] == "iopenpod.__main__:main"


def test_console_version_does_not_boot_the_gui(capsys, monkeypatch) -> None:
    package_main = importlib.import_module("iopenpod.__main__")
    monkeypatch.setattr(
        package_main,
        "run_pyqt_app",
        lambda: pytest.fail("--version must not boot the GUI"),
    )

    with pytest.raises(SystemExit) as exit_info:
        package_main.main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip()
