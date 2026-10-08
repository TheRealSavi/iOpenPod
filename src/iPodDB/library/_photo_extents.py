"""Retained PhotosDB thumbnail evidence for safe physical shard allocation."""

from collections import defaultdict

from iPodDB.library._photo_projection import normalize_photo_path
from iPodDB.library.writing import RetainedArtworkFile
from iPodDB.PhotosDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.PhotosDB.shared.constants import PhotosMhodType
from iPodDB.shared.chunk import DatabaseDocument


def retained_photo_thumbnail_files(
    document: DatabaseDocument[MhfdHeader],
) -> tuple[RetainedArtworkFile, ...]:
    """Expose every typed thumbnail filename and its physical allocation range.

    A zero optional allocation uses the raster size; padded allocations reserve
    their entire extent. Zero sizes, excessive extents and malformed filenames
    remain evidence for callers to reject when selecting append destinations.
    These metadata names never authorize filesystem access.
    """
    files: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for selection in document.find_chunks(MhiiHeader):
        for container in selection.chunk.children:
            if (
                not isinstance(container.header, MhodHeader)
                or container.header.mhod_type != PhotosMhodType.THUMBNAIL_IMAGE
                or not isinstance(container.payload, MhodContainerPayload)
            ):
                continue
            location = container.payload.child
            extent = (
                location.header.ithmb_offset,
                max(location.header.image_size, location.header.image_size_2),
            )
            for child in location.children:
                if (
                    isinstance(child.header, MhodHeader)
                    and child.header.mhod_type == PhotosMhodType.FILE_NAME
                    and isinstance(child.payload, MhodStringPayload)
                ):
                    raw_name = child.payload.value
                    files[normalize_photo_path(raw_name) or raw_name].add(extent)
    return tuple(
        RetainedArtworkFile(name, tuple(sorted(ranges)))
        for name, ranges in files.items()
    )
