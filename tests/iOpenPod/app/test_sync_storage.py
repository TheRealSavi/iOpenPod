from dataclasses import replace
from pathlib import Path

import pytest

from device_registry import DEFAULT_DEVICE_REGISTRY, IdentificationStatus
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
)
from iOpenPod.app.media.transcoding import TranscodeQuality, TranscodeSettings
from iOpenPod.app.models.device import (
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
)
from iOpenPod.app.sync_storage import SyncStorageProjection
from iPodDB.library import LibrarySnapshot, MediaType, Track, TrackMetadata
from storage import DevicePath, HostPath


def _candidate(total: int = 1_000, available: int = 400) -> DeviceCandidate:
    return DeviceCandidate(
        DeviceCandidateId("test-connection"),
        "Test iPod",
        "USB iPod",
        "usb",
        IdentificationStatus.UNKNOWN,
        DeviceReadiness.UNKNOWN,
        None,
        total,
        available,
    )


def _sources(tmp_path: Path) -> tuple[HostMediaLibrary, IPodMediaLibrary]:
    host = HostMediaLibrary(
        LibrarySnapshot(),
        (
            HostMediaSource(
                HostPath(tmp_path / "song.flac"), HostMediaFileKind.AUDIO, 300, 100
            ),
            HostMediaSource(
                HostPath(tmp_path / "photo.png"), HostMediaFileKind.PHOTO, 200, 100
            ),
        ),
        (),
        HostMediaCacheStats(),
    )
    ipod = IPodMediaLibrary(
        (IPodTrackFingerprint(100, 1, DevicePath("Music/song.m4a"), 90, 100, "1,2,3"),),
        (IPodImageFingerprint(1, DevicePath("Photos/photo.jpg"), 150, 100, "a" * 64),),
        (),
        IPodMediaCacheStats(),
        None,
        False,
    )
    return host, ipod


def _item(tmp_path: Path, action: SyncPlanAction) -> SyncPlanItem:
    return SyncPlanItem(
        action,
        SyncPlanMediaKind.TRACK,
        SyncPlanBasis.HOST_FACTS_CHANGED,
        "Song",
        host_path=str(tmp_path / "song.flac"),
        ipod_id=1,
        audio_payload_changed=action is SyncPlanAction.UPDATE,
    )


@pytest.mark.parametrize(
    ("action", "incoming", "outgoing"),
    [
        (SyncPlanAction.ADD, 300, 0),
        (SyncPlanAction.UPDATE, 300, 90),
        (SyncPlanAction.REMOVE, 0, 90),
        (SyncPlanAction.UNCHANGED, 0, 0),
    ],
)
def test_source_sizes_and_device_sizes_are_distinct(
    tmp_path: Path, action: SyncPlanAction, incoming: int, outgoing: int
) -> None:
    host, ipod = _sources(tmp_path)
    projection = SyncStorageProjection(host, ipod, _candidate())
    estimate = projection.estimate(SyncPlan((_item(tmp_path, action),)))

    # No media files exist: this must use captured facts, with no fresh file I/O.
    assert estimate.incoming_bytes == incoming
    assert estimate.outgoing_bytes == outgoing
    assert estimate.current_used_bytes == 600
    assert estimate.projected_used_bytes == 600 + incoming - outgoing
    assert estimate.unknown_items == 0


def test_tracks_and_photos_with_the_same_id_have_separate_sizes(tmp_path: Path) -> None:
    host, ipod = _sources(tmp_path)
    song = _item(tmp_path, SyncPlanAction.UPDATE)
    photo = replace(
        song,
        media_kind=SyncPlanMediaKind.PHOTO,
        host_path=str(tmp_path / "photo.png"),
    )
    estimate = SyncStorageProjection(host, ipod, _candidate()).estimate(
        SyncPlan((song, photo))
    )

    assert estimate.incoming_bytes == 500
    assert estimate.outgoing_bytes == 240
    assert estimate.net_bytes == 260
    assert estimate.free_bytes == 140


def test_unknown_changes_and_attention_do_not_invent_sizes(tmp_path: Path) -> None:
    host, ipod = _sources(tmp_path)
    item = _item(tmp_path, SyncPlanAction.UPDATE)
    plan = SyncPlan(
        (
            replace(item, host_path=str(tmp_path / "missing.flac")),
            replace(item, ipod_id=999),
            replace(item, action=SyncPlanAction.ATTENTION, audio_payload_changed=False),
        )
    )
    estimate = SyncStorageProjection(host, ipod, _candidate()).estimate(plan)

    assert estimate.unknown_items == 3
    assert estimate.net_bytes == 0
    assert estimate.incoming_bytes == estimate.outgoing_bytes == 0


