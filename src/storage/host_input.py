"""Read-only access to Host filesystem files, including network media sources.

Resolving a reference grants no read authority. Observe before review, then read or
capture only the exact approved observation. Reads never follow links or reparse
points. Explicit user selections have a separate canonical target resolver.
"""

from __future__ import annotations

import io
import os
import re
import stat
import sys
import tempfile
from collections import deque
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import unquote, urlsplit

from storage._filesystem import is_link_or_reparse
from storage.errors import (
    ConcurrentModificationError,
    FileSizeLimitError,
    InvalidHostPathError,
    UnsafeFilesystemPathError,
)
from storage.paths import HostPath

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from typing import BinaryIO

    from _typeshed import WriteableBuffer

_DRIVE = re.compile(r"^[A-Za-z]:/")
_RESERVED = re.compile(
    r"^(?:con|prn|aux|nul|conin\$|conout\$|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)", re.I
)
_CHUNK_BYTES = 1024 * 1024
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x1
_FILE_SHARE_WRITE = 0x2
_OPEN_EXISTING = 3
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000


class HostSelectionResolver:
    """Reuse ordinary ancestor probes within one selection or enumeration pass.

    Cached directories never authorize reads. If an ancestor is replaced, the
    mandatory no-link observation/open checks reject it. Link targets themselves
    are not cached here, and callers must discard this resolver between passes.
    """

    def __init__(self) -> None:
        self._directories: set[Path] = set()

    def resolve(self, path: HostPath) -> HostPath:
        return _resolve_host_selection(path, self._directories)


def resolve_host_selection(path: HostPath) -> HostPath:
    """Resolve one explicit selection without sharing any observations."""
    return HostSelectionResolver().resolve(path)


def _resolve_host_selection(path: HostPath, directories: set[Path]) -> HostPath:
    """Resolve an explicitly authorized selection, never an indirect reference.

    Only symbolic links are permitted. Other reparse points, device path
    syntax and special files remain unavailable. The returned spelling grants no
    read authority: callers must retain a normal no-link Storage observation.
    """
    source = Path(path)

    def validate(value: Path) -> None:
        spelling = os.fspath(value)
        validate_host_path_spelling(
            spelling.replace("\\", "/") if os.name == "nt" else spelling,
            allow_network=True,
        )
        _check_host_drive(value, allow_network=True)

    validate(source)
    current = Path(source.anchor)
    remaining = deque(source.parts[1:])
    links = 0
    while remaining:
        component = remaining.popleft()
        if component == "..":
            current = current.parent
            continue
        candidate = current / component
        if candidate in directories:
            current = candidate
            continue
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            links += 1
            if links > 40:
                raise UnsafeFilesystemPathError("Symbolic link cycle or too many links")
            target = candidate.readlink()
            # Native Windows links can return extended-length filesystem paths.
            raw_target = os.fspath(target)
            if os.name == "nt" and raw_target.startswith("\\\\?\\"):
                raw_target = raw_target[4:]
                if raw_target[:4].casefold() == "unc\\":
                    raw_target = "\\\\" + raw_target[4:]
                elif not _DRIVE.match(raw_target.replace("\\", "/")):
                    raise InvalidHostPathError("Device paths are not allowed")
                target = Path(raw_target)
            target = target if target.is_absolute() else current / target
            validate(target)
            current = Path(target.anchor)
            remaining.extendleft(reversed(target.parts[1:]))
            continue
        if is_link_or_reparse(metadata):
            raise UnsafeFilesystemPathError("Unsupported Host reparse point")
        if not stat.S_ISDIR(metadata.st_mode) and (
            remaining or not stat.S_ISREG(metadata.st_mode)
        ):
            raise UnsafeFilesystemPathError(
                "Host selection is not a regular file or directory"
            )
        current = candidate
        if stat.S_ISDIR(metadata.st_mode):
            directories.add(candidate)
    return HostPath(current)


