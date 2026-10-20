"""Readable, correctly timed subtitles survive real iPod media preparation."""

import re
import struct
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path

import pytest
from tests.iOpenPod.app.test_video_preparation import (
    _FFmpeg,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_video_preparation import ffmpeg as ffmpeg
from tests.iOpenPod.app.test_video_preparation import profile as profile
from tests.iOpenPod.app.test_video_preparation import video as video

from device_registry import DeviceProfile
from iOpenPod.app.media import MediaInspector
from iOpenPod.app.media.models import StreamKind
from iOpenPod.app.media.stream_selection import MediaStreamSelection
from iOpenPod.app.media.transcoding import (
    MediaTranscoder,
    TranscodeSettings,
    compatible_video,
)
from storage import HostPath

_ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 320
PlayResY: 240

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


@dataclass(frozen=True)
class _Cue:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class _Atom:
    kind: bytes
    payload: int
    end: int


@dataclass(frozen=True)
class _SubtitleLayout:
    width: int
    height: int
    text_box: tuple[int, int, int, int]
    matrix: tuple[int, ...]


def _atoms(data: bytes, start: int, end: int) -> tuple[_Atom, ...]:
    result: list[_Atom] = []
    while start < end:
        assert start + 8 <= end
        size, kind = struct.unpack_from(">I4s", data, start)
        header_size = 8
        if size == 1:
            size = int.from_bytes(data[start + 8 : start + 16], "big")
            header_size = 16
        elif size == 0:
            size = end - start
        assert size >= header_size
        assert start + size <= end
        result.append(_Atom(kind, start + header_size, start + size))
        start += size
    return tuple(result)


def _child(data: bytes, parent: _Atom, kind: bytes) -> _Atom:
    return next(
        atom for atom in _atoms(data, parent.payload, parent.end) if atom.kind == kind
    )


def _subtitle_atoms(data: bytes) -> tuple[_Atom, _Atom]:
    movie = next(atom for atom in _atoms(data, 0, len(data)) if atom.kind == b"moov")
    for track in _atoms(data, movie.payload, movie.end):
        if track.kind != b"trak":
            continue
        media = _child(data, track, b"mdia")
        info = _child(data, media, b"minf")
        table = _child(data, info, b"stbl")
        descriptions = _child(data, table, b"stsd")
        for entry in _atoms(data, descriptions.payload + 8, descriptions.end):
            if entry.kind == b"tx3g":
                return _child(data, track, b"tkhd"), entry
    raise AssertionError("The prepared movie has no tx3g sample description")


def _subtitle_layout(path: Path) -> _SubtitleLayout:
    data = path.read_bytes()
    track, description = _subtitle_atoms(data)
    width, height = struct.unpack_from(">II", data, track.end - 8)
    assert width % 65536 == height % 65536 == 0
    return _SubtitleLayout(
        width // 65536,
        height // 65536,
        struct.unpack_from(">4h", data, description.payload + 18),
        struct.unpack_from(">9i", data, track.end - 44),
    )


def _assert_bottom_subtitle_strip(path: Path, width: int, height: int) -> None:
    layout = _subtitle_layout(path)
    subtitle_height = height * 15 // 100
    assert (layout.width, layout.height) == (width, subtitle_height)
    assert layout.text_box == (0, 0, subtitle_height, width)
    assert layout.matrix == (
        65536,
        0,
        0,
        0,
        65536,
        0,
        0,
        (height - subtitle_height) * 65536,
        1073741824,
    )


def _set_native_subtitle_layout(path: Path) -> None:
    """Make the fixture contain valid native geometry, independent of production."""
    data = bytearray(path.read_bytes())
    track, description = _subtitle_atoms(bytes(data))
    struct.pack_into(">II", data, track.end - 8, 320 * 65536, 36 * 65536)
    struct.pack_into(">i", data, track.end - 16, 204 * 65536)
    struct.pack_into(">4h", data, description.payload + 18, 0, 0, 36, 320)
    path.write_bytes(data)


def _milliseconds(stamp: str) -> int:
    hours, minutes, seconds, milliseconds = map(int, re.split("[:,]", stamp))
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def _read_cues(
    path: HostPath, output: Path, ffmpeg: _FFmpeg, *, stream: int = 0
) -> tuple[_Cue, ...]:
    ffmpeg("-i", str(path), "-map", f"0:s:{stream}", "-c:s", "srt", str(output))
    text = output.read_text(encoding="utf-8")
    return tuple(
        _Cue(_milliseconds(start), _milliseconds(end), re.sub("<[^>]+>", "", content))
        for start, end, content in re.findall(
            r"\d+\n(\d\d:\d\d:\d\d,\d\d\d) --> (\d\d:\d\d:\d\d,\d\d\d)\n(.*?)(?=\n\n|\Z)",
            text,
            flags=re.DOTALL,
        )
    )


def _at(cues: tuple[_Cue, ...], milliseconds: int) -> str:
    return "\n".join(
        cue.text for cue in cues if cue.start_ms <= milliseconds < cue.end_ms
    )


def test_very_long_subtitle_retains_words_across_timed_text_samples(
    tmp_path: Path, video: Path, ffmpeg: _FFmpeg, profile: DeviceProfile
) -> None:
    text = "a" * 59_999 + " " + "字幕" * 1_000
    subtitle = tmp_path / "long.vtt"
    subtitle.write_text(
        f"WEBVTT\n\n00:00:00.000 --> 00:00:02.800\n{text}\n", encoding="utf-8"
    )
    path = _mux(video, subtitle, tmp_path / "long.mkv", ffmpeg)
    with MediaTranscoder().prepare(
        HostPath(path),
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
    ) as prepared:
        cues = _read_cues(prepared.source, tmp_path / "result.srt", ffmpeg)
        assert len(cues) == 2
        assert "".join(cue.text for cue in cues).replace(" ", "") == text.replace(
            " ", ""
        )
        assert any("split" in warning for warning in prepared.warnings)


def _selection(path: Path) -> MediaStreamSelection:
    observed = MediaInspector().inspect(HostPath(path), checkpoint=lambda: None)
    return MediaStreamSelection(
        observed.video_streams[0],
        next(iter(observed.audio_streams), None),
        tuple(s for s in observed.streams if s.kind is StreamKind.SUBTITLE),
    )


def _mux(
    video: Path, subtitle: Path, output: Path, ffmpeg: _FFmpeg, *arguments: str
) -> Path:
    ffmpeg(
        "-i",
        str(video),
        "-i",
        str(subtitle),
        "-map",
        "0:v",
        "-map",
        "1:s",
        "-c",
        "copy",
        *arguments,
        str(output),
    )
    return output


@pytest.mark.parametrize(("width", "height"), ((320, 240), (640, 360)))
@pytest.mark.parametrize("extension", ("srt", "ass"))
def test_converted_text_has_visible_ipod_subtitle_geometry(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    profile: DeviceProfile,
    width: int,
    height: int,
    extension: str,
) -> None:
    subtitle = tmp_path / f"source.{extension}"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:02,800\nVisible dialogue.\n"
        if extension == "srt"
        else _ASS_HEADER
        + "Dialogue: 0,0:00:00.00,0:00:02.80,Default,,0,0,0,,Visible dialogue.\n",
        encoding="utf-8",
    )
    sized_video = tmp_path / "sized.mp4"
    ffmpeg(
        "-i",
        str(video),
        "-an",
        "-vf",
        f"scale={width}:{height},setsar=1",
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-level:v",
        "3.0",
        "-b:v",
        "300k",
        str(sized_video),
    )
    path = _mux(sized_video, subtitle, tmp_path / "source.mkv", ffmpeg)

    with MediaTranscoder().prepare(
        HostPath(path), profile, TranscodeSettings(), checkpoint=lambda: None
    ) as prepared:
        _assert_bottom_subtitle_strip(Path(prepared.source.path), width, height)
        cues = _read_cues(prepared.source, tmp_path / "result.srt", ffmpeg)
        assert _at(cues, 1000) == "Visible dialogue."


