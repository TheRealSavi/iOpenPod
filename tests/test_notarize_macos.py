"""Validate notarization order and fail closed before distribution."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import notarize_macos

IDENTIFIER = "12345678-1234-1234-1234-123456789abc"


@pytest.mark.parametrize("status", ["Accepted", "Invalid", "In Progress"])
def test_staples_only_accepted_builds_and_saves_notary_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    (tmp_path / "dist/iOpenPod.app").mkdir(parents=True)
    commands: list[list[str]] = []

    def run(command: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        output = ""
        signature = "Authority=Developer ID Application: Test\nflags=0x10000(runtime)"
        if command[:3] == ["xcrun", "notarytool", "submit"]:
            output = json.dumps({"id": IDENTIFIER})
        elif command[:3] == ["xcrun", "notarytool", "wait"]:
            assert (
                tmp_path / f"build/packaging/notarization/{IDENTIFIER}-submission.json"
            ).is_file()
            output = json.dumps({"status": status})
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr=signature)

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", run)
    if status == "Accepted":
        assert (
            notarize_macos.notarize(tmp_path, "release-profile")
            == tmp_path / "dist/iOpenPod.app"
        )
        assert [command[:3] for command in commands[-3:]] == [
            ["xcrun", "stapler", "staple"],
            ["xcrun", "stapler", "validate"],
            ["spctl", "--assess", "--type"],
        ]
    else:
        with pytest.raises(ValueError, match="did not accept"):
            notarize_macos.notarize(tmp_path, "release-profile")
        assert not any(command[:2] == ["xcrun", "stapler"] for command in commands)
    assert any(command[:3] == ["xcrun", "notarytool", "log"] for command in commands)


def test_unsigned_candidate_is_never_uploaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "dist/iOpenPod.app").mkdir(parents=True)
    commands: list[list[str]] = []

    def run(command: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command, 0, stdout="", stderr="Signature=adhoc"
        )

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ValueError, match="Developer ID"):
        notarize_macos.notarize(tmp_path, "release-profile")
    assert all(command[0] == "codesign" for command in commands)
