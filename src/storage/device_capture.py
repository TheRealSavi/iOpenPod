"""Temporary Host copies of session-authorized Device files."""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from storage.paths import DevicePath, HostPath

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from storage.session import FilesystemSession


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
    checkpoint()
    with tempfile.TemporaryDirectory(
        prefix="iopenpod-device-capture-", dir=temporary_directory
    ) as directory:
        suffix = Path(source.name).suffix or ".media"
        destination = HostPath(Path(directory).resolve(strict=True) / f"input{suffix}")
        session.copy_to_host(source, destination, progress=lambda _copied: checkpoint())
        checkpoint()
        yield destination
