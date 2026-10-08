"""Private prepared files with an aggregate memory budget and disk overflow."""

from __future__ import annotations

import hashlib
import io
import tempfile
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from storage.errors import FilePreconditionError
from storage.host_input import LocalHostFile
from storage.paths import DevicePath, HostPath
from storage.transactions import FileContent

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable
    from typing import BinaryIO

    from storage.models import FileFingerprint
    from storage.session import FilesystemSession


class StagedContent:
    """Read-only captured output; usable until its workspace is closed."""

    def __init__(
        self, path: HostPath, content: FileContent, checkpoint: Callable[[], None]
    ) -> None:
        self._observed = LocalHostFile.observe(path)
        self._content = content
        self._checkpoint = checkpoint
        if self._observed.size_bytes != content.size:
            raise FilePreconditionError("Prepared content size changed.")

    @property
    def path(self) -> HostPath:
        return self._observed.path

    def __len__(self) -> int:
        return self._content.size

    @property
    def sha256(self) -> str:
        return self._content.sha256

    def read_at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or offset + length > len(self):
            raise ValueError("Prepared content read is out of bounds.")
        with self._observed.open_read(checkpoint=self._checkpoint) as stream:
            stream.seek(offset)
            data = stream.read(length)
        if len(data) != length:
            raise FilePreconditionError("Prepared content was truncated.")
        return data


@dataclass
class _MemoryBudget:
    limit: int
    retained: int = 0

    @property
    def remaining(self) -> int:
        return self.limit - self.retained


class ContentWorkspace:
    """Own temporary content and account for all retained in-memory buffers."""

    def __init__(
        self, directory: Path, memory_budget: int, checkpoint: Callable[[], None]
    ) -> None:
        if memory_budget < 0:
            raise ValueError("Content memory budget cannot be negative.")
        self._directory = directory
        self._budget = _MemoryBudget(memory_budget)
        self._checkpoint = checkpoint
        self._next_file = 0
        self._closed = False
        self._open_buffers: set[ContentFileBuffer] = set()

    @property
    def remaining_bytes(self) -> int:
        return self._budget.remaining

    def _path(self) -> HostPath:
        if self._closed:
            raise ValueError("Content workspace is closed.")
        self._checkpoint()
        self._next_file += 1
        return HostPath(self._directory / str(self._next_file))

    def new_buffer(self) -> ContentFileBuffer:
        if self._closed:
            raise ValueError("Content workspace is closed.")
        self._checkpoint()
        buffer = ContentFileBuffer(
            self._budget, self._checkpoint, self._path, self._open_buffers.discard
        )
        self._open_buffers.add(buffer)
        return buffer

    def store(self, data: bytes) -> bytes | StagedContent:
        return self.store_chunks((data,))

    def store_chunks(self, chunks: Iterable[bytes]) -> bytes | StagedContent:
        buffer = self.new_buffer()
        try:
            for chunk in chunks:
                buffer.append(chunk)
            return buffer.finish()
        finally:
            buffer.close()

    def capture_device(
        self, session: FilesystemSession, path: DevicePath
    ) -> tuple[bytes | StagedContent, FileContent]:
        """Capture complete Device content within the retained-memory budget."""
        data, fingerprint = self.capture_device_snapshot(session, path)
        return data, FileContent.from_fingerprint(fingerprint)

    def capture_device_snapshot(
        self, session: FilesystemSession, path: DevicePath
    ) -> tuple[bytes | StagedContent, FileFingerprint]:
        """Capture bytes and their Device precondition in the same read."""
        destination = self._path()
        copied = session.copy_to_host(
            path, destination, progress=lambda _: self._checkpoint()
        )
        content = FileContent(copied.bytes_copied, copied.sha256)
        if content.size <= self.remaining_bytes:
            data = LocalHostFile.observe(destination).read_bytes(
                max_bytes=self.remaining_bytes, checkpoint=self._checkpoint
            )
            self._budget.retained += len(data)
            Path(destination).unlink()
            return data, copied.source_fingerprint
        return (
            StagedContent(destination, content, self._checkpoint),
            copied.source_fingerprint,
        )

    def close(self) -> None:
        self._closed = True
        with ExitStack() as unfinished:
            for buffer in tuple(self._open_buffers):
                unfinished.callback(buffer.close)


class ContentFileBuffer:
    def __init__(
        self,
        budget: _MemoryBudget,
        checkpoint: Callable[[], None],
        new_path: Callable[[], HostPath],
        on_close: Callable[[ContentFileBuffer], None],
    ) -> None:
        self._budget = budget
        self._checkpoint = checkpoint
        self._new_path = new_path
        self._on_close = on_close
        self._memory = io.BytesIO()
        self._disk: BinaryIO | None = None
        self._path: HostPath | None = None
        self._size = 0
        self._reserved_memory = 0
        self._digest = hashlib.sha256()
        self._finished = False
        self._files = ExitStack()

    def __len__(self) -> int:
        return self._size

    def append(self, data: bytes) -> None:
        if self._finished:
            raise ValueError("Prepared content is already frozen.")
        self._checkpoint()
        if self._disk is None and len(data) > self._budget.remaining:
            self._path = self._new_path()
            # The workspace closes this handle on finish, failure, or cancellation.
            self._disk = self._files.enter_context(Path(self._path).open("xb"))  # noqa: SIM115
            self._memory.seek(0)
            while chunk := self._memory.read(1024 * 1024):
                self._checkpoint()
                self._disk.write(chunk)
            self._memory.close()
            self._budget.retained -= self._reserved_memory
            self._reserved_memory = 0
        if self._disk is None:
            self._memory.write(data)
            self._budget.retained += len(data)
            self._reserved_memory += len(data)
        else:
            self._disk.write(data)
        self._digest.update(data)
        self._size += len(data)

    def finish(self) -> bytes | StagedContent:
        if self._finished:
            raise ValueError("Prepared content is already frozen.")
        self._checkpoint()
        if self._disk is None:
            result: bytes | StagedContent = self._memory.getvalue()
            # The frozen bytes remain accounted for after this builder closes.
            self._reserved_memory = 0
        else:
            self._disk.close()
            assert self._path is not None
            result = StagedContent(
                self._path,
                FileContent(self._size, self._digest.hexdigest()),
                self._checkpoint,
            )
        self.close()
        return result

    def close(self) -> None:
        self._finished = True
        self._budget.retained -= self._reserved_memory
        self._reserved_memory = 0
        self._memory.close()
        try:
            self._files.close()
        finally:
            self._on_close(self)


@contextmanager
def content_workspace(
    *, memory_budget: int, checkpoint: Callable[[], None]
) -> Generator[ContentWorkspace]:
    checkpoint()
    with tempfile.TemporaryDirectory(prefix="iopenpod-content-") as directory:
        workspace = ContentWorkspace(
            Path(directory).resolve(strict=True), memory_budget, checkpoint
        )
        try:
            yield workspace
        finally:
            workspace.close()
