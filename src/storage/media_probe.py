"""Run an explicitly selected FFprobe with bounded output and cancellation."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import BinaryIO

    from storage import HostPath


class MediaInspectionError(Exception):
    """An incoming file could not supply trustworthy inspection facts."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# Single-file demuxers only: playlists, concat scripts, network protocols and image
# sequences are not authorization to open additional files. MOV external data
# references remain disabled by default; never enable enable_drefs/use_absolute_path.
_FORMATS = (
    "mov,mp3,aac,flac,wav,aiff,ogg,matroska,webm,avi,asf,mpeg,mpegts,"
    "ac3,eac3,dts,amr,ape,au,caf,wv,tta,aa,dsf,dff,tak,mpc,mpc8,rm"
)
_ENTRIES = (
    "format=format_name,duration,start_time,size,bit_rate,nb_streams:format_tags:"
    "stream=index,codec_type,codec_name,codec_tag_string,profile,level,duration,"
    "start_time,time_base,duration_ts,bit_rate,sample_rate,channels,channel_layout,"
    "bits_per_sample,bits_per_raw_sample,width,height,pix_fmt,avg_frame_rate,"
    "r_frame_rate,sample_aspect_ratio:stream_disposition:stream_tags:"
    "chapter=id,time_base,start,end,start_time,end_time:chapter_tags"
)
_CREATE_NO_WINDOW = cast("int", vars(subprocess).get("CREATE_NO_WINDOW", 0))


@dataclass(slots=True)
class _Output:
    limit: int
    data: bytearray = field(default_factory=bytearray)
    exceeded: threading.Event = field(default_factory=threading.Event)
    failed: threading.Event = field(default_factory=threading.Event)

    def read(self, pipe: BinaryIO) -> None:
        try:
            while chunk := pipe.read(65536):
                remaining = max(0, self.limit - len(self.data))
                self.data.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self.exceeded.set()
        except OSError:
            self.failed.set()


def probe(
    executable: HostPath,
    source: HostPath,
    checkpoint: Callable[[], None],
    *,
    timeout_seconds: float,
    max_output_bytes: int,
) -> bytes:
    checkpoint()
    args = [
        os.fspath(executable),
        "-v",
        "error",
        "-hide_banner",
        "-max_alloc",
        str(64 * 1024 * 1024),
        "-protocol_whitelist",
        "file",
        "-format_whitelist",
        _FORMATS,
        "-probesize",
        str(16 * 1024 * 1024),
        "-analyzeduration",
        "10000000",
        "-show_entries",
        _ENTRIES,
        "-of",
        "json",
        "-i",
        os.fspath(source),
    ]
    stdout = _Output(max_output_bytes)
    stderr = _Output(min(max_output_bytes, 65536))
    try:
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_CREATE_NO_WINDOW,
        )
    except OSError as error:
        raise MediaInspectionError(
            "media.probe_unavailable", f"Could not start FFprobe: {error}"
        ) from error
    assert process.stdout is not None and process.stderr is not None
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
                raise MediaInspectionError(
                    "media.probe_output_limit",
                    "FFprobe output exceeds the inspection limit",
                )
            if time.monotonic() >= deadline:
                raise MediaInspectionError(
                    "media.probe_timeout", "FFprobe inspection timed out"
                )
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=min(0.05, max(0.001, deadline - time.monotonic())))
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
        raise MediaInspectionError(
            "media.probe_output_limit", "FFprobe output exceeds the inspection limit"
        )
    if stdout.failed.is_set() or stderr.failed.is_set():
        raise MediaInspectionError("media.probe_io", "Could not read FFprobe output")
    if process.returncode != 0:
        detail = bytes(stderr.data).decode("utf-8", errors="replace").strip()[:2000]
        raise MediaInspectionError(
            "media.probe_failed", f"FFprobe could not inspect the file: {detail}"
        )
    if stderr.data.strip():
        logging.getLogger(__name__).debug(
            "FFprobe returned usable output with diagnostics: %s",
            bytes(stderr.data).decode("utf-8", errors="replace")[:2000],
        )
    return bytes(stdout.data)
