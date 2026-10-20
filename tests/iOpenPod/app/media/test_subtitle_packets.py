"""Subtitle packet recovery retains useful text without trusting broken timing."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import pytest

from iOpenPod.app.media.inspection import MediaInspectionError
from iOpenPod.app.media.models import MediaInspection, MediaStream, StreamKind
from iOpenPod.app.media.subtitles.preparation import prepare_subtitles, read_cues
from iOpenPod.app.media.subtitles.timing import SubtitleCue
from storage import FileFingerprint, HostPath
from storage.media_processing import MediaTools, ToolOutput, media_workspace


def _stream(codec: str = "subrip") -> MediaStream:
    return MediaStream(
        index=3,
        kind=StreamKind.SUBTITLE,
        codec=codec,
        codec_tag="",
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


def _tools(tmp_path: Path) -> MediaTools:
    return MediaTools(
        HostPath(tmp_path / "ffmpeg"),
        HostPath(tmp_path / "ffprobe"),
        None,
        frozenset({"mov_text"}),
    )


def _dump(payload: bytes) -> str:
    """The fixed hex and ASCII columns emitted by FFprobe's show_data output."""
    lines: list[str] = []
    for offset in range(0, len(payload), 16):
        row = payload[offset : offset + 16]
        hexadecimal = " ".join(
            row[index : index + 2].hex() for index in range(0, len(row), 2)
        )
        preview = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in row)
        lines.append(f"{offset:08x}: {hexadecimal:<39}  {preview}")
    return "\n" + "\n".join(lines) + "\n"


def _packet(
    payload: bytes, *, start: str | None = "0", duration: str | None = "1"
) -> dict[str, object]:
    packet: dict[str, object] = {"data": _dump(payload)}
    if start is not None:
        packet["pts_time"] = start
    if duration is not None:
        packet["duration_time"] = duration
    return packet


def _probe_output(
    monkeypatch: pytest.MonkeyPatch,
    output: ToolOutput,
) -> None:
    def run(
        executable: HostPath, arguments: tuple[str, ...], **options: object
    ) -> ToolOutput:
        assert executable.path.name == "ffprobe"
        assert arguments[arguments.index("-select_streams") + 1] == "3"
        assert "-show_packets" in arguments and "-show_data" in arguments
        assert options["check"] is False
        return output

    monkeypatch.setattr(
        "iOpenPod.app.media.subtitles.preparation.run_media_tool",
        run,
    )


def _read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    packets: list[dict[str, object]],
    *,
    codec: str = "subrip",
    duration_seconds: float = 10,
    offset: Fraction = Fraction(0),
    returncode: int = 0,
    stderr: bytes = b"",
) -> tuple[tuple[SubtitleCue, ...], tuple[str, ...]]:
    _probe_output(
        monkeypatch,
        ToolOutput(json.dumps({"packets": packets}).encode(), stderr, returncode),
    )
    return read_cues(
        HostPath(tmp_path / "source.mkv"),
        _stream(codec),
        _tools(tmp_path),
        containers=("matroska",),
        offset=offset,
        duration_seconds=duration_seconds,
        checkpoint=lambda: None,
    )


@pytest.mark.parametrize("duration", (None, "0", "N/A", "-1"))
def test_missing_or_nonpositive_duration_uses_next_marker_and_video_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, duration: str | None
) -> None:
    cues, warnings = _read(
        monkeypatch,
        tmp_path,
        [
            _packet(b"First", start="1", duration=duration),
            _packet(b"", start="2", duration="0"),
            _packet(b"Last", start="4", duration=duration),
        ],
        duration_seconds=5,
    )
    assert cues == (
        SubtitleCue(1_000, 2_000, "First"),
        SubtitleCue(4_000, 5_000, "Last"),
    )
    assert sum("durations were estimated" in item for item in warnings) == 1


def test_missing_timestamp_follows_previous_cue_and_warns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cues, warnings = _read(
        monkeypatch,
        tmp_path,
        [
            _packet(b"First", start="1", duration="2"),
            _packet(b"Recovered", start=None, duration="1.5"),
        ],
    )
    assert cues == (
        SubtitleCue(1_000, 3_000, "First"),
        SubtitleCue(3_000, 4_500, "Recovered"),
    )
    assert any("timestamps were estimated" in item for item in warnings)


def test_dts_recovers_missing_pts_and_applies_container_start_offset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    packet = _packet(b"On the video timeline", start="N/A", duration="1.25")
    packet["dts_time"] = "3.5"
    cues, warnings = _read(monkeypatch, tmp_path, [packet], offset=Fraction(5, 2))
    assert cues == (SubtitleCue(1_000, 2_250, "On the video timeline"),)
    assert not warnings


