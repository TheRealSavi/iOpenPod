"""Capture eligible retained Photo shards and reserve the complete namespace."""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import pairwise
from typing import TYPE_CHECKING

from iOpenPod.app.media.photo_shards import pack_photo_shards, photo_shard_identity
from iPodDB.library import FileDependency, SourceFile
from storage import DeviceEntryKind, DevicePath, StorageOperationError

if TYPE_CHECKING:
    from collections.abc import Callable

    from iPodDB.library import PhotoLibrary, PreparedPhoto, RetainedArtworkFile
    from storage import FilesystemSession
    from storage.content_workspace import ContentWorkspace

_THUMBNAILS = DevicePath("Photos/Thumbs")


def capture_and_pack(
    session: FilesystemSession,
    assets: tuple[PreparedPhoto, ...],
    retained: tuple[RetainedArtworkFile, ...],
    photos: PhotoLibrary | None,
    workspace: ContentWorkspace,
    checkpoint: Callable[[], None],
    *,
    max_file_bytes: int,
) -> tuple[PreparedPhoto, ...]:
    """Read only the last eligible partial shard for each requested format."""
    reserved = {file.file_name for file in retained}
    if photos is not None:
        reserved.update(
            representation.relative_path
            for photo in photos.photos
            for representation in photo.representations
        )
    ranges: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for file in retained:
        ranges[file.file_name.casefold()].extend(file.ranges)
    frame_sizes: dict[int, set[int]] = defaultdict(set)
    for asset in assets:
        for representation in asset.photo.representations:
            if photo_shard_identity(representation.relative_path) is not None:
                frame_sizes[representation.format_id].add(representation.size_bytes)
    entries = session.list_directory(_THUMBNAILS) if session.exists(_THUMBNAILS) else ()
    observed_names = Counter(str(entry.path).casefold() for entry in entries)
    candidates: dict[int, tuple[int, DevicePath]] = {}
    for entry in entries:
        checkpoint()
        path = str(entry.path)
        reserved.add(path)
        identity = photo_shard_identity(path)
        if (
            identity is None
            or entry.kind is not DeviceEntryKind.FILE
            or observed_names[path.casefold()] != 1
        ):
            continue
        format_id, number = identity
        sizes = frame_sizes.get(format_id, set())
        extents = ranges.get(path.casefold(), [])
        if len(sizes) != 1 or not extents:
            continue
        ordered = sorted(set(extents))
        frame_size = next(iter(sizes))
        if (
            frame_size <= 0
            or entry.size + frame_size > min(max_file_bytes, 0xFFFFFFFF)
            or any(
                offset < 0 or size <= 0 or offset + size > entry.size
                for offset, size in extents
            )
            or any(
                offset + size > following[0]
                for (offset, size), following in pairwise(ordered)
            )
        ):
            continue
        previous = candidates.get(format_id)
        if previous is None or number > previous[0]:
            candidates[format_id] = number, entry.path
    prefixes: list[SourceFile] = []
    for _, candidate_path in candidates.values():
        checkpoint()
        try:
            data, fingerprint = workspace.capture_device_snapshot(
                session, candidate_path
            )
        except (StorageOperationError, OSError):
            checkpoint()
            # Revalidate the connection before treating a read problem as a
            # reason to use a new shard. Cancellation/disconnect are not repairs.
            session.stat(_THUMBNAILS)
            continue
        if any(
            offset + size > fingerprint.size
            for offset, size in ranges[str(candidate_path).casefold()]
        ):
            continue
        identity = photo_shard_identity(str(candidate_path))
        assert identity is not None
        frame_size = next(iter(frame_sizes[identity[0]]))
        if fingerprint.size + frame_size > min(max_file_bytes, 0xFFFFFFFF):
            continue
        prefixes.append(
            SourceFile(
                FileDependency(
                    str(candidate_path), fingerprint.size, fingerprint.sha256
                ),
                data,
            )
        )
    return pack_photo_shards(
        assets,
        reserved_paths=reserved,
        prefixes=tuple(prefixes),
        max_file_bytes=max_file_bytes,
        create_buffer=workspace.new_buffer,
        checkpoint=checkpoint,
    )
