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
from pathlib import Path
from typing import TYPE_CHECKING

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

    An OS-held marker lock distinguishes abandoned workspaces from another live
    process's preparations. Only these marked, flat workspaces can be reaped.
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
            directory = Path(
                lifetime.enter_context(
                    tempfile.TemporaryDirectory(prefix=prefix, dir=root)
                )
            )
            lease = lifetime.enter_context(_open_lock_file(directory / _OWNER))
            _lock_file(lease, "Host staging workspace")
            lifetime.callback(_unlock_file, lease)
            # A directory without a complete marker is never cleanup authority.
            lease.write(_MARKER)
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
    except (OSError, ValueError, StorageError) as error:
        logger.debug("Host staging cleanup was unavailable: %s", error)
    return removed


def _remove_abandoned(directory: Path) -> bool:
    _require_owned_directory(directory)
    identity = directory.stat()
    marker = directory / _OWNER
    with (
        pin_host_directory(directory),
        _open_host_source(marker, writable=True) as lease,
    ):
        metadata = os.fstat(lease.fileno())
        if metadata.st_nlink != 1 or (
            sys.platform != "win32" and metadata.st_uid != os.getuid()
        ):
            return False
        _lock_file(lease, "Host staging workspace")
        try:
            if lease.read(len(_MARKER) + 1) != _MARKER:
                return False
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
