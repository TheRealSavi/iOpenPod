"""Bounded capture of an explicitly selected Host file for external inspection."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from storage._filesystem import (
    COPY_CHUNK_SIZE,
    fingerprint_from_stat,
    is_link_or_reparse,
    open_read_no_follow,
)
from storage.errors import (
    ConcurrentModificationError,
    FileSizeLimitError,
    StorageOperationError,
    UnsafeFilesystemPathError,
)
from storage.paths import HostPath

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from storage.models import FileFingerprint


@dataclass(frozen=True, slots=True)
class CapturedHostFile:
    """The snapshot path exists only inside its capture context.

    The fingerprint describes the selected source at capture time. Consumers retain
    that content identity, not the temporary snapshot path, for later publication.
    """

    source: HostPath
    snapshot: HostPath
    fingerprint: FileFingerprint


@contextmanager
def capture_host_file(
    source: HostPath,
    *,
    checkpoint: Callable[[], None],
    max_bytes: int | None = None,
) -> Generator[CapturedHostFile]:
    """Stream into a private temporary file; clean up on success or any failure.

    Source changes during capture fail. Once captured, later source edits cannot
    change the bytes being inspected. A later copy must verify the captured hash.
    """

    if max_bytes is not None and max_bytes < 0:
        raise ValueError("Host capture limit must not be negative")
    checkpoint()
    with tempfile.TemporaryDirectory(prefix="iopenpod-inspection-") as directory:
        # System temp roots may use an OS alias (for example macOS /var). Resolve
        # only this newly created private directory, never the selected source.
        private_root = Path(directory).resolve(strict=True)
        captured = _capture(source, private_root / "input", checkpoint, max_bytes)
        checkpoint()
        yield captured


def _capture(
    source: HostPath,
    snapshot: Path,
    checkpoint: Callable[[], None],
    max_bytes: int | None,
) -> CapturedHostFile:
    path = Path(source)
    callback_failed = False
    try:
        observed = path.lstat()
        if is_link_or_reparse(observed) or not stat.S_ISREG(observed.st_mode):
            raise UnsafeFilesystemPathError("Host source must be a regular file")
        with open_read_no_follow(path) as incoming:
            before = os.fstat(incoming.fileno())
            if _identity(observed) != _identity(before):
                raise ConcurrentModificationError("Host source changed before capture")
            if max_bytes is not None and before.st_size > max_bytes:
                raise FileSizeLimitError("Host source exceeds the capture limit")
            digest = hashlib.sha256()
            copied = 0
            with snapshot.open("xb") as output:
                while True:
                    try:
                        checkpoint()
                    except OSError:
                        callback_failed = True
                        raise
                    chunk = incoming.read(COPY_CHUNK_SIZE)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > before.st_size:
                        raise ConcurrentModificationError(
                            "Host source grew during capture"
                        )
                    output.write(chunk)
                    digest.update(chunk)
            after = os.fstat(incoming.fileno())
            current = path.lstat()
            if (
                copied != before.st_size
                or _identity(before) != _identity(after)
                or _identity(before) != _identity(current)
                or before.st_ctime_ns != after.st_ctime_ns
                or observed.st_ctime_ns != current.st_ctime_ns
                or is_link_or_reparse(current)
            ):
                raise ConcurrentModificationError("Host source changed during capture")
            return CapturedHostFile(
                source,
                HostPath(snapshot),
                fingerprint_from_stat(before, digest.hexdigest()),
            )
    except OSError as error:
        if callback_failed:
            raise
        raise StorageOperationError(f"Could not capture Host file: {error}") from error


def _identity(value: os.stat_result) -> tuple[int, int, int, int]:
    # Python 3.12 Windows path stat and descriptor fstat report different ctime
    # meanings. Compare ctime only between observations made through the same API.
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
    )