def test_shared_device_file_is_freed_only_after_its_last_reference(
    tmp_path: Path,
) -> None:
    host, ipod = _sources(tmp_path)
    ipod = replace(ipod, tracks=(*ipod.tracks, replace(ipod.tracks[0], track_id=2)))
    projection = SyncStorageProjection(host, ipod, _candidate())
    removal = _item(tmp_path, SyncPlanAction.REMOVE)

    assert projection.estimate(SyncPlan((removal,))).outgoing_bytes == 0
    both = SyncPlan((removal, replace(removal, ipod_id=2)))
    assert projection.estimate(both).outgoing_bytes == 90


def test_over_capacity_stays_negative_and_unknown_capacity_is_not_invented(
    tmp_path: Path,
) -> None:
    host, ipod = _sources(tmp_path)
    plan = SyncPlan((_item(tmp_path, SyncPlanAction.ADD),))
    estimate = SyncStorageProjection(host, ipod, _candidate(1_000, 100)).estimate(plan)
    assert estimate.projected_used_bytes == 1_200
    assert estimate.free_bytes == -200

    unknown = SyncStorageProjection(host, ipod, _candidate(0, 0)).estimate(plan)
    assert unknown.total_bytes == 0


def test_zero_length_files_are_known_sizes(tmp_path: Path) -> None:
    host, ipod = _sources(tmp_path)
    host = replace(host, sources=(replace(host.sources[0], size_bytes=0),))
    estimate = SyncStorageProjection(host, ipod, _candidate()).estimate(
        SyncPlan((_item(tmp_path, SyncPlanAction.UPDATE),))
    )
    assert estimate.net_bytes == -90
    assert estimate.unknown_items == 0


def test_metadata_only_track_update_does_not_project_media_replacement(
    tmp_path: Path,
) -> None:
    host, ipod = _sources(tmp_path)
    item = replace(_item(tmp_path, SyncPlanAction.UPDATE), audio_payload_changed=False)
    estimate = SyncStorageProjection(host, ipod, _candidate()).estimate(
        SyncPlan((item,))
    )
    assert estimate.incoming_bytes == 0
    assert estimate.outgoing_bytes == 0


def test_transcoding_settings_change_estimated_device_bytes(tmp_path: Path) -> None:
    host, ipod = _sources(tmp_path)
    track = Track(
        7,
        "Song",
        "Artist",
        "Album",
        60_000,
        metadata=TrackMetadata(
            location=str(tmp_path / "song.flac"), file_format="flac"
        ),
    )
    host = replace(host, snapshot=LibrarySnapshot(tracks=(track,)))
    profile = next(
        p for p in DEFAULT_DEVICE_REGISTRY.profiles if p.model_number == "MB565"
    )
    projection = SyncStorageProjection(host, ipod, _candidate(), profile)
    plan = SyncPlan((_item(tmp_path, SyncPlanAction.ADD),))

    assert projection.estimate(plan).incoming_bytes == 330
    compact = projection.estimate(
        plan,
        settings=TranscodeSettings(
            lossless_to_lossy=True, quality=TranscodeQuality.COMPACT
        ),
    )
    high = projection.estimate(
        plan,
        settings=TranscodeSettings(
            lossless_to_lossy=True, quality=TranscodeQuality.HIGH
        ),
    )
    assert compact.incoming_bytes == 979_200
    assert high.incoming_bytes == 1_958_400


def test_video_projection_uses_ipod_bitrate_limit(tmp_path: Path) -> None:
    host, ipod = _sources(tmp_path)
    source = replace(
        host.sources[0],
        path=HostPath(tmp_path / "movie.mkv"),
        kind=HostMediaFileKind.VIDEO,
        size_bytes=40_000_000,
    )
    track = Track(
        7,
        "Movie",
        "",
        "",
        60_000,
        media_types=(MediaType.VIDEO,),
        metadata=TrackMetadata(location=str(source.path), file_format="mkv"),
    )
    host = replace(
        host,
        sources=(source,),
        snapshot=LibrarySnapshot(tracks=(track,)),
    )
    profile = next(
        p for p in DEFAULT_DEVICE_REGISTRY.profiles if p.model_number == "MB565"
    )
    plan = SyncPlan(
        (replace(_item(tmp_path, SyncPlanAction.ADD), host_path=str(source.path)),)
    )
    estimate = SyncStorageProjection(host, ipod, _candidate(), profile).estimate(plan)

    assert estimate.incoming_bytes == 20_349_000
