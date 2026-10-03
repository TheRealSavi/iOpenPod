"""Narrow Host installation operations, independent of product and release policy.

There is deliberately no recursive deletion or directory mirroring operation.
Windows publication renames open files without replacing existing destinations.
An interrupted pair of renames retains both payloads for explicit recovery.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from storage._filesystem import is_link_or_reparse
from storage.host_directory import pin_host_directory
from storage.host_files import AtomicHostFile
from storage.host_input import open_local_file, validate_host_path_spelling

if TYPE_CHECKING:
    from collections.abc import Generator


@dataclass(frozen=True, slots=True)
class HostFileIdentity:
    device: int
    inode: int
    size: int
    sha256: str

    def to_json(self) -> dict[str, int | str]:
        return asdict(self)

    @classmethod
    def from_json(cls, value: object) -> HostFileIdentity:
        if not isinstance(value, dict):
            raise ValueError("Missing file identity")
        fields = cast("dict[str, object]", value)
        numbers = [fields.get(name) for name in ("device", "inode", "size")]
        digest = fields.get("sha256")
        if any(type(item) is not int or item < 0 for item in numbers):
            raise ValueError("Invalid file identity")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("Invalid file digest")
        return cls(
            cast("int", numbers[0]),
            cast("int", numbers[1]),
            cast("int", numbers[2]),
            digest,
        )


def require_plain_path(path: Path) -> Path:
    """Validate the supplied spelling without resolving a link into authority."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Installation paths must be absolute and normalized")
    validate_host_path_spelling(os.fspath(path).replace("\\", "/"))
    for parent in reversed(path.parents):
        info = parent.lstat()
        if is_link_or_reparse(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("Installation path traverses a link or special file")
    if (path.exists() or path.is_symlink()) and is_link_or_reparse(path.lstat()):
        raise ValueError("Installation path is a link or reparse point")
    return path


def file_identity(path: Path) -> HostFileIdentity:
    require_plain_path(path)
    with open_local_file(path) as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or is_link_or_reparse(info)
            or info.st_nlink != 1
        ):
            raise ValueError(
                "Installation payload must be a regular file without aliases"
            )
        hasher = hashlib.sha256()
        while chunk := stream.read(256 * 1024):
            hasher.update(chunk)
        digest = hasher.hexdigest()
        after = os.fstat(stream.fileno())
        if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("Installation payload changed while being inspected")
        return HostFileIdentity(info.st_dev, info.st_ino, info.st_size, digest)


def private_directory(parent: Path, prefix: str) -> Path:
    require_plain_path(parent)
    with pin_host_directory(parent):
        if sys.platform == "win32":
            from storage.platform.host_install_windows import create_private_directory

            return create_private_directory(parent, prefix)
        return Path(tempfile.mkdtemp(prefix=prefix, dir=parent))


def durable_write(path: Path, data: bytes) -> None:
    require_plain_path(path)
    with pin_host_directory(path.parent):
        AtomicHostFile(path).replace_bytes(data)


def remove_owned_file(path: Path, expected: HostFileIdentity) -> None:
    """Remove exactly the unchanged file; never infer ownership from its name."""
    with pin_host_directory(path.parent):
        if sys.platform == "win32":
            from storage.platform.host_install_windows import remove_file

            remove_file(path, expected)
        else:
            if file_identity(path) != expected:
                raise ValueError("Refusing to remove a changed Host file")
            path.unlink()


def move_owned_file(
    source: Path, destination: Path, expected: HostFileIdentity
) -> None:
    require_plain_path(source)
    require_plain_path(destination)
    if source.parent.stat().st_dev != destination.parent.stat().st_dev:
        raise ValueError("Installation publication must stay on the same volume")
    if sys.platform == "win32":
        from storage.platform.host_install_windows import rename_file

        rename_file(source, destination, expected)
    else:
        raise ValueError("Exact-file installation is supported only on Windows")


@contextmanager
def pin_installation(parent: Path) -> Generator[None]:
    """Keep the validated containing directory stable during a transaction."""
    require_plain_path(parent)
    with pin_host_directory(parent):
        yield
