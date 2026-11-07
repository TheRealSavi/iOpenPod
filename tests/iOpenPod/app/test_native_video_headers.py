"""Real, tiny MP4 fixtures exercise native-header adoption before publication."""

from __future__ import annotations

import io
import json
import struct
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from tests.iOpenPod.app.test_video_preparation import ffmpeg as ffmpeg
from tests.iOpenPod.app.test_video_preparation import profile as profile
from tests.iOpenPod.app.test_video_preparation import video as video

from iOpenPod.app.media import MediaInspectionError, MediaInspector
from iOpenPod.app.media.stream_selection import MediaStreamSelection
from iOpenPod.app.media.subtitles.compatibility import verify_compatibility
from iOpenPod.app.media.subtitles.layout import configure_layout, verify_layout
from iOpenPod.app.media.subtitles.preparation import read_cues
from iOpenPod.app.media.transcoding import MediaTranscoder, TranscodeSettings
from iPodDB.library import ArtworkPixels, Track
from storage import HostPath
from storage.media_processing import discover_media_tools, run_media_tool

if TYPE_CHECKING:
    from tests.iOpenPod.app.test_video_preparation import (
        _FFmpeg,  # pyright: ignore[reportPrivateUsage]
    )

    from device_registry import DeviceProfile
    from iOpenPod.app.media.subtitles.timing import SubtitleCue
    from storage.media_processing import MediaTools


@dataclass(frozen=True)
class _Box:
    kind: bytes
    payload: int
    end: int


def _boxes(data: bytes | bytearray, start: int, end: int) -> tuple[_Box, ...]:
    result: list[_Box] = []
    while start < end:
        size, kind = struct.unpack_from(">I4s", data, start)
        header = 8
        if size == 1:
            size = struct.unpack_from(">Q", data, start + 8)[0]
            header = 16
        elif size == 0:
            size = end - start
        assert header <= size <= end - start
        result.append(_Box(kind, start + header, start + size))
        start += size
    return tuple(result)


def _one(boxes: tuple[_Box, ...], kind: bytes) -> _Box:
    matches = [box for box in boxes if box.kind == kind]
    assert len(matches) == 1
    return matches[0]


def _children(data: bytes | bytearray, box: _Box) -> tuple[_Box, ...]:
    return _boxes(data, box.payload, box.end)


def _native_headers(data: bytes | bytearray) -> tuple[_Box, _Box, _Box, _Box]:
    assert (
        len(data) < 1024 * 1024
    )  # The long timeline still has only three video seconds.
    movie = _one(_boxes(data, 0, len(data)), b"moov")
    movie_children = _children(data, movie)
    subtitles: list[tuple[_Box, _Box, _Box]] = []
    for track in (box for box in movie_children if box.kind == b"trak"):
        children = _children(data, track)
        media = _children(data, _one(children, b"mdia"))
        handler = _one(media, b"hdlr")
        if data[handler.payload + 8 : handler.payload + 12] != b"sbtl":
            continue
        info = _children(data, _one(media, b"minf"))
        tables = _children(data, _one(info, b"stbl"))
        description = _one(tables, b"stsd")
        entry = _one(_boxes(data, description.payload + 8, description.end), b"tx3g")
        subtitles.append((_one(children, b"tkhd"), _one(media, b"mdhd"), entry))
    assert len(subtitles) == 1
    return (_one(movie_children, b"mvhd"), *subtitles[0])


def _clock(data: bytes, header: _Box) -> int:
    offset = header.payload + (12 if data[header.payload] == 0 else 20)
    return int.from_bytes(data[offset : offset + 4], "big")


def _make_subtitled(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    *,
    movie_timescale: int = 1000,
    long_timeline: bool = False,
) -> Path:
    subtitles = tmp_path / "native.srt"
    subtitles.write_text(
        "1\n00:00:00,250 --> 00:00:02,750\nEarly native dialogue.\n"
        + (
            "\n2\n01:00:00,000 --> 01:00:02,000\nLast synthetic cue after one hour.\n"
            if long_timeline
            else ""
        ),
        encoding="utf-8",
    )
    path = tmp_path / "native.mp4"
    ffmpeg(
        "-i",
        str(video),
        "-i",
        str(subtitles),
        "-map",
        "0:v",
        "-map",
        "0:a",
        "-map",
        "1:s",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-c:s",
        "mov_text",
        "-s:s",
        "320x240",
        "-metadata:s:s:0",
        "language=eng",
        "-movie_timescale",
        str(movie_timescale),
        str(path),
    )
    return path


def _configure_fixture(path: Path) -> None:
    stream = io.BytesIO(path.read_bytes())
    configure_layout(stream, (2,))
    path.write_bytes(stream.getvalue())


