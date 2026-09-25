from pathlib import Path

from PySide6.QtCore import Qt

from iOpenPod.app.host_media_library import (
    HostMediaCacheStats,
    HostMediaFileKind,
    HostMediaLibrary,
    HostMediaSource,
)
from iOpenPod.app.library_sync_helper import (
    IPodImageFingerprint,
    IPodMediaCacheStats,
    IPodMediaLibrary,
    IPodTrackFingerprint,
    SyncDetails,
)
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.sync_plan import (
    SyncPlanAction,
    SyncPlanBasis,
    prepare_sync_plan,
)
from iPodDB.library import (
    LibrarySnapshot,
    Photo,
    PhotoLibrary,
    PhotoRepresentation,
    PhotoRepresentationKind,
    Track,
    TrackMetadata,
)
from storage import DevicePath, HostPath


def _host_track(
    path: Path,
    *,
    track_id: int,
    fingerprint: str | None,
    size: int = 100,
    modified: int = 1_000,
) -> tuple[Track, HostMediaSource]:
    return (
        Track(
            track_id,
            f"Song {track_id}",
            "Artist",
            "Album",
            180_000,
            metadata=TrackMetadata(location=str(path)),
        ),
        HostMediaSource(
            HostPath(path),
            HostMediaFileKind.AUDIO,
            size,
            modified,
            acoustic_fingerprint=fingerprint,
        ),
    )


def _host_photo(
    path: Path,
    *,
    photo_id: int,
    fingerprint: str | None,
    size: int = 200,
    modified: int = 2_000,
) -> tuple[Photo, HostMediaSource]:
    return (
        Photo(
            photo_id,
            representations=(
                PhotoRepresentation(
                    PhotoRepresentationKind.FULL_RESOLUTION,
                    0,
                    str(path),
                    0,
                    size,
                    640,
                    480,
                ),
            ),
        ),
        HostMediaSource(
            HostPath(path),
            HostMediaFileKind.PHOTO,
            size,
            modified,
            content_sha256=fingerprint,
        ),
    )


def _host_library(
    tracks: tuple[Track, ...],
    photos: tuple[Photo, ...],
    sources: tuple[HostMediaSource, ...],
) -> HostMediaLibrary:
    return HostMediaLibrary(
        LibrarySnapshot(
            tracks=tracks,
            photos=PhotoLibrary(photos=photos) if photos else None,
        ),
        sources,
        (),
        HostMediaCacheStats(),
    )


def _ipod_library(
    tracks: tuple[IPodTrackFingerprint, ...],
    images: tuple[IPodImageFingerprint, ...] = (),
) -> IPodMediaLibrary:
    return IPodMediaLibrary(
        tracks,
        images,
        (),
        IPodMediaCacheStats(),
        None,
        False,
    )


def _ipod_track(
    *,
    track_id: int,
    fingerprint: str,
    sync: SyncDetails | None = None,
) -> IPodTrackFingerprint:
    return IPodTrackFingerprint(
        database_track_id=10_000 + track_id,
        track_id=track_id,
        path=DevicePath(f"iPod_Control/Music/F00/track-{track_id}.mp3"),
        size_bytes=90,
        modified_ns=900,
        acoustic_fingerprint=fingerprint,
        sync=sync,
    )


def _ipod_snapshot(*track_ids: int, photo_ids: tuple[int, ...] = ()) -> LibrarySnapshot:
    return LibrarySnapshot(
        tracks=tuple(
            Track(
                track_id,
                f"Song {track_id}",
                "Artist",
                "Album",
                180_000,
                metadata=TrackMetadata(
                    location=f"iPod_Control/Music/F00/track-{track_id}.mp3"
                ),
            )
            for track_id in track_ids
        ),
        photos=(
            PhotoLibrary(
                photos=tuple(
                    Photo(
                        photo_id,
                        representations=(
                            PhotoRepresentation(
                                PhotoRepresentationKind.FULL_RESOLUTION,
                                0,
                                f"Photos/Full Resolution/photo-{photo_id}.jpg",
                                0,
                                200,
                                640,
                                480,
                            ),
                        ),
                    )
                    for photo_id in photo_ids
                )
            )
            if photo_ids
            else None
        ),
    )


