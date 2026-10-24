"""Temporary Host copies of session-authorized Device files."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from storage.paths import DevicePath, HostPath

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from storage.models import FileFingerprint
    from storage.session import FilesystemSession


@dataclass(frozen=True, slots=True)
class CapturedDeviceFile:
    host_path: HostPath
    source_fingerprint: FileFingerprint


@contextmanager
def capture_device_file(
    session: FilesystemSession,
    source: DevicePath,
    *,
    checkpoint: Callable[[], None],
    temporary_directory: HostPath | None = None,
) -> Generator[HostPath]:
    """Copy through the session and remove the Host copy on every exit path.

    A caller processing many files can release each copy before capturing the
    next; disk usage is bounded by the files currently being processed.
    """
    with capture_device_file_with_fingerprint(
        session, source, checkpoint=checkpoint, temporary_directory=temporary_directory
    ) as captured:
        yield captured.host_path


@contextmanager
def capture_device_file_with_fingerprint(
    session: FilesystemSession,
    source: DevicePath,
    *,
    checkpoint: Callable[[], None],
    temporary_directory: HostPath | None = None,
) -> Generator[CapturedDeviceFile]:
    """Retain the source evidence computed by the single device-to-Host copy."""
    checkpoint()
    with tempfile.TemporaryDirectory(
        prefix="iopenpod-device-capture-", dir=temporary_directory
    ) as directory:
        suffix = Path(source.name).suffix or ".media"
        destination = HostPath(Path(directory).resolve(strict=True) / f"input{suffix}")
        copied = session.copy_to_host(
            source, destination, progress=lambda _copied: checkpoint()
        )
        checkpoint()
        yield CapturedDeviceFile(destination, copied.source_fingerprint)
