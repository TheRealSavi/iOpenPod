"""Stream intent is reviewed, validated, and passed to actual Sync preparation."""

from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import Qt
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_sync_execution import (
    _request,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_video_preparation import (
    _FFmpeg,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_video_preparation import ffmpeg as ffmpeg
from tests.iOpenPod.app.test_video_preparation import video as video

from iOpenPod.app.host_media_library import (
    HostMediaCacheStats,
    HostMediaFileKind,
    HostMediaLibrary,
    HostMediaSource,
)
from iOpenPod.app.media import MediaInspector
from iOpenPod.app.media.stream_selection import MediaStreamSelection
from iOpenPod.app.models.sync_plan_table_model import SyncPlanColumn, SyncPlanTableModel
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.sync_execution import (
    SyncExecutionStatus,
    SyncExecutor,
    _validate_plan,  # pyright: ignore[reportPrivateUsage]
)
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
    prepare_sync_plan,
    with_stream_selection,
)
from iPodDB.library import LibrarySnapshot, Track, TrackMetadata
from storage import HostPath
from storage.host_input import LocalHostFile


def host_library(path: Path) -> HostMediaLibrary:
    facts = LocalHostFile.observe(HostPath(path))
    return HostMediaLibrary(
        LibrarySnapshot(
            tracks=(
                Track(
                    100,
                    "Edition",
                    "Artist",
                    "Album",
                    3000,
                    metadata=TrackMetadata(location=str(path)),
                ),
            )
        ),
        (
            HostMediaSource(
                facts.path,
                HostMediaFileKind.AUDIO,
                facts.size_bytes,
                facts.modified_ns,
                "100,2,3",
            ),
        ),
        (),
        HostMediaCacheStats(),
    )


def test_choices_force_reviewed_replacement_and_can_be_restored(video: Path) -> None:
    host = host_library(video)
    observed = MediaInspector().scan_metadata(HostPath(video), checkpoint=lambda: None)
    choice = MediaStreamSelection(observed.video_streams[0], None)
    original = SyncPlanItem(
        SyncPlanAction.UNCHANGED,
        SyncPlanMediaKind.TRACK,
        SyncPlanBasis.HOST_FACTS_MATCH,
        "Edition",
        host_path=str(video),
        ipod_id=7,
        ipod_path="iPod_Control/Music/F00/AAAA.m4v",
    )
    comparison = SyncPlan((original,))
    selection = SyncSelection()
    selection.reset(host, comparison)
    selection.set_stream_selection(100, choice)
    (item,) = selection.review_plan.items
    assert item.action is SyncPlanAction.UPDATE and item.audio_payload_changed
    assert item.stream_selection == choice
    assert selection.comparison == comparison
    model = SyncPlanTableModel()
    model.replace_plan(selection.review_plan, selection)
    assert "Selected streams" in str(model.data(model.index(0, SyncPlanColumn.REASON)))
    selection.set_review_items_checked((item,), False)
    excluded = selection.selected_plan
    assert excluded.items == ()
    assert selection.track_check_state(100) is Qt.CheckState.Checked
    selection.set_tracks_checked((100,), False)
    (removal,) = selection.review_plan.items
    assert removal.action is SyncPlanAction.REMOVE and removal.stream_selection is None
    selection.set_tracks_checked((100,), True)
    assert selection.selected_plan.items[0].stream_selection == choice
    selection.set_stream_selection(100, None)
    assert selection.selected_plan.items == (original,)
    selection.set_stream_selection(100, choice)
    selection.reset(host, comparison)
    assert selection.stream_selection(100) == choice


def test_stream_choices_do_not_resolve_ambiguous_correlations(video: Path) -> None:
    host = host_library(video)
    observed = MediaInspector().scan_metadata(HostPath(video), checkpoint=lambda: None)
    selection = SyncSelection()
    original = SyncPlanItem(
        SyncPlanAction.ATTENTION,
        SyncPlanMediaKind.TRACK,
        SyncPlanBasis.AMBIGUOUS_IDENTITY,
        "Edition",
        host_path=str(video),
    )
    selection.reset(host, SyncPlan((original,)))
    selection.set_tracks_checked((100,), True)
    selection.set_stream_selection(
        100, MediaStreamSelection(observed.video_streams[0], None)
    )
    assert selection.selected_plan.items == (original,)


def test_selected_audio_reaches_committed_device_file(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
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
        "-metadata:s:a:0",
        "language=eng",
        "-metadata:s:a:1",
        "language=spa",
        str(path),
    )
    observed = MediaInspector().scan_metadata(HostPath(path), checkpoint=lambda: None)
    choice = MediaStreamSelection(None, observed.audio_streams[1])
    device = build_device(tmp_path)
    try:
        request = _request(device, host_library(path))
        item = next(
            item for item in request.plan.items if item.action is SyncPlanAction.ADD
        )
        request = replace(
            request, plan=SyncPlan((with_stream_selection(item, choice),))
        )
        _validate_plan(request)
        forged = replace(
            request, plan=SyncPlan((replace(request.plan.items[0], name="Forged"),))
        )
        with pytest.raises(ValueError, match="no longer matches"):
            _validate_plan(forged)
        result = SyncExecutor(device.coordinator).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        track = next(
            track for track in result.active.library.tracks if track.title == "Edition"
        )
        output = MediaInspector().scan_metadata(
            HostPath(device.root / track.metadata.location), checkpoint=lambda: None
        )
        assert len(output.audio_streams) == 1
        assert (
            next(
                tag.value
                for tag in output.audio_streams[0].tags
                if tag.name == "language"
            )
            == "spa"
        )
        assert result.helper is not None
        comparison = prepare_sync_plan(
            request.host, result.helper, result.active.library
        )
        retained = next(
            item for item in comparison.items if item.host_path == str(path)
        )
        assert retained.action is SyncPlanAction.UNCHANGED
        assert (
            with_stream_selection(retained, choice).action is SyncPlanAction.UNCHANGED
        )
        _validate_plan(
            replace(
                request,
                plan=SyncPlan((with_stream_selection(retained, choice),)),
                ipod=result.helper,
                source=result.active,
            )
        )
        replacement = with_stream_selection(
            retained, MediaStreamSelection(None, observed.audio_streams[0])
        )
        next_request = replace(
            request,
            plan=SyncPlan((replacement,)),
            ipod=result.helper,
            source=result.active,
        )
        replaced = SyncExecutor(device.coordinator).execute(
            next_request, lambda _: None, Event()
        )
        assert replaced.status is SyncExecutionStatus.SUCCESS, replaced.issues
        assert replaced.active is not None
        updated = next(
            item
            for item in replaced.active.library.tracks
            if item.track_id == track.track_id
        )
        output = MediaInspector().scan_metadata(
            HostPath(device.root / updated.metadata.location), checkpoint=lambda: None
        )
        assert (
            next(
                tag.value
                for tag in output.audio_streams[0].tags
                if tag.name == "language"
            )
            == "eng"
        )
        assert not (device.root / track.metadata.location).exists()
    finally:
        device.coordinator.close()