def _sync(path: Path, *, size: int = 100, modified: int = 1_000) -> SyncDetails:
    return SyncDetails(
        last_synced_at="2026-09-18T18:00:00Z",
        host_path_hint=str(path),
        host_size_bytes=size,
        host_modified_ns=modified,
        source_format="mp3",
        ipod_format="mp3",
        was_transcoded=False,
    )


def test_plan_classifies_host_only_ipod_only_and_content_matches(
    tmp_path: Path,
) -> None:
    matched_track, matched_source = _host_track(
        tmp_path / "matched.mp3",
        track_id=1,
        fingerprint="1,2,3",
    )
    added_track, added_source = _host_track(
        tmp_path / "added.mp3",
        track_id=2,
        fingerprint="4,5,6",
    )
    plan = prepare_sync_plan(
        _host_library(
            (matched_track, added_track),
            (),
            (matched_source, added_source),
        ),
        _ipod_library(
            (
                _ipod_track(track_id=10, fingerprint="1,2,3"),
                _ipod_track(track_id=30, fingerprint="7,8,9"),
            )
        ),
        _ipod_snapshot(10, 30),
    )

    assert plan.count(SyncPlanAction.ADD) == 1
    assert plan.count(SyncPlanAction.REMOVE) == 1
    assert plan.count(SyncPlanAction.UNCHANGED) == 1
    assert plan.change_count == 2
    assert (
        next(
            item for item in plan.items if item.action is SyncPlanAction.UNCHANGED
        ).basis
        is SyncPlanBasis.CONTENT_MATCH
    )


def test_prior_host_path_correlates_changed_content_as_update(tmp_path: Path) -> None:
    path = tmp_path / "changed.mp3"
    track, source = _host_track(
        path,
        track_id=1,
        fingerprint="4,5,6",
        size=120,
        modified=1_200,
    )
    plan = prepare_sync_plan(
        _host_library((track,), (), (source,)),
        _ipod_library(
            (
                _ipod_track(
                    track_id=10,
                    fingerprint="1,2,3",
                    sync=_sync(path),
                ),
            )
        ),
        _ipod_snapshot(10),
    )

    assert len(plan.items) == 1
    item = plan.items[0]
    assert item.action is SyncPlanAction.UPDATE
    assert item.basis is SyncPlanBasis.HOST_FACTS_CHANGED
    assert item.host_size_changed is True
    assert item.host_modified_changed is True


def test_matching_prior_host_facts_remain_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "unchanged.mp3"
    track, source = _host_track(
        path,
        track_id=1,
        fingerprint="1,2,3",
    )
    plan = prepare_sync_plan(
        _host_library((track,), (), (source,)),
        _ipod_library(
            (
                _ipod_track(
                    track_id=10,
                    fingerprint="1,2,3",
                    sync=_sync(path),
                ),
            )
        ),
        _ipod_snapshot(10),
    )

    assert plan.items[0].action is SyncPlanAction.UNCHANGED
    assert plan.items[0].basis is SyncPlanBasis.HOST_FACTS_MATCH


def test_same_content_at_a_moved_host_path_still_correlates(tmp_path: Path) -> None:
    old_path = tmp_path / "old" / "song.mp3"
    new_path = tmp_path / "new" / "song.mp3"
    track, source = _host_track(
        new_path,
        track_id=1,
        fingerprint="1,2,3",
    )
    plan = prepare_sync_plan(
        _host_library((track,), (), (source,)),
        _ipod_library(
            (
                _ipod_track(
                    track_id=10,
                    fingerprint="1,2,3",
                    sync=_sync(old_path),
                ),
            )
        ),
        _ipod_snapshot(10),
    )

    assert len(plan.items) == 1
    assert plan.items[0].action is SyncPlanAction.UNCHANGED


