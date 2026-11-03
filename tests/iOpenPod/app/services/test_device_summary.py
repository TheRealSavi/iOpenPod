"""Device storage estimates stay honest about indexed files and Volume capacity."""

from dataclasses import replace

import pytest

from device_registry import IdentificationStatus
from iOpenPod.app.models.device import (
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iOpenPod.app.services.device_summary import (
    StorageCategory,
    device_storage_breakdown,
)
from iPodDB.library import LibrarySnapshot, MediaType, Track, TrackMetadata
from iPodDB.library.photos import (
    Photo,
    PhotoLibrary,
    PhotoRepresentation,
    PhotoRepresentationKind,
)


def _candidate(total: int = 10_000, available: int = 4_000) -> DeviceCandidate:
    return DeviceCandidate(
        id=DeviceCandidateId("summary-device"),
        display_name="iPod",
        host_description="Test Volume",
        bus="USB",
        identification_status=IdentificationStatus.UNKNOWN,
        readiness=DeviceReadiness.READY,
        profile=None,
        total_bytes=total,
        available_bytes=available,
    )


def _track(
    identity: int,
    size: int,
    kinds: tuple[MediaType, ...] = (MediaType.AUDIO,),
    location: str | None = None,
) -> Track:
    return Track(
        identity,
        f"Track {identity}",
        "Artist",
        "Album",
        1_000,
        size_bytes=size,
        media_types=kinds,
        metadata=TrackMetadata(
            location=(
                f"iPod_Control/Music/F00/{identity}.m4a"
                if location is None
                else location
            )
        ),
    )


def _photo_representation(
    path: str = "Photos/Thumbs/F1024_1.ithmb", offset: int = 0, size: int = 100
) -> PhotoRepresentation:
    return PhotoRepresentation(
        PhotoRepresentationKind.THUMBNAIL, 1024, path, offset, size, 10, 10
    )


def test_categories_partition_capacity_and_do_not_double_count_media_flags() -> None:
    library = LibrarySnapshot(
        tracks=(
            _track(1, 1_000),
            _track(2, 500, (MediaType.AUDIO, MediaType.PODCAST)),
            _track(3, 600, (MediaType.VIDEO, MediaType.VIDEO_PODCAST)),
            _track(4, 700, (MediaType.AUDIO, MediaType.AUDIOBOOK)),
            _track(5, 800, (MediaType.VIDEO, MediaType.TV_SHOW)),
            _track(6, 200, (MediaType.AUDIO_VIDEO,)),
            _track(7, 100, (MediaType.PDF_BOOK,)),
        ),
        photos=PhotoLibrary(
            photos=(Photo(1, representations=(_photo_representation(),)),)
        ),
    )

    summary = device_storage_breakdown(_candidate(), library)

    assert {part.category: part.size_bytes for part in summary.segments} == {
        StorageCategory.MUSIC: 1_000,
        StorageCategory.VIDEOS: 1_000,
        StorageCategory.PODCASTS: 1_100,
        StorageCategory.AUDIOBOOKS: 700,
        StorageCategory.PHOTOS: 100,
        StorageCategory.GAMES: 0,
        StorageCategory.ALBUM_ARTWORK: 0,
        StorageCategory.OTHER: 2_100,
        StorageCategory.FREE: 4_000,
    }
    assert summary.used_bytes == 6_000
    assert not summary.metadata_exceeds_used
    assert sum(part.size_bytes for part in summary.segments) == summary.total_bytes


def test_shared_media_locations_count_once_and_conflicting_categories_are_other() -> (
    None
):
    library = LibrarySnapshot(
        tracks=(
            _track(1, 100, location=":iPod_Control:Music:F00:shared.mp3"),
            _track(2, 150, location="IPOD_CONTROL/MUSIC/F00/SHARED.MP3"),
            _track(3, 200, location="iPod_Control/Music/F00/conflict.m4a"),
            _track(
                4,
                250,
                (MediaType.AUDIOBOOK,),
                location="iPod_Control/Music/F00/conflict.m4a",
            ),
            _track(5, -200),
            _track(6, 2_000, location=""),
        )
    )

    summary = device_storage_breakdown(_candidate(), library)
    sizes = {part.category: part.size_bytes for part in summary.segments}

    assert sizes[StorageCategory.MUSIC] == 150
    assert sizes[StorageCategory.AUDIOBOOKS] == 0
    assert sizes[StorageCategory.OTHER] == 5_850


def test_photos_count_stored_ranges_not_source_sizes_or_shared_shards_twice() -> None:
    library = LibrarySnapshot(
        photos=PhotoLibrary(
            photos=(
                Photo(
                    1,
                    source_size_bytes=1_000_000,
                    representations=(
                        _photo_representation(),
                        _photo_representation(offset=50),
                        _photo_representation(offset=300),
                    ),
                ),
                Photo(
                    2,
                    source_size_bytes=2_000_000,
                    representations=(
                        _photo_representation(),
                        replace(
                            _photo_representation(
                                "Photos/Full Resolution/one.jpg", size=200
                            ),
                            kind=PhotoRepresentationKind.FULL_RESOLUTION,
                        ),
                        _photo_representation(offset=-1),
                        _photo_representation(size=-1),
                        _photo_representation(path=""),
                    ),
                ),
            )
        )
    )

    summary = device_storage_breakdown(_candidate(), library)
    sizes = {part.category: part.size_bytes for part in summary.segments}

    assert sizes[StorageCategory.PHOTOS] == 450
    assert sizes[StorageCategory.OTHER] == 5_550
    assert not summary.metadata_exceeds_used


def test_shared_photo_and_track_location_is_other_once() -> None:
    library = LibrarySnapshot(
        tracks=(_track(1, 100, location="Photos/shared.dat"),),
        photos=PhotoLibrary(
            photos=(
                Photo(
                    1,
                    representations=(
                        _photo_representation("photos/SHARED.dat", offset=50, size=100),
                    ),
                ),
            )
        ),
    )
    summary = device_storage_breakdown(_candidate(300, 150), library)
    sizes = {part.category: part.size_bytes for part in summary.segments}

    assert sizes[StorageCategory.MUSIC] == sizes[StorageCategory.PHOTOS] == 0
    assert sizes[StorageCategory.OTHER] == 150
    assert not summary.metadata_exceeds_used


def test_stale_metadata_falls_back_to_observed_used_and_free_space() -> None:
    library = LibrarySnapshot(tracks=(_track(1, 7_000),))

    summary = device_storage_breakdown(_candidate(), library)
    sizes = {part.category: part.size_bytes for part in summary.segments}

    assert summary.metadata_exceeds_used
    assert sizes[StorageCategory.MUSIC] == 0
    assert sizes[StorageCategory.OTHER] == 6_000
    assert sizes[StorageCategory.FREE] == 4_000
    assert sum(sizes.values()) == 10_000


def test_games_use_captured_folder_bytes_and_reduce_other() -> None:
    library = LibrarySnapshot(tracks=(_track(1, 1_000),))

    summary = device_storage_breakdown(_candidate(), library, game_storage_bytes=2_000)
    sizes = {part.category: part.size_bytes for part in summary.segments}

    assert sizes[StorageCategory.GAMES] == 2_000
    assert sizes[StorageCategory.MUSIC] == 1_000
    assert sizes[StorageCategory.OTHER] == 3_000
    assert sizes[StorageCategory.FREE] == 4_000
    assert sum(sizes.values()) == summary.total_bytes
    assert not summary.metadata_exceeds_used


def test_album_artwork_counts_the_whole_folder_and_never_duplicates_library_bytes() -> (
    None
):
    library = LibrarySnapshot(
        tracks=(
            _track(1, 100, location=":iPod_Control:Artwork:unexpected.m4a"),
            _track(2, 200),
            _track(3, 50, location="iPod_Control/Artwork_extra/unrelated.m4a"),
        ),
        photos=PhotoLibrary(
            photos=(
                Photo(
                    1,
                    representations=(
                        _photo_representation("IPOD_CONTROL\\ARTWORK\\shared.ithmb"),
                    ),
                ),
            )
        ),
    )

    summary = device_storage_breakdown(
        _candidate(),
        library,
        game_storage_bytes=1_000,
        album_artwork_storage_bytes=2_000,
    )
    sizes = {part.category: part.size_bytes for part in summary.segments}

    assert sizes[StorageCategory.GAMES] == 1_000
    assert sizes[StorageCategory.ALBUM_ARTWORK] == 2_000
    assert sizes[StorageCategory.MUSIC] == 250
    assert sizes[StorageCategory.PHOTOS] == 0
    assert sizes[StorageCategory.OTHER] == 2_750
    assert sum(sizes.values()) == summary.total_bytes
    assert not summary.metadata_exceeds_used


@pytest.mark.parametrize("game_storage_bytes", [None, 0, 300])
def test_game_locations_are_never_double_counted_as_media_or_photos(
    game_storage_bytes: int | None,
) -> None:
    library = LibrarySnapshot(
        tracks=(
            _track(1, 100, location=":iPod_Control:Games_RO:unknown:music.m4a"),
            _track(2, 100, location="IPOD_CONTROL/GAMEDATA_RW/shared.dat"),
            _track(3, 100, location="iPod_Control\\GameStats_WO\\nested\\stats.bin"),
            _track(4, 10, location="iPod_Control/Games_RO_extra/music.m4a"),
        ),
        photos=PhotoLibrary(
            photos=(
                Photo(
                    1,
                    representations=(
                        _photo_representation(
                            "iPod_Control/Games_RO/unknown/cover.bin"
                        ),
                    ),
                ),
            )
        ),
    )

    summary = device_storage_breakdown(
        _candidate(), library, game_storage_bytes=game_storage_bytes
    )
    sizes = {part.category: part.size_bytes for part in summary.segments}

    assert sizes[StorageCategory.GAMES] == (game_storage_bytes or 0)
    assert sizes[StorageCategory.MUSIC] == 10
    assert sizes[StorageCategory.PHOTOS] == 0
    assert sizes[StorageCategory.OTHER] == 5_990 - (game_storage_bytes or 0)


@pytest.mark.parametrize(("games", "artwork"), [(7_000, None), (None, 7_000)])
def test_stale_folder_sizes_retain_observed_capacity_fallback(
    games: int | None, artwork: int | None
) -> None:
    summary = device_storage_breakdown(
        _candidate(),
        LibrarySnapshot(),
        game_storage_bytes=games,
        album_artwork_storage_bytes=artwork,
    )
    sizes = {part.category: part.size_bytes for part in summary.segments}

    assert summary.metadata_exceeds_used
    assert sizes[StorageCategory.GAMES] == 0
    assert sizes[StorageCategory.ALBUM_ARTWORK] == 0
    assert sizes[StorageCategory.OTHER] == 6_000
    assert sizes[StorageCategory.FREE] == 4_000


@pytest.mark.parametrize(
    ("total", "available", "expected_total", "expected_available"),
    ((-1, 500, 0, 0), (0, 0, 0, 0), (100, -20, 100, 0), (100, 200, 100, 100)),
)
def test_invalid_capacity_never_yields_negative_or_overflowing_segments(
    total: int, available: int, expected_total: int, expected_available: int
) -> None:
    summary = device_storage_breakdown(_candidate(total, available), LibrarySnapshot())

    assert summary.total_bytes == expected_total
    assert summary.available_bytes == expected_available
    assert sum(part.size_bytes for part in summary.segments) == expected_total
    assert all(part.size_bytes >= 0 for part in summary.segments)
    assert bool(summary.segments) == bool(expected_total)
