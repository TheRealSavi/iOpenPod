from __future__ import annotations

import importlib
import tomllib
from pathlib import Path


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

