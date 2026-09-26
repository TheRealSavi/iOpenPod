"""Host-only, cancellable media tools and private processing workspaces.

This module knows codecs and files, never iPod policy or Library identities.
External tools access private captures or identity-checked, pinned Host inputs.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from mutagen.mp3 import MP3, BitrateMode

from storage._filesystem import COPY_CHUNK_SIZE, fingerprint_from_stat
from storage.errors import FilePreconditionError, StorageOperationError
from storage.host_capture import (
    CapturedHostFile,
    # Share the internal copier while retaining this Storage workspace's lifetime.
    _capture,  # pyright: ignore[reportPrivateUsage]
)
from storage.host_input import LocalHostFile
from storage.paths import HostPath

_TRANSFORM_LOCK = threading.BoundedSemaphore(1)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from storage.models import FileFingerprint


class MediaToolError(StorageOperationError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class MediaTools:
    ffmpeg: HostPath
    ffprobe: HostPath
    fpcalc: HostPath | None
    encoders: frozenset[str]


@dataclass(frozen=True, slots=True)
class ToolOutput:
    stdout: bytes
    stderr: bytes
    returncode: int = 0


@dataclass(slots=True)
class _Pipe:
    limit: int
    data: bytearray = field(default_factory=bytearray)
    exceeded: threading.Event = field(default_factory=threading.Event)
    failed: threading.Event = field(default_factory=threading.Event)

    def read(self, pipe: object) -> None:
        from typing import BinaryIO

        stream = cast("BinaryIO", pipe)
        try:
            while chunk := stream.read(65536):
                remaining = max(0, self.limit - len(self.data))
                self.data.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self.exceeded.set()
        except OSError:
            self.failed.set()


def run_media_tool(
    executable: HostPath,
    arguments: tuple[str, ...],
    *,
    checkpoint: Callable[[], None],
    timeout_seconds: float = 60,
    max_output_bytes: int = 4 * 1024 * 1024,
    max_stderr_bytes: int | None = None,
    low_priority: bool = False,
    check: bool = True,
    input_file: HostPath | None = None,
) -> ToolOutput:
    """Run a bounded tool, optionally appending one pinned, seekable Host input.

    The input handle remains open until the child is reaped. On Windows its file
    and ancestor handles prevent replacement; POSIX passes the verified descriptor
    instead of reopening an untrusted pathname. Neither path copies the full file.
    """
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("Media tool deadline must be finite and positive")
    if max_output_bytes <= 0:
        raise ValueError("Media tool output limit must be positive")
    if max_stderr_bytes is not None and max_stderr_bytes <= 0:
        raise ValueError("Media tool diagnostic limit must be positive")
    checkpoint()
    if input_file is not None:
        observed = LocalHostFile.observe(input_file)
        with observed.open_read(checkpoint=checkpoint) as source:
            path = os.fspath(input_file)
            inherited_fds: tuple[int, ...] = ()
            if os.name != "nt":
                inherited_fds = (source.fileno(),)
                path = f"/dev/fd/{inherited_fds[0]}"
            return _run_media_tool(
                executable,
                (*arguments, path),
                checkpoint=checkpoint,
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
                max_stderr_bytes=max_stderr_bytes,
                low_priority=low_priority,
                check=check,
                inherited_fds=inherited_fds,
            )
    return _run_media_tool(
        executable,
        arguments,
        checkpoint=checkpoint,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        max_stderr_bytes=max_stderr_bytes,
        low_priority=low_priority,
        check=check,
        inherited_fds=(),
    )


def _run_media_tool(
    executable: HostPath,
    arguments: tuple[str, ...],
    *,
    checkpoint: Callable[[], None],
    timeout_seconds: float,
    max_output_bytes: int,
    max_stderr_bytes: int | None,
    low_priority: bool,
    check: bool,
    inherited_fds: tuple[int, ...],
) -> ToolOutput:
    flags = cast("int", vars(subprocess).get("CREATE_NO_WINDOW", 0))
    if low_priority:
        flags |= cast("int", vars(subprocess).get("BELOW_NORMAL_PRIORITY_CLASS", 0))
    try:
        process = subprocess.Popen(
            [os.fspath(executable), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=flags,
            pass_fds=inherited_fds,
        )
    except OSError as error:
        raise MediaToolError(
            "media.tool_unavailable",
            f"Could not start {executable.path.name}: {error}. Install the tool and check its executable permissions and PATH, then retry Sync.",
        ) from error
    assert process.stdout is not None and process.stderr is not None
    stdout, stderr = (
        _Pipe(max_output_bytes),
        _Pipe(max_stderr_bytes if max_stderr_bytes is not None else max_output_bytes),
    )
    readers = (
        threading.Thread(target=stdout.read, args=(process.stdout,)),
        threading.Thread(target=stderr.read, args=(process.stderr,)),
    )
    deadline = time.monotonic() + timeout_seconds
    try:
        for reader in readers:
            reader.start()
        while process.poll() is None:
            checkpoint()
            if stdout.exceeded.is_set() or stderr.exceeded.is_set():
                raise MediaToolError(
                    "media.tool_output_limit",
                    "Media tool diagnostics exceeded the safety limit; check the source file and retry.",
                )
            if time.monotonic() >= deadline:
                raise MediaToolError(
                    "media.tool_timeout",
                    f"{executable.path.name} exceeded its processing deadline; check that the source plays correctly and retry this item.",
                )
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=0.05)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        for reader in readers:
            if reader.ident is not None:
                reader.join()
        process.stdout.close()
        process.stderr.close()
    checkpoint()
    if stdout.exceeded.is_set() or stderr.exceeded.is_set():
        raise MediaToolError(
            "media.tool_output_limit",
            "Media tool diagnostics exceeded the safety limit; check the source file and retry.",
        )
    if stdout.failed.is_set() or stderr.failed.is_set():
        raise MediaToolError(
            "media.tool_io", "Could not read media tool diagnostics; retry this item."
        )
    if check and process.returncode:
        detail = bytes(stderr.data).decode("utf-8", errors="replace").strip()[-2000:]
        raise MediaToolError(
            "media.tool_failed",
            f"{executable.path.name} failed (exit {process.returncode}): {detail or 'No diagnostic was returned'}. Check the source file and encoder settings, then retry this item.",
        )
    return ToolOutput(bytes(stdout.data), bytes(stderr.data), process.returncode)


def discover_media_tools(*, checkpoint: Callable[[], None]) -> MediaTools:
    """Resolve all required executables before beginning a Sync preparation batch."""
    found: dict[str, HostPath] = {}
    missing: list[str] = []
    for name in ("ffmpeg", "ffprobe"):
        checkpoint()
        path = shutil.which(name)
        if path is None:
            missing.append(name)
        else:
            found[name] = HostPath(path)
    if missing:
        raise MediaToolError(
            "media.tools_missing",
            f"Required media tools are missing: {', '.join(missing)}. Install FFmpeg (including FFprobe), add its executable folder to PATH, then restart iOpenPod and retry these Tracks. No device changes have been made by media preparation.",
        )
    run_media_tool(
        found["ffprobe"], ("-version",), checkpoint=checkpoint, timeout_seconds=15
    )
    output = run_media_tool(
        found["ffmpeg"],
        ("-hide_banner", "-encoders"),
        checkpoint=checkpoint,
        timeout_seconds=15,
    )
    encoders = frozenset(
        match.group(1)
        for line in output.stdout.decode("utf-8", errors="replace").splitlines()
        if (match := re.match(r"\s*[VAS][A-Z.]{5}\s+(\S+)\s", line))
    )
    return MediaTools(
        found["ffmpeg"], found["ffprobe"], find_media_tool("fpcalc"), encoders
    )


def find_media_tool(name: str) -> HostPath | None:
    """Perform executable-path filesystem discovery inside Storage."""
    path = shutil.which(name)
    return HostPath(path) if path is not None else None


def inspect_mp3_variable_bitrate(source: HostPath) -> bool:
    """Read native MP3 header facts without exposing filesystem readers to callers."""
    parsed = cast("Callable[[str], Any]", MP3)(str(source))
    return parsed.info.bitrate_mode in (BitrateMode.VBR, BitrateMode.ABR)


class MediaWorkspace:
    """A private Host directory retained until its enclosing context exits."""

    def __init__(self, directory: Path, checkpoint: Callable[[], None]) -> None:
        self._directory = directory
        self._checkpoint = checkpoint

    def capture(
        self, source: HostPath, *, expected: FileFingerprint | None = None
    ) -> CapturedHostFile:
        self._checkpoint()
        captured = _capture(source, self._directory / "source", self._checkpoint, None)
        if expected is not None and captured.fingerprint != expected:
            raise FilePreconditionError(
                "The Host media changed after Review. Rescan and review the updated file before Sync."
            )
        return captured

    def output_path(self, suffix: str) -> HostPath:
        if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) is None:
            raise ValueError("A processed file needs a safe extension")
        return HostPath(self._directory / f"processed{suffix}")

    def snapshot_fingerprint(self, captured: CapturedHostFile) -> FileFingerprint:
        """Bind already-hashed captured bytes to their actual temporary identity."""
        path = Path(captured.snapshot)
        if path.parent != self._directory:
            raise ValueError("Only this workspace's capture can be identified")
        self._checkpoint()
        return fingerprint_from_stat(path.stat(), captured.fingerprint.sha256)

    def discard_capture(self, captured: CapturedHostFile) -> None:
        """Release an input snapshot once verified output no longer needs it."""
        path = Path(captured.snapshot)
        if path != self._directory / "source":
            raise ValueError("Only this workspace's private input can be discarded")
        path.unlink()

    def inspect_output(self, path: HostPath) -> CapturedHostFile:
        """Hash output by streaming; no second temporary full-file copy."""
        resolved = Path(path)
        if resolved.parent != self._directory or not resolved.name.startswith(
            "processed."
        ):
            raise ValueError("Only this workspace's output can be inspected")
        self._checkpoint()
        digest = hashlib.sha256()
        with resolved.open("rb") as stream:
            before = os.fstat(stream.fileno())
            while chunk := stream.read(COPY_CHUNK_SIZE):
                self._checkpoint()
                digest.update(chunk)
        return CapturedHostFile(
            path, path, fingerprint_from_stat(before, digest.hexdigest())
        )

    def transform_bytes(
        self,
        source: HostPath,
        suffix: str,
        transform: Callable[[bytes], bytes],
        *,
        max_bytes: int = 256 * 1024 * 1024,
    ) -> CapturedHostFile:
        """Apply a pure byte transform with bounded, serialized buffer allocation.

        Transcoding remains parallel. Whole-file metadata buffers never multiply
        by the number of encoders; cancellation remains observable while queued.
        """
        path = Path(source)
        if path.parent != self._directory:
            raise ValueError("Only this workspace's private files can be transformed")
        while not _TRANSFORM_LOCK.acquire(timeout=0.05):
            self._checkpoint()
        try:
            self._checkpoint()
            if path.stat().st_size > max_bytes:
                raise MediaToolError(
                    "media.tagging_size_limit",
                    f"This file exceeds the {max_bytes // (1024 * 1024)} MiB safe metadata-editing limit. Use a smaller file or disable optional metadata rewriting, then retry this item.",
                )
            data = path.read_bytes()
            self._checkpoint()
            output = transform(data)
            del data
            self._checkpoint()
            if len(output) > max_bytes:
                raise MediaToolError(
                    "media.tagging_size_limit",
                    "Embedded metadata exceeds the safe file-editing limit; reduce embedded metadata and retry this item.",
                )
            destination = self.output_path(suffix)
            Path(destination).write_bytes(output)
            del output
            return self.inspect_output(destination)
        finally:
            _TRANSFORM_LOCK.release()


@contextmanager
def media_workspace(*, checkpoint: Callable[[], None]) -> Generator[MediaWorkspace]:
    checkpoint()
    with tempfile.TemporaryDirectory(prefix="iopenpod-media-") as directory:
        yield MediaWorkspace(Path(directory).resolve(strict=True), checkpoint)


def available_compute_threads() -> int:
    """Respect CPU affinity where the OS exposes it."""
    affinity = getattr(os, "sched_getaffinity", None)
    if affinity is not None:
        return max(1, len(affinity(0)))
    return max(1, os.cpu_count() or 1)