def test_fractional_frame_rate_subtitles_use_a_bounded_movie_clock(
    tmp_path: Path, video: Path, ffmpeg: _FFmpeg, profile: DeviceProfile
) -> None:
    subtitle = tmp_path / "source.srt"
    subtitle.write_text(
        "1\n00:00:00,400 --> 00:00:02,800\nKeep the movie clock bounded.\n",
        encoding="utf-8",
    )
    source = tmp_path / "fractional.mkv"
    ffmpeg(
        "-i",
        str(video),
        "-i",
        str(subtitle),
        "-map",
        "0:v",
        "-map",
        "0:a",
        "-map",
        "1:s",
        "-r",
        "24000/1001",
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-level:v",
        "3.0",
        "-c:a",
        "copy",
        "-c:s",
        "srt",
        str(source),
    )
    with MediaTranscoder().prepare(
        HostPath(source), profile, TranscodeSettings(), checkpoint=lambda: None
    ) as prepared:
        assert prepared.inspection.video_streams[0].frame_rate == Fraction(24000, 1001)
        assert prepared.inspection.audio_streams[0].sample_rate_hz == 44100
        data = Path(prepared.source.path).read_bytes()
        movie = next(
            atom for atom in _atoms(data, 0, len(data)) if atom.kind == b"moov"
        )
        header = _child(data, movie, b"mvhd")
        version = data[header.payload]
        assert version in (0, 1)
        clock_offset = header.payload + (12 if version == 0 else 20)
        assert int.from_bytes(data[clock_offset : clock_offset + 4], "big") == 1000
        cues = _read_cues(prepared.source, tmp_path / "result.srt", ffmpeg)
        assert _at(cues, 1000) == "Keep the movie clock bounded."


