"""One-time authorization installs only a narrow, fixed-syntax USB rule."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from storage import UsbControlAuthorizationError
from storage.platform import linux_usb_rules as rules


def _find_permission_tool(name: str) -> str:
    assert name in {"udevadm", "pkexec"}
    return f"/usr/bin/{name}"


@pytest.fixture
def rule_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(rules, "RULE_DIRECTORY", tmp_path / "etc")
    monkeypatch.setattr(rules, "SYSTEM_RULE_DIRECTORY", tmp_path / "lib")
    return tmp_path / "etc"


def test_install_publishes_only_selected_pair_and_triggers_no_other_usb(
    rule_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = MagicMock()

    def set_mode(_fd: int, _mode: int) -> None:
        pass

    monkeypatch.setattr(shutil, "which", _find_permission_tool)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(os, "fchmod", set_mode, raising=False)
    rules.install_rule(0x05AC, 0x1223)
    assert rules.installed(0x05AC, 0x1223)
    assert [path.name for path in rule_directory.iterdir()] == [
        rules.rule_name(0x05AC, 0x1223)
    ]
    text = (rule_directory / rules.rule_name(0x05AC, 0x1223)).read_text()
    assert 'TAG+="uaccess"' in text
    assert (
        "MODE" not in text and "GROUP" not in text and 'SUBSYSTEM=="block"' not in text
    )
    trigger = run.call_args_list[1].args[0]
    assert "--attr-match=idVendor=05ac" in trigger
    assert "--attr-match=idProduct=1223" in trigger
    assert "--subsystem-match=usb" in trigger


def test_admin_helper_rejects_arguments_that_could_change_rule_syntax(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install = MagicMock()
    monkeypatch.setattr(rules, "install_rule", install)
    with monkeypatch.context() as context:
        context.setattr(sys, "platform", "linux")
        context.setattr(os, "geteuid", lambda: 0, raising=False)
        for arguments in (
            ["05ac", "../root"],
            ["05ac", "*"],
            ['05ac"', "1223"],
            ["05ac"],
            ["05ac", "1223", "rule"],
        ):
            assert rules.main(arguments) == 2
    install.assert_not_called()


def test_existing_rule_does_not_cause_another_admin_prompt(
    rule_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rule_directory.mkdir()
    (rule_directory / rules.rule_name(0x05AC, 0x1223)).write_text(
        rules.rule_text(0x05AC, 0x1223)
    )
    run = MagicMock()
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(UsbControlAuthorizationError, match="active local desktop"):
        rules.authorize(0x05AC, 0x1223)
    run.assert_not_called()


@pytest.mark.parametrize("status", [126, 127, 1])
def test_denied_or_failed_authorization_is_terminal(
    rule_directory: Path, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    run = MagicMock(return_value=subprocess.CompletedProcess([], status))
    monkeypatch.setattr(shutil, "which", _find_permission_tool)
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(UsbControlAuthorizationError, match="not authorized"):
        rules.authorize(0x05AC, 0x1223)
    run.assert_called_once()
    arguments = run.call_args.args[0]
    assert arguments[-2:] == ["05ac", "1223"]
    assert "-I" in arguments and "-S" in arguments


def test_successful_helper_must_publish_effective_rule(
    rule_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = MagicMock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(shutil, "which", _find_permission_tool)
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(UsbControlAuthorizationError):
        rules.authorize(0x05AC, 0x1223)


def test_admin_override_takes_precedence_over_packaged_rule(
    rule_directory: Path,
) -> None:
    rules.SYSTEM_RULE_DIRECTORY.mkdir()
    name = rules.rule_name(0x05AC, 0x1223)
    (rules.SYSTEM_RULE_DIRECTORY / name).write_text(rules.rule_text(0x05AC, 0x1223))
    assert rules.installed(0x05AC, 0x1223)
    rule_directory.mkdir()
    (rule_directory / name).write_text("# disabled by administrator\n")
    assert not rules.installed(0x05AC, 0x1223)


def test_packaged_rule_matches_the_permission_helper() -> None:
    path = (
        Path(__file__).parents[2]
        / "src/iOpenPod/assets/linux/70-iopenpod-usb-05ac-1223.rules"
    )
    assert path.read_text() == rules.rule_text(0x05AC, 0x1223)
