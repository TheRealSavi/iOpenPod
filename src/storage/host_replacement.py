"""Stage and atomically replace one explicitly reviewed regular Host file."""

from __future__ import annotations

import os
import shutil
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
    this file; it is independent of any removable-device transaction.
    """
    path = Path(observed.path)
    with pin_host_directory(path.parent, allow_network=True) as parent:
        observed.validate()
        checkpoint()
        name = f".{path.name}.{uuid4().hex}.tmp"
        staged = path.parent / name
        directory = {"dir_fd": parent} if isinstance(parent, int) else {}
        descriptor = os.open(
            name if isinstance(parent, int) else staged,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
            **directory,
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
                if os.name != "nt":
                    os.fchmod(output.fileno(), mode)
                output.flush()
                os.fsync(output.fileno())
            observed.validate()
            checkpoint()
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