@pytest.mark.parametrize("explicit", (False, True))
@pytest.mark.parametrize(
    ("extension", "content"),
    (
        ("srt", "1\n00:00:00,400 --> 00:00:02,800\nCafé — 日本語 & français.\n"),
        (
            "vtt",
            "WEBVTT\n\n00:00.400 --> 00:02.800 line:90% align:start\n"
            "<v Speaker>Café — 日本語 &amp; français.</v>\n",
        ),
    ),
)
def test_unicode_text_survives_explicit_and_automatic_preparation(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    profile: DeviceProfile,
    extension: str,
    content: str,
    explicit: bool,
) -> None:
    subtitle = tmp_path / f"source.{extension}"
    subtitle.write_text(content, encoding="utf-8")
    path = _mux(video, subtitle, tmp_path / "source.mkv", ffmpeg)

    with MediaTranscoder().prepare(
        HostPath(path),
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
        stream_selection=_selection(path) if explicit else None,
    ) as prepared:
        assert compatible_video(prepared.inspection, profile)
        streams = tuple(
            s for s in prepared.inspection.streams if s.kind is StreamKind.SUBTITLE
        )
        assert [(s.codec, s.codec_tag) for s in streams] == [("mov_text", "tx3g")]
        cues = _read_cues(prepared.source, tmp_path / "result.srt", ffmpeg)
        assert _at(cues, 1000) == "Café — 日本語 & français."
        assert cues[0].start_ms == pytest.approx(400, abs=40)
        assert cues[-1].end_ms == pytest.approx(2800, abs=40)


def test_literal_punctuation_and_backslashes_survive_as_actual_tx3g_text(
    tmp_path: Path, video: Path, ffmpeg: _FFmpeg, profile: DeviceProfile
) -> None:
    text = r"<Jane> says &amp;copy; & goes C:\new\folder \N {example} — 日本語."
    expected = text.replace("&amp;copy;", "&copy;")
    subtitle = tmp_path / "source.srt"
    subtitle.write_text(f"1\n00:00:00,000 --> 00:00:02,800\n{text}\n", encoding="utf-8")
    path = _mux(video, subtitle, tmp_path / "source.mkv", ffmpeg)

    with MediaTranscoder().prepare(
        HostPath(path),
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
        stream_selection=_selection(path),
    ) as prepared:
        output = tmp_path / "subtitle.data"
        ffmpeg(
            "-i",
            str(prepared.source),
            "-map",
            "0:s:0",
            "-c:s",
            "copy",
            "-f",
            "data",
            str(output),
        )
        # Read the counted UTF-8 text directly. Exporting to SRT would introduce
        # another decoder's interpretation of literal angle brackets/backslashes.
        payload = output.read_bytes()
        length = int.from_bytes(payload[:2], "big")
        assert payload[2 : 2 + length].decode("utf-8") == expected


