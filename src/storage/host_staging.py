"""Large private Host workspaces kept off the system's default temporary volume."""

from __future__ import annotations

import errno
import logging
import os
import stat
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO
from uuid import uuid4

from storage._filesystem import is_link_or_reparse
from storage._writer_lock import (
    _lock_file,  # pyright: ignore[reportPrivateUsage]
    _open_lock_file,  # pyright: ignore[reportPrivateUsage]
    _unlock_file,  # pyright: ignore[reportPrivateUsage]
)
from storage.errors import DeviceBusyError, StorageError
from storage.host_directory import pin_host_directory
from storage.host_files import application_cache_file
from storage.session import _open_host_source  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)

_PREFIXES = ("iopenpod-media-", "iopenpod-content-", "iopenpod-chaptered-")
_OWNER = ".iopenpod-owner"
_MARKER = b"iopenpod-host-staging-v1\n"
_SHARED_MARKER = b"iopenpod-host-staging-v2\n"
_PROCESS_MARKER = b"iopenpod-host-staging-process-v2\n"
_PROCESS_PREFIX = ".iopenpod-process-"
_MARKER_LIMIT = len(_SHARED_MARKER) + len(_PROCESS_PREFIX) + 32 + 1


@dataclass
class _StagingOwner:
    path: Path
    lifetime: ExitStack
    references: int = 0


# Access is serialized by each root's cross-process cleanup guard. Include the
# PID so a fork cannot register new workspaces against its parent's ownership.
_OWNERS: dict[tuple[int, Path], _StagingOwner] = {}


def _retain_owner(root: Path) -> _StagingOwner:
    key = (os.getpid(), root)
    owner = _OWNERS.get(key)
    if owner is None:
        with ExitStack() as lifetime:
            path = root / f"{_PROCESS_PREFIX}{uuid4().hex}"
            lease = lifetime.enter_context(_open_lock_file(path))
            _lock_file(lease, "Host staging owner")
            lifetime.callback(_unlock_file, lease)
            lease.write(_PROCESS_MARKER)
            owner = _StagingOwner(path, lifetime.pop_all())
        _OWNERS[key] = owner
    owner.references += 1
    return owner


def _release_owner(root: Path, owner: _StagingOwner) -> None:
    owner.references -= 1
    if owner.references == 0:
        del _OWNERS[(os.getpid(), root)]
        owner.lifetime.close()
        # A failed TemporaryDirectory cleanup can leave a marked workspace. Its
        # now-unlocked owner record must remain available for a later reaper.
        if not any(path.name.startswith(_PREFIXES) for path in root.iterdir()):
            owner.path.unlink()


def _staging_root() -> Path:
    # Respect deliberate temporary-volume choices, but never silently spill a
    # complete Sync into Linux's commonly RAM-backed default /tmp.
    for name in ("TMPDIR", "TEMP", "TMP"):
        if value := os.environ.get(name):
            base = Path(value).resolve(strict=True)
            suffix = ""
            if sys.platform != "win32":
                suffix = f"-{os.getuid()}"
            return base / f"iopenpod-staging{suffix}"
    platform_name = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    return application_cache_file("iOpenPod", "staging", platform_name=platform_name)


def _require_owned_directory(path: Path) -> None:
    metadata = path.lstat()
    if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("Host staging must be a plain private directory")
    if sys.platform != "win32" and (
        metadata.st_uid != os.getuid() or metadata.st_mode & 0o077
    ):
        raise ValueError("Host staging must be private to the current user")


@contextmanager
def _cleanup_guard(root: Path, *, wait: bool = True) -> Generator[None]:
    # Serialize creation and normal removal with reaping. In particular, a
    # Windows cleaner must not pin a directory between its owner's unlock and
    # removal. The guard is never held while preparing or publishing content.
    with _open_lock_file(root / ".cleanup-lock") as lease:
        deadline = time.monotonic() + 30
        while True:
            try:
                _lock_file(lease, "Host staging cleanup")
            except DeviceBusyError as error:
                cause = error.__cause__
                if (
                    not wait
                    or not isinstance(cause, OSError)
                    or cause.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK)
                    or time.monotonic() >= deadline
                ):
                    raise
                time.sleep(0.01)
            else:
                break
        try:
            yield
        finally:
            _unlock_file(lease)


@contextmanager
def staging_directory(prefix: str) -> Generator[Path]:
    """Retain complete outputs on the selected Host volume until their owner exits.

    One OS-held owner lock per process and staging root protects every referenced
    workspace. Retaining a large batch therefore does not retain one descriptor
    per file. Only marked, flat workspaces can be reaped.
    """
    if prefix not in _PREFIXES:
        raise ValueError("Unsupported Host staging workspace")
    root = _staging_root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    _require_owned_directory(root)
    # Resolve conventional Host aliases (for example macOS /var) before later
    # identity-checked reads. The owned staging root itself cannot be a link.
    root = root.resolve(strict=True)
    with _cleanup_guard(root):
        lifetime = ExitStack()
        try:
            owner = _retain_owner(root)
            # Keep ownership until this workspace's files have been removed.
            lifetime.callback(_release_owner, root, owner)
            directory = Path(
                lifetime.enter_context(
                    tempfile.TemporaryDirectory(prefix=prefix, dir=root)
                )
            )
            # A directory without a complete marker is never cleanup authority.
            (directory / _OWNER).write_bytes(
                _SHARED_MARKER + owner.path.name.encode("ascii") + b"\n"
            )
        except BaseException:
            lifetime.close()
            raise
    try:
        yield directory
    finally:
        with _cleanup_guard(root):
            lifetime.close()


