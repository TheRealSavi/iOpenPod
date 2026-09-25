"""Linux host integration remains bundled and least privilege."""

import logging
import shlex
from pathlib import Path

import pytest

from iOpenPod.app.services.linux_identity import (
    UDEV_RULE_DESTINATION,
    UDEV_RULE_VERSION,
    UdevRuleStatusKind,
    inspect_udev_rule,
    udev_rule_text,
    udev_setup_command,
    udev_setup_script,
    udev_uninstall_command,
    udev_uninstall_script,
)


def test_bundled_rule_exports_only_the_product_serial_property() -> None:
    rule = udev_rule_text()

    assert "ID_IOPENPOD_RULE_VERSION" in rule
    assert "ID_IOPENPOD_PRODUCT_SERIAL" in rule
    assert f'ENV{{ID_IOPENPOD_RULE_VERSION}}="{UDEV_RULE_VERSION}"' in rule
    assert "--page=0x80" in rule
    assert 'MODE="' not in rule
    assert 'GROUP="' not in rule


def test_setup_command_atomically_installs_the_exact_bundled_rule() -> None:
    script = udev_setup_script()

    assert udev_rule_text().rstrip() in script
    assert f"RULE_DEST={UDEV_RULE_DESTINATION}" in script
    assert 'RULE_STAGE="${RULE_DEST}.new.$$"' in script
    assert 'install -o root -g root -m 0644 "$RULE_TEMP" "$RULE_STAGE"' in script
    assert 'mv -f "$RULE_STAGE" "$RULE_DEST"' in script
    assert "command -v sudo" in script
    assert "command -v doas" in script
    assert "udevadm control --reload-rules" in script
    assert "udevadm trigger" not in script
    assert 'TAG+="uaccess"' not in script
    assert "MODE=" not in script


def test_setup_command_explicitly_routes_the_script_through_posix_sh() -> None:
    command = udev_setup_command()

    assert shlex.split(command) == ["/bin/sh", "-c", udev_setup_script()]


def test_preparing_setup_command_is_logged_without_sensitive_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="iOpenPod.app.services.linux_identity")

    udev_setup_command()

    assert caplog.messages == [
        "Prepared Linux udev identity-rule setup command for bundled version 2; "
        "iOpenPod remains unprivileged"
    ]


def test_setup_explains_the_native_password_prompt_before_invoking_it() -> None:
    script = udev_setup_script()
    notice = "iOpenPod needs administrator access to install its udev identity rule."

    assert script.count(notice) == 1
    assert "iOpenPod cannot see or store it." in script
    assert "does not grant raw-disk access or change device permissions" in script
    assert script.index(notice) < script.index('sudo "$@"')
    assert script.index(notice) < script.index('doas "$@"')


def test_setup_explains_the_required_eject_remount_and_refresh_sequence() -> None:
    script = udev_setup_script()

    steps = (
        "Safely eject the iPod completely",
        "Physically disconnect and reconnect the iPod",
        "Wait for the operating system to mount the iPod again",
        "Choose Refresh in iOpenPod's device picker",
    )
    positions = tuple(script.index(step) for step in steps)

    assert positions == tuple(sorted(positions))
    assert "before the remount is not enough" in script


def test_rule_status_respects_the_highest_priority_existing_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import iOpenPod.app.services.linux_identity as linux_identity

    local = tmp_path / "etc" / UDEV_RULE_DESTINATION.rsplit("/", maxsplit=1)[-1]
    vendor = tmp_path / "usr" / UDEV_RULE_DESTINATION.rsplit("/", maxsplit=1)[-1]
    local.parent.mkdir()
    vendor.parent.mkdir()
    local.write_text("# disabled by administrator\n", encoding="utf-8")
    vendor.write_text(udev_rule_text(), encoding="utf-8")
    monkeypatch.setattr(linux_identity, "_UDEV_RULE_PATHS", (local, vendor))

    status = inspect_udev_rule()

    assert status.kind is UdevRuleStatusKind.DIFFERENT
    assert status.path == local


def test_rule_status_reports_current_and_missing_copies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import iOpenPod.app.services.linux_identity as linux_identity

    current = tmp_path / "61-iopenpod.rules"
    missing = tmp_path / "missing.rules"
    current.write_text(udev_rule_text(), encoding="utf-8")
    monkeypatch.setattr(linux_identity, "_UDEV_RULE_PATHS", (current,))

    assert inspect_udev_rule().kind is UdevRuleStatusKind.CURRENT

    monkeypatch.setattr(linux_identity, "_UDEV_RULE_PATHS", (missing,))

    assert inspect_udev_rule().kind is UdevRuleStatusKind.MISSING


def test_rule_status_reports_an_unreadable_or_broken_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import iOpenPod.app.services.linux_identity as linux_identity

    broken = tmp_path / "61-iopenpod.rules"
    broken.symlink_to(tmp_path / "absent-rule")
    monkeypatch.setattr(linux_identity, "_UDEV_RULE_PATHS", (broken,))

    status = inspect_udev_rule()

    assert status.kind is UdevRuleStatusKind.UNREADABLE
    assert status.path == broken


def test_uninstall_command_only_removes_the_local_rule() -> None:
    script = udev_uninstall_script()
    command = udev_uninstall_command()

    assert shlex.split(command) == ["/bin/sh", "-c", script]
    assert f"RULE_DEST={UDEV_RULE_DESTINATION}" in script
    assert 'run_as_root rm -f -- "$RULE_DEST"' in script
    assert "refusing to remove a directory at $RULE_DEST" in script
    assert "udevadm control --reload-rules" in script
    assert "Already-published identity properties remain cached" in script
    assert "physically disconnect" in script
    assert "Restarting iOpenPod alone does not clear" in script
    assert "/usr/lib/udev/rules.d/61-iopenpod.rules" not in script
    assert "/lib/udev/rules.d/61-iopenpod.rules" not in script
