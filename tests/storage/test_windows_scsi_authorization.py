"""A denied open may request a handle, never replay a device command."""

from __future__ import annotations

import struct
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest

from storage.platform import windows_scsi_authorization as authorization
from storage.scsi import ScsiSessionError

VOLUME = r"\\?\Volume{01234567-89ab-cdef-0123-456789abcdef}"


class _Native:
    def __init__(self, event: str) -> None:
        self.event = event
        self.calls: list[str] = []

    def pipe(self, name: str) -> nullcontext[int]:
        assert name.startswith(r"\\.\pipe\iOpenPod-volume-")
        return nullcontext(7)

    def birth(self) -> int:
        return 42

    def connection(self, pipe: int) -> nullcontext[None]:
        assert pipe == 7
        return nullcontext()

    def launch(self, _helper: Path, arguments: list[str]) -> nullcontext[int]:
        assert arguments[2:] == ["42", VOLUME, "2"]
        self.calls.append("launch")
        if self.event == "cancel":
            raise PermissionError("authorization was cancelled")
        return nullcontext(8)

    def complete(self, *_args: object) -> None:
        if self.event == "timeout":
            raise TimeoutError("authorization timed out")

    def require_peer(self, pipe: int, process: int) -> None:
        assert (pipe, process) == (7, 8)
        self.calls.append("peer")
        if self.event == "wrong-peer":
            raise PermissionError("process did not match")

    def exchange(self, _pipe: int, data: bytes | int, _timeout: int) -> bytes:
        self.calls.append("read" if isinstance(data, int) else "ready")
        if not isinstance(data, int):
            assert data == struct.pack("<I", 0x31504F49)
            return data
        assert data == 16
        if self.event == "denied":
            return struct.pack("<IIQ", 0x31504F49, 5, 0)
        if self.event == "invalid":
            return struct.pack("<IIQ", 0, 0, 123)
        return struct.pack("<IIQ", 0x31504F49, 0, 123)

    def require_exit(self, _process: int, _timeout: int) -> None:
        self.calls.append("exit")
        if self.event == "helper-failed":
            raise OSError("helper failed")


@pytest.mark.parametrize(
    "event",
    [
        "success",
        "cancel",
        "timeout",
        "wrong-peer",
        "denied",
        "invalid",
        "helper-failed",
    ],
)
def test_handoff_requires_authenticated_reply_and_successful_exit(
    monkeypatch: pytest.MonkeyPatch,
    event: str,
) -> None:
    native = _Native(event)

    def retained_helper(_native: _Native) -> nullcontext[Path]:
        return nullcontext(Path("helper.exe"))

    monkeypatch.setattr(authorization, "WindowsAccessNative", lambda: native)
    monkeypatch.setattr(authorization, "retained_helper", retained_helper)
    if event == "success":
        assert authorization.authorized_open(VOLUME, 2) == 123
        assert native.calls == ["launch", "peer", "ready", "read", "exit"]
    else:
        with pytest.raises(ScsiSessionError):
            authorization.authorized_open(VOLUME, 2)
        assert native.calls.count("launch") == 1
        if event in {"cancel", "timeout", "wrong-peer"}:
            assert "ready" not in native.calls


@pytest.mark.parametrize(
    "volume,disk",
    [(r"\\.\PhysicalDrive0", 2), (VOLUME + "\\", 2), (VOLUME, -1), (VOLUME, 2**32)],
)
def test_rejects_unbound_targets_before_native_access(volume: str, disk: int) -> None:
    with pytest.raises(ScsiSessionError, match="selected Volume GUID"):
        authorization.authorized_open(volume, disk)


def test_staged_helper_rejects_tampered_payload_before_creating_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "helper.exe"
    source.write_bytes(b"tampered")
    monkeypatch.setattr(authorization, "helper_payload", lambda: (source, "0" * 64))
    native: Any = object()
    with (
        pytest.raises(ValueError, match="failed verification"),
        authorization.retained_helper(native),
    ):
        pytest.fail("A changed helper cannot be launched")
