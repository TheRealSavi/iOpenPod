"""Retained Track classification changes use Sync without replacing media."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import NoReturn

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.test_sync_execution import (
    _host,  # pyright: ignore[reportPrivateUsage]
    _request,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.host_media_library import HostMediaFileKind
from iOpenPod.app.media.transcoding import MediaTranscoder
from iOpenPod.app.sync_execution import (
    SyncExecutionRequest,
    SyncExecutionStatus,
    SyncExecutor,
)
from iOpenPod.app.sync_plan import SyncPlanAction, prepare_sync_plan
from iOpenPod.app.sync_track_details import track_tag_edit_issues, track_tag_sha256
from iPodDB.library import IPodLibrary, MediaType, Track
from iPodDB.library.video import is_video_track


class _NoMediaPreparation(MediaTranscoder):
    def preflight(self, *, checkpoint: Callable[[], None]) -> NoReturn:
        pytest.fail("Classification updates must not prepare replacement media")


def _seed_classification(device: Device, kinds: tuple[MediaType, ...]) -> Track:
    first, *others = device.active.library.tracks
    seeded = device.save(
        device.prepare(
            replace(
                device.active.library,
                tracks=(replace(first, media_types=kinds, play_count=7), *others),
            )
        )
    )
    assert seeded.active is not None, seeded.issues
    device.coordinator.finalize_sync_success(seeded.active, seeded.recovery_path)
    return device.active.library.tracks[0]


def _metadata_request(
    tmp_path: Path, device: Device, kind: MediaType
) -> SyncExecutionRequest:
    host = _host(tmp_path, "Updated classification")
    incoming = replace(host.snapshot.tracks[0], media_types=(kind,))
    host = replace(
        host,
        snapshot=replace(host.snapshot, tracks=(incoming,)),
        sources=(
            replace(
                host.sources[0],
                kind=HostMediaFileKind.VIDEO
                if is_video_track(incoming)
                else HostMediaFileKind.AUDIO,
            ),
        ),
    )
    request = _request(device, host, update=True)
    prior = request.ipod.tracks[0].sync
    assert prior is not None
    original = device.active.library.tracks[0]
    acoustic = host.sources[0].acoustic_fingerprint
    assert acoustic is not None
    ipod = replace(
        request.ipod,
        tracks=(
            replace(
                request.ipod.tracks[0],
                acoustic_fingerprint=acoustic,
                sync=replace(
                    prior,
                    host_size_bytes=host.sources[0].size_bytes,
                    host_modified_ns=host.sources[0].modified_ns,
                    host_tag_sha256=track_tag_sha256(original),
                    ipod_tag_sha256=track_tag_sha256(original),
                ),
            ),
            *request.ipod.tracks[1:],
        ),
    )
    comparison = prepare_sync_plan(host, ipod, request.source.library)
    return replace(
        request,
        ipod=ipod,
        plan=replace(
            comparison,
            items=tuple(
                item
                for item in comparison.items
                if item.action is not SyncPlanAction.REMOVE
            ),
        ),
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ((MediaType.VIDEO,), MediaType.TV_SHOW),
        ((MediaType.TV_SHOW,), MediaType.VIDEO),
        ((MediaType.TV_SHOW,), MediaType.MUSIC_VIDEO),
        ((MediaType.VIDEO, MediaType.TV_SHOW), MediaType.VIDEO),
        ((MediaType.AUDIO,), MediaType.AUDIOBOOK),
        ((MediaType.AUDIOBOOK,), MediaType.AUDIO),
        ((MediaType.AUDIO,), MediaType.PODCAST),
        ((MediaType.PODCAST,), MediaType.AUDIO),
    ],
)
def test_sync_reclassifies_retained_media_and_records_the_update(
    tmp_path: Path, before: tuple[MediaType, ...], after: MediaType
) -> None:
    device = build_device(tmp_path, model="MB029")
    try:
        original = _seed_classification(device, before)
        media_path = device.root / original.metadata.location
        media_bytes = media_path.read_bytes()
        modified_ns = media_path.stat().st_mtime_ns
        request = _metadata_request(tmp_path, device, after)
        (item,) = request.plan.items
        assert item.action is SyncPlanAction.UPDATE
        assert item.metadata_changed and not item.audio_payload_changed

        result = SyncExecutor(
            device.coordinator, transcoder=_NoMediaPreparation()
        ).execute(request, lambda _: None, Event())

        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.helper is not None
        assert result.completed == (item,)
        reloaded = IPodLibrary(
            (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
        )
        saved = next(
            track
            for track in reloaded.snapshot.tracks
            if track.track_id == original.track_id
        )
        assert saved.media_types == (after,)
        assert saved.title == "Updated classification"
        assert saved.metadata.location == original.metadata.location
        assert saved.play_count == original.play_count
        assert saved.ipod is not None and original.ipod is not None
        assert saved.ipod.db_track_id == original.ipod.db_track_id
        assert media_path.read_bytes() == media_bytes
        assert media_path.stat().st_mtime_ns == modified_ns
        repeated = prepare_sync_plan(request.host, result.helper, result.active.library)
        assert (
            next(
                item.action
                for item in repeated.items
                if item.ipod_id == original.track_id
            )
            is SyncPlanAction.UNCHANGED
        )
    finally:
        device.coordinator.close()


def test_reclassification_does_not_bypass_invalid_metadata(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path, model="MB029")
    try:
        original = _seed_classification(device, (MediaType.VIDEO,))
        request = _metadata_request(tmp_path, device, MediaType.TV_SHOW)
        request = replace(
            request,
            host=replace(
                request.host,
                snapshot=replace(
                    request.host.snapshot,
                    tracks=(replace(request.host.snapshot.tracks[0], year=2**32),),
                ),
            ),
        )
        # Exercise the same per-item preparation boundary as ordinary Sync.
        updates, issues = SyncExecutor(device.coordinator)._prepare_metadata_updates(  # pyright: ignore[reportPrivateUsage]
            request, lambda: None
        )
        assert not updates
        assert any(
            issue.code == "track.invalid_value" and issue.field == "year"
            for issue in issues
        )
        assert not any(issue.field == "media_types" for issue in issues)
        assert device.active.library.tracks[0] == original
    finally:
        device.coordinator.close()


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ((MediaType.VIDEO,), (MediaType.AUDIO,)),
        ((MediaType.AUDIO,), (MediaType.TV_SHOW,)),
        ((MediaType.PDF_BOOK,), (MediaType.AUDIO,)),
        ((MediaType.VIDEO,), (MediaType.VIDEO, MediaType.TV_SHOW)),
        ((MediaType.VIDEO,), ()),
    ],
)
def test_sync_rejects_incompatible_classification(
    before: tuple[MediaType, ...], after: tuple[MediaType, ...]
) -> None:
    original = Track(1, "Retained", "", "", 1000, media_types=before)
    issues = track_tag_edit_issues(original, replace(original, media_types=after))
    assert [(issue.code, issue.field) for issue in issues] == [
        ("track.unsupported_edit", "media_types")
    ]


def test_sync_preserves_unchanged_compound_classification() -> None:
    original = Track(
        1, "Retained", "", "", 1000, media_types=(MediaType.VIDEO, MediaType.TV_SHOW)
    )
    assert not track_tag_edit_issues(original, replace(original, title="Updated"))
