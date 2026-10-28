"""Real two-audio preparation preserves selected content through virtual Sync."""

import shutil
import struct
import subprocess
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_sync_execution import (
    _request,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_sync_stream_selection import host_library
from tests.iOpenPod.app.test_video_preparation import (
    _FFmpeg,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_video_preparation import ffmpeg as ffmpeg
from tests.iOpenPod.app.test_video_preparation import profile as profile
from tests.iOpenPod.app.test_video_preparation import video as video

from device_registry import DeviceProfile
from iOpenPod.app.host_media_library import HostMediaFileKind
from iOpenPod.app.media import MediaInspector
from iOpenPod.app.media.models import MediaInspection, MediaStream
from iOpenPod.app.media.stream_selection import MediaStreamSelection
from iOpenPod.app.media.stream_selection_codec import selection_digest
from iOpenPod.app.media.transcoding import (
    MediaTranscoder,
    TranscodeSettings,
    compatible_video,
)
from iOpenPod.app.media_stream_preferences import MediaStreamPreferences
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor
from iOpenPod.app.sync_plan import SyncPlanAction, prepare_sync_plan
from iPodDB.library import MediaType, Track
from storage import AtomicHostFile, HostPath


def _two_audio_source(
    tmp_path: Path, video: Path, ffmpeg: _FFmpeg, *, mixed_codecs: bool = False
) -> Path:
    path = tmp_path / ("mixed-audio.mov" if mixed_codecs else "two-audio.mov")
    ffmpeg(
        "-i",
        str(video),
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=880:sample_rate=44100",
        "-t",
        "3",
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a:0",
        "pcm_s16le" if mixed_codecs else "copy",
        "-c:a:1",
        "aac",
        "-b:a:1",
        "96k",
        "-disposition:a:0",
        "default",
        "-disposition:a:1",
        "0",
        "-metadata:s:a:0",
        "language=eng",
        "-metadata:s:a:1",
        "language=spa",
        str(path),
    )
    return path


def _selection(path: Path) -> MediaStreamSelection:
    observed = MediaInspector().scan_metadata(HostPath(path), checkpoint=lambda: None)
    return MediaStreamSelection(
        observed.video_streams[0],
        observed.audio_streams[1],
        alternate_audio=observed.audio_streams[0],
    )


def _ffmpeg_output(*arguments: str) -> bytes:
    executable = shutil.which("ffmpeg")
    assert executable is not None
    return subprocess.run(
        [executable, "-v", "error", *arguments],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout


def _packet_hashes(path: Path | HostPath, stream: MediaStream) -> tuple[str, ...]:
    # Streamcopy into framehash hashes compressed packet payloads, not decoded PCM.
    output = _ffmpeg_output(
        "-i",
        str(path),
        "-map",
        f"0:{stream.index}",
        "-c",
        "copy",
        "-f",
        "framehash",
        "-",
    )
    hashes = tuple(
        line.rsplit(",", 1)[1].strip()
        for line in output.decode().splitlines()
        if line and not line.startswith("#")
    )
    assert hashes
    return hashes


def _frequency(path: Path | HostPath, stream: MediaStream) -> float:
    output = _ffmpeg_output(
        "-i",
        str(path),
        "-map",
        f"0:{stream.index}",
        "-t",
        "1",
        "-ar",
        "8000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        "-f",
        "s16le",
        "-",
    )
    samples = tuple(int(value) for (value,) in struct.iter_unpack("<h", output))
    assert len(samples) > 7000
    crossings = sum(left <= 0 < right for left, right in pairwise(samples))
    return crossings * 8000 / len(samples)


def _assert_selected_audio(observed: MediaInspection, profile: DeviceProfile) -> None:
    assert len(observed.video_streams) == 1
    assert len(observed.audio_streams) == 2
    assert compatible_video(observed, profile)
    assert [
        next(tag.value for tag in audio.tags if tag.name == "language")
        for audio in observed.audio_streams
    ] == ["spa", "eng"]
    assert [audio.default for audio in observed.audio_streams] == [True, False]
    assert all(
        (audio.codec, audio.codec_tag, audio.profile) == ("aac", "mp4a", "LC")
        for audio in observed.audio_streams
    )
    for stream, frequency in zip(observed.audio_streams, (880, 440), strict=True):
        assert _frequency(observed.source, stream) == pytest.approx(frequency, abs=5)


@pytest.mark.parametrize(
    "reencode,metadata", ((False, False), (False, True), (True, True))
)
def test_distinct_audio_streams_survive_copy_metadata_and_reencoding(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    profile: DeviceProfile,
    reencode: bool,
    metadata: bool,
) -> None:
    path = _two_audio_source(tmp_path, video, ffmpeg)
    selection = _selection(path)
    source_hashes = tuple(
        _packet_hashes(path, audio) for audio in selection.audio_streams
    )
    assert source_hashes[0] != source_hashes[1]
    with MediaTranscoder().prepare(
        HostPath(path),
        profile,
        TranscodeSettings(retranscode_lossy=reencode),
        checkpoint=lambda: None,
        stream_selection=selection,
        metadata=Track(
            1, "Both editions", "Artist", "Album", 3000, media_types=(MediaType.VIDEO,)
        )
        if metadata
        else None,
        rockbox_metadata=metadata,
    ) as prepared:
        _assert_selected_audio(prepared.inspection, profile)
        result_hashes = tuple(
            _packet_hashes(prepared.source, audio)
            for audio in prepared.inspection.audio_streams
        )
        if reencode:
            assert all(
                output != original
                for output, original in zip(result_hashes, source_hashes, strict=True)
            )
        else:
            assert result_hashes == source_hashes
        if metadata:
            assert {tag.name: tag.value for tag in prepared.inspection.tags}[
                "title"
            ] == "Both editions"
        assert not prepared.warnings


def test_unsupported_alternate_codec_does_not_reencode_compatible_primary(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    profile: DeviceProfile,
) -> None:
    path = _two_audio_source(tmp_path, video, ffmpeg, mixed_codecs=True)
    selection = _selection(path)
    assert selection.audio is not None and selection.audio.codec == "aac"
    assert selection.alternate_audio is not None
    assert selection.alternate_audio.codec == "pcm_s16le"
    primary_hashes = _packet_hashes(path, selection.audio)
    with MediaTranscoder().prepare(
        HostPath(path),
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
        stream_selection=selection,
    ) as prepared:
        _assert_selected_audio(prepared.inspection, profile)
        assert (
            _packet_hashes(prepared.source, prepared.inspection.audio_streams[0])
            == primary_hashes
        )


def test_dual_audio_sound_check_measures_only_primary_audio(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    profile: DeviceProfile,
) -> None:
    original = _two_audio_source(tmp_path, video, ffmpeg)
    path = tmp_path / "different-audio-levels.mov"
    ffmpeg(
        "-i",
        str(original),
        "-map",
        "0",
        "-c",
        "copy",
        "-c:a:0",
        "aac",
        "-b:a:0",
        "96k",
        "-filter:a:0",
        "volume=0.1",
        str(path),
    )
    choice = _selection(path)
    measured: list[float] = []
    for audio in choice.audio_streams:
        with MediaTranscoder().prepare(
            HostPath(path),
            profile,
            TranscodeSettings(),
            checkpoint=lambda: None,
            stream_selection=MediaStreamSelection(choice.video, audio),
            compute_sound_check=True,
        ) as prepared:
            assert prepared.normalization_gain_db is not None
            measured.append(prepared.normalization_gain_db)
    primary_gain, alternate_gain = measured
    assert alternate_gain > primary_gain + 15
    with MediaTranscoder().prepare(
        HostPath(path),
        profile,
        TranscodeSettings(),
        checkpoint=lambda: None,
        stream_selection=choice,
        compute_sound_check=True,
    ) as prepared:
        _assert_selected_audio(prepared.inspection, profile)
        assert prepared.normalization_gain_db == pytest.approx(primary_gain, abs=0.1)
        assert prepared.normalization_gain_db != pytest.approx(alternate_gain, abs=0.1)


def test_saved_dual_audio_choice_survives_virtual_sync_without_repeat_replacement(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
) -> None:
    path = _two_audio_source(tmp_path, video, ffmpeg)
    choice = _selection(path)
    host = host_library(path)
    host = replace(
        host,
        snapshot=replace(
            host.snapshot,
            tracks=(replace(host.snapshot.tracks[0], media_types=(MediaType.VIDEO,)),),
        ),
        sources=(replace(host.sources[0], kind=HostMediaFileKind.VIDEO),),
    )
    file = AtomicHostFile(tmp_path / "choices.json")
    model = SyncSelection(stream_preferences=MediaStreamPreferences(file))
    device = build_device(tmp_path)
    try:
        request = _request(device, host)
        model.reset(host, request.plan)
        model.set_stream_selection(100, choice)
        model.set_tracks_checked((100,), True)
        result = SyncExecutor(device.coordinator).execute(
            replace(request, plan=model.selected_plan), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.helper is not None
        receipt = next(
            entry
            for entry in result.helper.tracks
            if entry.sync and entry.sync.host_path_hint == str(path)
        )
        assert receipt.sync is not None
        assert receipt.sync.stream_selection_sha256 == selection_digest(choice)
        saved_path = device.root / str(receipt.path)
        output = MediaInspector().inspect(HostPath(saved_path), checkpoint=lambda: None)
        _assert_selected_audio(output, result.active.profile)
        for selected, saved in zip(
            choice.audio_streams, output.audio_streams, strict=True
        ):
            assert _packet_hashes(path, selected) == _packet_hashes(saved_path, saved)
        original_bytes = saved_path.read_bytes()
        restarted = SyncSelection(stream_preferences=MediaStreamPreferences(file))
        restarted.reset(
            host, prepare_sync_plan(host, result.helper, result.active.library)
        )
        (retained,) = restarted.selected_plan.items
        assert retained.action is SyncPlanAction.UNCHANGED
        assert retained.stream_selection == choice
        assert restarted.selected_plan.change_count == 0
        assert saved_path.read_bytes() == original_bytes
    finally:
        device.coordinator.close()