class RetainedStagingDirectory:
    """Transfer a marked workspace to a draft that explicitly owns its cleanup."""

    def __init__(self, prefix: str) -> None:
        self._lifetime = ExitStack()
        self.name = str(self._lifetime.enter_context(staging_directory(prefix)))

    def cleanup(self) -> None:
        self._lifetime.close()


def cleanup_stale_staging() -> int:
    """Remove only marked, unlocked workspaces from the current staging root.

    Old unmarked system-temp directories and unexpected entries are untouched.
    Cleanup is best effort; a busy or unreadable workspace cannot block startup.
    """
    removed = 0
    try:
        root = _staging_root()
        if not root.exists():
            return 0
        _require_owned_directory(root)
        root = root.resolve(strict=True)
        with _cleanup_guard(root, wait=False), pin_host_directory(root):
            for directory in root.iterdir():
                if not directory.name.startswith(_PREFIXES):
                    continue
                try:
                    if _remove_abandoned(directory):
                        removed += 1
                except (OSError, ValueError, StorageError):
                    # Includes active leases, files being closed by their owner,
                    # and another process completing the same cleanup.
                    continue
            # Retain owner records while any workspace remains, including unsafe
            # entries that may become cleanable later. Normal owners remove their
            # own record when their last workspace closes.
            if not any(p.name.startswith(_PREFIXES) for p in root.iterdir()):
                _cleanup_idle_owners(root)
    except (OSError, ValueError, StorageError) as error:
        logger.debug("Host staging cleanup was unavailable: %s", error)
    return removed


def _remove_abandoned(directory: Path) -> bool:
    _require_owned_directory(directory)
    identity = directory.stat()
    marker = directory / _OWNER
    with (
        pin_host_directory(directory),
        ExitStack() as captures,
    ):
        lease = captures.enter_context(_open_host_source(marker, writable=True))
        if not _private_file(lease):
            return False
        data = lease.read(_MARKER_LIMIT + 1)
        if data != _MARKER:
            name = _shared_owner_name(data)
            if name is None:
                return False
            lease = captures.enter_context(
                _open_host_source(directory.parent / name, writable=True)
            )
            if (
                not _private_file(lease)
                or lease.read(_MARKER_LIMIT + 1) != _PROCESS_MARKER
            ):
                return False
        _lock_file(lease, "Host staging workspace")
        try:
            children = tuple(directory.iterdir())
            # These workspaces contain regular files only. Do not recurse into
            # unexpected directories or follow links left by external changes.
            for child in children:
                info = child.lstat()
                if is_link_or_reparse(info) or not stat.S_ISREG(info.st_mode):
                    return False
            for child in children:
                if child.name != _OWNER:
                    child.unlink()
        finally:
            _unlock_file(lease)
    # Windows cannot remove the open marker or pinned directory. Close handles
    # first, then recheck identity before removing the now-empty workspace.
    current = directory.lstat()
    if is_link_or_reparse(current) or (current.st_dev, current.st_ino) != (
        identity.st_dev,
        identity.st_ino,
    ):
        return False
    marker.unlink()
    directory.rmdir()
    return True


def _private_file(stream: BinaryIO) -> bool:
    metadata = os.fstat(stream.fileno())
    return metadata.st_nlink == 1 and (
        sys.platform == "win32" or metadata.st_uid == os.getuid()
    )


def _is_owner_name(name: str) -> bool:
    token = name.removeprefix(_PROCESS_PREFIX)
    return (
        name.startswith(_PROCESS_PREFIX)
        and len(token) == 32
        and all(character in "0123456789abcdef" for character in token)
    )


def _shared_owner_name(data: bytes) -> str | None:
    if not data.startswith(_SHARED_MARKER) or not data.endswith(b"\n"):
        return None
    try:
        name = data[len(_SHARED_MARKER) : -1].decode("ascii")
    except UnicodeDecodeError:
        return None
    return name if _is_owner_name(name) else None


def _cleanup_idle_owners(root: Path) -> None:
    for path in root.iterdir():
        if not _is_owner_name(path.name):
            continue
        try:
            with _open_host_source(path, writable=True) as lease:
                if (
                    not _private_file(lease)
                    or lease.read(_MARKER_LIMIT + 1) != _PROCESS_MARKER
                ):
                    continue
                identity = os.fstat(lease.fileno())
                _lock_file(lease, "Host staging owner")
                _unlock_file(lease)
            current = path.lstat()
            if not is_link_or_reparse(current) and (current.st_dev, current.st_ino) == (
                identity.st_dev,
                identity.st_ino,
            ):
                path.unlink()
        except (OSError, ValueError, StorageError):
            continue
