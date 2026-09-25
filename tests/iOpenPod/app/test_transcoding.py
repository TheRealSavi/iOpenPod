"""Device policy and real media conversion run before any device publication."""

from __future__ import annotations

import base64
import io
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from mutagen.mp3 import MP3

from device_registry.data.catalog import DEFAULT_CATALOG
from iOpenPod.app.media import MediaInspectionError, MediaInspector, MediaTag
from iOpenPod.app.media.transcoding import (
    BitrateMode,
    LossyEncoder,
    MediaTranscoder,
    TranscodeQuality,
    TranscodeSettings,
    VideoEncoding,
    compatible_audio,
    compatible_video,
    enrich_source_metadata,
    resolve_transcode,
)
from iPodDB.library import AudioEncoding, MediaKind, Track, TrackMetadata
from storage import HostPath, capture_host_file
from storage.media_processing import MediaToolError

if TYPE_CHECKING:
    from collections.abc import Callable

    from device_registry import DeviceProfile

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "media"


@pytest.fixture
def profile() -> DeviceProfile:
    return next(
        p for p in DEFAULT_CATALOG.profiles if p.capabilities.audio.supports_alac
    )


@pytest.fixture(
    params=sorted(
        {
            p.display_name
            for p in DEFAULT_CATALOG.profiles
            if p.capabilities.video.supported
        }
    )
)
def video_profile(request: pytest.FixtureRequest) -> DeviceProfile:
    return next(p for p in DEFAULT_CATALOG.profiles if p.display_name == request.param)


def source(tmp_path: Path, filename: str) -> HostPath:
    path = tmp_path / filename
    path.write_bytes(base64.decodebytes((FIXTURES / f"{filename}.b64").read_bytes()))
    return HostPath(path)


@pytest.fixture
def transcoder() -> MediaTranscoder:
    if any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe", "fpcalc")):
        pytest.skip("Actual media preparation needs FFmpeg, FFprobe and fpcalc")
    return MediaTranscoder()


def test_all_missing_tools_are_reported_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_tool(_name: str) -> None:
        return None

    monkeypatch.setattr(shutil, "which", missing_tool)
    with pytest.raises(MediaToolError, match="ffmpeg, ffprobe, fpcalc") as error:
        MediaTranscoder().preflight(checkpoint=lambda: None)
    assert error.value.code == "media.tools_missing"
    assert "PATH" in str(error.value)
    assert "No device changes" in str(error.value)


@pytest.mark.parametrize("filename", ["tone.mp3", "tone.m4a", "lossless.m4a"])
def test_compatible_copy_preserves_exact_bytes_and_cleans_temporary_files(
    tmp_path: Path, profile: DeviceProfile, transcoder: MediaTranscoder, filename: str
) -> None:
    original = source(tmp_path, filename)
    with transcoder.prepare(
        original, profile, TranscodeSettings(), checkpoint=lambda: None
    ) as result:
        captured = Path(result.source)
        assert captured.read_bytes() == Path(original).read_bytes()
        assert not result.was_transcoded
        assert compatible_audio(result.inspection, profile) is result.encoding
        with capture_host_file(result.source, checkpoint=lambda: None) as recaptured:
            assert recaptured.fingerprint == result.inspection.fingerprint
    assert not captured.exists()
    assert Path(original).exists()


def test_high_resolution_surround_lossless_becomes_verified_stereo_alac(
    tmp_path: Path, profile: DeviceProfile, transcoder: MediaTranscoder
) -> None:
    with transcoder.prepare(
        source(tmp_path, "surround.flac"),
        profile,
        TranscodeSettings(normalize_44100=True),
        checkpoint=lambda: None,
    ) as result:
        assert result.was_transcoded
        assert result.encoding is AudioEncoding.ALAC
        audio = result.inspection.audio_streams[0]
        assert (audio.sample_rate_hz, audio.channels, audio.bits_per_raw_sample) == (
            44100,
            2,
            16,
        )
        assert len(result.warnings) == 3


def test_spoken_word_overrides_lossless_and_encodes_mono_at_selected_bitrate(
    tmp_path: Path, profile: DeviceProfile, transcoder: MediaTranscoder
) -> None:
    settings = TranscodeSettings(
        lossy_encoder=LossyEncoder.MP3,
        bitrate_mode=BitrateMode.CBR,
        spoken_word_bitrate_kbps=48,
    )
    with transcoder.prepare(
        source(tmp_path, "lossless.m4a"),
        profile,
        settings,
        spoken_word=True,
        checkpoint=lambda: None,
    ) as result:
        assert result.encoding is AudioEncoding.MP3
        assert result.inspection.audio_streams[0].channels == 1
        assert result.inspection.audio_streams[0].bitrate_bps == 48000