def _extend_synthetic_subtitle_gap(path: Path) -> None:
    """Author an exact long stts gap without asking FFmpeg to encode long video.

    Some FFmpeg versions clamp a mov_text delta above INT32_MAX to one tick.
    Build that unsigned file-format delta explicitly, preserving all samples.
    """
    data = bytearray(path.read_bytes())
    movie, header, media_header, _ = _native_headers(data)
    assert (
        data[header.payload] == data[media_header.payload] == data[movie.payload] == 0
    )
    root = _one(_boxes(data, 0, len(data)), b"moov")
    tracks = [box for box in _children(data, root) if box.kind == b"trak"]
    track = next(box for box in tracks if _one(_children(data, box), b"tkhd") == header)
    children = _children(data, track)
    media = _children(data, _one(children, b"mdia"))
    info = _children(data, _one(media, b"minf"))
    tables = _children(data, _one(info, b"stbl"))
    stts = _one(tables, b"stts")
    count = int.from_bytes(data[stts.payload + 4 : stts.payload + 8], "big")
    runs = [
        struct.unpack_from(">II", data, stts.payload + 8 + index * 8)
        for index in range(count)
    ]
    assert runs[:2] == [(1, 250_000), (1, 2_500_000)]
    assert runs[2][0] == 1 and runs[3] == (1, 2_000_000)
    struct.pack_into(">I", data, stts.payload + 12 + 2 * 8, 3_597_250_000)
    struct.pack_into(">I", data, media_header.payload + 16, 3_602_000_000)
    struct.pack_into(">I", data, header.payload + 20, 3_602_000)
    struct.pack_into(">I", data, movie.payload + 16, 3_602_000)
    edit = _one(_children(data, _one(children, b"edts")), b"elst")
    assert data[edit.payload] == 0
    assert int.from_bytes(data[edit.payload + 4 : edit.payload + 8], "big") == 1
    struct.pack_into(">I", data, edit.payload + 8, 3_602_000)
    path.write_bytes(data)


def _packet_hashes(path: HostPath, tools: MediaTools) -> tuple[tuple[str, ...], ...]:
    output = run_media_tool(
        tools.ffprobe,
        (
            "-v",
            "error",
            "-show_packets",
            "-show_data_hash",
            "sha256",
            "-show_entries",
            "packet=stream_index,data_hash",
            "-of",
            "json",
            str(path),
        ),
        checkpoint=lambda: None,
        timeout_seconds=20,
        max_output_bytes=1024 * 1024,
    )
    document = cast("dict[str, list[dict[str, str | int]]]", json.loads(output.stdout))
    groups: dict[int, list[str]] = {}
    for packet in document["packets"]:
        index, digest = packet["stream_index"], packet["data_hash"]
        assert isinstance(index, int) and isinstance(digest, str)
        groups.setdefault(index, []).append(digest)
    return tuple(tuple(groups[index]) for index in sorted(groups))


def _cues(path: HostPath, tools: MediaTools) -> tuple[SubtitleCue, ...]:
    observed = MediaInspector().inspect(path, checkpoint=lambda: None)
    stream = next(stream for stream in observed.streams if stream.codec_tag == "tx3g")
    cues, warnings = read_cues(
        path,
        stream,
        tools,
        containers=observed.containers,
        offset=observed.start_seconds or Fraction(0),
        duration_seconds=float(
            max(observed.duration_seconds or 0, stream.duration_seconds or 0)
        ),
        checkpoint=lambda: None,
    )
    assert not warnings
    return cues


def test_high_movie_clock_remux_repairs_version_one_tkhd_without_encoding_packets(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    profile: DeviceProfile,
) -> None:
    # Three seconds at two billion movie units/second forces a 64-bit tkhd.
    source = _make_subtitled(tmp_path, video, ffmpeg, movie_timescale=2_000_000_000)
    before = source.read_bytes()
    movie, track, _, _ = _native_headers(before)
    assert _clock(before, movie) == 2_000_000_000
    assert before[track.payload] == 1
    tools = discover_media_tools(checkpoint=lambda: None)
    packets = _packet_hashes(HostPath(source), tools)
    cues = _cues(HostPath(source), tools)

    with MediaTranscoder().prepare(
        HostPath(source),
        profile,
        TranscodeSettings(),
        tools=tools,
        checkpoint=lambda: None,
    ) as prepared:
        after = Path(str(prepared.source)).read_bytes()
        movie, track, _, _ = _native_headers(after)
        assert prepared.was_transcoded  # This includes a stream-copy remux.
        assert _clock(after, movie) == 1000
        assert after[track.payload] == 0
        verify_compatibility(io.BytesIO(after), (2,))
        assert _packet_hashes(prepared.source, tools) == packets
        assert _cues(prepared.source, tools) == cues
    assert source.read_bytes() == before


