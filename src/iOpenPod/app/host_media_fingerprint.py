"""Generate bounded, cancellable Chromaprint fingerprints with ``fpcalc``."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from storage import HostPath, StorageError
from storage.media_processing import MediaToolError, find_media_tool, run_media_tool

if TYPE_CHECKING:
    from collections.abc import Callable


_ALGORITHM = 2
_LENGTH_SECONDS = 120
# Never let libavformat auto-detect a playlist/manifest hidden behind a media
# extension. These demuxers consume one file; MOV external references stay disabled
# by the decoder's default policy.
_INPUT_FORMATS = {
    ".aac": "aac",
    ".aif": "aiff",
    ".aiff": "aiff",
    ".alac": "mov",
    ".flac": "flac",
    ".m4a": "mov",
    ".m4b": "mov",
    ".mp3": "mp3",
    ".oga": "ogg",
    ".ogg": "ogg",
    ".opus": "ogg",
    ".wav": "wav",
    ".wma": "asf",
    ".wv": "wv",
    ".avi": "avi",
    ".m4v": "mov",
    ".mkv": "matroska",
    ".mov": "mov",
    ".mp4": "mov",
    ".mpeg": "mpeg",
    ".mpg": "mpeg",
    ".webm": "matroska",
    ".wmv": "asf",
}


class FpcalcError(RuntimeError):
    """One media file did not produce a trustworthy acoustic fingerprint."""


class FpcalcUnavailableError(FpcalcError):
    """The required ``fpcalc`` executable could not be found or started."""


class FpcalcFingerprinter:
    """Adapt ``fpcalc`` to the Host Media Scan's cancellation contract.

    Raw algorithm-2 output is retained because later matching needs the individual
    Chromaprint values. Work is capped at the same first 120 seconds used by the
    Original iOpenPod rather than decoding an unbounded audiobook or movie.
    """

    def __init__(
        self,
        executable: HostPath | None = None,
        *,
        timeout_seconds: float = 300,
        max_output_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("fpcalc timeout must be positive and finite")
        if max_output_bytes <= 0:
            raise ValueError("fpcalc output limit must be positive")
        self._executable = executable
        self._timeout = timeout_seconds
        self._output_limit = max_output_bytes

    def fingerprint(
        self,
        source: HostPath,
        *,
        checkpoint: Callable[[], None],
    ) -> str:
        """Return one canonical raw fingerprint for a Host audio-bearing file."""

        executable = self._resolve_executable()
        output = _run_fpcalc(
            executable,
            source,
            checkpoint,
            timeout_seconds=self._timeout,
            max_output_bytes=self._output_limit,
        )
        return _parse_output(output)

    def _resolve_executable(self) -> HostPath:
        if self._executable is not None:
            return self._executable
        discovered = find_media_tool("fpcalc")
        if discovered is None:
            raise FpcalcUnavailableError(
                "Install Chromaprint's fpcalc, add its executable folder to PATH, "
                "then restart iOpenPod and retry the scan."
            )
        return discovered


def _run_fpcalc(
    executable: HostPath,
    source: HostPath,
    checkpoint: Callable[[], None],
    *,
    timeout_seconds: float,
    max_output_bytes: int,
) -> bytes:
    checkpoint()
    input_format = _INPUT_FORMATS.get(source.path.suffix.casefold())
    if input_format is None:
        raise FpcalcError(
            "No safe single-file decoder is configured for this extension"
        )
    arguments = (
        "-algorithm",
        str(_ALGORITHM),
        "-raw",
        "-length",
        str(_LENGTH_SECONDS),
        "-text",
        "-format",
        input_format,
    )
    try:
        result = run_media_tool(
            executable,
            arguments,
            input_file=source,
            checkpoint=checkpoint,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            max_stderr_bytes=min(max_output_bytes, 65536),
            low_priority=True,
            check=False,
        )
    except MediaToolError as error:
        if error.code == "media.tool_unavailable":
            raise FpcalcUnavailableError(
                f"Could not start fpcalc: {error.__cause__ or error}"
            ) from error
        message = {
            "media.tool_output_limit": "fpcalc output exceeds the scan limit",
            "media.tool_timeout": "fpcalc fingerprinting timed out",
            "media.tool_io": "Could not read fpcalc output",
        }.get(error.code, str(error))
        raise FpcalcError(message) from error
    except (OSError, StorageError) as error:
        raise FpcalcError(str(error)) from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[:2000]
        raise FpcalcError(detail or "fpcalc could not fingerprint the file")
    return result.stdout


def _parse_output(payload: bytes) -> str:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FpcalcError("fpcalc did not return UTF-8 text") from error
    values = [
        line.removeprefix("FINGERPRINT=").strip()
        for line in text.splitlines()
        if line.startswith("FINGERPRINT=")
    ]
    if len(values) != 1 or not values[0]:
        raise FpcalcError("fpcalc did not return exactly one fingerprint")
    return normalize_fpcalc_fingerprint(values[0])


def normalize_fpcalc_fingerprint(value: str) -> str:
    """Validate and canonicalize one raw unsigned ``fpcalc`` fingerprint."""

    parts = value.split(",")
    if len(parts) > 250_000:
        raise FpcalcError("fpcalc returned too many fingerprint values")
    if not value or any(not part.isascii() or not part.isdigit() for part in parts):
        raise FpcalcError("fpcalc returned an invalid raw fingerprint")
    numbers = tuple(int(part) for part in parts)
    if any(number > 2**32 - 1 for number in numbers):
        raise FpcalcError("fpcalc returned an out-of-range fingerprint value")
    return ",".join(str(number) for number in numbers)


__all__ = [
    "FpcalcError",
    "FpcalcFingerprinter",
    "FpcalcUnavailableError",
    "normalize_fpcalc_fingerprint",
]
