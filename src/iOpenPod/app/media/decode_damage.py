"""Recognize and report source packets FFmpeg could not decode.

A strict FFmpeg run aborts on the first undecodable packet. When the failure
is a decoder's, not the container's, preparation runs a lenient second pass
that skips the damage the way players do. This module classifies FFmpeg's
diagnostics line by line with plain string tests so each recognized shape is
named in code and easy to extend when FFmpeg changes its wording.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from iOpenPod.app.media.inspection import MediaInspectionError
from storage.media_processing import MediaToolError

if TYPE_CHECKING:
    from collections.abc import Callable

SOURCE_DAMAGED_MESSAGE = (
    "The source is too damaged to play completely: its decodable audio is shorter "
    "than the file reports. Repair or replace the source file; this item was not "
    "written to the iPod."
)

# FFmpeg's text for AVERROR_INVALIDDATA. Demuxers and decoders both use it, so
# the surrounding context decides whether a line names a skippable packet.
_INVALID_DATA = b"Invalid data found when processing input"
# FFmpeg 7 tags decoder diagnostics, for example:
# "[aist#0:0/mp3 @ 0x2] [dec:mp3float @ 0x3] Error submitting packet to decoder: Invalid data ..."
_DECODER_TAG = b"[dec:"
# FFmpeg 6.0's lenient pass names the stream instead:
# "Error while decoding stream #0:0: Invalid data found when processing input"
_STREAM_DECODE_ERROR = b"Error while decoding stream #"
# FFmpeg 6.1 uses the input stream context without a nested [dec:] tag.
_INPUT_STREAM_TAGS = (b"[aist#", b"[vist#")
_DECODE_ERRORS = (b"Error submitting packet to decoder:", b"Decoding error:")
# FFmpeg 6.0 exits under -xerror before logging the stream-level error. These
# codec-specific messages identify damaged MP3/FLAC frames, not container faults.
# Keep this fallback separate from packet counting: several codec lines can
# describe one packet. Unknown codec-only errors continue to fail closed.
_LEGACY_FRAME_ERRORS = (
    (b"[mp3float @", b"Header missing"),
    (b"[mp3 @", b"Header missing"),
    (b"[flac @", b"invalid frame header"),
)
# A lenient pass that produced no output decoded nothing at all.
_NOTHING_DECODED = (b"Output file is empty", b"nothing was encoded")
# Stream, input and output contexts describe structure, not a codec's complaint.
_STRUCTURAL_CONTEXTS = (
    b"[in#",
    b"[out#",
    b"[aist#",
    b"[vist#",
    b"[sist#",
    b"[dec:",
    b"[enc:",
)


def is_skipped_packet(line: bytes) -> bool:
    """Whether one FFmpeg diagnostic line reports an undecodable source packet.

    Container errors such as ``[in#0 @ 0x1] Error during demuxing: Invalid data
    found when processing input`` carry the same text without a decoder or
    stream context and are not skippable.
    """
    phrase = line.find(_INVALID_DATA)
    if phrase == -1:
        return False
    tag = line.find(_DECODER_TAG)
    if tag != -1 and b"]" in line[tag:phrase]:
        return True
    for prefix in _INPUT_STREAM_TAGS:
        tag = line.find(prefix)
        close = line.find(b"]", tag) if tag != -1 else -1
        if close != -1 and line[close + 1 : phrase].strip() in _DECODE_ERRORS:
            return True
    marker = line.find(_STREAM_DECODE_ERROR)
    if marker == -1:
        return False
    stream = line[marker + len(_STREAM_DECODE_ERROR) : phrase].strip()
    if not stream.endswith(b":"):
        return False
    numbers = stream[:-1].split(b":")
    return len(numbers) == 2 and all(number.isdigit() for number in numbers)


def _mentions_skipped_packet(diagnostics: bytes) -> bool:
    return any(is_skipped_packet(line) for line in diagnostics.splitlines())


def _decoded_nothing(diagnostics: bytes) -> bool:
    return any(phrase in diagnostics for phrase in _NOTHING_DECODED)


def _without_contexts(line: bytes) -> bytes:
    """Drop the leading ``[codec @ 0x...]`` tags from a diagnostic line."""
    while line.startswith(b"["):
        close = line.find(b"]")
        if close == -1:
            break
        line = line[close + 1 :].lstrip()
    return line


def is_decode_failure(error: MediaToolError) -> bool:
    """Whether a strict FFmpeg run stopped on an undecodable source packet."""
    if error.code != "media.tool_failed":
        return False
    diagnostics = str(error).encode("utf-8", errors="replace")
    if _mentions_skipped_packet(diagnostics):
        return True
    for line in diagnostics.splitlines():
        for context, message in _LEGACY_FRAME_ERRORS:
            tag = line.find(context)
            close = line.find(b"]", tag) if tag != -1 else -1
            if close != -1 and line[close + 1 :].lstrip().startswith(message):
                return True
    return False


def retry_skipping_damage[T](run: Callable[[], T]) -> T:
    """Run the lenient second pass after a confirmed decode failure.

    A pass that floods the diagnostics, still stops on undecodable packets, or
    decodes nothing names the source as too damaged. Any other failure, such as
    an encoder fault or a full Host workspace, keeps its own diagnosis.
    """
    try:
        return run()
    except MediaToolError as error:
        if error.code == "media.tool_output_limit":
            raise MediaInspectionError(
                "media.source_damaged", SOURCE_DAMAGED_MESSAGE
            ) from error
        if error.code == "media.tool_failed":
            detail = str(error).encode("utf-8", errors="replace")
            if _mentions_skipped_packet(detail) or _decoded_nothing(detail):
                raise MediaInspectionError(
                    "media.source_damaged", SOURCE_DAMAGED_MESSAGE
                ) from error
        raise


def damage_warnings(stderr: bytes) -> tuple[str, ...]:
    """Warn about a lenient pass even when its diagnostics could not be parsed.

    The strict pass already proved the source has undecodable packets, so a
    successful retry must never be reported as a clean conversion.
    """
    return _decode_error_warnings(stderr) or (
        "Skipped damaged packets in the source. Playback may glitch briefly at "
        "that point. Replace the source file to remove the damage.",
    )


def _decode_error_warnings(stderr: bytes) -> tuple[str, ...]:
    """Summarize the source packets FFmpeg skipped during a lenient pass.

    The lenient pass logs with ``repeat`` so every skipped packet keeps its own
    decoder line. The codec's own lines immediately before the first skip, such
    as ``Header missing`` or ``invalid sync code``, explain the damage; the
    first is quoted.
    """
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    skips = [index for index, line in enumerate(lines) if is_skipped_packet(line)]
    if not skips:
        return ()
    explanation = b""
    index = skips[0] - 1
    while index >= 0:
        line = lines[index]
        if not line.startswith(b"[") or line.startswith(_STRUCTURAL_CONTEXTS):
            break
        explanation = _without_contexts(line)
        index -= 1
    detail = (
        f" ({explanation.decode('utf-8', errors='replace')[:120]})"
        if explanation
        else ""
    )
    skipped = len(skips)
    packets = "packet" if skipped == 1 else "packets"
    return (
        f"Skipped {skipped} damaged {packets} in the source{detail}. Playback may "
        "glitch briefly at that point. Replace the source file to remove the damage.",
    )