def test_native_empty_text_box_is_repaired_without_changing_subtitle_packets(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    profile: DeviceProfile,
) -> None:
    source = _make_subtitled(tmp_path, video, ffmpeg)
    before = source.read_bytes()
    _, track, _, entry = _native_headers(before)
    assert before[track.payload] == 0
    assert struct.unpack_from(">4h", before, entry.payload + 18) == (0, 0, 0, 0)
    tools = discover_media_tools(checkpoint=lambda: None)
    packets = _packet_hashes(HostPath(source), tools)

    with MediaTranscoder().prepare(
        HostPath(source),
        profile,
        TranscodeSettings(),
        tools=tools,
        checkpoint=lambda: None,
    ) as prepared:
        after = Path(str(prepared.source)).read_bytes()
        verify_layout(io.BytesIO(after), (2,))
        verify_compatibility(io.BytesIO(after), (2,))
        assert _packet_hashes(prepared.source, tools) == packets
    assert source.read_bytes() == before


def test_safe_native_headers_and_media_remain_byte_exact(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    profile: DeviceProfile,
) -> None:
    source = _make_subtitled(tmp_path, video, ffmpeg)
    _configure_fixture(source)
    before = source.read_bytes()
    verify_compatibility(io.BytesIO(before), (2,))

    with MediaTranscoder().prepare(
        HostPath(source),
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
    ) as prepared:
        assert not prepared.was_transcoded
        assert Path(str(prepared.source)).read_bytes() == before
    assert source.read_bytes() == before


def test_artwork_tagging_preserves_final_native_headers_and_cues(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    profile: DeviceProfile,
) -> None:
    source = _make_subtitled(tmp_path, video, ffmpeg)
    _configure_fixture(source)
    before = source.read_bytes()
    tools = discover_media_tools(checkpoint=lambda: None)
    transcoder = MediaTranscoder()
    artwork = ArtworkPixels(32, 32, bytes((30, 80, 140)) * (32 * 32))
    with transcoder.prepare(
        HostPath(source),
        profile,
        TranscodeSettings(),
        tools=tools,
        checkpoint=lambda: None,
    ) as prepared:
        cues = _cues(prepared.source, tools)
        tagged = transcoder.embed_artwork(
            prepared,
            Track(1, "Native subtitle artwork", "", "", 3000),
            artwork,
            checkpoint=lambda: None,
        )
        data = Path(str(tagged.source)).read_bytes()
        assert tagged.inspection.pictures
        assert tagged.inspection.fingerprint != prepared.inspection.fingerprint
        verify_compatibility(io.BytesIO(data), (2,))
        verify_layout(io.BytesIO(data), (2,))
        assert _cues(tagged.source, tools) == cues
    assert source.read_bytes() == before


@pytest.mark.parametrize("explicit_remux", [False, True])
def test_synthetic_hour_long_subtitle_clock_preserves_last_cue_on_tiny_video(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    profile: DeviceProfile,
    explicit_remux: bool,
) -> None:
    # Only subtitle timestamps extend past one hour; audiovisual packets still
    # cover three seconds, so preparation decodes no hour-long audio or video.
    source = _make_subtitled(tmp_path, video, ffmpeg, long_timeline=True)
    _configure_fixture(source)
    _extend_synthetic_subtitle_gap(source)
    before = source.read_bytes()
    _, track, media, _ = _native_headers(before)
    assert before[track.payload] == 0
    assert _clock(before, media) == 1_000_000
    with pytest.raises(MediaInspectionError) as caught:
        verify_compatibility(io.BytesIO(before), (2,))
    assert caught.value.code == "media.subtitle_incompatible"
    tools = discover_media_tools(checkpoint=lambda: None)
    packets = _packet_hashes(HostPath(source), tools)
    cues = _cues(HostPath(source), tools)
    assert cues[-1].text == "Last synthetic cue after one hour."
    assert (cues[-1].start_ms, cues[-1].end_ms) == (3_600_000, 3_602_000)
    selected = None
    if explicit_remux:
        observed = MediaInspector().inspect(HostPath(source), checkpoint=lambda: None)
        selected = MediaStreamSelection(
            observed.video_streams[0],
            observed.audio_streams[0],
            tuple(stream for stream in observed.streams if stream.codec_tag == "tx3g"),
        )

    with MediaTranscoder().prepare(
        HostPath(source),
        profile,
        TranscodeSettings(),
        tools=tools,
        checkpoint=lambda: None,
        stream_selection=selected,
    ) as prepared:
        after = Path(str(prepared.source)).read_bytes()
        _, _, media, _ = _native_headers(after)
        assert _clock(after, media) == 1000
        assert prepared.inspection.video_streams[0].duration_seconds == 3
        verify_compatibility(io.BytesIO(after), (2,))
        # A stream-copy muxer may insert empty subtitle timing packets. Every
        # compressed A/V packet and every actual text cue must remain intact.
        assert _packet_hashes(prepared.source, tools)[:2] == packets[:2]
        assert _cues(prepared.source, tools) == cues
    assert source.read_bytes() == before
