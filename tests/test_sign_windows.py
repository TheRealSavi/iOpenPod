"""Unsigned candidates are allowed; configured signing must succeed."""

import subprocess
from pathlib import Path

import pytest
from scripts.sign_windows import sign


def test_configured_signing_uses_certificate_store_then_verifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    environment = {
        "IOPENPOD_WINDOWS_CERTIFICATE": "A" * 40,
        "IOPENPOD_WINDOWS_TIMESTAMP_URL": "https://timestamp.example.test",
        "IOPENPOD_SIGNTOOL": "signtool.exe",
    }

    def run(
        command: list[str], **options: object
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        assert options["check"] is True and options["env"] == environment
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    sign(Path("helper.exe"), {})
    assert calls == []
    sign(Path("helper.exe"), environment)
    assert calls[0][1:6] == ["sign", "/sha1", "A" * 40, "/fd", "SHA256"]
    assert calls[1] == ["signtool.exe", "verify", "/pa", "helper.exe"]


@pytest.mark.parametrize(
    "identity,url",
    [
        ("invalid", "https://example.test"),
        ("A" * 40, ""),
        ("A" * 40, "http://example.test"),
    ],
)
def test_incomplete_signing_cannot_fall_back_to_unsigned(
    identity: str, url: str
) -> None:
    with pytest.raises(ValueError):
        sign(
            Path("helper.exe"),
            {
                "IOPENPOD_WINDOWS_CERTIFICATE": identity,
                "IOPENPOD_WINDOWS_TIMESTAMP_URL": url,
            },
        )