def test_complex_ass_keeps_dialogue_before_during_and_after_overlapping_signs(
    tmp_path: Path, video: Path, ffmpeg: _FFmpeg, profile: DeviceProfile
) -> None:
    subtitle = tmp_path / "source.ass"
    subtitle.write_text(
        _ASS_HEADER
        + "Dialogue: 0,0:00:00.00,0:00:02.80,Default,,0,0,0,,Keep the dialogue.\n"
        + r"Dialogue: 1,0:00:01.00,0:00:02.00,Default,,0,0,0,,{\move(0,0,20,20)\t(0,100,\fs40)\k20}Sta{\k30}tion"
        + "\n"
        + r"Dialogue: 2,0:00:00.40,0:00:00.60,Default,,0,0,0,,{\p1}m 0 0 l 10 0 10 10{\p0}"
        + "\n"
        + r"Dialogue: 2,0:00:02.00,0:00:02.60,Default,,0,0,0,,{\p1}m 0 0 l 10 0 10 10{\p0}Readable ending."
        + "\n",
        encoding="utf-8",
    )
    path = _mux(video, subtitle, tmp_path / "source.mkv", ffmpeg)

    with MediaTranscoder().prepare(
        HostPath(path),
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
        stream_selection=_selection(path),
    ) as prepared:
        cues = _read_cues(prepared.source, tmp_path / "result.srt", ffmpeg)
        assert _at(cues, 200) == "Keep the dialogue."
        assert _at(cues, 500) == "Keep the dialogue."
        assert "Keep the dialogue." in _at(cues, 1500)
        assert "Station" in _at(cues, 1500)
        assert "Keep the dialogue." in _at(cues, 2300)
        assert "Readable ending." in _at(cues, 2300)
        assert _at(cues, 2700) == "Keep the dialogue."
        assert all(
            token not in "\n".join(cue.text for cue in cues)
            for token in ("{", "\\", "m 0 0", "l 10 0")
        )
        assert cues[-1].end_ms == pytest.approx(2800, abs=40)
        assert prepared.warnings


def test_compatible_tx3g_keeps_the_original_media_bytes(
    tmp_path: Path, video: Path, ffmpeg: _FFmpeg, profile: DeviceProfile
) -> None:
    subtitle = tmp_path / "source.srt"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:02,800\nAlready compatible.\n", encoding="utf-8"
    )
    path = _mux(
        video,
        subtitle,
        tmp_path / "source.mp4",
        ffmpeg,
        "-c:s",
        "mov_text",
        "-s:s",
        "320x240",
    )
    _set_native_subtitle_layout(path)
    original = path.read_bytes()

    with MediaTranscoder().prepare(
        HostPath(path), profile, TranscodeSettings(), checkpoint=lambda: None
    ) as prepared:
        assert not prepared.was_transcoded
        assert Path(prepared.source.path).read_bytes() == original
        _assert_bottom_subtitle_strip(Path(prepared.source.path), 320, 240)
        assert not prepared.warnings


@pytest.mark.parametrize("explicit", (False, True))
def test_tx3g_canvas_follows_aspect_preserving_video_resize(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    profile: DeviceProfile,
    explicit: bool,
) -> None:
    subtitle = tmp_path / "source.srt"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:02,800\nStill readable.\n", encoding="utf-8"
    )
    path = _mux(
        video,
        subtitle,
        tmp_path / "source.mp4",
        ffmpeg,
        "-c:s",
        "mov_text",
        "-s:s",
        "320x240",
    )
    # The height limit does not constrain a 4:3 source; its actual result is 160x120.
    profile = replace(
        profile,
        capabilities=replace(
            profile.capabilities,
            video=replace(profile.capabilities.video, max_width=160, max_height=160),
        ),
    )

    with MediaTranscoder().prepare(
        HostPath(path),
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
        stream_selection=_selection(path) if explicit else None,
    ) as prepared:
        motion = prepared.inspection.video_streams[0]
        subtitles = tuple(
            s for s in prepared.inspection.streams if s.kind is StreamKind.SUBTITLE
        )
        assert (motion.width, motion.height) == (160, 120)
        assert [(s.width, s.height) for s in subtitles] == [(160, 18)]
        _assert_bottom_subtitle_strip(Path(prepared.source.path), 160, 120)
        cues = _read_cues(prepared.source, tmp_path / "result.srt", ffmpeg)
        assert _at(cues, 1000) == "Still readable."


