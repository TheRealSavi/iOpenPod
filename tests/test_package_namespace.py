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


def test_console_can_print_bundled_linux_identity_rule(
    capsys,
    monkeypatch,
) -> None:
    package_main = importlib.import_module("iopenpod.__main__")
    monkeypatch.setattr(
        package_main,
        "run_pyqt_app",
        lambda: pytest.fail("printing the rule must not boot the GUI"),
    )

    package_main.main(["--print-linux-udev-rule"])

    output = capsys.readouterr().out
    assert "ID_IOPENPOD_PRODUCT_SERIAL" in output
    assert 'TAG+="uaccess"' not in output


def test_console_can_silently_check_bundled_linux_identity_rule(
    capsys,
    monkeypatch,
) -> None:
    package_main = importlib.import_module("iopenpod.__main__")
    monkeypatch.setattr(
        package_main,
        "run_pyqt_app",
        lambda: pytest.fail("checking the rule must not boot the GUI"),
    )

    package_main.main(["--check-linux-udev-rule"])

    assert capsys.readouterr().out == ""


def test_console_linux_identity_status_is_nonzero_when_setup_is_required(
    capsys,
    monkeypatch,
    tmp_path,
) -> None:
    package_main = importlib.import_module("iopenpod.__main__")
    linux_identity = importlib.import_module("iopenpod.device.linux_identity")
    linux_integration = importlib.import_module(
        "iopenpod.device.linux_integration",
    )
    monkeypatch.setattr(package_main.sys, "platform", "linux")
    monkeypatch.setattr(
        linux_identity,
        "find_block_device",
        lambda _mount: "/dev/sdb1",
    )
    monkeypatch.setattr(
        linux_identity,
        "probe_linux_identity",
        lambda _mount: {"usb_pid": 0x1261},
    )
    monkeypatch.setattr(
        linux_integration,
        "_HOST_RULE_PATHS",
        (tmp_path / "missing.rules",),
    )

    with pytest.raises(SystemExit) as exit_info:
        package_main.main(["--linux-identity-status", "/media/ipod"])

    assert exit_info.value.code == 1
    assert "state=setup_required" in capsys.readouterr().out


def test_console_linux_identity_status_rejects_non_mount(
    capsys,
    monkeypatch,
) -> None:
    package_main = importlib.import_module("iopenpod.__main__")
    linux_identity = importlib.import_module("iopenpod.device.linux_identity")
    monkeypatch.setattr(package_main.sys, "platform", "linux")
    monkeypatch.setattr(
        linux_identity,
        "find_block_device",
        lambda _mount: None,
    )

    with pytest.raises(SystemExit) as exit_info:
        package_main.main(["--linux-identity-status", "/not/an/ipod"])

    assert exit_info.value.code == 2
    assert "state=invalid_mount" in capsys.readouterr().out