def resolve_local_file_reference(
    value: str, relative_to: HostPath, *, uri: bool = False
) -> HostPath:
    """Normalize a filesystem path without probing it or expanding shell syntax.

    URI paths are percent-decoded exactly once. Ordinary paths retain literal
    percent signs. Windows separators are normalized on Windows; POSIX
    backslashes remain filename characters.
    """

    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if not value or len(value) > 32768:
        raise InvalidHostPathError("Empty or oversized file reference")
    if os.name == "nt":
        value = value.replace("\\", "/")
    if not _DRIVE.match(value):
        parsed = urlsplit(value)
        is_uri = uri or parsed.scheme.casefold() == "file" or "://" in value
        if is_uri:
            if parsed.scheme.casefold() not in {"", "file"}:
                raise InvalidHostPathError("Network and non-file URLs are not allowed")
            remote_authority = parsed.netloc.casefold() not in {"", "localhost"}
            if remote_authority and os.name != "nt":
                raise InvalidHostPathError("Remote file URLs are not allowed")
            if parsed.query or parsed.fragment:
                raise InvalidHostPathError(
                    "File URLs cannot contain queries or fragments"
                )
            value = unquote(parsed.path, errors="strict")
            if os.name == "nt":
                value = value.replace("\\", "/")
            if re.match(r"^/[A-Za-z]:/", value):
                value = value[1:]
            if remote_authority:
                value = "//" + parsed.netloc + "/" + value.lstrip("/")
            if parsed.scheme and not (value.startswith("/") or _DRIVE.match(value)):
                raise InvalidHostPathError("File URLs must name an absolute path")
    validate_host_path_spelling(value, allow_network=True)
    if _DRIVE.match(value) and os.name != "nt":
        raise InvalidHostPathError("A Windows drive path is unavailable on this Host")
    path = Path(value)
    if not path.is_absolute():
        path = Path(relative_to).parent / path
    result = HostPath(os.path.abspath(path))
    result_spelling = os.fspath(result)
    if os.name == "nt":
        result_spelling = result_spelling.replace("\\", "/")
    validate_host_path_spelling(result_spelling, allow_network=True)
    return result


def validate_host_path_spelling(value: str, *, allow_network: bool = False) -> None:
    """Validate slash-separated Host paths; media may opt into ordinary UNC paths."""
    if not value or value.startswith(("//?/", "//./", "/??/", "//??/", r"\\")):
        raise InvalidHostPathError("Device paths are not allowed")
    if value.startswith("//") and not (allow_network and os.name == "nt"):
        raise InvalidHostPathError("Network and device paths are not allowed")
    if value.startswith("//"):
        authority = value[2:].split("/")
        if len(authority) < 2 or any(part in {"", ".", ".."} for part in authority[:2]):
            raise InvalidHostPathError("A network path must name a server and share")
    tail = value[3:] if _DRIVE.match(value) else value
    if any(ord(char) < 32 or (os.name == "nt" and char in '<>:"|?*') for char in tail):
        raise InvalidHostPathError("File reference contains unsafe path characters")
    if os.name == "nt" and any(
        _RESERVED.match(part)
        or (part not in {"", ".", ".."} and part.endswith((".", " ")))
        for part in tail.split("/")
    ):
        raise InvalidHostPathError("Reserved or ambiguous file name")


