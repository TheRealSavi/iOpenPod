"""Inspect all streams of captured Host media without choosing a Library role."""

from __future__ import annotations

import json
import logging
import math
import re
import time
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import TYPE_CHECKING, cast

from iOpenPod.app.media.models import (
    MediaChapter,
    MediaInspection,
    MediaStream,
    MediaTag,
    StreamKind,
)
from storage import HostPath, capture_host_file
from storage.media_probe import MediaInspectionError as MediaInspectionError
from storage.media_probe import probe
from storage.media_processing import find_media_tool

if TYPE_CHECKING:
    from collections.abc import Callable

    from storage import CapturedHostFile

logger = logging.getLogger(__name__)


class MediaInspector:
    """FFprobe is required only when inspecting incoming files.

    Inspection identifies container/stream facts and a captured content hash. It
    does not decode every packet, establish device support, or grant write authority.
    The caller chooses the semantic role (Podcast, audiobook, movie, etc.) separately.
    """

    def __init__(
        self,
        executable: HostPath | None = None,
        *,
        timeout_seconds: float = 60,
        max_output_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Inspection timeout must be positive and finite")
        if max_output_bytes <= 0:
            raise ValueError("Inspection output limit must be positive")
        self._executable = executable
        self._timeout = timeout_seconds
        self._output_limit = max_output_bytes

    def inspect(
        self,
        source: HostPath,
        *,
        checkpoint: Callable[[], None],
    ) -> MediaInspection:
        self._resolve_executable()
        with capture_host_file(source, checkpoint=checkpoint) as captured:
            return self.inspect_captured(captured, checkpoint=checkpoint)

    def _resolve_executable(self) -> HostPath:
        if self._executable is not None:
            return self._executable
        discovered = find_media_tool("ffprobe")
        if discovered is None:
            raise MediaInspectionError(
                "media.probe_unavailable",
                "Install FFmpeg (including FFprobe) using Settings > Media Tools > "
                "Set Up Media Tools, or add its executable folder to PATH, then retry "
                "inspecting incoming media.",
            )
        return discovered

    def inspect_captured(
        self,
        captured: CapturedHostFile,
        *,
        checkpoint: Callable[[], None],
    ) -> MediaInspection:
        """Observe an existing Storage capture, shared with metadata readers."""
        checkpoint()
        source = captured.source
        executable = self._resolve_executable()
        started = time.monotonic()
        logger.debug("Media inspection started file=%s", source.path.name)
        try:
            data = probe(
                executable,
                captured.snapshot,
                checkpoint,
                timeout_seconds=self._timeout,
                max_output_bytes=self._output_limit,
            )
            result = _parse(data, captured)
            checkpoint()
        except MediaInspectionError as error:
            logger.debug(
                "Media inspection blocked code=%s detail=%s", error.code, error
            )
            raise
        logger.debug(
            "Media inspection completed file=%s size=%d sha256=%s containers=%s streams=%d chapters=%d elapsed_ms=%.1f",
            source.path.name,
            result.fingerprint.size,
            result.fingerprint.sha256,
            result.containers,
            len(result.streams),
            len(result.chapters),
            (time.monotonic() - started) * 1000,
        )
        for stream in result.streams:
            logger.debug(
                "Media stream index=%d kind=%s codec=%s tag=%s profile=%s level=%s sample_rate=%s channels=%s dimensions=%sx%s fps=%s bitrate=%s picture=%s",
                stream.index,
                stream.kind,
                stream.codec,
                stream.codec_tag,
                stream.profile,
                stream.level,
                stream.sample_rate_hz,
                stream.channels,
                stream.width,
                stream.height,
                stream.frame_rate,
                stream.bitrate_bps,
                stream.attached_picture,
            )
        return result


def _invalid(message: str) -> MediaInspectionError:
    return MediaInspectionError("media.probe_invalid", message)


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _invalid(f"Expected an object for {label}")
    fields = cast("dict[object, object]", value)
    if any(not isinstance(key, str) for key in fields):
        raise _invalid(f"Expected an object for {label}")
    return cast("dict[str, object]", fields)


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise _invalid(f"Expected an array for {label}")
    return cast("list[object]", value)


def _text(value: object, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _invalid(f"Expected text for {label}")
    return value


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise _invalid(f"Duplicate FFprobe field: {key}")
        values[key] = value
    return values


def _constant(value: str) -> object:
    raise _invalid(f"Invalid JSON numeric constant: {value}")


def _integer(value: object, label: str, *, signed: bool = False) -> int | None:
    if value is None or value == "N/A":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise _invalid(f"Expected an integer for {label}")
    text = str(value)
    if len(text) > 20 or re.fullmatch(r"-?\d+", text, flags=re.ASCII) is None:
        raise _invalid(f"Invalid integer for {label}")
    number = int(text)
    if abs(number) > 2**64 - 1 or (number < 0 and not signed):
        raise _invalid(f"Integer out of range for {label}")
    return number


def _rational(
    value: object,
    label: str,
    *,
    signed: bool = False,
    rate: bool = False,
) -> Fraction | None:
    if value is None or value == "N/A":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise _invalid(f"Expected a number for {label}")
    text = str(value)
    if len(text) > 80:
        raise _invalid(f"Number too long for {label}")
    try:
        if "/" in text or ":" in text:
            parts = re.split(r"[/:]", text)
            if len(parts) != 2:
                raise _invalid(f"Invalid fraction for {label}")
            numerator = _integer(parts[0], label, signed=signed)
            denominator = _integer(parts[1], label)
            if numerator is None or denominator is None:
                raise _invalid(f"Invalid fraction for {label}")
            if denominator == 0:
                if rate and numerator == 0:
                    return None
                raise _invalid(f"Zero denominator for {label}")
            number = Fraction(numerator, denominator)
        else:
            decimal = Decimal(text)
            exponent = decimal.as_tuple().exponent
            if (
                not decimal.is_finite()
                or not isinstance(exponent, int)
                or abs(exponent) > 20
            ):
                raise _invalid(f"Non-finite or excessive precision for {label}")
            if abs(decimal) > 2**64 - 1:
                raise _invalid(f"Number out of range for {label}")
            number = Fraction(decimal)
    except (ValueError, InvalidOperation) as error:
        raise _invalid(f"Invalid number for {label}") from error
    if number < 0 and not signed:
        raise _invalid(f"Negative number for {label}")
    return None if rate and number == 0 else number


def _tags(value: object) -> tuple[MediaTag, ...]:
    return tuple(
        MediaTag(k, _text(v, f"tag {k}")) for k, v in _object(value, "tags").items()
    )


def _flag(value: object, label: str) -> bool | None:
    number = _integer(value, label)
    if number is None:
        return None
    if number not in (0, 1):
        raise _invalid(f"Expected zero or one for {label}")
    return bool(number)


def _stream(value: object) -> MediaStream:
    row = _object(value, "stream")
    index = _integer(row.get("index"), "stream index")
    if index is None:
        raise _invalid("Stream index is missing")
    raw_kind = _text(row.get("codec_type"), "codec_type")
    kind = StreamKind(raw_kind) if raw_kind in StreamKind else StreamKind.UNKNOWN
    disposition = _object(row.get("disposition", {}), "disposition")
    time_base = _rational(row.get("time_base"), "time_base", rate=True)
    ticks = _integer(row.get("duration_ts"), "duration_ts")
    # Integer ticks preserve exact timing. Rounded decimal duration is a fallback.
    duration = (
        ticks * time_base
        if ticks is not None and time_base is not None
        else _rational(row.get("duration"), "stream duration")
    )
    return MediaStream(
        index=index,
        kind=kind,
        codec=_text(row.get("codec_name"), "codec_name"),
        codec_tag=_text(row.get("codec_tag_string"), "codec_tag_string"),
        profile=_text(row.get("profile"), "profile"),
        level=_integer(row.get("level"), "level", signed=True),
        duration_seconds=duration,
        start_seconds=_rational(row.get("start_time"), "stream start", signed=True),
        time_base=time_base,
        duration_ticks=ticks,
        bitrate_bps=_integer(row.get("bit_rate"), "stream bit_rate"),
        sample_rate_hz=_integer(row.get("sample_rate"), "sample_rate"),
        channels=_integer(row.get("channels"), "channels"),
        channel_layout=_text(row.get("channel_layout"), "channel_layout"),
        bits_per_sample=_integer(row.get("bits_per_sample"), "bits_per_sample"),
        bits_per_raw_sample=_integer(
            row.get("bits_per_raw_sample"), "bits_per_raw_sample"
        ),
        width=_integer(row.get("width"), "width"),
        height=_integer(row.get("height"), "height"),
        pixel_format=_text(row.get("pix_fmt"), "pix_fmt"),
        frame_rate=_rational(row.get("avg_frame_rate"), "avg_frame_rate", rate=True),
        nominal_frame_rate=_rational(
            row.get("r_frame_rate"), "r_frame_rate", rate=True
        ),
        sample_aspect_ratio=_rational(
            row.get("sample_aspect_ratio"), "sample_aspect_ratio", rate=True
        ),
        attached_picture=_flag(disposition.get("attached_pic"), "attached_pic"),
        default=_flag(disposition.get("default"), "default"),
        dispositions=tuple(k for k, v in disposition.items() if _flag(v, k)),
        tags=_tags(row.get("tags", {})),
    )


def _chapter(value: object) -> MediaChapter:
    row = _object(value, "chapter")
    chapter_id = _integer(row.get("id"), "chapter id", signed=True)
    time_base = _rational(row.get("time_base"), "chapter time_base", rate=True)
    start = _integer(row.get("start"), "chapter start")
    end = _integer(row.get("end"), "chapter end")
    start_time = (
        start * time_base
        if start is not None and time_base is not None
        else _rational(row.get("start_time"), "chapter start_time")
    )
    end_time = (
        end * time_base
        if end is not None and time_base is not None
        else _rational(row.get("end_time"), "chapter end_time")
    )
    if (
        chapter_id is None
        or start_time is None
        or end_time is None
        or end_time < start_time
    ):
        raise _invalid("Chapter has a missing identity or invalid time interval")
    return MediaChapter(chapter_id, start_time, end_time, _tags(row.get("tags", {})))


def _parse(data: bytes, captured: CapturedHostFile) -> MediaInspection:
    try:
        raw: object = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_float=Decimal,
            parse_constant=_constant,
        )
    except (ValueError, RecursionError) as error:
        raise _invalid("FFprobe did not return valid UTF-8 JSON") from error
    root = _object(raw, "FFprobe result")
    format_row = _object(root.get("format"), "format")
    size = _integer(format_row.get("size"), "format size")
    if size != captured.fingerprint.size:
        raise _invalid("FFprobe size does not match the captured file")
    containers = tuple(_text(format_row.get("format_name"), "format_name").split(","))
    if any(not name for name in containers):
        raise _invalid("FFprobe did not identify the container")
    rows = _array(root.get("streams"), "streams")
    if not rows:
        raise _invalid("FFprobe did not report any streams")
    streams = tuple(_stream(row) for row in rows)
    if len({stream.index for stream in streams}) != len(streams):
        raise _invalid("FFprobe returned duplicate stream indexes")
    count = _integer(format_row.get("nb_streams"), "nb_streams")
    if count is not None and count != len(streams):
        raise _invalid("FFprobe did not report every stream")
    return MediaInspection(
        captured.source,
        captured.fingerprint,
        containers,
        _rational(format_row.get("duration"), "format duration"),
        _rational(format_row.get("start_time"), "format start", signed=True),
        _integer(format_row.get("bit_rate"), "format bit_rate"),
        _tags(format_row.get("tags", {})),
        streams,
        tuple(_chapter(row) for row in _array(root.get("chapters", []), "chapters")),
    )
