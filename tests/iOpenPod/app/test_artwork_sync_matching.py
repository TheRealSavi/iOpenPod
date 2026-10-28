"""Verified Library retags preserve committed Sync matches without decoding again."""

import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Literal

import pytest
from PySide6.QtCore import Qt
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_media_lyrics import WORDS, media_payload
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
from iOpenPod.app.media.stream_selection import MediaStreamSelection
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    prepare_sync_plan,
    with_stream_selection,
)
from iPodDB.library import MediaType
from storage import DevicePath, FilesystemSession, HostPath

pytestmark = pytest.mark.skipif(
    shutil.which("fpcalc") is None,
    reason="Artwork Sync matching requires fpcalc",
)


@pytest.mark.parametrize(
    ("edit", "rockbox", "model"),
    (
        ("artwork", False, "MB565"),
        ("artwork", True, "MB565"),
        ("tags", True, "MB565"),
        ("lyrics", False, "MB754"),
        ("lyrics", False, "MB565"),
    ),
)
def test_library_edit_keeps_transcoded_video_matched(
    tmp_path: Path,
    ffmpeg: _FFmpeg,
    monkeypatch: pytest.MonkeyPatch,
    edit: Literal["artwork", "tags", "lyrics"],
    rockbox: bool,
    model: str,
) -> None:
    source = tmp_path / "episode.mkv"
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=160x120:r=25",
        "-f",
        "lavfi",
        "-i",
        "anoisesrc=color=pink:seed=11:sample_rate=44100",
        "-t",
        "15",
        "-map",
        "0:v",
        "-map",
        "1:a",
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
        str(source),
    )
    fingerprinter = FpcalcFingerprinter()
    acoustic = fingerprinter.fingerprint(HostPath(source), checkpoint=lambda: None)
    original_host = host_library(source)
    original_track = original_host.snapshot.tracks[0]
    host = replace(
        original_host,
        snapshot=replace(
            original_host.snapshot,
            tracks=(
                replace(
                    original_track,
                    length_ms=15_000,
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
        inspected.video_streams[0], inspected.audio_streams[0]
    )
    device = build_device(tmp_path, model=model)
    try:
        request = _request(device, host)
        item = next(
            item for item in request.plan.items if item.action is SyncPlanAction.ADD
        )
        request = replace(
            request, plan=SyncPlan((with_stream_selection(item, choice),))
        )
        result = SyncExecutor(device.coordinator).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.helper is not None
        track = next(
            item for item in result.active.library.tracks if item.title == "Edition"
        )
        helper_before = next(
            item for item in result.helper.tracks if item.track_id == track.track_id
        )
        assert helper_before.sync is not None
        assert helper_before.sync.stream_selection_sha256 is not None
        assert helper_before.acoustic_fingerprint == acoustic
        output_path = device.root / track.metadata.location
        output_acoustic = fingerprinter.fingerprint(
            HostPath(output_path), checkpoint=lambda: None
        )
        assert output_acoustic != acoustic, (
            "This regression requires unequal Host and transcoded fingerprints."
        )
        media_bytes_before = output_path.read_bytes()
        payload_before = media_payload(media_bytes_before, output_path.suffix)
        selection = SyncSelection()
        before_plan = prepare_sync_plan(host, result.helper, result.active.library)
        selection.reset(host, before_plan)
        assert (
            selection.track_check_state(original_track.track_id)
            is Qt.CheckState.Checked
        )
        old_facts = (output_path.stat().st_size, output_path.stat().st_mtime_ns)
        helper_path = device.root / str(LIBRARY_SYNC_HELPER_PATH)
        helper_bytes_before = helper_path.read_bytes()
        database_path = device.root / "iPod_Control/iTunes/iTunesDB"
        database_bytes_before = database_path.read_bytes()

        decoded: list[DevicePath] = []
        original_fingerprint = FpcalcFingerprinter.fingerprint_device

        def fingerprint_device(
            self: FpcalcFingerprinter,
            session: FilesystemSession,
            source: DevicePath,
            *,
            checkpoint: Callable[[], None],
        ) -> str:
            decoded.append(source)
            return original_fingerprint(self, session, source, checkpoint=checkpoint)

        monkeypatch.setattr(
            FpcalcFingerprinter, "fingerprint_device", fingerprint_device
        )
        edited = (
            replace(track, artwork_id=BLUE.artwork_id)
            if edit == "artwork"
            else replace(track, title="Edited title")
            if edit == "tags"
            else replace(track, metadata=replace(track.metadata, lyrics=WORDS))
        )
        desired = replace(
            result.active.library,
            tracks=tuple(
                edited if item.track_id == track.track_id else item
                for item in result.active.library.tracks
            ),
        )
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                desired,
                result.active,
                1,
                1,
                artwork=(BLUE,) if edit == "artwork" else (),
                rockbox_metadata=rockbox,
            ),
            lambda _: None,
            Event(),
        )
        blocked_lyrics = edit == "lyrics" and model == "MB565"
        if blocked_lyrics:
            # This Classic decoder selects MP4 audio lyrics by filename. Nano
            # retains the existing successful retag/matching coverage above.
            assert output_path.suffix in (".m4v", ".mp4")
            assert review.result.prepared is None
            assert not review.file_changes
            assert any(
                "filename does not select the native MP4 audio lyrics decoder"
                in issue.detail
                for issue in review.result.issues
            ), review.result.issues
            rejected = device.coordinator.save_library(
                review, result.active, lambda _: None, Event()
            )
            assert rejected.active is None
            assert output_path.read_bytes() == media_bytes_before
            assert helper_path.read_bytes() == helper_bytes_before
            assert database_path.read_bytes() == database_bytes_before
            active_after = result.active
        else:
            assert review.result.prepared is not None, review.result.issues
            saved = device.coordinator.save_library(
                review, result.active, lambda _: None, Event()
            )
            assert saved.active is not None, saved.issues
            active_after = saved.active
        new_facts = (output_path.stat().st_size, output_path.stat().st_mtime_ns)
        media_changed = not blocked_lyrics and (rockbox or edit == "lyrics")
        assert (old_facts != new_facts) is media_changed
        if media_changed:
            assert helper_path.read_bytes() != helper_bytes_before
        assert (
            media_payload(output_path.read_bytes(), output_path.suffix)
            == payload_before
        )

        scanned = device.coordinator.scan_ipod_media(
            active_after, lambda _: None, Event()
        )
        after_record = next(
            item for item in scanned.tracks if item.track_id == track.track_id
        )
        assert after_record.sync == helper_before.sync
        assert after_record.acoustic_fingerprint == acoustic
        assert (after_record.size_bytes, after_record.modified_ns) == new_facts
        assert helper_before.path not in decoded
        after_plan = prepare_sync_plan(host, scanned, active_after.library)
        selection.reset(host, after_plan)
        assert (
            selection.track_check_state(original_track.track_id)
            is Qt.CheckState.Checked
        )
        retained = next(
            item for item in after_plan.items if item.host_path == str(source)
        )
        assert retained.ipod_id == track.track_id
        assert retained.action is not SyncPlanAction.ADD
    finally:
        device.coordinator.close()
