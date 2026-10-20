"""Retained video streams survive real FFmpeg preparation and verification."""

import shutil
import subprocess
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Protocol

import pytest

from device_registry import DeviceProfile
from device_registry.data.catalog import DEFAULT_CATALOG
from iOpenPod.app.media import MediaInspector
from iOpenPod.app.media.models import StreamKind
from iOpenPod.app.media.transcoding import (
    MediaTranscoder,
    TranscodeSettings,
    compatible_video,
    resolve_transcode,
)
from iPodDB.library import Track
from storage import HostPath


class _FFmpeg(Protocol):
    def __call__(self, *arguments: str) -> None: ...


@pytest.fixture
def ffmpeg() -> _FFmpeg:
    executable = shutil.which("ffmpeg")
    if executable is None or shutil.which("ffprobe") is None:
        pytest.skip("Video preparation requires FFmpeg and FFprobe")

    def run(*arguments: str) -> None:
        subprocess.run(
            [executable, "-v", "error", "-y", *arguments],
            check=True,
            capture_output=True,
        )

    return run


@pytest.fixture
def profile() -> DeviceProfile:
    return next(
        p
        for p in DEFAULT_CATALOG.profiles
        if p.capabilities.video.supports_tx3g_subtitles
        and p.capabilities.video.supports_cea608_captions
    )


@pytest.fixture
def video(tmp_path: Path, ffmpeg: _FFmpeg) -> Path:
    path = tmp_path / "video.mp4"
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=320x240:r=25",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=44100",
        "-t",
        "3",
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-level:v",
        "3.0",
        "-pix_fmt",
        "yuv420p",
        "-b:v",
        "300k",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-metadata:s:a:0",
        "language=fra",
        "-metadata",
        "title=Source title",
        str(path),
    )
    return path


@pytest.fixture
def captioned_video(tmp_path: Path, video: Path, ffmpeg: _FFmpeg) -> Path:
    captions = tmp_path / "captions.scc"
    captions.write_text(
        "Scenarist_SCC V1.0\n\n"
        "00:00:01:00\t9420 9420 94ae 94ae 94e0 94e0 c845 4c4c 4f20 "
        "574f 524c c480 942f 942f\n\n00:00:02:00\t942c 942c\n",
        encoding="ascii",
    )
    path = tmp_path / "captioned.mov"
    ffmpeg(
        "-i",
        str(video),
        "-i",
        str(captions),
        "-map",
        "0:v",
        "-map",
        "0:a",
        "-map",
        "1:s",
        "-c",
        "copy",
        "-metadata:s:s:0",
        "language=eng",
        "-f",
        "mov",
        str(path),
    )
    return path


@pytest.mark.parametrize("convert", (False, True))
def test_supported_cea608_survives_copy_and_conversion(
    captioned_video: Path, profile: DeviceProfile, convert: bool
) -> None:
    with MediaTranscoder().prepare(
        HostPath(captioned_video),
        profile,
        TranscodeSettings(retranscode_lossy=convert),
        checkpoint=lambda: None,
    ) as prepared:
        captions = [
            stream
            for stream in prepared.inspection.streams
            if stream.kind is StreamKind.SUBTITLE
        ]
        assert [(s.codec, s.codec_tag) for s in captions] == [("eia_608", "c608")]
        assert prepared.was_transcoded is convert
        assert compatible_video(prepared.inspection, profile)
        assert not prepared.warnings


def test_unsupported_cea608_is_excluded_with_a_warning(
    captioned_video: Path, profile: DeviceProfile
) -> None:
    profile = replace(
        profile,
        capabilities=replace(
            profile.capabilities,
            video=replace(profile.capabilities.video, supports_cea608_captions=False),
        ),
    )
    with MediaTranscoder().prepare(
        HostPath(captioned_video), profile, TranscodeSettings(), checkpoint=lambda: None
    ) as prepared:
        assert not any(
            s.kind is StreamKind.SUBTITLE for s in prepared.inspection.streams
        )
        assert any("eia_608" in warning for warning in prepared.warnings)


@pytest.mark.parametrize("rockbox_metadata", (False, True))
def test_selected_stream_languages_survive_conversion(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    profile: DeviceProfile,
    rockbox_metadata: bool,
) -> None:
    subtitles = tmp_path / "subtitles.srt"
    subtitles.write_text(
        "1\n00:00:00,000 --> 00:00:02,800\nKeep the language.\n", encoding="utf-8"
    )
    path = tmp_path / "subtitled.mp4"
    # The selected default audio is not the first input audio stream.
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
        "-disposition:a:0",
        "0",
        "-disposition:a:1",
        "default",
        "-metadata:s:a:0",
        "language=deu",
        "-metadata:s:a:1",
        "language=fra",
        "-metadata:s:s:0",
        "language=eng",
        str(path),
    )
    with MediaTranscoder().prepare(
        HostPath(path),
        profile,
        TranscodeSettings(retranscode_lossy=True),
        metadata=Track(1, "Source title", "", "", 3_000),
        rockbox_metadata=rockbox_metadata,
        checkpoint=lambda: None,
    ) as prepared:
        languages = [
            (stream.kind, next(t.value for t in stream.tags if t.name == "language"))
            for stream in prepared.inspection.streams
            if stream.kind in (StreamKind.AUDIO, StreamKind.SUBTITLE)
        ]
        assert languages == [(StreamKind.AUDIO, "fra"), (StreamKind.SUBTITLE, "eng")]
        assert prepared.inspection.audio_streams[0].default
        tags = {tag.name: tag.value for tag in prepared.inspection.tags}
        assert (tags.get("title") == "Source title") is rockbox_metadata


def test_variable_frame_rate_bursts_are_normalized_below_the_device_limit(
    tmp_path: Path, ffmpeg: _FFmpeg, profile: DeviceProfile
) -> None:
    path = tmp_path / "variable.mp4"
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=320x240:r=60:d=4",
        "-vf",
        "select='lt(n,60)+gte(n,60)*not(mod(n,6))'",
        "-fps_mode",
        "vfr",
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-level:v",
        "3.0",
        "-b:v",
        "300k",
        str(path),
    )
    observed = MediaInspector().inspect(HostPath(path), checkpoint=lambda: None)
    motion = observed.video_streams[0]
    assert motion.frame_rate is not None and motion.frame_rate < 30
    assert motion.nominal_frame_rate == 60
    assert not compatible_video(observed, profile)

    with MediaTranscoder().prepare(
        HostPath(path), profile, TranscodeSettings(), checkpoint=lambda: None
    ) as prepared:
        result = prepared.inspection.video_streams[0]
        assert prepared.was_transcoded
        assert result.frame_rate == result.nominal_frame_rate == 30
        assert compatible_video(prepared.inspection, profile)


@pytest.mark.parametrize("nominal", (None, Fraction(0), Fraction(20)))
def test_unverified_constant_frame_rate_requires_normalization(
    video: Path, profile: DeviceProfile, nominal: Fraction | None
) -> None:
    observed = MediaInspector().inspect(HostPath(video), checkpoint=lambda: None)
    observed = replace(
        observed,
        streams=(replace(observed.video_streams[0], nominal_frame_rate=nominal),),
    )
    assert not compatible_video(observed, profile)
    plan = resolve_transcode(
        observed, profile, TranscodeSettings(), frozenset(("libx264",))
    )
    assert "libx264" in plan.output_arguments
    filters = plan.output_arguments[plan.output_arguments.index("-vf") + 1]
    assert f"fps={nominal or 25}" in filters
