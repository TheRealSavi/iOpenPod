from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from iOpenPod.app.host_media_library import (
    HostArtworkKind,
    HostMediaArtworkSource,
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
    SyncDuplicatePair,
    SyncDuplicateResolution,
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanMediaKind,
    host_path_identity,
    prepare_sync_plan,
    resolve_sync_duplicates,
    select_sync_plan,
)
from iOpenPod.app.sync_track_details import track_tag_sha256
from iPodDB.library import (
    LibrarySnapshot,
    MediaType,
    Photo,
    PhotoLibrary,
    PhotoRepresentation,
    PhotoRepresentationKind,
    Playlist,
    PlaylistEntry,
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


@pytest.mark.parametrize("changed", [False, True])
def test_prior_sync_path_still_matches_when_acoustic_analysis_is_unavailable(
    tmp_path: Path, changed: bool
) -> None:
    path = tmp_path / "silent-video.mp4"
    track, source = _host_track(
        path, track_id=100, fingerprint=None, size=101 if changed else 100
    )
    plan = prepare_sync_plan(
        _host_library((replace(track, title="Song 1"),), (), (source,)),
        _ipod_library((_ipod_track(track_id=1, fingerprint="", sync=_sync(path)),)),
        _ipod_snapshot(1),
    )
    assert len(plan.items) == 1
    assert plan.items[0].action is (
        SyncPlanAction.UPDATE if changed else SyncPlanAction.UNCHANGED
    )
    assert plan.items[0].audio_payload_changed is changed


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
    assert item.basis is SyncPlanBasis.AUDIO_PAYLOAD_CHANGED
    assert item.host_size_changed is True
    assert item.host_modified_changed is True
    assert item.metadata_changed is True
    assert item.audio_payload_changed is True


def test_matching_prior_host_facts_remain_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "unchanged.mp3"
    track, source = _host_track(
        path,
        track_id=1,
        fingerprint="1,2,3",
    )
    plan = prepare_sync_plan(
        _host_library((replace(track, title="Song 10"),), (), (source,)),
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


def test_ipod_tag_edit_updates_with_unchanged_host_file_facts(tmp_path: Path) -> None:
    path = tmp_path / "manually-edited.mp3"
    track, source = _host_track(path, track_id=1, fingerprint="1,2,3")
    baseline = track_tag_sha256(
        replace(_ipod_snapshot(10).tracks[0], title="Original iPod title")
    )
    plan = prepare_sync_plan(
        _host_library((track,), (), (source,)),
        _ipod_library(
            (
                _ipod_track(
                    track_id=10,
                    fingerprint="1,2,3",
                    sync=replace(_sync(path), ipod_tag_sha256=baseline),
                ),
            )
        ),
        _ipod_snapshot(10),
    )

    assert plan.items[0].action is SyncPlanAction.UPDATE
    assert plan.items[0].metadata_changed is True
    assert plan.items[0].host_size_changed is False
    assert plan.items[0].host_modified_changed is False


def test_rechecked_host_tags_can_confirm_an_ipod_edit_is_already_resolved(
    tmp_path: Path,
) -> None:
    path = tmp_path / "already-matching.mp3"
    host_track, source = _host_track(path, track_id=1, fingerprint="1,2,3")
    baseline = track_tag_sha256(
        replace(_ipod_snapshot(10).tracks[0], title="Prior iPod title")
    )
    host = replace(
        _host_library((replace(host_track, title="Song 10"),), (), (source,)),
        rechecked_track_paths=frozenset({str(path)}),
    )
    plan = prepare_sync_plan(
        host,
        _ipod_library(
            (
                _ipod_track(
                    track_id=10,
                    fingerprint="1,2,3",
                    sync=replace(_sync(path), ipod_tag_sha256=baseline),
                ),
            )
        ),
        _ipod_snapshot(10),
    )

    assert plan.items[0].action is SyncPlanAction.UNCHANGED
    assert plan.items[0].metadata_changed is False


def test_changed_file_facts_without_changed_tags_or_artwork_stay_in_sync(
    tmp_path: Path,
) -> None:
    path = tmp_path / "same-tags.mp3"
    host_track, source = _host_track(
        path, track_id=1, fingerprint="1,2,3", size=101, modified=1_001
    )
    plan = prepare_sync_plan(
        _host_library((replace(host_track, title="Song 10"),), (), (source,)),
        _ipod_library(
            (_ipod_track(track_id=10, fingerprint="1,2,3", sync=_sync(path)),)
        ),
        _ipod_snapshot(10),
    )
    assert plan.items[0].action is SyncPlanAction.UNCHANGED
    assert plan.items[0].basis is SyncPlanBasis.TRACK_DETAILS_MATCH


def test_changed_file_facts_update_when_tags_differ(tmp_path: Path) -> None:
    path = tmp_path / "retitled.mp3"
    host_track, source = _host_track(
        path, track_id=1, fingerprint="1,2,3", modified=1_001
    )
    plan = prepare_sync_plan(
        _host_library((replace(host_track, title="New title"),), (), (source,)),
        _ipod_library(
            (_ipod_track(track_id=10, fingerprint="1,2,3", sync=_sync(path)),)
        ),
        _ipod_snapshot(10),
    )
    assert plan.items[0].action is SyncPlanAction.UPDATE
    assert plan.items[0].metadata_changed is True
    assert plan.items[0].artwork_changed is False
    assert plan.items[0].audio_payload_changed is False


@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize(
    "host_fingerprint,ipod_fingerprint", [(None, "1,2,3"), ("1,2,3", ""), (None, "")]
)
def test_missing_acoustic_evidence_falls_back_to_host_file_facts(
    tmp_path: Path, changed: bool, host_fingerprint: str | None, ipod_fingerprint: str
) -> None:
    path = tmp_path / "legacy.mp3"
    track, source = _host_track(
        path,
        track_id=10,
        fingerprint=host_fingerprint,
        modified=1001 if changed else 1000,
    )
    sync = _sync(path)
    plan = prepare_sync_plan(
        _host_library((track,), (), (source,)),
        _ipod_library(
            (_ipod_track(track_id=10, fingerprint=ipod_fingerprint, sync=sync),)
        ),
        _ipod_snapshot(10),
    )
    assert plan.items[0].action is (
        SyncPlanAction.UPDATE if changed else SyncPlanAction.UNCHANGED
    )
    assert plan.items[0].audio_payload_changed is changed


def test_matching_acoustic_fingerprint_accepts_changed_container(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tail-changed.mp3"
    track, source = _host_track(path, track_id=10, fingerprint="1,2,3", modified=1001)
    plan = prepare_sync_plan(
        _host_library((track,), (), (source,)),
        _ipod_library(
            (_ipod_track(track_id=10, fingerprint="1,2,3", sync=_sync(path)),)
        ),
        _ipod_snapshot(10),
    )
    assert plan.items[0].action is SyncPlanAction.UNCHANGED
    assert not plan.items[0].audio_payload_changed
    assert not plan.items[0].metadata_changed


def test_normalized_tag_baselines_remain_in_sync_after_touch(tmp_path: Path) -> None:
    path = tmp_path / "normalized.mp3"
    track, source = _host_track(path, track_id=10, fingerprint="1,2,3", modified=1001)
    host_track = replace(track, title="  Song 10  ")
    ipod = _ipod_snapshot(10)
    sync = replace(
        _sync(path),
        host_tag_sha256=track_tag_sha256(host_track),
        ipod_tag_sha256=track_tag_sha256(ipod.tracks[0]),
    )
    plan = prepare_sync_plan(
        _host_library((host_track,), (), (source,)),
        _ipod_library((_ipod_track(track_id=10, fingerprint="1,2,3", sync=sync),)),
        ipod,
    )
    assert plan.items[0].action is SyncPlanAction.UNCHANGED


def test_changed_folder_artwork_updates_without_media_file_change(
    tmp_path: Path,
) -> None:
    path = tmp_path / "album" / "song.mp3"
    host_track, source = _host_track(path, track_id=1, fingerprint="1,2,3")
    cover = HostMediaArtworkSource(
        20,
        HostArtworkKind.FOLDER,
        HostPath(tmp_path / "album" / "cover.jpg"),
        100,
        1_000,
        "b" * 64,
    )
    host = replace(
        _host_library(
            (replace(host_track, title="Song 10", artwork_id=20),), (), (source,)
        ),
        artwork_sources=(cover,),
    )
    ipod = replace(
        _ipod_snapshot(10),
        tracks=(replace(_ipod_snapshot(10).tracks[0], artwork_id=7),),
    )
    sync = replace(_sync(path), host_artwork_sha256="a" * 64, ipod_artwork_id=7)
    plan = prepare_sync_plan(
        host,
        _ipod_library((_ipod_track(track_id=10, fingerprint="1,2,3", sync=sync),)),
        ipod,
    )
    assert plan.items[0].action is SyncPlanAction.UPDATE
    assert plan.items[0].artwork_changed is True
    assert plan.items[0].host_size_changed is False
    assert plan.items[0].host_modified_changed is False


def test_removed_host_artwork_updates_ipod_cover(tmp_path: Path) -> None:
    path = tmp_path / "no-cover.mp3"
    host_track, source = _host_track(path, track_id=1, fingerprint="1,2,3")
    ipod = replace(
        _ipod_snapshot(10),
        tracks=(replace(_ipod_snapshot(10).tracks[0], artwork_id=7),),
    )
    sync = replace(_sync(path), host_artwork_sha256="a" * 64, ipod_artwork_id=7)
    plan = prepare_sync_plan(
        _host_library((replace(host_track, title="Song 10"),), (), (source,)),
        _ipod_library((_ipod_track(track_id=10, fingerprint="1,2,3", sync=sync),)),
        ipod,
    )
    assert plan.items[0].action is SyncPlanAction.UPDATE
    assert plan.items[0].artwork_changed is True


def test_transformed_rockbox_artwork_does_not_look_changed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rockbox.mp3"
    host_track, source = _host_track(path, track_id=1, fingerprint="1,2,3")
    cover = HostMediaArtworkSource(
        20,
        HostArtworkKind.FOLDER,
        HostPath(tmp_path / "cover.jpg"),
        100,
        1_000,
        "a" * 64,
    )
    host = replace(
        _host_library(
            (replace(host_track, title="Song 10", artwork_id=20),),
            (),
            (source,),
        ),
        artwork_sources=(cover,),
    )
    ipod = replace(
        _ipod_snapshot(10),
        tracks=(replace(_ipod_snapshot(10).tracks[0], artwork_id=7),),
    )
    sync = replace(
        _sync(path),
        host_artwork_sha256="a" * 64,
        ipod_artwork_id=7,
    )

    plan = prepare_sync_plan(
        host,
        _ipod_library((_ipod_track(track_id=10, fingerprint="1,2,3", sync=sync),)),
        ipod,
    )

    assert plan.items[0].action is SyncPlanAction.UNCHANGED
    assert plan.items[0].artwork_changed is False


def test_same_content_at_a_moved_host_path_still_correlates(tmp_path: Path) -> None:
    old_path = tmp_path / "old" / "song.mp3"
    new_path = tmp_path / "new" / "song.mp3"
    track, source = _host_track(
        new_path,
        track_id=1,
        fingerprint="1,2,3",
    )
    plan = prepare_sync_plan(
        _host_library((replace(track, title="Song 10"),), (), (source,)),
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


def test_repeated_host_source_is_one_track_but_keeps_playlist_occurrences(
    tmp_path: Path,
) -> None:
    track, source = _host_track(tmp_path / "one.mp3", track_id=1, fingerprint="1,2,3")
    library = _host_library((track,), (), (source, source))
    library = replace(
        library,
        snapshot=replace(
            library.snapshot,
            playlists=(
                Playlist(
                    1,
                    "Repeated",
                    entries=(PlaylistEntry("first", 1), PlaylistEntry("second", 1)),
                ),
            ),
        ),
    )
    plan = prepare_sync_plan(library, _ipod_library(()), _ipod_snapshot())
    assert plan.count(SyncPlanAction.ADD) == 1
    assert plan.duplicate_groups == ()
    assert library.snapshot.playlists[0].track_ids == (1, 1)


def test_host_copies_in_different_albums_remain_independent_adds(
    tmp_path: Path,
) -> None:
    first, source1 = _host_track(
        tmp_path / "album" / "song.mp3", track_id=1, fingerprint="1,2,3"
    )
    second, source2 = _host_track(
        tmp_path / "hits" / "song.mp3", track_id=2, fingerprint="1,2,3"
    )
    first, second = (
        replace(first, album="Original"),
        replace(second, album="Greatest Hits"),
    )
    plan = prepare_sync_plan(
        _host_library((first, second), (), (source1, source2)),
        _ipod_library(()),
        _ipod_snapshot(),
    )
    (group,) = plan.duplicate_groups
    assert not group.requires_resolution
    assert {member.album for member in group.hosts} == {"Original", "Greatest Hits"}
    assert plan.count(SyncPlanAction.ADD) == 2
    for selected_count in (0, 1, 2):
        selected = select_sync_plan(
            plan,
            selected_host_paths=frozenset(
                host_path_identity(member.host_path)
                for member in group.hosts[:selected_count]
            ),
            selected_ipod_removals=frozenset(),
        )
        assert selected.count(SyncPlanAction.ADD) == selected_count


def test_known_pair_survives_duplicate_group_and_extra_host_stays_optional(
    tmp_path: Path,
) -> None:
    path = tmp_path / "original.mp3"
    first, source1 = _host_track(path, track_id=1, fingerprint="1,2,3")
    second, source2 = _host_track(
        tmp_path / "copy.mp3", track_id=2, fingerprint="1,2,3"
    )
    host = _host_library((first, second), (), (source1, source2))
    plan = prepare_sync_plan(
        host,
        _ipod_library(
            (_ipod_track(track_id=10, fingerprint="1,2,3", sync=_sync(path)),)
        ),
        _ipod_snapshot(10),
    )
    (group,) = plan.duplicate_groups
    assert group.established_pairs == (SyncDuplicatePair(str(path), 10),)
    assert group.pairable_ipod_ids(str(source2.path)) == ()
    selection = SyncSelection()
    selection.reset(host, plan)
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 0
    with pytest.raises(ValueError, match="preserve known pairs"):
        resolve_sync_duplicates(
            plan,
            (
                SyncDuplicateResolution(
                    group.group_id, pairs=(SyncDuplicatePair(str(source2.path), 10),)
                ),
            ),
        )


@pytest.mark.parametrize(("host_count", "ipod_count"), [(2, 1), (1, 2), (2, 2), (3, 2)])
def test_ambiguous_copies_require_individual_pairs_and_never_infer_remaining_pairs(
    tmp_path: Path,
    host_count: int,
    ipod_count: int,
) -> None:
    tracks, sources = zip(
        *(
            _host_track(
                tmp_path / f"host-{index}.mp3", track_id=index + 1, fingerprint="1,2,3"
            )
            for index in range(host_count)
        ),
        strict=True,
    )
    plan = prepare_sync_plan(
        _host_library(tracks, (), sources),
        _ipod_library(
            tuple(
                _ipod_track(track_id=index + 10, fingerprint="1,2,3")
                for index in range(ipod_count)
            )
        ),
        _ipod_snapshot(*range(10, 10 + ipod_count)),
    )
    (group,) = plan.duplicate_groups
    assert group.requires_resolution
    assert plan.change_count == 0
    path = group.hosts[0].host_path
    assert group.pairable_ipod_ids(path) == tuple(range(10, 10 + ipod_count))
    resolution = SyncDuplicateResolution(
        group.group_id, pairs=(SyncDuplicatePair(path, 10),)
    )
    resolved = resolve_sync_duplicates(plan, (resolution,))
    selected = select_sync_plan(
        resolved,
        selected_host_paths=frozenset({host_path_identity(path)}),
        selected_ipod_removals=frozenset(),
    )
    (item,) = selected.items
    assert item.action is SyncPlanAction.UPDATE
    assert item.basis is SyncPlanBasis.USER_MATCH
    assert item.ipod_id == 10
    assert not item.audio_payload_changed
    assert selected.duplicate_resolutions == (resolution,)
    assert resolved.count(SyncPlanAction.UPDATE) == 1
    assert resolved.count(SyncPlanAction.ADD) == host_count - 1
    assert resolved.count(SyncPlanAction.REMOVE) == ipod_count - 1


def test_duplicate_choices_allow_explicit_add_remove_or_skip_everything(
    tmp_path: Path,
) -> None:
    track, source = _host_track(tmp_path / "song.mp3", track_id=1, fingerprint="1,2,3")
    plan = prepare_sync_plan(
        _host_library((track,), (), (source,)),
        _ipod_library(
            (
                _ipod_track(track_id=10, fingerprint="1,2,3"),
                _ipod_track(track_id=11, fingerprint="1,2,3"),
            )
        ),
        _ipod_snapshot(10, 11),
    )
    (group,) = plan.duplicate_groups
    skipped = select_sync_plan(
        plan,
        duplicate_resolutions=(SyncDuplicateResolution(group.group_id),),
        selected_host_paths=frozenset(),
        selected_ipod_removals=frozenset(),
    )
    assert skipped.items == ()
    selected = select_sync_plan(
        plan,
        duplicate_resolutions=(
            SyncDuplicateResolution(
                group.group_id,
                added_host_paths=frozenset({str(source.path)}),
                removed_ipod_ids=frozenset({11}),
            ),
        ),
        selected_host_paths=frozenset({host_path_identity(str(source.path))}),
        selected_ipod_removals=frozenset({(SyncPlanMediaKind.TRACK, 11)}),
    )
    assert selected.count(SyncPlanAction.ADD) == 1
    assert selected.count(SyncPlanAction.REMOVE) == 1
    assert all(item.ipod_id != 10 for item in selected.items)


def test_ipod_only_duplicates_are_retained_and_report_individual_history() -> None:
    snapshot = _ipod_snapshot(10, 11)
    snapshot = replace(
        snapshot,
        tracks=(
            replace(snapshot.tracks[0], play_count=80, rating=100),
            snapshot.tracks[1],
        ),
        playlists=(Playlist(1, "Favorites", entries=(PlaylistEntry("favorite", 10),)),),
    )
    plan = prepare_sync_plan(
        _host_library((), (), ()),
        _ipod_library(
            (
                _ipod_track(track_id=10, fingerprint="1,2,3"),
                _ipod_track(track_id=11, fingerprint="1,2,3"),
            )
        ),
        snapshot,
    )
    (group,) = plan.duplicate_groups
    first, second = group.ipods
    assert (first.play_count, first.rating, first.playlist_names) == (
        80,
        100,
        ("Favorites",),
    )
    assert (second.play_count, second.rating, second.playlist_names) == (0, 0, ())
    assert not group.requires_resolution
    selected = select_sync_plan(
        plan, selected_host_paths=frozenset(), selected_ipod_removals=frozenset()
    )
    assert selected.items == ()


def test_same_title_artist_without_matching_audio_does_not_create_duplicate_group(
    tmp_path: Path,
) -> None:
    first, source1 = _host_track(
        tmp_path / "studio.mp3", track_id=1, fingerprint="4,5,6"
    )
    second, source2 = _host_track(
        tmp_path / "live.mp3", track_id=2, fingerprint="7,8,9"
    )
    second = replace(second, title=first.title)
    plan = prepare_sync_plan(
        _host_library((first, second), (), (source1, source2)),
        _ipod_library(()),
        _ipod_snapshot(),
    )
    assert plan.duplicate_groups == ()
    assert plan.count(SyncPlanAction.ADD) == 2


def test_duplicate_prior_path_choice_retains_changed_payload_intent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "changed.mp3"
    track, source = _host_track(path, track_id=1, fingerprint="7,8,9", size=101)
    plan = prepare_sync_plan(
        _host_library((track,), (), (source,)),
        _ipod_library(
            tuple(
                _ipod_track(track_id=item_id, fingerprint="1,2,3", sync=_sync(path))
                for item_id in (10, 11)
            )
        ),
        _ipod_snapshot(10, 11),
    )
    (group,) = plan.duplicate_groups
    assert group.requires_resolution
    assert group.pairable_ipod_ids(str(path)) == (10, 11)
    selected = select_sync_plan(
        plan,
        selected_host_paths=frozenset({host_path_identity(str(path))}),
        selected_ipod_removals=frozenset(),
        duplicate_resolutions=(
            SyncDuplicateResolution(
                group.group_id, pairs=(SyncDuplicatePair(str(path), 11),)
            ),
        ),
    )
    (item,) = selected.items
    assert item.ipod_id == 11
    assert item.action is SyncPlanAction.UPDATE
    assert item.basis is SyncPlanBasis.USER_MATCH
    assert item.audio_payload_changed


def test_transitive_duplicate_group_does_not_allow_unrelated_pair(
    tmp_path: Path,
) -> None:
    first, source1 = _host_track(
        tmp_path / "first.mp3", track_id=1, fingerprint="1,2,3"
    )
    second, source2 = _host_track(
        tmp_path / "second.mp3", track_id=2, fingerprint="4,5,6"
    )
    plan = prepare_sync_plan(
        _host_library((first, second), (), (source1, source2)),
        _ipod_library(
            (
                _ipod_track(
                    track_id=10, fingerprint="4,5,6", sync=_sync(tmp_path / "first.mp3")
                ),
                _ipod_track(
                    track_id=11, fingerprint="7,8,9", sync=_sync(tmp_path / "first.mp3")
                ),
            )
        ),
        _ipod_snapshot(10, 11),
    )
    (group,) = plan.duplicate_groups
    assert group.pairable_ipod_ids(str(source2.path)) == (10,)
    with pytest.raises(ValueError, match="no matching scan evidence"):
        resolve_sync_duplicates(
            plan,
            (
                SyncDuplicateResolution(
                    group.group_id, pairs=(SyncDuplicatePair(str(source2.path), 11),)
                ),
            ),
        )


def test_explicit_matching_tags_still_commit_association_without_payload_change(
    tmp_path: Path,
) -> None:
    track, source = _host_track(tmp_path / "song.mp3", track_id=1, fingerprint="1,2,3")
    snapshot = _ipod_snapshot(10, 11)
    track = replace(track, title=snapshot.tracks[0].title)
    plan = prepare_sync_plan(
        _host_library((track,), (), (source,)),
        _ipod_library(
            tuple(
                _ipod_track(track_id=item_id, fingerprint="1,2,3")
                for item_id in (10, 11)
            )
        ),
        snapshot,
    )
    (group,) = plan.duplicate_groups
    selected = select_sync_plan(
        plan,
        selected_host_paths=frozenset({host_path_identity(str(source.path))}),
        selected_ipod_removals=frozenset(),
        duplicate_resolutions=(
            SyncDuplicateResolution(
                group.group_id, pairs=(SyncDuplicatePair(str(source.path), 10),)
            ),
        ),
    )
    (item,) = selected.items
    assert item.action is SyncPlanAction.UPDATE
    assert not item.metadata_changed
    assert not item.artwork_changed
    assert not item.audio_payload_changed


def test_photo_duplicate_choices_use_exact_digest_and_retain_extra_photo(
    tmp_path: Path,
) -> None:
    photo, source = _host_photo(
        tmp_path / "photo.jpg", photo_id=1, fingerprint="a" * 64
    )
    ipod = _ipod_library(
        (),
        tuple(
            IPodImageFingerprint(
                image_id=item_id,
                path=DevicePath(f"Photos/Full Resolution/photo-{item_id}.jpg"),
                size_bytes=200,
                modified_ns=2000,
                content_sha256="a" * 64,
            )
            for item_id in (90, 91)
        ),
    )
    plan = prepare_sync_plan(
        _host_library((), (photo,), (source,)),
        ipod,
        _ipod_snapshot(photo_ids=(90, 91)),
        file_tag_policy="rockbox",
    )
    (group,) = plan.duplicate_groups
    assert group.media_kind is SyncPlanMediaKind.PHOTO
    selected = select_sync_plan(
        plan,
        selected_host_paths=frozenset({host_path_identity(str(source.path))}),
        selected_ipod_removals=frozenset(),
        duplicate_resolutions=(
            SyncDuplicateResolution(
                group.group_id, pairs=(SyncDuplicatePair(str(source.path), 91),)
            ),
        ),
    )
    (item,) = selected.items
    assert item.ipod_id == 91
    assert not item.file_tags_changed
    assert item.action is SyncPlanAction.UPDATE


def test_conflicting_photo_facts_are_not_offered_as_pairing_choices(
    tmp_path: Path,
) -> None:
    path = tmp_path / "photo.jpg"
    photo, source = _host_photo(path, photo_id=1, fingerprint="b" * 64)
    prior = replace(_sync(path, size=200, modified=2000), host_content_sha256="a" * 64)
    ipod = _ipod_library(
        (),
        tuple(
            IPodImageFingerprint(
                image_id=item_id,
                path=DevicePath(f"Photos/Full Resolution/photo-{item_id}.jpg"),
                size_bytes=200,
                modified_ns=2000,
                content_sha256="a" * 64,
                sync=prior,
            )
            for item_id in (90, 91)
        ),
    )
    plan = prepare_sync_plan(
        _host_library((), (photo,), (source,)), ipod, _ipod_snapshot(photo_ids=(90, 91))
    )
    (group,) = plan.duplicate_groups
    assert group.requires_resolution
    assert group.pairable_ipod_ids(str(path)) == ()
    with pytest.raises(ValueError, match="Conflicting source facts"):
        resolve_sync_duplicates(
            plan,
            (
                SyncDuplicateResolution(
                    group.group_id, pairs=(SyncDuplicatePair(str(path), 90),)
                ),
            ),
        )


def test_duplicate_group_ids_ignore_scan_order_and_multiple_groups_resolve_independently(
    tmp_path: Path,
) -> None:
    first, source1 = _host_track(
        tmp_path / "first.mp3", track_id=1, fingerprint="1,2,3"
    )
    second, source2 = _host_track(
        tmp_path / "second.mp3", track_id=2, fingerprint="4,5,6"
    )
    records = tuple(
        _ipod_track(track_id=item_id, fingerprint=fingerprint)
        for item_id, fingerprint in (
            (10, "1,2,3"),
            (11, "1,2,3"),
            (20, "4,5,6"),
            (21, "4,5,6"),
        )
    )
    snapshot = _ipod_snapshot(10, 11, 20, 21)
    plan = prepare_sync_plan(
        _host_library((first, second), (), (source1, source2)),
        _ipod_library(records),
        snapshot,
    )
    reordered = prepare_sync_plan(
        _host_library((second, first), (), (source2, source1)),
        _ipod_library(tuple(reversed(records))),
        snapshot,
    )
    assert tuple(g.group_id for g in plan.duplicate_groups) == tuple(
        g.group_id for g in reordered.duplicate_groups
    )
    resolutions = tuple(
        SyncDuplicateResolution(
            group.group_id,
            pairs=(
                SyncDuplicatePair(group.hosts[0].host_path, group.ipods[0].ipod_id),
            ),
        )
        for group in plan.duplicate_groups
    )
    selected = select_sync_plan(
        plan,
        selected_host_paths=frozenset(
            {
                host_path_identity(str(source1.path)),
                host_path_identity(str(source2.path)),
            }
        ),
        selected_ipod_removals=frozenset(),
        duplicate_resolutions=resolutions,
    )
    assert selected.count(SyncPlanAction.UPDATE) == 2
    assert {item.ipod_id for item in selected.items} == {10, 20}


@pytest.mark.parametrize(
    "invalid_choice",
    [
        "reused_host",
        "reused_ipod",
        "foreign_host",
        "foreign_ipod",
        "paired_add",
        "paired_remove",
        "foreign_add",
        "foreign_remove",
        "foreign_group",
        "reused_group",
    ],
)
def test_invalid_duplicate_choices_are_rejected(
    tmp_path: Path, invalid_choice: str
) -> None:
    first, source1 = _host_track(
        tmp_path / "first.mp3", track_id=1, fingerprint="1,2,3"
    )
    second, source2 = _host_track(
        tmp_path / "second.mp3", track_id=2, fingerprint="1,2,3"
    )
    plan = prepare_sync_plan(
        _host_library((first, second), (), (source1, source2)),
        _ipod_library(
            (
                _ipod_track(track_id=10, fingerprint="1,2,3"),
                _ipod_track(track_id=11, fingerprint="1,2,3"),
            )
        ),
        _ipod_snapshot(10, 11),
    )
    (group,) = plan.duplicate_groups
    path1, path2 = str(source1.path), str(source2.path)
    resolution = SyncDuplicateResolution(
        group.group_id, pairs=(SyncDuplicatePair(path1, 10),)
    )
    match invalid_choice:
        case "reused_host":
            resolution = replace(
                resolution, pairs=(*resolution.pairs, SyncDuplicatePair(path1, 11))
            )
        case "reused_ipod":
            resolution = replace(
                resolution, pairs=(*resolution.pairs, SyncDuplicatePair(path2, 10))
            )
        case "foreign_host":
            resolution = replace(
                resolution, pairs=(SyncDuplicatePair(str(tmp_path / "other.mp3"), 10),)
            )
        case "foreign_ipod":
            resolution = replace(resolution, pairs=(SyncDuplicatePair(path1, 999),))
        case "paired_add":
            resolution = replace(resolution, added_host_paths=frozenset({path1}))
        case "paired_remove":
            resolution = replace(resolution, removed_ipod_ids=frozenset({10}))
        case "foreign_add":
            resolution = replace(
                resolution, added_host_paths=frozenset({str(tmp_path / "other.mp3")})
            )
        case "foreign_remove":
            resolution = replace(resolution, removed_ipod_ids=frozenset({999}))
        case "foreign_group":
            resolution = replace(resolution, group_id="missing")
        case "reused_group":
            pass
        case _:
            pytest.fail(f"Unknown invalid duplicate choice: {invalid_choice}")
    resolutions = (
        (resolution, resolution) if invalid_choice == "reused_group" else (resolution,)
    )
    if invalid_choice != "reused_group":
        with pytest.raises(ValueError):
            group.resolved_items(resolution, file_tag_policy=None)
    with pytest.raises(ValueError):
        resolve_sync_duplicates(plan, resolutions)


def test_unchanged_file_facts_with_changed_audio_payload_need_update(
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

    assert plan.items[0].action is SyncPlanAction.UPDATE
    assert plan.items[0].basis is SyncPlanBasis.AUDIO_PAYLOAD_CHANGED
    assert plan.items[0].audio_payload_changed is True


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


def test_selecting_a_host_video_without_a_fingerprint_plans_an_add(
    tmp_path: Path,
) -> None:
    path = tmp_path / "silent-video.mp4"
    track = Track(
        1,
        "Silent video",
        "Artist",
        "Videos",
        1_000,
        media_types=(MediaType.VIDEO,),
        metadata=TrackMetadata(location=str(path)),
    )
    source = HostMediaSource(
        HostPath(path),
        HostMediaFileKind.VIDEO,
        100,
        1_000,
        acoustic_fingerprint=None,
    )
    comparison = prepare_sync_plan(
        _host_library((track,), (), (source,)),
        _ipod_library(()),
        _ipod_snapshot(),
    )
    assert comparison.items[0].action is SyncPlanAction.ATTENTION

    selection = SyncSelection()
    selection.reset(
        _host_library((track,), (), (source,)),
        comparison,
    )
    assert selection.set_tracks_checked((track.track_id,), True)

    item = selection.selected_plan.items[0]
    assert item.action is SyncPlanAction.ADD
    assert item.basis is SyncPlanBasis.HOST_ONLY
