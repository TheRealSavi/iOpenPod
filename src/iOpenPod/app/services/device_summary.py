"""Read-only storage estimates from a committed Active iPod's Library Snapshot.

Category sizes describe indexed file bytes, not filesystem allocation. Unindexed
files, other database bytes, filesystem overhead, and unused Photo shard space
remain in Other. Games and Album artwork use captured folder file sizes. This
projection neither scans nor opens the device.
"""

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from iOpenPod.app.models.device import DeviceCandidate
from iOpenPod.app.services.device_storage import (
    ALBUM_ARTWORK_STORAGE_ROOTS,
    GAME_STORAGE_ROOTS,
    is_folder_storage_location,
)
from iPodDB.library import LibrarySnapshot, MediaType, Track, is_video_track


class StorageCategory(StrEnum):
    """Stable storage legend identities; presentation owns labels and colors."""

    MUSIC = "music"
    VIDEOS = "videos"
    PODCASTS = "podcasts"
    AUDIOBOOKS = "audiobooks"
    PHOTOS = "photos"
    GAMES = "games"
    ALBUM_ARTWORK = "album_artwork"
    OTHER = "other"
    FREE = "free"


@dataclass(frozen=True, slots=True)
class StorageSegment:
    category: StorageCategory
    size_bytes: int


@dataclass(frozen=True, slots=True)
class DeviceStorageBreakdown:
    """Bounded estimates whose segments partition the observed Volume capacity.

    Zero-sized categories remain in enum order. Unknown/zero capacity has no
    segments. Inconsistent Library sizes fall back to Other and Free, rather than
    inventing scaled category values; ``metadata_exceeds_used`` explains why.
    """

    total_bytes: int
    available_bytes: int
    segments: tuple[StorageSegment, ...]
    metadata_exceeds_used: bool = False

    @property
    def used_bytes(self) -> int:
        return self.total_bytes - self.available_bytes


def device_storage_breakdown(
    candidate: DeviceCandidate,
    library: LibrarySnapshot,
    *,
    game_storage_bytes: int | None = None,
    album_artwork_storage_bytes: int | None = None,
) -> DeviceStorageBreakdown:
    """Estimate committed content using known locations and stored byte ranges.

    Tracks with a missing location or invalid size cannot identify stored bytes.
    Repeated locations count once using their largest declared size; conflicting
    classifications remain Other. Photo source sizes are deliberately ignored:
    the source original need not have been copied onto the iPod. Only the union
    of actual stored representation ranges contributes to Photos.
    Game and Artwork folders are owned by their captured totals, even if Library
    metadata refers to files there. Unavailable measurements remain in Other.
    """

    total = max(0, candidate.total_bytes)
    available = max(0, min(total, candidate.available_bytes))
    if total == 0:
        return DeviceStorageBreakdown(0, 0, ())

    sizes = dict.fromkeys(StorageCategory, 0)
    sizes[StorageCategory.GAMES] = max(0, game_storage_bytes or 0)
    sizes[StorageCategory.ALBUM_ARTWORK] = max(0, album_artwork_storage_bytes or 0)
    measured_roots = (*GAME_STORAGE_ROOTS, *ALBUM_ARTWORK_STORAGE_ROOTS)
    files: dict[str, tuple[StorageCategory, int]] = {}
    for track in library.tracks:
        path = _location_key(track.metadata.location)
        if (
            not path
            or track.size_bytes <= 0
            or is_folder_storage_location(path, measured_roots)
        ):
            continue
        category = _track_category(track)
        prior = files.get(path)
        if prior is not None:
            prior_category, prior_size = prior
            if prior_category != category:
                category = StorageCategory.OTHER
            size = max(prior_size, track.size_bytes)
        else:
            size = track.size_bytes
        files[path] = category, size
    for category, size in files.values():
        sizes[category] += size

    ranges: dict[str, list[tuple[int, int]]] = defaultdict(list)
    if library.photos is not None:
        for photo in library.photos.photos:
            for representation in photo.representations:
                path = _location_key(representation.relative_path)
                if (
                    not path
                    or is_folder_storage_location(path, measured_roots)
                    or representation.offset < 0
                    or representation.size_bytes <= 0
                ):
                    continue
                ranges[path].append(
                    (
                        representation.offset,
                        representation.offset + representation.size_bytes,
                    )
                )
    for path, intervals in ranges.items():
        if path in files:
            # Conflicting metadata cannot turn one file into two categories.
            category, size = files[path]
            sizes[category] -= size
            sizes[StorageCategory.OTHER] += max(size, max(end for _, end in intervals))
        else:
            sizes[StorageCategory.PHOTOS] += _covered_bytes(intervals)

    used = total - available
    indexed = sum(sizes.values())
    inconsistent = indexed > used
    if inconsistent:
        sizes = dict.fromkeys(StorageCategory, 0)
        sizes[StorageCategory.OTHER] = used
    else:
        sizes[StorageCategory.OTHER] += used - indexed
    sizes[StorageCategory.FREE] = available
    return DeviceStorageBreakdown(
        total,
        available,
        tuple(StorageSegment(category, size) for category, size in sizes.items()),
        metadata_exceeds_used=inconsistent,
    )


def _track_category(track: Track) -> StorageCategory:
    kinds = track.media_types
    if MediaType.PODCAST in kinds or MediaType.VIDEO_PODCAST in kinds:
        return StorageCategory.PODCASTS
    if MediaType.AUDIOBOOK in kinds:
        return StorageCategory.AUDIOBOOKS
    if is_video_track(track):
        return StorageCategory.VIDEOS
    if MediaType.AUDIO in kinds:
        return StorageCategory.MUSIC
    return StorageCategory.OTHER


def _location_key(location: str) -> str:
    """Compare descriptive iPod locations without granting filesystem authority."""

    return location.replace("\\", "/").replace(":", "/").strip("/").casefold()


def _covered_bytes(intervals: list[tuple[int, int]]) -> int:
    """Count shared or overlapping Photo representations once per shard."""

    end = 0
    size = 0
    for start, stop in sorted(intervals):
        size += max(0, stop - max(start, end))
        end = max(end, stop)
    return size
