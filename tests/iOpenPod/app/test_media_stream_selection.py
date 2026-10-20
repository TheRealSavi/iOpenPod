"""Explicit stream choices survive preparation and reject stale observations."""

from dataclasses import replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.test_video_preparation import (
    _FFmpeg,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_video_preparation import captioned_video as captioned_video
from tests.iOpenPod.app.test_video_preparation import ffmpeg as ffmpeg
from tests.iOpenPod.app.test_video_preparation import profile as profile
from tests.iOpenPod.app.test_video_preparation import video as video

from device_registry import DeviceProfile
from iOpenPod.app.media import MediaInspectionError, MediaInspector
from iOpenPod.app.media.models import MediaStream, StreamKind
from iOpenPod.app.media.stream_selection import (
    MediaStreamSelection,
    SubtitleHandling,
    is_caption,
    subtitle_handling,
)
from iOpenPod.app.media.transcoding import (
    MediaTranscoder,
    TranscodeSettings,
    resolve_transcode,
)
from storage import HostPath


@pytest.fixture
def multiple_streams(tmp_path: Path, captioned_video: Path, ffmpeg: _FFmpeg) -> Path:
    text = tmp_path / "french.srt"
    text.write_text("1\n00:00:00,000 --> 00:00:02,800\nBonjour.\n", encoding="utf-8")
    path = tmp_path / "choices.mov"
    ffmpeg(
        "-i",
        str(captioned_video),
        "-i",
        str(text),
        "-map",
        "0:v",
        "-map",
        "0:v",
        "-map",
        "0:a",
        "-map",
        "0:a",
        "-map",
        "1:s",
        "-map",
        "0:s",
        "-c:v:0",
        "copy",
        "-c:v:1",
        "libx264",
        "-profile:v:1",
        "baseline",
        "-level:v:1",
        "3.0",
        "-filter:v:1",
        "scale=160:120",
        "-c:a",
        "copy",
        "-c:s:0",
        "mov_text",
        "-tag:s:0",
        "tx3g",
        "-s:s:0",
        "320x240",
        "-c:s:1",
        "copy",
        "-disposition:v:0",
        "default",
        "-disposition:v:1",
        "0",
        "-disposition:a:0",
        "default",
        "-disposition:a:1",
        "0",
        "-disposition:s:0",
        "forced",
        "-metadata:s:a:0",
        "language=eng",
        "-metadata:s:a:1",
        "language=spa",
        "-metadata:s:s:0",
        "language=fra",
        "-f",
        "mov",
        str(path),
    )
    return path


def language(stream: MediaStream) -> str:
    return next((tag.value for tag in stream.tags if tag.name == "language"), "")


def test_nondefault_video_audio_subtitle_and_caption_reach_output(
    multiple_streams: Path,
    profile: DeviceProfile,
) -> None:
    source = HostPath(multiple_streams)
    observed = MediaInspector().scan_metadata(source, checkpoint=lambda: None)
    selection = MediaStreamSelection(
        observed.video_streams[1],
        observed.audio_streams[1],
        tuple(
            s
            for s in observed.streams
            if s.kind is StreamKind.SUBTITLE and not is_caption(s)
        ),
        tuple(s for s in observed.streams if is_caption(s)),
    )
    with MediaTranscoder().prepare(
        source,
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
        stream_selection=selection,
    ) as result:
        assert len(result.inspection.video_streams) == 1
        assert result.inspection.video_streams[0].width == 160
        assert len(result.inspection.audio_streams) == 1
        assert language(result.inspection.audio_streams[0]) == "spa"
        subtitles = [
            s for s in result.inspection.streams if s.kind is StreamKind.SUBTITLE
        ]
        assert [(s.codec_tag, language(s)) for s in subtitles] == [
            ("tx3g", "fra"),
            ("c608", "eng"),
        ]
        assert subtitles[0].dispositions == selection.subtitles[0].dispositions
        assert (subtitles[0].width, subtitles[0].height) == (160, 18)
        assert result.inspection.audio_streams[0].default
        assert result.inspection.video_streams[0].default
        assert not result.warnings


def test_explicit_none_removes_audio_subtitles_and_captions(
    multiple_streams: Path,
    profile: DeviceProfile,
) -> None:
    source = HostPath(multiple_streams)
    observed = MediaInspector().scan_metadata(source, checkpoint=lambda: None)
    choice = MediaStreamSelection(observed.video_streams[0], None)
    with MediaTranscoder().prepare(
        source,
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
        stream_selection=choice,
    ) as result:
        assert len(result.inspection.video_streams) == 1
        assert result.inspection.audio_streams == ()
        assert not any(s.kind is StreamKind.SUBTITLE for s in result.inspection.streams)


def test_selected_subrip_converts_to_dimensioned_ipod_text(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    profile: DeviceProfile,
) -> None:
    text = tmp_path / "text.srt"
    text.write_text("1\n00:00:00,000 --> 00:00:02,800\nHello.\n", encoding="utf-8")
    path = tmp_path / "subrip.mkv"
    ffmpeg(
        "-i",
        str(video),
        "-i",
        str(text),
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
        str(path),
    )
    source = HostPath(path)
    observed = MediaInspector().scan_metadata(source, checkpoint=lambda: None)
    subtitle = next(s for s in observed.streams if s.kind is StreamKind.SUBTITLE)
    choice = MediaStreamSelection(
        observed.video_streams[0], observed.audio_streams[0], (subtitle,)
    )
    with MediaTranscoder().prepare(
        source,
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
        stream_selection=choice,
    ) as result:
        subtitle = next(
            s for s in result.inspection.streams if s.kind is StreamKind.SUBTITLE
        )
        assert (subtitle.codec, subtitle.codec_tag, language(subtitle)) == (
            "mov_text",
            "tx3g",
            "eng",
        )
        assert subtitle.width and subtitle.height


def test_selected_audio_only_stream_retains_its_language(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    profile: DeviceProfile,
) -> None:
    path = tmp_path / "two-audio.m4a"
    ffmpeg(
        "-i",
        str(video),
        "-map",
        "0:a",
        "-map",
        "0:a",
        "-c",
        "copy",
        "-metadata:s:a:1",
        "language=spa",
        str(path),
    )
    source = HostPath(path)
    observed = MediaInspector().scan_metadata(source, checkpoint=lambda: None)
    choice = MediaStreamSelection(None, observed.audio_streams[1])
    with MediaTranscoder().prepare(
        source,
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
        stream_selection=choice,
    ) as result:
        assert len(result.inspection.audio_streams) == 1
        assert language(result.inspection.audio_streams[0]) == "spa"
        assert result.inspection.video_streams == ()


@pytest.mark.parametrize("change", ["index", "language"])
def test_selection_rejects_changed_stream_evidence_before_conversion(
    video: Path,
    profile: DeviceProfile,
    change: str,
) -> None:
    observed = MediaInspector().inspect(HostPath(video), checkpoint=lambda: None)
    audio = observed.audio_streams[0]
    audio = replace(audio, index=999) if change == "index" else replace(audio, tags=())
    with pytest.raises(MediaInspectionError, match="selected streams changed"):
        resolve_transcode(
            observed,
            profile,
            TranscodeSettings(),
            frozenset(),
            stream_selection=MediaStreamSelection(observed.video_streams[0], audio),
        )


def test_bitmap_subtitles_are_explicitly_unavailable(
    video: Path, profile: DeviceProfile
) -> None:
    observed = MediaInspector().inspect(HostPath(video), checkpoint=lambda: None)
    bitmap = replace(
        observed.audio_streams[0],
        kind=StreamKind.SUBTITLE,
        codec="hdmv_pgs_subtitle",
        codec_tag="",
    )
    assert subtitle_handling(bitmap, profile) is SubtitleHandling.UNSUPPORTED
    observed = replace(observed, streams=(*observed.streams, replace(bitmap, index=9)))
    with pytest.raises(MediaInspectionError, match="cannot be prepared"):
        resolve_transcode(
            observed,
            profile,
            TranscodeSettings(),
            frozenset(),
            stream_selection=MediaStreamSelection(
                observed.video_streams[0], None, (observed.streams[-1],)
            ),
        )


def test_selection_requires_playable_media_and_cannot_reclassify_streams(
    video: Path,
) -> None:
    observed = MediaInspector().scan_metadata(HostPath(video), checkpoint=lambda: None)
    with pytest.raises(ValueError, match="playable"):
        MediaStreamSelection(None, None)
    with pytest.raises(ValueError, match="motion-video"):
        MediaStreamSelection(observed.audio_streams[0], None)
    with pytest.raises(ValueError, match="audio stream"):
        MediaStreamSelection(None, observed.video_streams[0])


def test_duration_verification_follows_the_selected_video_edition(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    profile: DeviceProfile,
) -> None:
    path = tmp_path / "short-edition.mp4"
    ffmpeg(
        "-i",
        str(video),
        "-t",
        "1",
        "-i",
        str(video),
        "-map",
        "0:v",
        "-map",
        "1:v",
        "-c",
        "copy",
        str(path),
    )
    source = HostPath(path)
    observed = MediaInspector().scan_metadata(source, checkpoint=lambda: None)
    choice = MediaStreamSelection(observed.video_streams[1], None)
    assert choice.video is not None and choice.video.duration_seconds is not None
    assert observed.video_streams[0].duration_seconds is not None
    assert choice.video.duration_seconds < observed.video_streams[0].duration_seconds
    with MediaTranscoder().prepare(
        source,
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
        stream_selection=choice,
    ) as result:
        assert (
            result.inspection.video_streams[0].duration_seconds
            == choice.video.duration_seconds
        )