@dataclass(frozen=True, slots=True)
class LocalHostFile:
    """One regular Host file and the identity observed before authorization."""

    path: HostPath
    size_bytes: int
    modified_ns: int
    device: int
    inode: int

    @classmethod
    def observe(cls, path: HostPath) -> LocalHostFile:
        source = Path(path)
        source_spelling = os.fspath(source)
        if os.name == "nt":
            source_spelling = source_spelling.replace("\\", "/")
        validate_host_path_spelling(source_spelling, allow_network=True)
        _check_host_drive(source, allow_network=True)
        for parent in reversed(source.parents):
            metadata = parent.lstat()
            if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
                raise UnsafeFilesystemPathError(
                    "Host path contains a link or reparse point"
                )
        metadata = source.lstat()
        _require_regular(metadata)
        return cls._from_stat(path, metadata)

    @classmethod
    def _from_stat(cls, path: HostPath, value: os.stat_result) -> LocalHostFile:
        return cls(path, value.st_size, value.st_mtime_ns, value.st_dev, value.st_ino)

    def validate(self) -> None:
        if self.observe(self.path) != self:
            raise ConcurrentModificationError("The reviewed Host file changed")

    @contextmanager
    def open_read(
        self,
        *,
        checkpoint: Callable[[], None] | None = None,
        max_bytes: int | None = None,
    ) -> Generator[BinaryIO]:
        """Lend a seekable read-only stream for this exact observed file.

        Reads and seeks run the cancellation checkpoint. The stream is closed on
        scope exit; successful use verifies that neither identity nor file facts
        changed. ``max_bytes`` optionally limits the accepted source file size.
        """
        if max_bytes is not None:
            if max_bytes < 0:
                raise ValueError("The read limit must not be negative")
            if self.size_bytes > max_bytes:
                raise FileSizeLimitError("Host file exceeds the allowed read limit")
        if checkpoint is not None:
            checkpoint()
        with (
            self._open() as source,
            _ReadOnlyHostStream(source, self, checkpoint) as reader,
        ):
            yield cast("BinaryIO", reader)
            if checkpoint is not None:
                checkpoint()

    @contextmanager
    def _open(self) -> Generator[BinaryIO]:
        self.validate()
        with open_local_file(Path(self.path)) as source:
            before = os.fstat(source.fileno())
            _require_regular(before)
            if self._from_stat(self.path, before) != self:
                raise ConcurrentModificationError("The reviewed Host file was replaced")
            yield source
            after = os.fstat(source.fileno())
            if (
                self._from_stat(self.path, after) != self
                or before.st_ctime_ns != after.st_ctime_ns
            ):
                raise ConcurrentModificationError(
                    "The Host file changed while being read"
                )
            self.validate()

    def read_bytes(self, *, max_bytes: int, checkpoint: Callable[[], None]) -> bytes:
        if max_bytes < 0:
            raise ValueError("The read limit must not be negative")
        if self.size_bytes > max_bytes:
            raise FileSizeLimitError("Host file exceeds the allowed read limit")
        data = bytearray()
        with self._open() as source:
            while True:
                checkpoint()
                chunk = source.read(min(_CHUNK_BYTES, max_bytes + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise FileSizeLimitError("Host file exceeds the allowed read limit")
        return bytes(data)

    @contextmanager
    def capture(self, *, checkpoint: Callable[[], None]) -> Generator[HostPath]:
        """Inspect a private copy; preserve the filename for format detection."""

        with tempfile.TemporaryDirectory(prefix="iopenpod-local-input-") as directory:
            snapshot = Path(directory).resolve(strict=True) / self.path.path.name
            copied = 0
            with self._open() as source, snapshot.open("xb") as output:
                while True:
                    checkpoint()
                    chunk = source.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > self.size_bytes:
                        raise ConcurrentModificationError(
                            "Host file grew during capture"
                        )
                    output.write(chunk)
                if copied != self.size_bytes:
                    raise ConcurrentModificationError("Host file shrank during capture")
            checkpoint()
            yield HostPath(snapshot)


class _ReadOnlyHostStream(io.BufferedIOBase):
    """A non-owning facade; closing it cannot bypass the owner's final checks."""

    def __init__(
        self,
        source: BinaryIO,
        observed: LocalHostFile,
        checkpoint: Callable[[], None] | None,
    ) -> None:
        super().__init__()
        self._source, self._observed, self._checkpoint = source, observed, checkpoint

    @property
    def name(self) -> str:
        return os.fspath(self._observed.path)

    def _check(self) -> None:
        if self.closed:
            raise ValueError("Read from closed Host file stream")
        if self._checkpoint is not None:
            self._checkpoint()

    def _read_limit(self, size: int | None) -> int:
        remaining = max(0, self._observed.size_bytes - self._source.tell())
        return remaining + 1 if size is None or size < 0 else min(size, remaining + 1)

    def _verify_read(self, start: int, length: int) -> None:
        if length and start + length > self._observed.size_bytes:
            raise ConcurrentModificationError("The Host file grew while being read")

    def read(self, size: int | None = -1) -> bytes:
        self._check()
        start = self._source.tell()
        result = self._source.read(self._read_limit(size))
        self._verify_read(start, len(result))
        return result

    def read1(self, size: int = -1) -> bytes:
        return self.read(size)

    def readinto(self, buffer: WriteableBuffer) -> int:
        view = memoryview(buffer).cast("B")
        result = self.read(view.nbytes)
        view[: len(result)] = result
        return len(result)

    def readinto1(self, buffer: WriteableBuffer) -> int:
        return self.readinto(buffer)

    def readline(self, size: int | None = -1) -> bytes:
        self._check()
        start = self._source.tell()
        result = self._source.readline(self._read_limit(size))
        self._verify_read(start, len(result))
        return result

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        self._check()
        return self._source.seek(offset, whence)

    def tell(self) -> int:
        self._check()
        return self._source.tell()

    def fileno(self) -> int:
        self._check()
        return self._source.fileno()

    def readable(self) -> bool:
        return not self.closed

    def seekable(self) -> bool:
        return not self.closed

    def writable(self) -> bool:
        return False


def _require_regular(value: os.stat_result) -> None:
    if is_link_or_reparse(value) or not stat.S_ISREG(value.st_mode):
        raise UnsafeFilesystemPathError(
            "Host source must be a regular file without links"
        )


def _check_host_drive(path: Path, *, allow_network: bool = False) -> None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
        kernel.GetDriveTypeW.restype = wintypes.UINT
        allowed = {2, 3, 5, 6}
        if allow_network:
            allowed.add(4)  # DRIVE_REMOTE: a normal filesystem source for Host media.
        if kernel.GetDriveTypeW(path.anchor) not in allowed:
            raise UnsafeFilesystemPathError(
                "Host input must be on an available filesystem drive"
                if allow_network
                else "Host input must be on a local drive"
            )


@contextmanager
def open_local_file(path: Path) -> Generator[BinaryIO]:
    """Open a local path without following links while retaining its parent handles."""
    if os.name == "nt":
        with _open_windows_file(path) as source:
            yield source
        return
    # Pin every directory; O_NOFOLLOW applies to each component, not just the leaf.
    directory_flag = cast("int", vars(os)["O_DIRECTORY"])
    no_follow = cast("int", vars(os)["O_NOFOLLOW"])
    nonblock = cast("int", vars(os)["O_NONBLOCK"])
    with ExitStack() as stack:
        directory = os.open(path.anchor, os.O_RDONLY | directory_flag)
        stack.callback(os.close, directory)
        for component in path.parts[1:-1]:
            directory = os.open(
                component, os.O_RDONLY | directory_flag | no_follow, dir_fd=directory
            )
            stack.callback(os.close, directory)
        descriptor = os.open(
            path.name, os.O_RDONLY | no_follow | nonblock, dir_fd=directory
        )
        with os.fdopen(descriptor, "rb") as source:
            yield source


@contextmanager
def _open_windows_file(path: Path) -> Generator[BinaryIO]:
    if sys.platform != "win32":
        raise OSError("Windows file handles are unavailable on this Host")
    import ctypes
    import msvcrt
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

    def open_handle(target: Path, *, directory: bool) -> int:
        handle = kernel.CreateFileW(
            os.fspath(target),
            _GENERIC_READ,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE if directory else _FILE_SHARE_READ,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_OPEN_REPARSE_POINT
            | (_FILE_FLAG_BACKUP_SEMANTICS if directory else 0),
            None,
        )
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        return int(handle)

    # OPEN_REPARSE_POINT never follows the current component. Omitting DELETE
    # sharing pins each validated directory against rename/replacement until close.
    with ExitStack() as stack:
        for parent in reversed(path.parents):
            handle = open_handle(parent, directory=True)
            stack.callback(kernel.CloseHandle, handle)
            metadata = parent.lstat()
            if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
                raise UnsafeFilesystemPathError(
                    "Host path contains a link or reparse point"
                )
        handle = open_handle(path, directory=False)
        try:
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle(handle)
            raise
        with os.fdopen(descriptor, "rb") as source:
            yield source
