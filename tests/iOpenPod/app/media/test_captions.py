"""Caption inspection keeps firmware commands intact and rejects lossy remuxes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from fractions import Fraction
from typing import TYPE_CHECKING

import pytest
from tests.iOpenPod.app.test_video_preparation import captioned_video as captioned_video
from tests.iOpenPod.app.test_video_preparation import ffmpeg as ffmpeg
from tests.iOpenPod.app.test_video_preparation import video as video

from iOpenPod.app.media import MediaInspector
from iOpenPod.app.media.captions import inspect_caption_packet, verify_captions
from iOpenPod.app.media.inspection import MediaInspectionError
from iOpenPod.app.media.models import MediaInspection, MediaStream, StreamKind
from storage import FileFingerprint, HostPath
from storage.media_processing import MediaTools, ToolOutput, discover_media_tools

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from iOpenPod.app.media.captions import CaptionStreamVerification


def _triplets(pairs: bytes, *, marker: int = 0xFC) -> bytes:
    assert len(pairs) % 2 == 0
    return b"".join(
        bytes((marker,)) + pairs[index : index + 2] for index in range(0, len(pairs), 2)
    )


@pytest.mark.parametrize("parity", (0, 0x80))
@pytest.mark.parametrize("prefix", (0x14, 0x1C))
def test_supported_decoder_controls_and_repetitions_are_retained(
    parity: int, prefix: int
) -> None:
    # Pop-on, roll-up, paint-on, erase, carriage return, backspace, and duplicate
    # controls remain commands; this inspector must not flatten them to text.
    suffixes = (0x20, 0x21, 0x24, 0x25, 0x26, 0x27, 0x29, 0x2C, 0x2D, 0x2E, 0x2F)
    pairs = b"".join(
        bytes((prefix | parity, suffix | parity)) * 2 for suffix in suffixes
    )
    payload = _triplets(pairs) + _triplets(b"HELLO WORLD ")
    original = bytes(payload)
    information = inspect_caption_packet(payload)
    assert information.warnings == ()
    assert not information.has_field_2
    assert payload == original


@pytest.mark.parametrize("parity", (0, 0x80))
@pytest.mark.parametrize("prefix", (0x14, 0x1C))
@pytest.mark.parametrize(
    ("suffix", "warning"),
    (
        (0x22, "alarm"),
        (0x23, "alarm"),
        (0x28, "flashing"),
        (0x2A, "text mode"),
        (0x2B, "text mode"),
    ),
)
def test_valid_controls_with_limited_firmware_support_warn_without_rewriting(
    parity: int, prefix: int, suffix: int, warning: str
) -> None:
    payload = _triplets(bytes((prefix | parity, suffix | parity)) * 2)
    original = bytes(payload)
    information = inspect_caption_packet(payload)
    assert len(information.warnings) == 1
    assert warning in information.warnings[0]
    assert "retained" in information.warnings[0]
    assert payload == original


@pytest.mark.parametrize(
    "pairs",
    (
        b"\x10\x28\x11\x2a\x12\x2b\x13\x23\x17\x22",
        b"\x14\x40\x1c\x7f",  # Preamble addresses are not misc controls.
        b"\x00\x00\x2a\x5c\x5e\x5f\x60\x7b\x7c\x7d\x7e\x7f",
    ),
)
def test_character_style_and_preamble_bytes_are_not_mistaken_for_misc_controls(
    pairs: bytes,
) -> None:
    assert not inspect_caption_packet(_triplets(pairs)).warnings


@pytest.mark.parametrize("payload", (b"", b"\xfc", b"\xfc\x94", b"\xfc\x94\x20\xfc"))
def test_truncated_caption_triplets_fail(payload: bytes) -> None:
    with pytest.raises(ValueError, match="complete byte-pair triplets"):
        inspect_caption_packet(payload)


@pytest.mark.parametrize("marker", (0x00, 0x04, 0xF8, 0xFA))
def test_invalid_demuxed_caption_markers_fail(marker: int) -> None:
    with pytest.raises(ValueError, match="invalid field marker"):
        inspect_caption_packet(bytes((marker, 0x94, 0x20)))


@pytest.mark.parametrize("marker", (0xFE, 0xFF))
def test_cea708_is_not_treated_as_supported_cea608(marker: int) -> None:
    with pytest.raises(ValueError, match="CEA-708"):
        inspect_caption_packet(bytes((marker, 0x94, 0x20)))


def test_field_2_is_recognized_without_guessing_its_display_behavior() -> None:
    information = inspect_caption_packet(_triplets(b"\x94\x20", marker=0xFD))
    assert information.has_field_2
    assert not information.warnings


def _stream() -> MediaStream:
    return MediaStream(
        index=3,
        kind=StreamKind.SUBTITLE,
        codec="eia_608",
        codec_tag="c608",
        profile="",
        level=None,
        duration_seconds=Fraction(10),
        start_seconds=Fraction(0),
        time_base=Fraction(1, 1_000),
        duration_ticks=10_000,
        bitrate_bps=None,
        sample_rate_hz=None,
        channels=None,
        channel_layout="",
        bits_per_sample=None,
        bits_per_raw_sample=None,
        width=None,
        height=None,
        pixel_format="",
        frame_rate=None,
        nominal_frame_rate=None,
        sample_aspect_ratio=None,
        attached_picture=False,
        default=False,
        dispositions=(),
        tags=(),
    )


def _packet(payload: bytes) -> dict[str, object]:
    rows: list[str] = []
    for offset in range(0, len(payload), 16):
        row = payload[offset : offset + 16]
        hexadecimal = " ".join(
            row[index : index + 2].hex() for index in range(0, len(row), 2)
        )
        preview = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in row)
        rows.append(f"{offset:08x}: {hexadecimal:<39}  {preview}")
    return {"size": str(len(payload)), "data": "\n" + "\n".join(rows) + "\n"}


def _verify(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    packets: list[object],
    *,
    remux: bool = False,
    stderr: bytes = b"",
    returncode: int = 0,
    stdout: bytes | None = None,
    checkpoint: Callable[[], None] = lambda: None,
) -> tuple[CaptionStreamVerification, ...]:
    output = ToolOutput(
        json.dumps({"packets": packets}).encode() if stdout is None else stdout,
        stderr,
        returncode,
    )

    def run(
        executable: HostPath, arguments: tuple[str, ...], **options: object
    ) -> ToolOutput:
        assert executable.path.name == "ffprobe"
        assert arguments[arguments.index("-select_streams") + 1] == "3"
        assert arguments[arguments.index("-show_entries") + 1] == "packet=data,size"
        assert "-show_packets" in arguments and "-show_data" in arguments
        assert options["check"] is False
        return output

    monkeypatch.setattr("iOpenPod.app.media.captions.run_media_tool", run)
    source = HostPath(tmp_path / "captured.mov")
    observed = MediaInspection(
        source,
        FileFingerprint(0, 0, 0, 0, "0" * 64),
        ("mov",),
        Fraction(10),
        Fraction(0),
        None,
        (),
        (_stream(),),
        (),
    )
    tools = MediaTools(
        HostPath(tmp_path / "ffmpeg"), HostPath(tmp_path / "ffprobe"), None, frozenset()
    )
    return verify_captions(
        observed.streams,
        observed,
        source,
        tools,
        remux=remux,
        duration_seconds=10,
        checkpoint=checkpoint,
    )


def test_packet_digest_covers_original_parity_and_duplicate_control_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original = (
        _triplets(b"\x94\x20\x94\x20HELLO "),
        _triplets(b"\x94\xa8\x94\xa8\x94\x2f\x94\x2f"),
    )
    result = _verify(
        monkeypatch, tmp_path, [_packet(data) for data in original], remux=True
    )
    assert len(result) == 1
    assert result[0].source_index == 3
    assert result[0].packet_count == 2
    assert result[0].payload_sha256 == hashlib.sha256(b"".join(original)).hexdigest()
    assert len(result[0].warnings) == 1
    assert result[0].warnings[0].startswith("Caption stream 3:")
    assert not result[0].has_field_2
    changed = (_triplets(b"\x14\x20\x14\x20HELLO "), original[1])
    parity_changed = _verify(monkeypatch, tmp_path, [_packet(data) for data in changed])
    assert parity_changed[0].payload_sha256 != result[0].payload_sha256


def test_field_2_is_retained_in_unchanged_copy_with_uncertainty_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = _triplets(b"HELLO ", marker=0xFD)
    result = _verify(monkeypatch, tmp_path, [_packet(payload)])
    assert result[0].has_field_2
    assert result[0].payload_sha256 == hashlib.sha256(payload).hexdigest()
    assert any("field 2" in warning for warning in result[0].warnings)


def test_field_2_cannot_be_silently_dropped_by_remux(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(MediaInspectionError, match="cannot retain") as error:
        _verify(
            monkeypatch, tmp_path, [_packet(_triplets(b"HI", marker=0xFD))], remux=True
        )
    assert error.value.code == "media.caption_field_2"


@pytest.mark.parametrize(
    "packet",
    (
        None,
        {},
        {"size": "3"},
        _packet(b"\xfc\x94"),
        {
            "size": "4",
            "data": "\n00000000: fc94 20                                  .. \n",
        },
        {
            "size": "3",
            "data": "\n00000001: fc94 20                                  .. \n",
        },
        {
            "size": "3",
            "data": "\n00000000: xx94 20                                  .. \n",
        },
    ),
)
def test_malformed_caption_packets_block_preparation_instead_of_skipping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, packet: object
) -> None:
    with pytest.raises(MediaInspectionError, match="malformed caption data") as error:
        _verify(monkeypatch, tmp_path, [_packet(_triplets(b"HI")), packet])
    assert error.value.code == "media.caption_invalid"


@pytest.mark.parametrize("stderr,returncode", ((b"Truncated cdat atom", 0), (b"", 1)))
def test_demux_errors_are_not_accepted_as_complete_caption_preservation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stderr: bytes, returncode: int
) -> None:
    with pytest.raises(
        MediaInspectionError, match="could not be read completely"
    ) as error:
        _verify(
            monkeypatch,
            tmp_path,
            [_packet(_triplets(b"HI"))],
            stderr=stderr,
            returncode=returncode,
        )
    assert error.value.code == "media.caption_unreadable"


@pytest.mark.parametrize("stdout", (b"not json", b"{", b'{"packets": null}', b"[]"))
def test_unreadable_caption_probe_document_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stdout: bytes
) -> None:
    with pytest.raises(MediaInspectionError) as error:
        _verify(monkeypatch, tmp_path, [], stdout=stdout)
    assert error.value.code == "media.caption_unreadable"


def test_empty_caption_track_fails_with_specific_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(
        MediaInspectionError, match="contains no caption packets"
    ) as error:
        _verify(monkeypatch, tmp_path, [])
    assert error.value.code == "media.caption_empty"


def test_caption_inspection_obeys_cancellation_between_packets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = 0

    def cancel() -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("Cancelled")

    with pytest.raises(RuntimeError, match="Cancelled"):
        _verify(
            monkeypatch,
            tmp_path,
            [_packet(_triplets(b"HI")), _packet(_triplets(b"BY"))],
            checkpoint=cancel,
        )


def test_no_selected_captions_does_not_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A selected non-caption track is never included by the caller; an empty
    # caption selection must not expand into inspecting the whole source.
    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("Unselected captions were inspected")

    monkeypatch.setattr("iOpenPod.app.media.captions.run_media_tool", unexpected)
    source = HostPath(tmp_path / "captured.mov")
    observed = MediaInspection(
        source,
        FileFingerprint(0, 0, 0, 0, "0" * 64),
        ("mov",),
        Fraction(10),
        Fraction(0),
        None,
        (),
        (replace(_stream(), index=7),),
        (),
    )
    tools = MediaTools(source, source, None, frozenset())
    assert not verify_captions(
        (),
        observed,
        source,
        tools,
        remux=True,
        duration_seconds=10,
        checkpoint=lambda: None,
    )


def test_real_ffprobe_caption_data_uses_original_byte_pairs_with_field_markers(
    captioned_video: Path,
) -> None:
    tools = discover_media_tools(checkpoint=lambda: None)
    source = HostPath(captioned_video)
    observed = MediaInspector(tools.ffprobe).inspect(source, checkpoint=lambda: None)
    streams = tuple(stream for stream in observed.streams if stream.codec_tag == "c608")
    results = verify_captions(
        streams,
        observed,
        source,
        tools,
        remux=True,
        duration_seconds=3,
        checkpoint=lambda: None,
    )
    pairs = bytes.fromhex(
        "9420 9420 94ae 94ae 94e0 94e0 c845 4c4c 4f20 574f 524c c480 942f 942f"
    )
    assert len(results) == 1
    assert results[0].packet_count > 0
    assert results[0].payload_sha256 == hashlib.sha256(_triplets(pairs)).hexdigest()
    assert results[0].warnings == ()
