"""Bounded in-memory decoding for complete-song analysis."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import numpy as np
from numpy.typing import NDArray

from storage.media_processing import find_media_tool

from .models import AnalysisProgress, AnalysisStage

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import BinaryIO

FloatArray = NDArray[np.float32]

_READ_SIZE = 1024 * 1024
_ERROR_LIMIT = 64 * 1024
_CREATE_NO_WINDOW = cast("int", vars(subprocess).get("CREATE_NO_WINDOW", 0))
_FORMATS = (
    "mov,mp3,aac,flac,wav,aiff,ogg,matroska,webm,avi,asf,mpeg,mpegts,"
    "ac3,eac3,dts,amr,ape,au,caf,wv,tta,aa,dsf,dff,tak,mpc,mpc8,rm"
)


class AudioDecodeError(Exception):
    """The selected file could not become bounded float PCM."""


@dataclass(frozen=True, slots=True)
class DecodedAudio:
    sample_rate_hz: int
    samples: FloatArray

    def __post_init__(self) -> None:
        if self.sample_rate_hz <= 0:
            raise ValueError("Decoded sample rate must be positive")
        if self.samples.ndim != 2 or self.samples.shape[1] != 2:
            raise ValueError("Analysis audio must contain two channels")
        if self.samples.dtype != np.float32:
            raise ValueError("Decoded samples must use float32")
        if not self.samples.flags.c_contiguous:
            raise ValueError("Decoded samples must be contiguous")

    @property
    def duration_seconds(self) -> float:
        return len(self.samples) / self.sample_rate_hz


@dataclass(slots=True)
class _DecodeState:
    byte_limit: int
    pcm: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    error: BaseException | None = None
    exceeded: bool = False


class FFmpegDecoder:
    """Decode one explicit Host file without creating derived files."""

    def __init__(
        self,
        executable: str | None = None,
        *,
        sample_rate_hz: int = 32_000,
        maximum_duration_seconds: float = 15 * 60,
    ) -> None:
        if not 16_000 <= sample_rate_hz <= 192_000:
            raise ValueError("Analysis sample rate is outside the supported range")
        if maximum_duration_seconds <= 0.0:
            raise ValueError("Maximum analysis duration must be positive")
        self._executable = executable
        self._sample_rate_hz = sample_rate_hz
        self._maximum_duration_seconds = maximum_duration_seconds

    def decode(
        self,
        source: Path,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[AnalysisProgress], None],
    ) -> DecodedAudio:
        resolved = source.expanduser().resolve(strict=True)
        if not resolved.is_file():
            raise AudioDecodeError(f"Analysis source is not a file: {resolved}")
        checkpoint()
        progress(
            AnalysisProgress(
                0.01,
                AnalysisStage.DECODE,
                f"Decoding {resolved.name} into bounded memory",
            )
        )
        command = [
            self._resolve_executable(),
            "-v",
            "error",
            "-hide_banner",
            "-nostdin",
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            _FORMATS,
            "-i",
            os.fspath(resolved),
            "-map",
            "0:a:0",
            "-vn",
            "-sn",
            "-dn",
            "-ac",
            "2",
            "-ar",
            str(self._sample_rate_hz),
            "-f",
            "f32le",
            "pipe:1",
        ]
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=_CREATE_NO_WINDOW,
            )
        except OSError as error:
            raise AudioDecodeError(f"Could not start FFmpeg: {error}") from error
        assert process.stdout is not None
        assert process.stderr is not None
        byte_limit = int(self._maximum_duration_seconds * self._sample_rate_hz * 8)
        state = _DecodeState(byte_limit)
        readers = (
            threading.Thread(
                target=_read_pcm,
                args=(process.stdout, state),
                name="music-analysis-pcm",
            ),
            threading.Thread(
                target=_read_stderr,
                args=(process.stderr, state),
                name="music-analysis-errors",
            ),
        )
        try:
            for reader in readers:
                reader.start()
            while process.poll() is None:
                checkpoint()
                if state.error is not None or state.exceeded:
                    process.kill()
                    break
                time.sleep(0.02)
        except BaseException:
            process.kill()
            raise
        finally:
            process.wait()
            process.stdout.close()
            process.stderr.close()
            for reader in readers:
                reader.join()
        checkpoint()
        if state.error is not None:
            raise AudioDecodeError(f"Could not decode audio: {state.error}")
        if state.exceeded:
            raise AudioDecodeError(
                "Decoded audio exceeds the configured duration limit"
            )
        if process.returncode != 0:
            detail = bytes(state.stderr).decode("utf-8", errors="replace").strip()
            raise AudioDecodeError(detail or "FFmpeg could not decode the audio file")
        samples = np.frombuffer(state.pcm, dtype="<f4")
        samples = samples[: samples.size - samples.size % 2]
        if samples.size < self._sample_rate_hz:
            raise AudioDecodeError("The selected file contains less than half a second")
        stereo = np.ascontiguousarray(samples.reshape(-1, 2), dtype=np.float32)
        progress(
            AnalysisProgress(
                0.08,
                AnalysisStage.DECODE,
                f"Decoded {len(stereo) / self._sample_rate_hz:.1f} seconds",
            )
        )
        return DecodedAudio(self._sample_rate_hz, stereo)

    def _resolve_executable(self) -> str:
        if self._executable is not None:
            return self._executable
        executable = find_media_tool("ffmpeg")
        if executable is None:
            raise AudioDecodeError("Install FFmpeg to analyze music")
        return str(executable)


def _read_pcm(stream: BinaryIO, state: _DecodeState) -> None:
    try:
        while chunk := stream.read(_READ_SIZE):
            remaining = state.byte_limit - len(state.pcm)
            state.pcm.extend(chunk[: max(0, remaining)])
            if len(chunk) > remaining:
                state.exceeded = True
                return
    except OSError as error:
        state.error = error


def _read_stderr(stream: BinaryIO, state: _DecodeState) -> None:
    try:
        while chunk := stream.read(8192):
            remaining = _ERROR_LIMIT - len(state.stderr)
            state.stderr.extend(chunk[: max(0, remaining)])
    except OSError as error:
        state.error = error


__all__ = ["AudioDecodeError", "DecodedAudio", "FFmpegDecoder"]
