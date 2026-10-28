"""Real prepared videos retain caption bytes and reject known field-2 loss."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from tests.iOpenPod.app.test_video_preparation import captioned_video as captioned_video
from tests.iOpenPod.app.test_video_preparation import ffmpeg as ffmpeg
from tests.iOpenPod.app.test_video_preparation import profile as profile
from tests.iOpenPod.app.test_video_preparation import video as video

from iOpenPod.app.media import MediaInspectionError, MediaInspector
from iOpenPod.app.media.stream_selection import MediaStreamSelection
from iOpenPod.app.media.transcoding import MediaTranscoder, TranscodeSettings
from iPodDB.library import Track
from storage import HostPath
from storage.media_processing import discover_media_tools, run_media_tool

if TYPE_CHECKING:
    from device_registry import DeviceProfile
    from storage.media_processing import MediaTools


def _caption_sample(path: Path, atom_type: bytes = b"cdat") -> tuple[int, bytes]:
    """Locate the first, indexed caption sample in this tiny synthetic fixture."""
    data = path.read_bytes()
    assert atom_type in data
    position = data.index(atom_type)
    size = int.from_bytes(data[position - 4 : position], "big")
    assert 10 <= size <= len(data) - position + 4
    return position, data[position + 4 : position + size - 4]


def _selection(path: Path) -> MediaStreamSelection:
    observed = MediaInspector().scan_metadata(HostPath(path), checkpoint=lambda: None)
    return MediaStreamSelection(
        observed.video_streams[0],
        observed.audio_streams[0],
        captions=tuple(
            stream for stream in observed.streams if stream.codec_tag == "c608"
        ),
    )


def _caption_timing(
    path: HostPath, tools: MediaTools
) -> tuple[tuple[Fraction, Fraction], ...]:
    output = run_media_tool(
        tools.ffprobe,
        (
            "-v",
            "error",
            "-select_streams",
            "s",
            "-show_packets",
            "-show_entries",
            "packet=pts_time,duration_time",
            "-of",
            "json",
            "-i",
            str(path),
        ),
        checkpoint=lambda: None,
    )
    document = cast("dict[str, list[dict[str, str]]]", json.loads(output.stdout))
    return tuple(
        (Fraction(packet["pts_time"]), Fraction(packet["duration_time"]))
        for packet in document["packets"]
    )


@pytest.mark.parametrize("remux", (False, True))
def test_caption_parity_repeated_commands_and_timing_survive_metadata_preparation(
    captioned_video: Path, profile: DeviceProfile, remux: bool
) -> None:
    _, original = _caption_sample(captioned_video)
    # The fixture contains real parity bits and repeated RCL/EOC commands.
    assert original.startswith(bytes.fromhex("9420 9420"))
    assert original.endswith(bytes.fromhex("942f 942f"))
    tools = discover_media_tools(checkpoint=lambda: None)
    timing = _caption_timing(HostPath(captioned_video), tools)
    with MediaTranscoder().prepare(
        HostPath(captioned_video),
        profile,
        TranscodeSettings(),
        tools=tools,
        stream_selection=_selection(captioned_video) if remux else None,
        metadata=Track(1, "Caption preservation", "", "", 3_000),
        rockbox_metadata=True,
        checkpoint=lambda: None,
    ) as prepared:
        assert prepared.was_transcoded is remux
        assert _caption_sample(Path(prepared.source))[1] == original
        assert _caption_timing(prepared.source, tools) == timing
        # MOV can retain its original QuickTime title beside the newly written
        # iTunes-style tag, so FFprobe's preferred title is not authoritative.
        assert b"Caption preservation" in Path(prepared.source).read_bytes()
        assert not prepared.warnings


@pytest.fixture
def field_2_video(captioned_video: Path, tmp_path: Path) -> Path:
    position, _ = _caption_sample(captioned_video)
    data = bytearray(captioned_video.read_bytes())
    data[position : position + 4] = b"cdt2"
    path = tmp_path / "field-2.mov"
    path.write_bytes(data)
    return path


def test_unchanged_field_2_copy_preserves_entire_file_and_reports_uncertainty(
    field_2_video: Path, profile: DeviceProfile
) -> None:
    original = field_2_video.read_bytes()
    with MediaTranscoder().prepare(
        HostPath(field_2_video),
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
    ) as prepared:
        assert not prepared.was_transcoded
        assert Path(prepared.source).read_bytes() == original
        assert any(
            "field 2" in warning and "not been verified" in warning
            for warning in prepared.warnings
        )
    assert field_2_video.read_bytes() == original


def test_field_2_remux_is_blocked_before_caption_bytes_are_lost(
    field_2_video: Path, profile: DeviceProfile
) -> None:
    original = field_2_video.read_bytes()
    with (
        pytest.raises(MediaInspectionError, match="cannot retain") as error,
        MediaTranscoder().prepare(
            HostPath(field_2_video),
            profile,
            TranscodeSettings(),
            stream_selection=_selection(field_2_video),
            checkpoint=lambda: None,
        ),
    ):
        pytest.fail("Field-2 captions were silently dropped by preparation")
    assert error.value.code == "media.caption_field_2"
    assert field_2_video.read_bytes() == original


@pytest.mark.parametrize(
    ("control", "warning"), ((0xA2, "alarm"), (0xA8, "flashing"), (0xAA, "text mode"))
)
def test_valid_caption_controls_warn_and_survive_remux_unchanged(
    captioned_video: Path, profile: DeviceProfile, control: int, warning: str
) -> None:
    position, _ = _caption_sample(captioned_video)
    data = bytearray(captioned_video.read_bytes())
    # Replace the repeated initial command with the same valid control twice.
    data[position + 4 : position + 8] = bytes((0x94, control)) * 2
    captioned_video.write_bytes(data)
    original = _caption_sample(captioned_video)[1]
    with MediaTranscoder().prepare(
        HostPath(captioned_video),
        profile,
        TranscodeSettings(),
        stream_selection=_selection(captioned_video),
        checkpoint=lambda: None,
    ) as prepared:
        assert prepared.was_transcoded
        assert _caption_sample(Path(prepared.source))[1] == original
        assert any(warning in message for message in prepared.warnings)