def test_bad_packet_hex_does_not_discard_remaining_readable_packets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broken = _packet(b"Broken")
    broken["data"] = "00000000: zzzz                                     Broken"
    cues, warnings = _read(
        monkeypatch,
        tmp_path,
        [
            _packet(b"Before", start="0"),
            broken,
            _packet(b"After", start="2"),
        ],
    )
    assert cues == (
        SubtitleCue(0, 1_000, "Before"),
        SubtitleCue(2_000, 3_000, "After"),
    )
    assert any("unreadable subtitle packet was skipped" in item for item in warnings)


def test_probe_failure_with_usable_json_retains_readable_text_and_warns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cues, warnings = _read(
        monkeypatch,
        tmp_path,
        [_packet(b"Recovered subtitle")],
        returncode=1,
        stderr=b"Truncated packet at end of source\n",
    )
    assert cues == (SubtitleCue(0, 1_000, "Recovered subtitle"),)
    assert any("readable subtitle packets were recovered" in item for item in warnings)


@pytest.mark.parametrize(
    "stdout",
    (b'{"packets": [', b"not json", b'{"packets": null}', b'{"packets": {}}'),
)
def test_unreadable_probe_document_raises_specific_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stdout: bytes
) -> None:
    _probe_output(monkeypatch, ToolOutput(stdout, b"", 1))
    with pytest.raises(MediaInspectionError, match="could not be read") as error:
        read_cues(
            HostPath(tmp_path / "source.mkv"),
            _stream(),
            _tools(tmp_path),
            containers=("matroska",),
            offset=Fraction(0),
            duration_seconds=10,
            checkpoint=lambda: None,
        )
    assert error.value.code == "media.subtitle_unreadable"


def test_subrip_legacy_encoding_recovers_dialogue_and_warns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cues, warnings = _read(
        monkeypatch,
        tmp_path,
        [_packet(b"\x93A caf\xe9 \x96 lovely.\x94")],
    )
    assert cues == (SubtitleCue(0, 1_000, "“A café \u2013 lovely.”"),)
    assert any("Windows-1252" in item for item in warnings)


def test_hex_looking_ascii_preview_is_never_decoded_as_additional_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cues, warnings = _read(
        monkeypatch,
        tmp_path,
        [_packet(b"dead beef"), _packet(b"1234567890abcdef", start="2")],
    )
    assert cues == (
        SubtitleCue(0, 1_000, "dead beef"),
        SubtitleCue(2_000, 3_000, "1234567890abcdef"),
    )
    assert not warnings


@pytest.mark.parametrize(
    ("codec", "packets"),
    (
        ("subrip", []),
        ("mov_text", [_packet(b"\x00\x00")]),
        ("ass", [_packet(b"{\\p1}m 0 0 l 50 50 60 20{\\p0}")]),
    ),
)
def test_empty_or_drawing_only_selection_has_explicit_no_readable_text_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    codec: str,
    packets: list[dict[str, object]],
) -> None:
    _probe_output(
        monkeypatch, ToolOutput(json.dumps({"packets": packets}).encode(), b"")
    )
    source = HostPath(tmp_path / "source.mkv")
    stream = _stream(codec)
    observed = MediaInspection(
        source,
        FileFingerprint(0, 0, 0, 0, "0" * 64),
        ("matroska",),
        Fraction(10),
        Fraction(0),
        None,
        (),
        (stream,),
        (),
    )
    with (
        media_workspace(checkpoint=lambda: None) as workspace,
        pytest.raises(MediaInspectionError, match="no readable text") as error,
    ):
        prepare_subtitles(
            (stream,),
            observed,
            source,
            workspace,
            _tools(tmp_path),
            duration_seconds=10,
            checkpoint=lambda: None,
        )
    assert error.value.code == "media.subtitle_empty"
    assert "Choose another subtitle stream or uncheck it" in str(error.value)


def test_recovered_text_is_staged_in_real_workspace_with_stream_scoped_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    packets = [_packet(b"Caf\xe9 & <unknown>", start="1", duration="1")]
    _probe_output(
        monkeypatch, ToolOutput(json.dumps({"packets": packets}).encode(), b"")
    )
    source = HostPath(tmp_path / "source.mkv")
    stream = _stream()
    observed = MediaInspection(
        source,
        FileFingerprint(0, 0, 0, 0, "0" * 64),
        ("matroska",),
        Fraction(10),
        Fraction(0),
        None,
        (),
        (stream,),
        (),
    )
    with media_workspace(checkpoint=lambda: None) as workspace:
        prepared = prepare_subtitles(
            (stream,),
            observed,
            source,
            workspace,
            _tools(tmp_path),
            duration_seconds=10,
            checkpoint=lambda: None,
        )
        assert len(prepared) == 1
        assert prepared[0].source_index == 3
        assert prepared[0].cues == (SubtitleCue(1_000, 2_000, "Café & <unknown>"),)
        staged = Path(prepared[0].source)
        assert staged.read_text(encoding="utf-8") == (
            "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\n{\\r}Café & <unknown>\n\n"
        )
        assert any(
            item.startswith("Subtitle stream 3:") and "Windows-1252" in item
            for item in prepared[0].warnings
        )
    assert not staged.exists()
