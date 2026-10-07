"""Duplicate choices cross the real Library verification and Storage transaction."""

import hashlib
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from tests.iOpenPod.app.services.test_library_resources import Device, build_device

# Reuse the execution fixtures while keeping their test-only API private.
from tests.iOpenPod.app.test_sync_execution import (
    _AvailableTools,  # pyright: ignore[reportPrivateUsage]
    _Executor,  # pyright: ignore[reportPrivateUsage]
    _host,  # pyright: ignore[reportPrivateUsage]
    _ipod,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.host_media_library import (
    HostArtworkKind,
    HostMediaArtworkSource,
    HostMediaLibrary,
)
from iOpenPod.app.library_sync_helper import (
    LIBRARY_SYNC_HELPER_PATH,
    IPodMediaLibrary,
    SyncDetails,
)
from iOpenPod.app.library_write import WriteProgress
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.sync_execution import (
    SyncExecutionRequest,
    SyncExecutionStatus,
    SyncExecutor,
    preview_playlist_sync,
)
from iOpenPod.app.sync_plan import (
    SyncDuplicatePair,
    SyncDuplicateResolution,
    SyncPlanAction,
    SyncPlanBasis,
    prepare_sync_plan,
)
from iPodDB.library import Playlist, playlist_entries
from storage import HostPath
from storage.host_input import LocalHostFile


def _duplicates(
    device: Device, tmp_path: Path, *, hosts: int = 1
) -> tuple[HostMediaLibrary, IPodMediaLibrary, SyncSelection]:
    snapshot = replace(
        device.active.library,
        tracks=tuple(
            replace(track, artwork_id=0) for track in device.active.library.tracks
        ),
    )
    saved = device.coordinator.save_library(
        device.prepare(snapshot), device.active, lambda _: None, Event()
    )
    assert saved.active is not None, saved.issues
    host = _host(tmp_path, *(f"Host copy {index}" for index in range(hosts)))
    original = device.active.library.tracks[0]
    # Retain semantic metadata so even a relationship-only Update is exercised.
    host = replace(
        host,
        snapshot=replace(
            host.snapshot,
            tracks=tuple(
                replace(
                    original,
                    track_id=track.track_id,
                    ipod=None,
                    metadata=replace(
                        original.metadata, location=track.metadata.location
                    ),
                )
                for track in host.snapshot.tracks
            ),
        ),
        sources=tuple(
            replace(source, acoustic_fingerprint="1,2,3") for source in host.sources
        ),
    )
    ipod = _ipod(device)
    ipod = replace(
        ipod,
        tracks=tuple(
            replace(track, acoustic_fingerprint="1,2,3") for track in ipod.tracks
        ),
    )
    selection = SyncSelection()
    selection.reset(host, prepare_sync_plan(host, ipod, device.active.library))
    return host, ipod, selection


@pytest.mark.parametrize("shared_media", [False, True])
@pytest.mark.parametrize("prior_claims", [False, True])
def test_explicit_match_alone_persists_for_one_identity_and_preserves_media(
    tmp_path: Path, shared_media: bool, prior_claims: bool
) -> None:
    device = build_device(tmp_path, shared_media=shared_media)
    try:
        host, ipod, selection = _duplicates(device, tmp_path)
        if prior_claims:
            source = host.sources[0]
            prior_details = SyncDetails(
                "2026-01-01T00:00:00+00:00",
                str(source.path),
                source.size_bytes,
                source.modified_ns,
                "m4a",
                "m4a",
                False,
            )
            ipod = replace(
                ipod, tracks=tuple(replace(t, sync=prior_details) for t in ipod.tracks)
            )
            selection.reset(host, prepare_sync_plan(host, ipod, device.active.library))
        originals = device.active.library.tracks
        chosen = originals[0]
        payloads = {
            track.metadata.location: (
                device.root / track.metadata.location
            ).read_bytes()
            for track in originals
        }
        group = selection.comparison.duplicate_groups[0]
        selection.set_duplicate_resolution(
            SyncDuplicateResolution(
                group.group_id,
                pairs=(SyncDuplicatePair(str(host.sources[0].path), chosen.track_id),),
            )
        )
        plan = selection.selected_plan
        assert plan.change_count == 1
        item = next(
            item for item in plan.items if item.basis is SyncPlanBasis.USER_MATCH
        )
        assert not item.audio_payload_changed
        assert not item.metadata_changed
        assert not item.artwork_changed
        result = SyncExecutor(device.coordinator).execute(
            SyncExecutionRequest(plan, host, ipod, device.active, 1, 1),
            lambda _: None,
            Event(),
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.helper is not None
        assert result.completed == (item,)
        assert result.active.library.tracks == originals
        for path, data in payloads.items():
            assert (device.root / path).read_bytes() == data
        synced = {track.track_id: track.sync for track in result.helper.tracks}
        details = synced[chosen.track_id]
        assert details is not None
        assert details.host_path_hint == str(host.sources[0].path)
        assert all(
            (value is not None and value.host_path_hint == "")
            if prior_claims
            else value is None
            for key, value in synced.items()
            if key != chosen.track_id
        )
        reloaded = device.coordinator.scan_ipod_media(
            result.active, lambda _: None, Event()
        )
        assert reloaded.cache.fingerprinted == 0
        repeated = prepare_sync_plan(host, reloaded, result.active.library)
        pair = next(item for item in repeated.items if item.host_path)
        assert pair.ipod_id == chosen.track_id
        assert pair.action is SyncPlanAction.UNCHANGED
        # The optional extra copy is still present and never auto-removed.
        assert len(result.active.library.tracks) == len(originals)
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("shared_media", [False, True])
def test_deferred_cover_still_persists_match_with_unchanged_library(
    tmp_path: Path, shared_media: bool
) -> None:
    device = build_device(tmp_path, shared_media=shared_media)
    try:
        original = device.active.library.tracks[0]
        host = _host(tmp_path, "Host copy")
        path = tmp_path / "cover.png"
        Image.new("RGB", (180, 180), "blue").save(path)
        observed = LocalHostFile.observe(HostPath(path))
        cover = HostMediaArtworkSource(
            123,
            HostArtworkKind.FOLDER,
            observed.path,
            observed.size_bytes,
            observed.modified_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        host = replace(
            host,
            snapshot=replace(
                host.snapshot,
                tracks=(
                    replace(
                        original,
                        track_id=host.snapshot.tracks[0].track_id,
                        ipod=None,
                        artwork_id=cover.artwork_id,
                        metadata=replace(
                            original.metadata,
                            location=host.snapshot.tracks[0].metadata.location,
                        ),
                    ),
                ),
            ),
            sources=tuple(
                replace(source, acoustic_fingerprint="1,2,3") for source in host.sources
            ),
            artwork_sources=(cover,),
        )
        ipod = _ipod(device)
        ipod = replace(
            ipod,
            tracks=tuple(
                replace(track, acoustic_fingerprint="1,2,3") for track in ipod.tracks
            ),
        )
        selection = SyncSelection()
        selection.reset(host, prepare_sync_plan(host, ipod, device.active.library))
        selection.set_duplicate_resolution(
            SyncDuplicateResolution(
                selection.comparison.duplicate_groups[0].group_id,
                pairs=(
                    SyncDuplicatePair(str(host.sources[0].path), original.track_id),
                ),
            )
        )
        item = next(
            item
            for item in selection.selected_plan.items
            if item.basis is SyncPlanBasis.USER_MATCH
        )
        assert item.artwork_changed
        assert not item.metadata_changed and not item.audio_payload_changed
        next((device.root / "iPod_Control/Artwork").glob("*.ithmb")).unlink()
        database = device.root / "iPod_Control/iTunes/iTunesDB"
        before = database.read_bytes()
        events: list[WriteProgress] = []
        result = SyncExecutor(device.coordinator).execute(
            SyncExecutionRequest(
                selection.selected_plan, host, ipod, device.active, 1, 1
            ),
            events.append,
            Event(),
        )
        assert result.status is SyncExecutionStatus.PARTIAL, result.issues
        assert any(issue.code == "sync.artwork_deferred" for issue in result.issues)
        assert result.completed == (item,)
        assert result.active is not None and result.helper is not None
        assert result.active.library.tracks[0] == original
        assert database.read_bytes() == before
        assert not any(event.phase == "save.storage_transaction" for event in events)
        recorded = next(
            track
            for track in result.helper.tracks
            if track.track_id == original.track_id
        )
        assert recorded.sync is not None
        assert recorded.sync.host_path_hint == str(host.sources[0].path)
        assert recorded.sync.host_artwork_sha256 == ""
        assert all(
            track.sync is None
            for track in result.helper.tracks
            if track.track_id != original.track_id
        )
        repeated = prepare_sync_plan(host, result.helper, result.active.library)
        next_item = next(item for item in repeated.items if item.host_path)
        assert next_item.ipod_id == original.track_id
        assert next_item.action is SyncPlanAction.UPDATE and next_item.artwork_changed
        assert not next_item.audio_payload_changed
    finally:
        device.coordinator.close()


def test_duplicate_add_and_pair_commit_distinct_album_entries(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    try:
        host, ipod, selection = _duplicates(device, tmp_path, hosts=2)
        host = replace(
            host,
            snapshot=replace(
                host.snapshot,
                tracks=(
                    replace(host.snapshot.tracks[0], album="Original Album"),
                    replace(host.snapshot.tracks[1], album="Greatest Hits"),
                ),
            ),
        )
        selection.reset(host, prepare_sync_plan(host, ipod, device.active.library))
        selected_id = device.active.library.tracks[0].track_id
        selection.set_duplicate_resolution(
            SyncDuplicateResolution(
                selection.comparison.duplicate_groups[0].group_id,
                pairs=(SyncDuplicatePair(str(host.sources[0].path), selected_id),),
                added_host_paths=frozenset({str(host.sources[1].path)}),
            )
        )
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            SyncExecutionRequest(
                selection.selected_plan, host, ipod, device.active, 1, 1
            ),
            lambda _: None,
            Event(),
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.helper is not None
        assert len(result.active.library.tracks) == len(ipod.tracks) + 1
        repeated = prepare_sync_plan(host, result.helper, result.active.library)
        pairs = [item for item in repeated.items if item.host_path]
        assert len(pairs) == 2
        assert all(item.action is SyncPlanAction.UNCHANGED for item in pairs)
        assert len({item.ipod_id for item in pairs}) == 2
        assert {
            track.album
            for track in result.active.library.tracks
            if track.track_id in {item.ipod_id for item in pairs}
        } == {"Original Album", "Greatest Hits"}
    finally:
        device.coordinator.close()


def test_duplicate_removal_is_explicit_and_keeps_shared_file(tmp_path: Path) -> None:
    device = build_device(tmp_path, shared_media=True)
    try:
        host, ipod, selection = _duplicates(device, tmp_path)
        keep, remove = device.active.library.tracks[:2]
        shared = device.root / keep.metadata.location
        payload = shared.read_bytes()
        selection.set_duplicate_resolution(
            SyncDuplicateResolution(
                selection.comparison.duplicate_groups[0].group_id,
                pairs=(SyncDuplicatePair(str(host.sources[0].path), keep.track_id),),
                removed_ipod_ids=frozenset({remove.track_id}),
            )
        )
        result = SyncExecutor(device.coordinator).execute(
            SyncExecutionRequest(
                selection.selected_plan, host, ipod, device.active, 1, 1
            ),
            lambda _: None,
            Event(),
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        assert keep in result.active.library.tracks
        assert all(t.track_id != remove.track_id for t in result.active.library.tracks)
        assert shared.read_bytes() == payload
        assert all(
            remove.track_id not in playlist.track_ids
            for playlist in result.active.library.playlists
        )
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("resolve_skip", [False, True])
def test_unresolved_or_skipped_duplicates_cannot_trim_playlist(
    tmp_path: Path, resolve_skip: bool
) -> None:
    device = build_device(tmp_path)
    try:
        ids = tuple(track.track_id for track in device.active.library.tracks)
        snapshot = replace(
            device.active.library,
            playlists=(
                *device.active.library.playlists,
                Playlist(-1, "Host Playlist", entries=playlist_entries((*ids, ids[0]))),
            ),
        )
        saved = device.coordinator.save_library(
            device.prepare(snapshot), device.active, lambda _: None, Event()
        )
        assert saved.active is not None, saved.issues
        host, ipod, selection = _duplicates(device, tmp_path)
        extra_dir = tmp_path / "extra"
        extra_dir.mkdir()
        extra = _host(extra_dir, "Independent")
        new_track = replace(extra.snapshot.tracks[0], track_id=500)
        host = replace(
            host,
            sources=(*host.sources, *extra.sources),
            snapshot=replace(
                host.snapshot,
                tracks=(*host.snapshot.tracks, new_track),
                playlists=(
                    Playlist(1, "Host Playlist", entries=playlist_entries((100, 500))),
                ),
            ),
        )
        comparison = prepare_sync_plan(host, ipod, device.active.library)
        selection.reset(host, comparison)
        if resolve_skip:
            selection.set_duplicate_resolution(
                SyncDuplicateResolution(comparison.duplicate_groups[0].group_id)
            )
        selection.set_tracks_checked((500,), True)
        request = SyncExecutionRequest(
            selection.selected_plan, host, ipod, device.active, 1, 1
        )
        assert not preview_playlist_sync(request.plan, host, ipod, device.active)
        before = next(
            p for p in device.active.library.playlists if p.name == "Host Playlist"
        )
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        assert (
            next(p for p in result.active.library.playlists if p.name == before.name)
            == before
        )
        assert any(t.title == "Independent" for t in result.active.library.tracks)
        assert any(
            issue.code == "sync.playlist_unresolved_matches" for issue in result.issues
        )
    finally:
        device.coordinator.close()


def test_explicitly_deselected_pair_allows_other_playlist_changes(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        host, ipod, selection = _duplicates(device, tmp_path)
        extra_dir = tmp_path / "extra"
        extra_dir.mkdir()
        extra = _host(extra_dir, "New song")
        host = replace(
            host,
            sources=(*host.sources, *extra.sources),
            snapshot=replace(
                host.snapshot,
                tracks=(
                    *host.snapshot.tracks,
                    replace(extra.snapshot.tracks[0], track_id=500),
                ),
                playlists=(
                    Playlist(1, "Host Playlist", entries=playlist_entries((100, 500))),
                ),
            ),
        )
        selection.reset(host, prepare_sync_plan(host, ipod, device.active.library))
        chosen = ipod.tracks[0].track_id
        selection.set_duplicate_resolution(
            SyncDuplicateResolution(
                selection.comparison.duplicate_groups[0].group_id,
                pairs=(SyncDuplicatePair(str(host.sources[0].path), chosen),),
            )
        )
        selection.set_tracks_checked((100,), False)
        selection.set_tracks_checked((500,), True)
        preview = preview_playlist_sync(
            selection.selected_plan, host, ipod, device.active
        )
        assert len(preview) == 1 and preview[0].added_count == 1
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            SyncExecutionRequest(
                selection.selected_plan, host, ipod, device.active, 1, 1
            ),
            lambda _: None,
            Event(),
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        assert all(track.track_id != chosen for track in result.active.library.tracks)
        added = next(
            track for track in result.active.library.tracks if track.title == "New song"
        )
        assert next(
            p for p in result.active.library.playlists if p.name == "Host Playlist"
        ).track_ids == (added.track_id,)
    finally:
        device.coordinator.close()


def test_review_exclusion_keeps_pairing_but_never_becomes_removal(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        host, ipod, selection = _duplicates(device, tmp_path)
        chosen = device.active.library.tracks[0].track_id
        resolution = SyncDuplicateResolution(
            selection.comparison.duplicate_groups[0].group_id,
            pairs=(SyncDuplicatePair(str(host.sources[0].path), chosen),),
        )
        selection.set_duplicate_resolution(resolution)
        item = next(
            i
            for i in selection.review_plan.items
            if i.basis is SyncPlanBasis.USER_MATCH
        )
        selection.set_review_items_checked((item,), False)
        assert (
            selection.track_check_state(host.snapshot.tracks[0].track_id)
            is Qt.CheckState.Checked
        )
        assert selection.selected_plan.change_count == 0
        assert selection.selected_plan.duplicate_resolutions == (resolution,)
        # New scans clear user choices rather than reusing them against new facts.
        selection.reset(host, prepare_sync_plan(host, ipod, device.active.library))
        assert not selection.duplicate_resolutions
        assert selection.selected_plan.attention_count > 0
    finally:
        device.coordinator.close()


@pytest.mark.parametrize(
    "failure",
    [
        "helper",
        "cancel",
        "helper_cancel",
        "changed_host",
        "changed_device",
        "host_during_prepare",
        "device_during_prepare",
    ],
)
def test_uncommitted_pair_never_records_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    device = build_device(tmp_path)
    try:
        host, ipod, selection = _duplicates(device, tmp_path)
        selection.set_duplicate_resolution(
            SyncDuplicateResolution(
                selection.comparison.duplicate_groups[0].group_id,
                pairs=(
                    SyncDuplicatePair(
                        str(host.sources[0].path), ipod.tracks[0].track_id
                    ),
                ),
            )
        )
        if failure == "helper":

            def fail_helper(*args: object, **kwargs: object) -> IPodMediaLibrary:
                raise OSError("Helper unavailable")

            monkeypatch.setattr(device.coordinator, "publish_sync_success", fail_helper)
        elif failure == "changed_host":
            Path(host.sources[0].path).write_bytes(b"changed after review")
        elif failure == "changed_device":
            (device.root / str(ipod.tracks[0].path)).write_bytes(
                b"changed after review"
            )
        cancelled = Event()
        if failure == "cancel":
            cancelled.set()
        before = (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()

        def progress(event: WriteProgress) -> None:
            if failure == "helper_cancel" and event.phase == "sync.helper":
                cancelled.set()
            if event.phase == "save.source_check":
                if failure == "host_during_prepare":
                    Path(host.sources[0].path).write_bytes(
                        b"changed during preparation"
                    )
                elif failure == "device_during_prepare":
                    (device.root / str(ipod.tracks[0].path)).write_bytes(
                        b"changed during preparation"
                    )

        result = SyncExecutor(device.coordinator).execute(
            SyncExecutionRequest(
                selection.selected_plan, host, ipod, device.active, 1, 1
            ),
            progress,
            cancelled,
        )
        assert result.status is (
            SyncExecutionStatus.CANCELLED
            if failure in {"cancel", "helper_cancel"}
            else SyncExecutionStatus.FAILED
        ), result.issues
        assert not result.completed
        assert not (device.root / str(LIBRARY_SYNC_HELPER_PATH)).exists()
        assert (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes() == before
    finally:
        device.coordinator.close()


def test_execution_rejects_pairing_without_its_reviewed_resolution(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        host, ipod, selection = _duplicates(device, tmp_path)
        selection.set_duplicate_resolution(
            SyncDuplicateResolution(
                selection.comparison.duplicate_groups[0].group_id,
                pairs=(
                    SyncDuplicatePair(
                        str(host.sources[0].path), ipod.tracks[0].track_id
                    ),
                ),
            )
        )
        forged = replace(selection.selected_plan, duplicate_resolutions=())
        before = (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
        result = SyncExecutor(device.coordinator).execute(
            SyncExecutionRequest(forged, host, ipod, device.active, 1, 1),
            lambda _: None,
            Event(),
        )
        assert result.status is SyncExecutionStatus.FAILED
        assert (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes() == before
    finally:
        device.coordinator.close()
