"""Stage and atomically replace one explicitly reviewed regular Host file."""

from __future__ import annotations

import os
import shutil
import sys
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from storage.host_directory import pin_host_directory
from storage.host_input import LocalHostFile

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import BinaryIO


def replace_host_file(
    observed: LocalHostFile,
    transform: Callable[[BinaryIO], object],
    *,
    checkpoint: Callable[[], None] = lambda: None,
) -> LocalHostFile:
    """Transform a private copy, then revalidate and replace the reviewed source.

    ``transform`` must verify its result before returning. A transformation or
    precondition failure leaves the original intact. Publication is atomic for
    this file; it is independent of any removable-device transaction. The
    replacement must change at least one of size and modification time.
    """
    path = Path(observed.path)
    with pin_host_directory(path.parent, allow_network=True) as parent:
        observed.validate()
        checkpoint()
        name = f".{path.name}.{uuid4().hex}.tmp"
        staged = path.parent / name
        stage_path = name if isinstance(parent, int) else staged
        parent_fd = parent if isinstance(parent, int) else None
        descriptor = os.open(
            stage_path,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
            dir_fd=parent_fd,
        )
        try:
            with os.fdopen(descriptor, "w+b") as output:
                with observed.open_read() as source:
                    mode = os.fstat(source.fileno()).st_mode & 0o777
                    if not mode & 0o222:
                        raise PermissionError("The paired Host file is read-only.")
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                output.seek(0)
                transform(output)
                output.flush()
                if sys.platform != "win32":
                    os.fchmod(output.fileno(), mode)
                    _advance_colliding_mtime(
                        output.fileno(), os.fstat(output.fileno()), observed
                    )
                os.fsync(output.fileno())
            if sys.platform == "win32":
                # Windows can defer the last write time until the writer closes.
                _advance_colliding_mtime(staged, staged.lstat(), observed)
            staged_metadata = os.stat(
                stage_path, dir_fd=parent_fd, follow_symlinks=False
            )
            if (staged_metadata.st_size, staged_metadata.st_mtime_ns) == (
                observed.size_bytes,
                observed.modified_ns,
            ):
                raise OSError(
                    "The Host filesystem did not advance the staged modification time."
                )
            observed.validate()
            checkpoint()
            metadata = (
                os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                if isinstance(parent, int)
                else path.lstat()
            )
            if metadata.st_nlink > 1:
                raise ValueError("The paired Host file has multiple hard links.")
            if isinstance(parent, int):
                os.replace(name, path.name, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            else:
                os.replace(staged, path)
        finally:
            if isinstance(parent, int):
                with suppress(FileNotFoundError):
                    os.unlink(name, dir_fd=parent)
            else:
                staged.unlink(missing_ok=True)
    return LocalHostFile.observe(observed.path)


def _advance_colliding_mtime(
    stage: Path | int, metadata: os.stat_result, observed: LocalHostFile
) -> None:
    if (metadata.st_size, metadata.st_mtime_ns) == (
        observed.size_bytes,
        observed.modified_ns,
    ):
        # A full FAT timestamp tick covers filesystems with coarser resolution
        # than the system clock. The caller verifies the stored value.
        os.utime(stage, ns=(metadata.st_atime_ns, observed.modified_ns + 2_000_000_000))
