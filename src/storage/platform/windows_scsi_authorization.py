"""Ask UAC once to open one USB Volume; all SCSI work stays in the user process."""

from __future__ import annotations

import hashlib
import importlib
import logging
import os
import re
import struct
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from storage.platform.windows_access_native import WindowsAccessNative
from storage.scsi import ScsiSessionError

if TYPE_CHECKING:
    from collections.abc import Generator

_MAGIC = 0x31504F49
_VOLUME = re.compile(
    r"\\\\\?\\Volume\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}"
)
_TIMEOUT_MS = 120_000


def helper_payload() -> tuple[Path, str]:
    if getattr(sys, "frozen", False):
        root = Path(str(vars(sys)["_MEIPASS"])) / "storage-access"
        digest: object = importlib.import_module("_iopenpod_storage_helper").SHA256
    else:
        root = Path(__file__).resolve().parents[3] / "build/packaging/storage-access"
        manifest = (root / "_iopenpod_storage_helper.py").read_text(encoding="utf-8")
        match = re.fullmatch(r'SHA256 = "([0-9a-f]{64})"\n', manifest)
        digest = match.group(1) if match else None
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("The Storage helper digest is missing")
    return root / "iOpenPod-storage-access.exe", digest


@contextmanager
def retained_helper(native: WindowsAccessNative) -> Generator[Path]:
    source, digest = helper_payload()
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("The bundled Storage helper failed verification")
    root = Path(tempfile.gettempdir()) / f"iOpenPod-storage-{uuid.uuid4().hex}"
    native.create_directory(root)
    target = root / source.name
    try:
        with native.pin(root, directory=True):
            with target.open("xb") as stream:
                stream.write(data)
            with native.pin(target):
                if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise ValueError("The staged Storage helper failed verification")
                yield target
    finally:
        # Only these two known paths; never recursively delete a computed tree.
        try:
            target.unlink(missing_ok=True)
            root.rmdir()
        except OSError:
            logging.getLogger(__name__).warning(
                "Could not remove the temporary Storage helper: %s", root
            )


def authorized_open(volume: str, disk: int) -> int:
    if _VOLUME.fullmatch(volume) is None or not 0 <= disk <= 0xFFFFFFFF:
        raise ScsiSessionError(
            "Authorization requires the selected Volume GUID and disk"
        )
    try:
        native = WindowsAccessNative()
        name = rf"\\.\pipe\iOpenPod-volume-{uuid.uuid4().hex}"
        with retained_helper(native) as helper, native.pipe(name) as pipe:
            arguments = [name, str(os.getpid()), str(native.birth()), volume, str(disk)]
            with (
                native.connection(pipe) as pending,
                native.launch(helper, arguments) as process,
            ):
                native.complete(pipe, pending, _TIMEOUT_MS)
                native.require_peer(pipe, process)
                native.exchange(pipe, struct.pack("<I", _MAGIC), _TIMEOUT_MS)
                reply = native.exchange(pipe, 16, _TIMEOUT_MS)
                # Until exit 0, the helper owns (and may revoke) its duplicate.
                native.require_exit(process, _TIMEOUT_MS)
                magic, error, handle = struct.unpack("<IIQ", reply)
                if magic != _MAGIC or (error and handle) or (not error and not handle):
                    raise OSError("Invalid Storage authorization result")
                if error:
                    raise OSError(
                        error, f"Opening the USB Volume failed (Windows error {error})"
                    )
                return int(handle)
    except (OSError, ValueError, ImportError) as error:
        raise ScsiSessionError(f"Windows firmware access: {error}") from error


def check_runtime() -> None:
    """Exercise the compiled helper and real IPC without UAC or device access."""
    native = WindowsAccessNative()
    name = rf"\\.\pipe\iOpenPod-volume-{uuid.uuid4().hex}"
    with retained_helper(native) as helper, native.pipe(name, diagnostic=True) as pipe:
        arguments = [
            name,
            str(os.getpid()),
            str(native.birth()),
            r"\\?\Volume{00000000-0000-0000-0000-000000000000}",
            "0",
        ]
        with (
            native.connection(pipe) as pending,
            native.diagnostic_process(helper, arguments) as process,
        ):
            native.complete(pipe, pending, 10_000)
            native.require_peer(pipe, process)
            native.exchange(pipe, struct.pack("<I", _MAGIC), 10_000)
            reply = native.exchange(pipe, 16, 10_000)
            native.require_exit(process, 10_000)
            if reply != struct.pack("<IIQ", _MAGIC, 50, 0):
                raise ValueError("Unexpected Storage helper diagnostic reply")