def test_duplicate_or_missing_identities_need_attention(tmp_path: Path) -> None:
    first, first_source = _host_track(
        tmp_path / "first.mp3",
        track_id=1,
        fingerprint="1,2,3",
    )
    second, second_source = _host_track(
        tmp_path / "second.mp3",
        track_id=2,
        fingerprint="1,2,3",
    )
    missing, missing_source = _host_track(
        tmp_path / "missing.mp3",
        track_id=3,
        fingerprint=None,
    )
    plan = prepare_sync_plan(
        _host_library(
            (first, second, missing),
            (),
            (first_source, second_source, missing_source),
        ),
        _ipod_library((_ipod_track(track_id=10, fingerprint="1,2,3"),)),
        _ipod_snapshot(10, 20),
    )

    assert plan.change_count == 0
    assert plan.attention_count == 5
    assert {item.basis for item in plan.items} == {
        SyncPlanBasis.AMBIGUOUS_IDENTITY,
        SyncPlanBasis.MISSING_IDENTITY,
    }


def test_photos_use_exact_content_identity_and_sync_facts(tmp_path: Path) -> None:
    path = tmp_path / "photo.jpg"
    photo, source = _host_photo(
        path,
        photo_id=1,
        fingerprint="a" * 64,
        modified=2_001,
    )
    image = IPodImageFingerprint(
        image_id=91,
        path=DevicePath("Photos/Full Resolution/photo-91.jpg"),
        size_bytes=200,
        modified_ns=2_000,
        content_sha256="a" * 64,
        sync=_sync(path, size=200, modified=2_000),
    )

    plan = prepare_sync_plan(
        _host_library((), (photo,), (source,)),
        _ipod_library((), (image,)),
        _ipod_snapshot(photo_ids=(91,)),
    )

    assert len(plan.items) == 1
    assert plan.items[0].action is SyncPlanAction.UPDATE
    assert plan.items[0].host_modified_changed is True
    assert plan.items[0].host_size_changed is False


def test_unchanged_file_facts_with_conflicting_content_need_attention(
    tmp_path: Path,
) -> None:
    path = tmp_path / "contradiction.mp3"
    track, source = _host_track(
        path,
        track_id=1,
        fingerprint="4,5,6",
    )
    plan = prepare_sync_plan(
        _host_library((track,), (), (source,)),
        _ipod_library(
            (
                _ipod_track(
                    track_id=10,
                    fingerprint="1,2,3",
                    sync=_sync(path),
                ),
            )
        ),
        _ipod_snapshot(10),
    )

    assert plan.items[0].action is SyncPlanAction.ATTENTION
    assert plan.items[0].basis is SyncPlanBasis.CONFLICTING_IDENTITY


def test_sync_selection_defaults_to_correlated_host_media_and_opt_in_removals(
    tmp_path: Path,
) -> None:
    matched, matched_source = _host_track(
        tmp_path / "matched.mp3",
        track_id=1,
        fingerprint="1,2,3",
    )
    host_only, host_only_source = _host_track(
        tmp_path / "host-only.mp3",
        track_id=2,
        fingerprint="4,5,6",
    )
    library = _host_library(
        (matched, host_only),
        (),
        (matched_source, host_only_source),
    )
    comparison = prepare_sync_plan(
        library,
        _ipod_library(
            (
                _ipod_track(track_id=10, fingerprint="1,2,3"),
                _ipod_track(track_id=30, fingerprint="7,8,9"),
            )
        ),
        _ipod_snapshot(10, 30),
    )
    selection = SyncSelection()

    selection.reset(library, comparison)

    assert selection.track_check_state(1) is Qt.CheckState.Checked
    assert selection.track_check_state(2) is Qt.CheckState.Unchecked
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 0
    assert selection.selected_plan.count(SyncPlanAction.REMOVE) == 0

    assert selection.set_tracks_checked((2,), True)
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 1
    assert selection.set_tracks_checked((1,), False)
    deselection = next(
        item
        for item in selection.selected_plan.items
        if item.basis is SyncPlanBasis.USER_DESELECTED
    )
    assert deselection.action is SyncPlanAction.REMOVE

    candidate = selection.potential_removals[0]
    assert selection.removal_check_state(candidate) is Qt.CheckState.Unchecked
    assert selection.set_removal_checked(candidate, True)
    assert selection.selected_plan.count(SyncPlanAction.REMOVE) == 2