def test_encoder_options_and_auto_policy_use_only_available_encoders(
    tmp_path: Path, profile: DeviceProfile, transcoder: MediaTranscoder
) -> None:
    inspection = MediaInspector().inspect(
        source(tmp_path, "tone.wav"), checkpoint=lambda: None
    )
    auto = resolve_transcode(
        inspection,
        profile,
        TranscodeSettings(lossless_to_lossy=True),
        frozenset(("aac", "libmp3lame", "libfdk_aac")),
    )
    assert "libfdk_aac" in auto.output_arguments
    assert "aac_low" in auto.output_arguments
    manual = resolve_transcode(
        inspection,
        profile,
        TranscodeSettings(
            lossless_to_lossy=True,
            lossy_encoder=LossyEncoder.MP3,
            bitrate_mode=BitrateMode.ABR,
            bitrate_kbps=128,
        ),
        frozenset(("libmp3lame",)),
    )
    assert manual.output_arguments[manual.output_arguments.index("-abr") + 1] == "1"
    with pytest.raises(MediaToolError, match="selected encoder"):
        resolve_transcode(
            inspection,
            profile,
            TranscodeSettings(
                lossless_to_lossy=True, lossy_encoder=LossyEncoder.FDK_AAC
            ),
            frozenset(("aac",)),
        )


def test_normalization_only_downsamples_above_44100_and_wav_setting_controls_passthrough(
    tmp_path: Path, profile: DeviceProfile, transcoder: MediaTranscoder
) -> None:
    inspection = MediaInspector().inspect(
        source(tmp_path, "tone.wav"), checkpoint=lambda: None
    )
    lower = replace(
        inspection,
        streams=(replace(inspection.audio_streams[0], sample_rate_hz=22050),),
    )
    plan = resolve_transcode(
        lower,
        profile,
        TranscodeSettings(wav_aiff_to_alac=False, normalize_44100=True),
        frozenset(("alac",)),
    )
    assert not plan.requires_transcode
    assert plan.sample_rate_hz == 22050


def test_failure_inside_output_context_always_removes_host_staging(
    tmp_path: Path, profile: DeviceProfile, transcoder: MediaTranscoder
) -> None:
    prepared: Path | None = None
    with (
        pytest.raises(RuntimeError, match="cancelled"),
        transcoder.prepare(
            source(tmp_path, "tone.wav"),
            profile,
            TranscodeSettings(),
            checkpoint=lambda: None,
        ) as result,
    ):
        prepared = Path(result.source)
        assert prepared.exists()
        raise RuntimeError("cancelled")
    assert prepared is not None
    assert not prepared.exists()


def test_settings_reject_unsupported_bitrate_modes() -> None:
    with pytest.raises(ValueError, match="does not support"):
        TranscodeSettings(
            lossy_encoder=LossyEncoder.FDK_AAC, bitrate_mode=BitrateMode.ABR
        )


@pytest.mark.parametrize("filename", ["silent.mp4", "source.mkv"])
def test_video_output_is_verified_against_model_specific_limits(
    tmp_path: Path, transcoder: MediaTranscoder, filename: str
) -> None:
    profile = next(
        p for p in DEFAULT_CATALOG.profiles if p.capabilities.video.supported
    )
    with transcoder.prepare(
        source(tmp_path, filename),
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
    ) as prepared:
        assert prepared.encoding is VideoEncoding.MP4
        assert compatible_video(prepared.inspection, profile)
        assert prepared.inspection.audio_streams == ()


def test_lossless_preference_is_preserved_when_device_cannot_play_alac(
    tmp_path: Path, profile: DeviceProfile, transcoder: MediaTranscoder
) -> None:
    profile = replace(
        profile,
        capabilities=replace(
            profile.capabilities,
            audio=replace(profile.capabilities.audio, supports_alac=False),
        ),
    )
    with transcoder.prepare(
        source(tmp_path, "surround.flac"),
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
    ) as prepared:
        assert prepared.encoding is AudioEncoding.WAV
        assert any("Preserved lossless" in message for message in prepared.warnings)


def test_rockbox_tags_and_lyrics_are_written_to_private_copy_and_reverified(
    tmp_path: Path, profile: DeviceProfile, transcoder: MediaTranscoder
) -> None:
    original = source(tmp_path, "tone.mp3")
    before = Path(original).read_bytes()
    track = Track(
        1,
        "Reviewed title",
        "Reviewed artist",
        "Reviewed album",
        250,
        metadata=TrackMetadata(lyrics="Reviewed lyrics", composer="Composer"),
    )
    with transcoder.prepare(
        original,
        profile,
        TranscodeSettings(),
        metadata=track,
        rockbox_metadata=True,
        checkpoint=lambda: None,
    ) as prepared:
        tagged = cast("Callable[[io.BytesIO], Any]", MP3)(
            io.BytesIO(Path(prepared.source).read_bytes())
        )
        assert tagged.tags is not None
        assert str(tagged.tags["TIT2"]) == "Reviewed title"
        assert str(tagged.tags["TCOM"]) == "Composer"
        assert str(tagged.tags.getall("USLT")[0].text) == "Reviewed lyrics"
        assert (
            prepared.inspection.fingerprint.sha256
            != prepared.original_fingerprint.sha256
        )
    assert Path(original).read_bytes() == before


