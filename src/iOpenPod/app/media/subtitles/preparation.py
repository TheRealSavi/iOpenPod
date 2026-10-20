"""Read timed text packets and stage readable, non-overlapping iPod subtitles.

FFprobe supplies container timestamps, including frame-based legacy formats.
Format converters own payload syntax; Storage owns processes and temporary files.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, cast

from iOpenPod.app.media.inspection import MediaInspectionError
from iOpenPod.app.media.subtitles import convert_packet
from iOpenPod.app.media.subtitles.timing import (
    SubtitleCue,
    normalize_cues,
    to_webvtt,
)
from storage.media_processing import run_media_tool

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.media.models import MediaInspection, MediaStream
    from storage import HostPath
    from storage.media_processing import MediaTools, MediaWorkspace


@dataclass(frozen=True, slots=True)
class SubtitleConversion:
    stream: MediaStream
    output_index: int


@dataclass(frozen=True, slots=True)
class PreparedSubtitle:
    source_index: int
    source: HostPath
    cues: tuple[SubtitleCue, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Packet:
    start_ms: int | None
    duration_ms: int | None
    text: str


def prepare_subtitles(
    streams: tuple[MediaStream, ...],
    observed: MediaInspection,
    source: HostPath,
    workspace: MediaWorkspace,
    tools: MediaTools,
    *,
    duration_seconds: float,
    checkpoint: Callable[[], None],
) -> tuple[PreparedSubtitle, ...]:
    prepared: list[PreparedSubtitle] = []
    for index, stream in enumerate(streams):
        checkpoint()
        cues, warnings = read_cues(
            source,
            stream,
            tools,
            containers=observed.containers,
            offset=observed.start_seconds or Fraction(0),
            duration_seconds=duration_seconds,
            checkpoint=checkpoint,
        )
        if not cues:
            raise MediaInspectionError(
                "media.subtitle_empty",
                f"Subtitle stream {stream.index} ({stream.codec}) contains no readable "
                "text with usable timing in this video. Choose another subtitle "
                "stream or uncheck it; this item was not written to the iPod.",
            )
        data = to_webvtt(cues)
        staged = workspace.capture_stream(
            io.BytesIO(data), f".s{index}", max_bytes=len(data)
        )
        prepared.append(
            PreparedSubtitle(
                stream.index,
                staged.snapshot,
                cues,
                tuple(f"Subtitle stream {stream.index}: {item}" for item in warnings),
            )
        )
    return tuple(prepared)


def read_cues(
    source: HostPath,
    stream: MediaStream,
    tools: MediaTools,
    *,
    containers: tuple[str, ...],
    offset: Fraction,
    duration_seconds: float,
    checkpoint: Callable[[], None],
) -> tuple[tuple[SubtitleCue, ...], tuple[str, ...]]:
    """Read only this stream; malformed styling never invokes a subtitle decoder."""
    output = run_media_tool(
        tools.ffprobe,
        (
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            ",".join(containers),
            "-select_streams",
            str(stream.index),
            "-show_packets",
            "-show_data",
            "-show_entries",
            "packet=pts_time,dts_time,duration_time,data",
            "-of",
            "json",
            "-i",
            str(source),
        ),
        checkpoint=checkpoint,
        timeout_seconds=max(120, duration_seconds),
        max_output_bytes=64 * 1024 * 1024,
        max_stderr_bytes=65536,
        check=False,
    )
    try:
        document: object = json.loads(output.stdout)
        raw_packets = _object(document).get("packets", [])
        if not isinstance(raw_packets, list):
            raise ValueError("Invalid subtitle packet list")
        packets = cast("list[object]", raw_packets)
    except (ValueError, UnicodeError) as error:
        raise MediaInspectionError(
            "media.subtitle_unreadable",
            f"Subtitle stream {stream.index} could not be read. "
            "Choose another subtitle stream or repair the source.",
        ) from error
    warnings: list[str] = []
    if output.returncode or output.stderr.strip():
        warnings.append(
            "The source reported errors; readable subtitle packets were recovered."
        )
    decoded: list[_Packet] = []
    offset_ms = round(offset * 1000)
    for packet in packets:
        checkpoint()
        try:
            fields = _object(packet)
        except ValueError:
            warnings.append("An unreadable subtitle packet was skipped.")
            continue
        raw = fields.get("data")
        if not isinstance(raw, str):
            continue
        try:
            payload = _payload(raw)
        except ValueError:
            warnings.append("An unreadable subtitle packet was skipped.")
            continue
        converted = convert_packet(stream.codec, payload)
        warnings.extend(converted.warnings)
        start = _milliseconds(fields.get("pts_time"))
        if start is None:
            start = _milliseconds(fields.get("dts_time"))
        decoded.append(
            _Packet(
                None if start is None else start - offset_ms,
                _milliseconds(fields.get("duration_time")),
                converted.text,
            )
        )
    cues = _timed_cues(decoded, round(duration_seconds * 1000), warnings)
    normalized = normalize_cues(tuple(cues))
    warnings.extend(normalized.warnings)
    return normalized.cues, tuple(dict.fromkeys(warnings))


def verify_subtitles(
    prepared: tuple[PreparedSubtitle, ...],
    converted_streams: tuple[MediaStream, ...],
    result: MediaInspection,
    tools: MediaTools,
    *,
    duration_seconds: float,
    checkpoint: Callable[[], None],
) -> None:
    """Verify encoded text and timing, not merely a nonempty stream header."""
    for expected, stream in zip(prepared, converted_streams, strict=True):
        actual, _ = read_cues(
            result.source,
            stream,
            tools,
            containers=result.containers,
            # Staged subtitles already share the output media timeline.
            offset=Fraction(0),
            duration_seconds=duration_seconds,
            checkpoint=checkpoint,
        )
        if len(actual) != len(expected.cues) or any(
            left.text != right.text
            or abs(left.start_ms - right.start_ms) > 2
            or abs(left.end_ms - right.end_ms) > 2
            for left, right in zip(expected.cues, actual, strict=True)
        ):
            raise MediaInspectionError(
                "media.subtitle_output_mismatch",
                f"Subtitle stream {expected.source_index} lost text or timing during "
                "conversion. This item was not written to the iPod.",
            )


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Invalid subtitle packet object")
    return cast("dict[str, object]", value)


def _milliseconds(value: object) -> int | None:
    if not isinstance(value, (str, int)):
        return None
    try:
        return round(Fraction(value) * 1000)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def _payload(dump: str) -> bytes:
    # FFprobe's xxd dump has sixteen payload bytes followed by an ASCII preview.
    # Read its fixed-width hex column so text resembling hex cannot become data.
    rows = [line.partition(":") for line in dump.splitlines() if line.strip()]
    if any(
        not separator
        or not address
        or any(char not in "0123456789abcdefABCDEF" for char in address)
        for address, separator, _ in rows
    ):
        raise ValueError("Invalid subtitle packet dump")
    return bytes.fromhex("".join(data[1:40] for _, _, data in rows))


def _timed_cues(
    packets: list[_Packet], duration_ms: int, warnings: list[str]
) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    previous_end = 0
    # Empty tx3g samples are useful end markers even though they contain no text.
    next_start: list[int | None] = [None] * len(packets)
    known_start: int | None = None
    for index in range(len(packets) - 1, -1, -1):
        next_start[index] = known_start
        if packets[index].start_ms is not None:
            known_start = packets[index].start_ms
    for index, packet in enumerate(packets):
        if not packet.text.strip():
            continue
        start = packet.start_ms
        if start is None:
            start = previous_end
            warnings.append(
                "Missing subtitle timestamps were estimated from nearby cues."
            )
        duration = packet.duration_ms
        if duration is None or duration <= 0:
            following = next_start[index]
            end = (
                following
                if following is not None and following > start
                else min(duration_ms, start + 3000)
            )
            warnings.append(
                "Missing subtitle durations were estimated from nearby cues."
            )
        else:
            end = start + duration
        if end <= 0 or start >= duration_ms:
            warnings.append("Subtitle cues outside this video's duration were omitted.")
            continue
        start = max(0, start)
        end = min(duration_ms, max(start + 1, end))
        cues.append(SubtitleCue(start, end, packet.text))
        previous_end = end
    return cues
