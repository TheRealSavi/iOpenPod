"""Inspect retained CEA-608 packets without rewriting their decoder commands.

FFmpeg's MOV demuxer replaces cdat/cdt2 atoms with A53-style triplets: a
0xfc/0xfd field marker and the original byte pair. These checks cover that
representation, not the complete source atom envelope. See get_eia608_packet:
https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/mov.c

Control diagnostics follow Classic 120GB RetailOS 2.0.1's miscellaneous-control
handler. They are neither a caption renderer nor a claim about every iPod.
Parity is masked only for inspection; hashes always use the original bytes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from iOpenPod.app.display_text import source_text
from iOpenPod.app.media.inspection import MediaInspectionError
from storage.media_processing import run_media_tool

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.media.models import MediaInspection, MediaStream
    from storage import HostPath
    from storage.media_processing import MediaTools


@dataclass(frozen=True, slots=True)
class CaptionPacketInfo:
    warnings: tuple[str, ...] = ()
    has_field_2: bool = False


@dataclass(frozen=True, slots=True)
class CaptionStreamVerification:
    source_index: int
    packet_count: int
    payload_sha256: str
    warnings: tuple[str, ...]
    has_field_2: bool


def inspect_caption_packet(payload: bytes) -> CaptionPacketInfo:
    """Validate demuxed c608 triplets, preserving parity and repeated commands."""
    if not payload or len(payload) % 3:
        raise ValueError("Caption packet does not contain complete byte-pair triplets")
    warnings: list[str] = []
    field_2 = False
    for offset in range(0, len(payload), 3):
        marker, first, second = payload[offset : offset + 3]
        if marker in (0xFE, 0xFF):
            raise ValueError("CEA-708 data is not supported in a retained c608 stream")
        if marker not in (0xFC, 0xFD):
            raise ValueError("Caption packet contains an invalid field marker")
        field_2 |= marker == 0xFD
        # Firmware masks parity before interpreting commands. Never normalize
        # the retained bytes or collapse duplicate control pairs here.
        first &= 0x7F
        second &= 0x7F
        if first not in (0x14, 0x1C):
            continue
        if second in (0x22, 0x23):
            warnings.append(
                source_text(
                    "Caption alarm controls may not work on this iPod. Original caption commands are retained."
                )
            )
        elif second == 0x28:
            warnings.append(
                source_text(
                    "Caption flashing may not display on this iPod. Original caption commands are retained."
                )
            )
        elif second in (0x2A, 0x2B):
            warnings.append(
                source_text(
                    "Caption text mode may not display on this iPod. Original caption commands are retained."
                )
            )
    return CaptionPacketInfo(tuple(dict.fromkeys(warnings)), field_2)


def verify_captions(
    streams: tuple[MediaStream, ...],
    observed: MediaInspection,
    source: HostPath,
    tools: MediaTools,
    *,
    remux: bool,
    duration_seconds: float,
    checkpoint: Callable[[], None],
) -> tuple[CaptionStreamVerification, ...]:
    """Inspect selected captured streams and fingerprint their original payloads.

    The MOV writer retains only field-1 triplets. Reject a remux that would drop
    field 2; unchanged file copies can retain it with a playback-uncertainty warning.
    The digest covers packet bytes in order, not the original atom envelope or a
    rendered interpretation. Packet counts are retained as a separate verification.
    """
    verified: list[CaptionStreamVerification] = []
    for stream in streams:
        checkpoint()
        output = run_media_tool(
            tools.ffprobe,
            (
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-format_whitelist",
                ",".join(observed.containers),
                "-select_streams",
                str(stream.index),
                "-show_packets",
                "-show_data",
                "-show_entries",
                "packet=data,size",
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
            if output.returncode or output.stderr.strip():
                raise ValueError("The caption demuxer reported an error")
            document: object = json.loads(output.stdout)
            raw_packets = _object(document).get("packets")
            if not isinstance(raw_packets, list):
                raise ValueError("Invalid caption packet list")
            packets = cast("list[object]", raw_packets)
        except (ValueError, UnicodeError) as error:
            raise MediaInspectionError(
                "media.caption_unreadable",
                f"Caption stream {stream.index} could not be read completely. "
                "Repair the source or uncheck this caption stream; this item was not written to the iPod.",
            ) from error
        if not packets:
            raise MediaInspectionError(
                "media.caption_empty",
                f"Caption stream {stream.index} contains no caption packets. "
                "Choose another caption stream or uncheck it.",
            )
        digest = hashlib.sha256()
        warnings: list[str] = []
        field_2 = False
        for packet in packets:
            checkpoint()
            try:
                fields = _object(packet)
                payload = _payload(fields.get("data"), fields.get("size"))
                information = inspect_caption_packet(payload)
            except ValueError as error:
                raise MediaInspectionError(
                    "media.caption_invalid",
                    f"Caption stream {stream.index} contains malformed caption data. "
                    "Repair the source or uncheck this caption stream; this item was not written to the iPod.",
                ) from error
            digest.update(payload)
            warnings.extend(information.warnings)
            field_2 |= information.has_field_2
        if field_2:
            if remux:
                raise MediaInspectionError(
                    "media.caption_field_2",
                    f"Caption stream {stream.index} contains field-2 captions that FFmpeg cannot retain in this prepared video. "
                    "Choose another caption stream or uncheck it; this item was not written to the iPod.",
                )
            warnings.append(
                source_text(
                    "Caption field 2 is retained unchanged; its playback on this iPod has not been verified."
                )
            )
        verified.append(
            CaptionStreamVerification(
                stream.index,
                len(packets),
                digest.hexdigest(),
                tuple(
                    f"Caption stream {stream.index}: {warning}"
                    for warning in dict.fromkeys(warnings)
                ),
                field_2,
            )
        )
    return tuple(verified)


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) for key in cast("dict[object, object]", value)
    ):
        raise ValueError("Invalid caption packet object")
    return cast("dict[str, object]", value)


def _payload(dump: object, size: object) -> bytes:
    if not isinstance(dump, str) or not isinstance(size, str) or not size.isdecimal():
        raise ValueError("Missing caption packet bytes or size")
    data = bytearray()
    for line in dump.splitlines():
        if not line.strip():
            continue
        address, separator, columns = line.partition(":")
        if not separator or int(address, 16) != len(data):
            raise ValueError("Invalid caption packet dump address")
        # FFprobe emits sixteen bytes in a fixed-width column, then ASCII.
        # Hex-looking ASCII text must not become additional payload.
        row = bytes.fromhex(columns[1:40])
        if not 0 < len(row) <= 16:
            raise ValueError("Invalid caption packet dump row")
        data.extend(row)
    if len(data) != int(size):
        raise ValueError("Caption packet dump does not match its reported size")
    return bytes(data)