def test_video_and_audio_are_converted_together_and_fully_decoded(
    tmp_path: Path, transcoder: MediaTranscoder, video_profile: DeviceProfile
) -> None:
    path = tmp_path / "high-profile.mkv"
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=640x480:r=60",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-c:a",
            "libmp3lame",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    observed = MediaInspector().inspect(HostPath(path), checkpoint=lambda: None)
    caps = video_profile.capabilities.video
    for quality in TranscodeQuality:
        plan = resolve_transcode(
            observed,
            video_profile,
            TranscodeSettings(quality=quality),
            frozenset(("libx264", "aac")),
        )
        args = plan.output_arguments
        assert args[args.index("-preset") + 1] == "medium"
        assert args[args.index("-crf") + 1] == "23"
        assert "-b:v" not in args
        assert args[args.index("-level:v") + 1] == caps.h264_level
        assert args[args.index("-maxrate") + 1] == f"{caps.max_bitrate_kbps}k"
        assert args[args.index("-bufsize") + 1] == f"{caps.max_bitrate_kbps * 2}k"
    with transcoder.prepare(
        HostPath(path),
        video_profile,
        TranscodeSettings(normalize_44100=True),
        checkpoint=lambda: None,
    ) as prepared:
        assert compatible_video(prepared.inspection, video_profile)
        assert prepared.inspection.audio_streams[0].codec == "aac"
        assert prepared.inspection.audio_streams[0].sample_rate_hz == 44100
        assert prepared.inspection.video_streams[0].frame_rate == caps.max_fps
        assert prepared.was_transcoded
        # A compatible result can be copied on the next Sync without an encoder.
        assert not resolve_transcode(
            prepared.inspection,
            video_profile,
            TranscodeSettings(),
            frozenset(),
        ).requires_transcode


def test_video_is_rejected_for_an_ipod_without_video_support(
    tmp_path: Path, profile: DeviceProfile, transcoder: MediaTranscoder
) -> None:
    assert not profile.capabilities.video.supported
    observed = MediaInspector().inspect(
        source(tmp_path, "source.mkv"), checkpoint=lambda: None
    )
    with pytest.raises(MediaInspectionError, match="cannot play video"):
        resolve_transcode(
            observed,
            profile,
            TranscodeSettings(),
            frozenset(("libx264", "aac")),
        )


def test_source_metadata_enrichment_preserves_reviewed_core_and_carries_lyrics_chapters(
    tmp_path: Path, transcoder: MediaTranscoder
) -> None:
    observed = MediaInspector().inspect(
        source(tmp_path, "chapters-cover.m4a"), checkpoint=lambda: None
    )
    observed = replace(
        observed,
        tags=(
            *observed.tags,
            MediaTag("lyrics-eng", "Source lyrics"),
            MediaTag("composer", "Source composer"),
        ),
    )
    reviewed = Track(
        1, "Normalized title", "Normalized artist", "Normalized album", 250
    )
    enriched = enrich_source_metadata(reviewed, observed)
    assert enriched.title == reviewed.title
    assert enriched.artist == reviewed.artist
    assert enriched.metadata.lyrics == "Source lyrics"
    assert enriched.metadata.composer == "Source composer"
    assert [chapter.start_ms for chapter in enriched.metadata.chapters] == [0, 100]


def test_m4b_content_activates_spoken_settings_before_transcoding(
    tmp_path: Path, profile: DeviceProfile, transcoder: MediaTranscoder
) -> None:
    original = source(tmp_path, "lossless.m4a")
    book = Path(original).with_suffix(".m4b")
    Path(original).rename(book)
    host = Track(1, "Book", "Author", "Book", 250)
    with transcoder.prepare(
        HostPath(book),
        profile,
        TranscodeSettings(),
        metadata=host,
        checkpoint=lambda: None,
    ) as prepared:
        assert prepared.metadata is not None
        assert prepared.metadata.media_kind is MediaKind.AUDIOBOOK
        assert prepared.encoding in (AudioEncoding.AAC, AudioEncoding.MP3)
        assert prepared.inspection.audio_streams[0].channels == 1
        assert prepared.was_transcoded
