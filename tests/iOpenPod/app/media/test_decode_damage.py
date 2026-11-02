"""Recognizing and reporting source packets FFmpeg could not decode."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from iOpenPod.app.media import MediaInspectionError
from iOpenPod.app.media.decode_damage import (
    damage_warnings,
    is_decode_failure,
    is_skipped_packet,
    retry_skipping_damage,
)
from storage.media_processing import MediaToolError

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.mark.parametrize(
    ("line", "skipped"),
    [
        # FFmpeg 7 and later tag the decoder.
        (
            b"[aist#0:0/mp3 @ 0x2] [dec:mp3float @ 0x3] Decoding error: Invalid data "
            b"found when processing input",
            True,
        ),
        (
            b"[aist#0:0/mp3 @ 0x2] [dec:mp3float @ 0x3] Error submitting packet to "
            b"decoder: Invalid data found when processing input",
            True,
        ),
        # FFmpeg 6 names the stream.
        (
            b"Error while decoding stream #0:0: Invalid data found when processing input",
            True,
        ),
        (
            b"Error while decoding stream #12:3:Invalid data found when processing input",
            True,
        ),
        # FFmpeg 6.1 uses the input-stream context without a nested decoder tag.
        (
            b"[aist#0:0/mp3 @ 0x2] Error submitting packet to decoder: Invalid "
            b"data found when processing input",
            True,
        ),
        (
            b"[aist#0:0/flac @ 0x2] Decoding error: Invalid data found when processing input",
            True,
        ),
        (
            b"[aist#0:0/mp3 @ 0x2] Error during demuxing: Invalid data found when processing input",
            False,
        ),
        # The container, not a decoder, rejected the data.
        (
            b"[in#0 @ 0x1] Error during demuxing: Invalid data found when processing input",
            False,
        ),
        (b"[mp3 @ 0x1] Invalid data found when processing input", False),
        # A stream reference that is not FFmpeg's "#input:stream" form.
        (
            b"Error while decoding stream #a:b: Invalid data found when processing input",
            False,
        ),
        # The decoder tag appears, but the complaint is something else.
        (b"[dec:aac @ 0x2] Decoding error: Input buffer exhausted", False),
        (b"[flac @ 0x1] Header missing", False),
    ],
)
def test_is_skipped_packet_classifies_one_diagnostic_line(
    line: bytes, skipped: bool
) -> None:
    assert is_skipped_packet(line) is skipped


def test_damage_warnings_summarize_skipped_packets() -> None:
    stderr = (
        b"[mp3float @ 0x55d] Header missing\n"
        b"[aist#0:0/mp3 @ 0x55e] [dec:mp3float @ 0x55f] Decoding error: Invalid "
        b"data found when processing input\n"
        b"[aist#0:0/mp3 @ 0x55e] [dec:mp3float @ 0x55f] Decoding error: Invalid "
        b"data found when processing input\n"
    )
    (warning,) = damage_warnings(stderr)
    assert warning.startswith(
        "Skipped 2 damaged packets in the source (Header missing)"
    )
    assert "Replace the source file" in warning


def test_damage_warnings_quote_the_codec_not_structural_info_lines() -> None:
    # Sound Check runs verification at info level, so stream and input
    # descriptions precede the codec's complaint and must not be quoted.
    stderr = (
        b"[in#0 @ 0x1] Format mp3 detected only with low score of 1\n"
        b"Input #0, mp3, from '/home/user/Music/track.mp3':\n"
        b"  Duration: 00:03:00.00, start: 0.000000, bitrate: 128 kb/s\n"
        b"[flac @ 0x2] invalid sync code\n"
        b"[flac @ 0x2] invalid frame header\n"
        b"[flac @ 0x2] decode_frame() failed\n"
        b"[aist#0:0/flac @ 0x3] [dec:flac @ 0x4] Decoding error: Invalid data "
        b"found when processing input\n"
        b"[Parsed_ebur128_0 @ 0x5] Summary:\n"
    )
    (warning,) = damage_warnings(stderr)
    assert warning.startswith(
        "Skipped 1 damaged packet in the source (invalid sync code)"
    )
    assert "/home/user" not in warning


def test_a_successful_retry_always_carries_a_damage_warning() -> None:
    # The strict pass already proved the source is damaged, so diagnostics that
    # cannot be counted still earn a warning, just without a packet count.
    for stderr in (b"", b"[flac @ 0x1] unrelated notice\n"):
        (fallback,) = damage_warnings(stderr)
        assert fallback.startswith("Skipped damaged packets in the source")


def test_ffmpeg_6_decode_errors_are_recognized_without_a_decoder_context() -> None:
    older = MediaToolError(
        "media.tool_failed",
        "ffmpeg failed (exit 69): [mp3float @ 0x1] Header missing\n"
        "Error while decoding stream #0:0: Invalid data found when processing input",
    )
    assert is_decode_failure(older)
    stderr = (
        b"[mp3float @ 0x1] Header missing\n"
        b"Error while decoding stream #0:0: Invalid data found when processing input\n"
        b"[mp3float @ 0x1] Header missing\n"
        b"Error while decoding stream #0:0: Invalid data found when processing input\n"
    )
    (warning,) = damage_warnings(stderr)
    assert warning.startswith(
        "Skipped 2 damaged packets in the source (Header missing)"
    )


@pytest.mark.parametrize(
    "diagnostics",
    [
        "[mp3float @ 0x1] Header missing",
        "[mp3 @ 0x1] Header missing",
        "[flac @ 0x1] invalid sync code\n"
        "[flac @ 0x1] invalid frame header\n"
        "[flac @ 0x1] decode_frame() failed",
    ],
)
def test_ffmpeg_60_strict_decode_failure_uses_codec_diagnostics(
    diagnostics: str,
) -> None:
    # In 6.0, -xerror exits before "Error while decoding stream" is logged.
    error = MediaToolError(
        "media.tool_failed", f"ffmpeg failed (exit 1): {diagnostics}"
    )
    assert is_decode_failure(error)
    # Codec explanations do not independently count packets in a lenient run.
    assert not any(
        is_skipped_packet(line) for line in diagnostics.encode().splitlines()
    )


@pytest.mark.parametrize(
    "diagnostics",
    [
        "[mp3 @ 0x1] Failed to read frame size: Could not seek to 1026.",
        "[flac @ 0x1] invalid metadata block",
        "[mp3float @ 0x1] Could not allocate memory",
        # FLAC uses this generic footer for allocation failures too.
        "[flac @ 0x1] decode_frame() failed",
        "[in#0 @ 0x1] Header missing",
    ],
)
def test_legacy_diagnostics_do_not_admit_container_or_resource_failures(
    diagnostics: str,
) -> None:
    assert not is_decode_failure(MediaToolError("media.tool_failed", diagnostics))


def test_demuxer_errors_are_not_treated_as_skippable_packets() -> None:
    # A corrupt container also says "Invalid data found", but without a decoder
    # context; it must keep failing strictly rather than earning a lenient pass.
    demux = MediaToolError(
        "media.tool_failed",
        "ffmpeg failed (exit 183): [in#0 @ 0x1] Error during demuxing: Invalid "
        "data found when processing input",
    )
    decode = MediaToolError(
        "media.tool_failed",
        "ffmpeg failed (exit 183): [mp3float @ 0x1] Header missing\n"
        "[aist#0:0/mp3 @ 0x2] [dec:mp3float @ 0x3] Decoding error: Invalid data "
        "found when processing input",
    )
    assert not is_decode_failure(demux)
    assert is_decode_failure(decode)
    assert not is_decode_failure(MediaToolError("media.tool_output_limit", str(decode)))


def test_lenient_retry_blames_the_source_only_for_decode_failures() -> None:
    def failing(code: str, message: str) -> Callable[[], None]:
        def run() -> None:
            raise MediaToolError(code, message)

        return run

    for code, message in (
        ("media.tool_output_limit", "Media tool diagnostics exceeded the safety limit"),
        (
            "media.tool_failed",
            "ffmpeg failed (exit 1): [aist#0:0/aac @ 0x1] [dec:aac @ 0x2] Decoding "
            "error: Invalid data found when processing input",
        ),
        (
            "media.tool_failed",
            "ffmpeg failed (exit 1): Output file is empty, nothing was encoded",
        ),
    ):
        with pytest.raises(MediaInspectionError) as damaged:
            retry_skipping_damage(failing(code, message))
        assert damaged.value.code == "media.source_damaged"

    workspace_full = failing(
        "media.tool_failed", "ffmpeg failed (exit 1): No space left on device"
    )
    with pytest.raises(MediaToolError) as unrelated:
        retry_skipping_damage(workspace_full)
    assert "No space left" in str(unrelated.value)
    assert retry_skipping_damage(lambda: "ok") == "ok"
