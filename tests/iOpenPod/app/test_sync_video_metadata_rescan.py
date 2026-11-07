"""Retained video tag edits preserve explicit stream choices and Sync evidence."""

import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import NoReturn

import pytest
from PySide6.QtCore import Qt
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_media_lyrics import media_payload
from tests.iOpenPod.app.test_sync_execution import (
    _request,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_sync_stream_selection import host_library
from tests.iOpenPod.app.test_video_preparation import (
    _FFmpeg,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_video_preparation import ffmpeg as ffmpeg
from tests.iPodDB.library.test_write_artwork import BLUE

from iOpenPod.app.host_media_fingerprint import FpcalcFingerprinter
from iOpenPod.app.host_media_library import HostMediaFileKind
from iOpenPod.app.library_sync_helper import LIBRARY_SYNC_HELPER_PATH
from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.media import MediaInspector
from iOpenPod.app.media.models import StreamKind
from iOpenPod.app.media.stream_selection import MediaStreamSelection
from iOpenPod.app.media.stream_selection_codec import selection_digest
from iOpenPod.app.media.transcoding import MediaTranscoder
from iOpenPod.app.media_stream_preferences import MediaStreamPreferences
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    prepare_sync_plan,
    with_stream_selection,
)
from iPodDB.library import MediaType
from storage import AtomicHostFile, HostPath

pytestmark = pytest.mark.skipif(
    shutil.which("fpcalc") is None,
    reason="Real Chromaprint evidence is required",
)


class _NoMediaPreparation(MediaTranscoder):
    def preflight(self, *, checkpoint: Callable[[], None]) -> NoReturn:
        pytest.fail("A retained video artwork edit must not prepare replacement media")


@pytest.mark.parametrize("rockbox", [False, True])
def test_artwork_edit_preserves_video_match_after_fresh_scan(
    tmp_path: Path, ffmpeg: _FFmpeg, rockbox: bool
) -> None:
    source = tmp_path / "episode.mkv"
    subtitles = tmp_path / "dialogue.srt"
    subtitles.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nKeep this selected subtitle.\n",
        encoding="utf-8",
    )
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=160x120:r=25",
        "-f",
        "lavfi",
        "-i",
        "anoisesrc=color=pink:seed=11:sample_rate=44100",
        "-i",
        str(subtitles),
        "-t",
        "15",
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-map",
        "2:s",
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-level:v",
        "3.0",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "flac",
        "-c:s",
        "srt",
        str(source),
    )
    fingerprinter = FpcalcFingerprinter()
    acoustic = fingerprinter.fingerprint(HostPath(source), checkpoint=lambda: None)
    original_host = host_library(source)
    host = replace(
        original_host,
        snapshot=replace(
            original_host.snapshot,
            tracks=(
                replace(
                    original_host.snapshot.tracks[0],
                    length_ms=15000,
                    media_types=(MediaType.VIDEO,),
                ),
            ),
        ),
        sources=(
            replace(
                original_host.sources[0],
                kind=HostMediaFileKind.VIDEO,
                acoustic_fingerprint=acoustic,
            ),
        ),
    )
    inspected = MediaInspector().scan_metadata(
        HostPath(source), checkpoint=lambda: None
    )
    choice = MediaStreamSelection(
        inspected.video_streams[0],
        inspected.audio_streams[0],
        tuple(s for s in inspected.streams if s.kind is StreamKind.SUBTITLE),
    )
    assert choice.subtitles
    preferences = AtomicHostFile(tmp_path / "choices.json")
    selection = SyncSelection(stream_preferences=MediaStreamPreferences(preferences))
    device = build_device(tmp_path)
    try:
        request = _request(device, host)
        selection.reset(host, request.plan)
        selection.set_stream_selection(100, choice)
        selection.set_tracks_checked((100,), True)
        request = replace(request, plan=selection.selected_plan)
        initial = SyncExecutor(device.coordinator).execute(
            request, lambda _: None, Event()
        )
        assert initial.status is SyncExecutionStatus.SUCCESS, initial.issues
        assert initial.active is not None and initial.helper is not None
        track = next(t for t in initial.active.library.tracks if t.title == "Edition")
        receipt = next(t for t in initial.helper.tracks if t.track_id == track.track_id)
        assert receipt.sync is not None and receipt.sync.was_transcoded
        assert receipt.sync.stream_selection_sha256 == selection_digest(choice)
        output = device.root / track.metadata.location
        before = output.read_bytes()
        output_acoustic = fingerprinter.fingerprint(
            HostPath(output), checkpoint=lambda: None
        )
        # This is the historical failure: stale helper facts would make a fresh
        # scan replace Host acoustic evidence with unequal encoded-output evidence.
        assert output_acoustic != acoustic
        output_info = MediaInspector().scan_metadata(
            HostPath(output), checkpoint=lambda: None
        )
        assert output_info.video_streams and output_info.audio_streams
        assert any(stream.codec_tag == "tx3g" for stream in output_info.streams)
        old_facts = output.stat().st_size, output.stat().st_mtime_ns
        helper_path = device.root / str(LIBRARY_SYNC_HELPER_PATH)
        helper_before = helper_path.read_bytes()
        desired = replace(
            initial.active.library,
            tracks=tuple(
                replace(t, artwork_id=BLUE.artwork_id)
                if t.track_id == track.track_id
                else t
                for t in initial.active.library.tracks
            ),
        )
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                desired,
                initial.active,
                1,
                1,
                artwork=(BLUE,),
                rockbox_metadata=rockbox,
            ),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        assert review.plan is not None and not review.plan.required_media
        assert not review.plan.draft.replace_media
        assert review.plan.required_lyrics == ((track.track_id,) if rockbox else ())
        # Device.save retains recovery for transaction tests. An ordinary editor
        # save must use the default contract that updates helper facts atomically.
        saved = device.coordinator.save_library(
            review, initial.active, lambda _: None, Event()
        )
        assert saved.active is not None, saved.issues
        after = output.read_bytes()
        assert (
            old_facts != (output.stat().st_size, output.stat().st_mtime_ns)
        ) is rockbox
        assert (before != after) is rockbox
        assert media_payload(after, ".m4v") == media_payload(before, ".m4v")
        scanned = device.coordinator.scan_ipod_media(
            saved.active, lambda _: None, Event()
        )
        retained = next(t for t in scanned.tracks if t.track_id == track.track_id)
        assert retained.sync == receipt.sync
        assert (helper_path.read_bytes() != helper_before) is rockbox
        assert retained.acoustic_fingerprint == receipt.acoustic_fingerprint == acoustic
        assert retained.path == receipt.path
        assert retained.size_bytes == output.stat().st_size

        comparison = prepare_sync_plan(host, scanned, saved.active.library)
        restarted = SyncSelection(
            stream_preferences=MediaStreamPreferences(preferences)
        )
        restarted.reset(host, comparison)
        assert restarted.stream_selection(100) == choice
        assert restarted.track_check_state(100) is Qt.CheckState.Checked
        item = next(
            t for t in restarted.selected_plan.items if t.host_path == str(source)
        )
        assert item.ipod_id == track.track_id
        assert item.applied_stream_selection_sha256 == selection_digest(choice)
        assert item.action is SyncPlanAction.UNCHANGED
        assert not item.audio_payload_changed
        assert not item.stream_selection_changed
        assert with_stream_selection(item, choice).action is SyncPlanAction.UNCHANGED
        repeated = SyncExecutor(
            device.coordinator, transcoder=_NoMediaPreparation()
        ).execute(
            replace(
                request,
                plan=SyncPlan((item,)),
                source=saved.active,
                ipod=scanned,
            ),
            lambda _: None,
            Event(),
        )
        assert repeated.status is SyncExecutionStatus.SUCCESS, repeated.issues
        assert output.read_bytes() == after
    finally:
        device.coordinator.close()
