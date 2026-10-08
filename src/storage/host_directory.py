"""Identity-bound, read-only directory observations for local Host scanning."""

from __future__ import annotations

import os
import stat
import sys
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, cast

from storage._filesystem import is_link_or_reparse
from storage.errors import (
    ConcurrentModificationError,
    StorageError,
    UnsafeFilesystemPathError,
)
from storage.host_input import (
    HostSelectionResolver,
    LocalHostFile,
    _check_local_drive,  # pyright: ignore[reportPrivateUsage]
    validate_host_path_spelling,
)
from storage.paths import HostPath

if TYPE_CHECKING:
    from collections.abc import Callable, Generator


class HostEntryKind(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"
    LINK_OR_REPARSE_POINT = "link_or_reparse_point"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class HostDirectoryEntry:
    path: HostPath
    kind: HostEntryKind
    size_bytes: int
    modified_ns: int
    file: LocalHostFile | None = None
    directory: LocalHostDirectory | None = None


@dataclass(frozen=True, slots=True)
class LocalHostDirectory:
    """An observed directory; enumerating it does not follow child links."""

    path: HostPath
    size_bytes: int
    modified_ns: int
    device: int
    inode: int

    @classmethod
    def observe(cls, path: HostPath) -> LocalHostDirectory:
        source = Path(path)
        validate_host_path_spelling(os.fspath(source).replace("\\", "/"))
        _check_local_drive(source)
        for parent in reversed(source.parents):
            _require_directory(parent.lstat())
        metadata = source.lstat()
        _require_directory(metadata)
        return cls._from_stat(path, metadata)

    @classmethod
    def _from_stat(cls, path: HostPath, value: os.stat_result) -> LocalHostDirectory:
        return cls(path, value.st_size, value.st_mtime_ns, value.st_dev, value.st_ino)

    def list_entries(
        self,
        *,
        checkpoint: Callable[[], None],
        on_issue: Callable[[HostPath, OSError | StorageError], None] | None = None,
        include_file: Callable[[str], bool] | None = None,
        include_directories: bool = True,
        include_links: bool = False,
        on_entry: Callable[[HostDirectoryEntry], None] | None = None,
    ) -> tuple[HostDirectoryEntry, ...]:
        """Stat each child once while pinning this directory and its parents.

        Returned file/directory observations reuse those exact stat identities.
        Links and special files have no readable observation. A replaced or
        concurrently edited directory fails instead of publishing a partial list.
        Supplying on_issue permits best-effort enumeration of changing contents,
        while directory identity and no-link checks remain mandatory.
        An optional filename predicate skips unneeded non-directory entries before
        stat where the Host supplies directory-entry type information. Directories
        are retained independently when include_directories is true.
        Symbolic links are retained with directories, or independently when
        include_links is true, without following their targets. on_entry
        reports provisional observations for progress; only a successfully returned
        listing has passed the final directory identity checks.
        """
        checkpoint()
        entries: list[HostDirectoryEntry] = []
        with pin_host_directory(Path(self.path)) as pinned:
            before = _directory_stat(pinned)
            _require_directory(before)
            if (before.st_dev, before.st_ino) != (self.device, self.inode) or (
                on_issue is None and self._from_stat(self.path, before) != self
            ):
                raise ConcurrentModificationError("The observed Host directory changed")
            with os.scandir(pinned) as iterator:
                for entry in iterator:
                    checkpoint()
                    path = HostPath(self.path.path / entry.name)
                    # Windows DirEntry.stat() omits device/inode identity. Parent
                    # handles are already pinned, so one leaf lstat supplies it
                    # without rescanning the ancestor chain for each child.
                    try:
                        if (
                            include_file is not None
                            and not include_file(entry.name)
                            and not (
                                (include_links or include_directories)
                                and entry.is_symlink()
                            )
                            and (
                                not include_directories
                                or not entry.is_dir(follow_symlinks=False)
                            )
                        ):
                            continue
                        metadata = (
                            Path(path).lstat()
                            if os.name == "nt"
                            else entry.stat(follow_symlinks=False)
                        )
                    except OSError as error:
                        if on_issue is None:
                            raise
                        on_issue(path, error)
                        continue
                    kind = _entry_kind(metadata)
                    if kind is HostEntryKind.DIRECTORY and not include_directories:
                        continue
                    observation = HostDirectoryEntry(
                        path,
                        kind,
                        metadata.st_size,
                        metadata.st_mtime_ns,
                        LocalHostFile._from_stat(path, metadata)  # pyright: ignore[reportPrivateUsage]
                        if kind is HostEntryKind.FILE
                        else None,
                        self._from_stat(path, metadata)
                        if kind is HostEntryKind.DIRECTORY
                        else None,
                    )
                    entries.append(observation)
                    if on_entry is not None:
                        on_entry(observation)
            checkpoint()
            after = _directory_stat(pinned)
            current = self.observe(self.path)
            if (after.st_dev, after.st_ino) != (self.device, self.inode) or (
                current.device,
                current.inode,
            ) != (self.device, self.inode):
                raise ConcurrentModificationError(
                    "The observed Host directory was replaced"
                )
            if (
                self._from_stat(self.path, after) != self
                or before.st_ctime_ns != after.st_ctime_ns
                or current != self
            ):
                issue = ConcurrentModificationError(
                    "The Host directory changed while being listed"
                )
                if on_issue is None:
                    raise issue
                on_issue(self.path, issue)
        return tuple(sorted(entries, key=lambda item: str(item.path).casefold()))


def _entry_kind(value: os.stat_result) -> HostEntryKind:
    if is_link_or_reparse(value):
        return HostEntryKind.LINK_OR_REPARSE_POINT
    if stat.S_ISREG(value.st_mode):
        return HostEntryKind.FILE
    if stat.S_ISDIR(value.st_mode):
        return HostEntryKind.DIRECTORY
    return HostEntryKind.OTHER


def resolve_host_entry(
    path: HostPath, *, resolver: HostSelectionResolver | None = None
) -> HostDirectoryEntry:
    """Observe the canonical target of an explicitly authorized symbolic link."""
    resolved = (resolver or HostSelectionResolver()).resolve(path)
    metadata = Path(resolved).lstat()
    kind = _entry_kind(metadata)
    if kind not in (HostEntryKind.FILE, HostEntryKind.DIRECTORY):
        raise UnsafeFilesystemPathError(
            "The resolved Host target is not a file or directory"
        )
    return HostDirectoryEntry(
        resolved,
        kind,
        metadata.st_size,
        metadata.st_mtime_ns,
        LocalHostFile._from_stat(resolved, metadata)  # pyright: ignore[reportPrivateUsage]
        if kind is HostEntryKind.FILE
        else None,
        LocalHostDirectory._from_stat(resolved, metadata)  # pyright: ignore[reportPrivateUsage]
        if kind is HostEntryKind.DIRECTORY
        else None,
    )


def _require_directory(value: os.stat_result) -> None:
    if is_link_or_reparse(value) or not stat.S_ISDIR(value.st_mode):
        raise UnsafeFilesystemPathError(
            "Host directory path contains a link, reparse point, or non-directory"
        )


def _directory_stat(pinned: Path | int) -> os.stat_result:
    return os.fstat(pinned) if isinstance(pinned, int) else pinned.lstat()


@contextmanager
def pin_host_directory(path: Path) -> Generator[Path | int]:
    """Retain the validated directory and its ancestors for a Host operation."""
    validate_host_path_spelling(os.fspath(path).replace("\\", "/"))
    _check_local_drive(path)
    if os.name == "nt":
        with _pin_windows_directory(path):
            yield path
        return
    # Enumerate the pinned descriptor, not a path that could be renamed or swapped.
    directory_flag = cast("int", vars(os)["O_DIRECTORY"])
    no_follow = cast("int", vars(os)["O_NOFOLLOW"])
    with ExitStack() as stack:
        descriptor = os.open(path.anchor, os.O_RDONLY | directory_flag | no_follow)
        stack.callback(os.close, descriptor)
        for component in path.parts[1:]:
            descriptor = os.open(
                component, os.O_RDONLY | directory_flag | no_follow, dir_fd=descriptor
            )
            stack.callback(os.close, descriptor)
        yield descriptor


@contextmanager
def _pin_windows_directory(path: Path) -> Generator[None]:
    if sys.platform != "win32":
        raise OSError("Windows directory handles are unavailable on this Host")
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    with ExitStack() as stack:
        for current in (*reversed(path.parents), path):
            # OPEN_REPARSE_POINT avoids following this component. Omitting DELETE
            # sharing pins it against rename/replacement until enumeration ends.
            handle = kernel.CreateFileW(
                os.fspath(current),
                0x80000000,  # GENERIC_READ also makes sharing restrictions effective
                0x1 | 0x2,  # FILE_SHARE_READ | FILE_SHARE_WRITE
                None,
                3,  # OPEN_EXISTING
                0x00200000 | 0x02000000,  # OPEN_REPARSE_POINT | BACKUP_SEMANTICS
                None,
            )
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            stack.callback(kernel.CloseHandle, handle)
            _require_directory(current.lstat())
        yield


__all__ = [
    "HostDirectoryEntry",
    "HostEntryKind",
    "LocalHostDirectory",
    "pin_host_directory",
]
