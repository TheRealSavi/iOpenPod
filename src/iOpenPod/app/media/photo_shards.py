"""Pack captured Photo frames without reading or changing device files."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from iPodDB.library import (
    FileDependency,
    MemoryContentBuffer,
    PhotoRepresentationKind,
    PreparedPhoto,
    SourceFile,
    content_chunks,
    content_sha256,
    read_content,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

    from iPodDB.library import ContentBuffer, PhotoRepresentation

_SHARD = re.compile(r"Photos/Thumbs/F([1-9][0-9]*)_([1-9][0-9]*)\.ithmb", re.I)


def photo_shard_identity(path: str) -> tuple[int, int] | None:
    """Recognize the bounded Photo thumbnail namespace, preserving path spelling."""
    match = _SHARD.fullmatch(path)
    if match is None or any(len(group) > 10 for group in match.groups()):
        return None
    identity = int(match[1]), int(match[2])
    return identity if max(identity) <= 0xFFFFFFFF else None


@dataclass
class _Shard:
    path: str
    buffer: ContentBuffer
    prefix: FileDependency | None = None


def pack_photo_shards(
    assets: tuple[PreparedPhoto, ...],
    *,
    reserved_paths: Collection[str] = (),
    prefixes: tuple[SourceFile, ...] = (),
    max_file_bytes: int,
    create_buffer: Callable[[], ContentBuffer] = MemoryContentBuffer,
    checkpoint: Callable[[], None] = lambda: None,
) -> tuple[PreparedPhoto, ...]:
    """Append frames to one current shard per format and roll over at capacity.

    Every original remains separate. Captured prefixes remain byte-exact, and all
    output references share one frozen SourceFile per shard. The caller reserves
    both observed paths and retained database names, even for unavailable files.
    """
    if max_file_bytes <= 0:
        raise ValueError("Photo shard capacity must be positive.")
    limit = min(max_file_bytes, 0xFFFFFFFF)
    reserved = {path.casefold() for path in reserved_paths}
    shards: dict[str, _Shard] = {}
    current: dict[int, _Shard] = {}
    for source in prefixes:
        checkpoint()
        dependency = source.dependency
        identity = photo_shard_identity(dependency.relative_path)
        if identity is None or identity[0] in current:
            raise ValueError("Photo prefixes require one valid shard per format.")
        if (
            len(source.data) != dependency.size
            or content_sha256(source.data) != dependency.sha256
            or dependency.size >= limit
        ):
            raise ValueError("Photo prefix differs from its captured fingerprint.")
        buffer = create_buffer()
        for chunk in content_chunks(source.data):
            checkpoint()
            buffer.append(chunk)
        captured_shard = _Shard(dependency.relative_path, buffer, dependency)
        current[identity[0]] = captured_shard
        reserved.add(captured_shard.path.casefold())

    placements: list[tuple[PhotoRepresentation, ...]] = []
    originals: list[tuple[SourceFile, ...]] = []
    for asset in assets:
        checkpoint()
        sources = {source.dependency.relative_path: source for source in asset.files}
        representations: list[PhotoRepresentation] = []
        original_files: list[SourceFile] = []
        for representation in asset.photo.representations:
            source = sources[representation.relative_path]
            if representation.kind is PhotoRepresentationKind.FULL_RESOLUTION:
                representations.append(representation)
                original_files.append(source)
                continue
            size = representation.size_bytes
            if size <= 0 or size > limit:
                raise ValueError("A Photo thumbnail exceeds the shard capacity.")
            if (
                len(source.data) != source.dependency.size
                or content_sha256(source.data) != source.dependency.sha256
            ):
                raise ValueError("Photo frame differs from its captured fingerprint.")
            payload = read_content(source.data, representation.offset, size)
            shard = current.get(representation.format_id)
            offset = 0 if shard is None else len(shard.buffer)
            if shard is None or offset + size > limit:
                number = 1
                while True:
                    path = f"Photos/Thumbs/F{representation.format_id}_{number}.ithmb"
                    if path.casefold() not in reserved:
                        break
                    number += 1
                    if number > 0xFFFFFFFF:
                        raise ValueError("The Photo shard identity space is exhausted.")
                reserved.add(path.casefold())
                shard = _Shard(path, create_buffer())
                current[representation.format_id] = shard
                offset = 0
            shard.buffer.append(payload)
            shards[shard.path] = shard
            representations.append(
                replace(representation, relative_path=shard.path, offset=offset)
            )
        placements.append(tuple(representations))
        originals.append(tuple(original_files))

    files: dict[str, SourceFile] = {}
    for path, shard in shards.items():
        checkpoint()
        data = shard.buffer.finish()
        files[path] = SourceFile(
            FileDependency(path, len(data), content_sha256(data)), data
        )
    return tuple(
        replace(
            asset,
            photo=replace(asset.photo, representations=representations),
            files=(
                *original_files,
                *(
                    files[representation.relative_path]
                    for representation in representations
                    if representation.kind is PhotoRepresentationKind.THUMBNAIL
                ),
            ),
            file_prefixes=tuple(
                prefix
                for representation in representations
                if representation.kind is PhotoRepresentationKind.THUMBNAIL
                and (prefix := shards[representation.relative_path].prefix) is not None
            ),
        )
        for asset, representations, original_files in zip(
            assets, placements, originals, strict=True
        )
    )