def test_multiple_selected_subtitles_keep_languages_and_report_lost_forced_flag(
    tmp_path: Path, video: Path, ffmpeg: _FFmpeg, profile: DeviceProfile
) -> None:
    french = tmp_path / "french.srt"
    french.write_text("1\n00:00:00,000 --> 00:00:02,800\nBonjour.\n", encoding="utf-8")
    japanese = tmp_path / "japanese.ass"
    japanese.write_text(
        _ASS_HEADER + "Dialogue: 0,0:00:00.00,0:00:02.80,Default,,0,0,0,,日本語。\n",
        encoding="utf-8",
    )
    path = tmp_path / "languages.mkv"
    ffmpeg(
        "-i",
        str(video),
        "-i",
        str(french),
        "-i",
        str(japanese),
        "-map",
        "0:v",
        "-map",
        "1:s",
        "-map",
        "2:s",
        "-c",
        "copy",
        "-metadata:s:s:0",
        "language=fra",
        "-metadata:s:s:1",
        "language=jpn",
        "-disposition:s:0",
        "0",
        "-disposition:s:1",
        "forced",
        str(path),
    )
    original = _selection(path)
    selection = replace(original, subtitles=tuple(reversed(original.subtitles)))

    with MediaTranscoder().prepare(
        HostPath(path),
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
        stream_selection=selection,
    ) as prepared:
        subtitles = tuple(
            s for s in prepared.inspection.streams if s.kind is StreamKind.SUBTITLE
        )
        assert [
            next(tag.value for tag in stream.tags if tag.name == "language")
            for stream in subtitles
        ] == ["jpn", "fra"]
        # FFmpeg's iPod muxer cannot retain this flag in all supported versions.
        # Keep the readable stream and report the loss instead of silently dropping it.
        assert "forced" in subtitles[0].dispositions or any(
            "forced" in warning.casefold() for warning in prepared.warnings
        )
        assert "forced" not in subtitles[1].dispositions
        assert (
            _at(
                _read_cues(prepared.source, tmp_path / "japanese-result.srt", ffmpeg),
                1000,
            )
            == "日本語。"
        )
        assert (
            _at(
                _read_cues(
                    prepared.source, tmp_path / "french-result.srt", ffmpeg, stream=1
                ),
                1000,
            )
            == "Bonjour."
        )


@pytest.mark.parametrize("include_audio", (False, True))
def test_nonzero_container_start_keeps_subtitles_on_the_video_timeline(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    profile: DeviceProfile,
    include_audio: bool,
) -> None:
    subtitle = tmp_path / "source.srt"
    subtitle.write_text(
        "1\n00:00:00,400 --> 00:00:02,800\nOn time.\n", encoding="utf-8"
    )
    path = _mux(
        video,
        subtitle,
        tmp_path / "shifted.mkv",
        ffmpeg,
        "-output_ts_offset",
        "5",
        *(("-map", "0:a") if include_audio else ()),
    )
    observed = MediaInspector().inspect(HostPath(path), checkpoint=lambda: None)
    assert observed.start_seconds == 5

    with MediaTranscoder().prepare(
        HostPath(path),
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
        stream_selection=_selection(path),
    ) as prepared:
        cues = _read_cues(prepared.source, tmp_path / "result.srt", ffmpeg)
        assert cues[0].start_ms == pytest.approx(400, abs=40)
        assert cues[-1].end_ms == pytest.approx(2800, abs=40)
        assert _at(cues, 1000) == "On time."
