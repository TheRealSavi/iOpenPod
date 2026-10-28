"""Small immutable projection of ArtworkDB image-to-iTHMB relationships."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.ArtworkDB.shared.constants import ArtworkMhodType

if TYPE_CHECKING:
    from collections.abc import Mapping

    from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
    from iPodDB.ArtworkDB.shared.chunk_defs.mhni import MhniHeader
    from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IthmbLocation:
    """One bounded byte range containing an image in an iTHMB file."""

    format_id: int
    file_name: str
    offset: int
    byte_length: int
    width: int
    height: int
    horizontal_padding: int = 0
    vertical_padding: int = 0
    display_time_ms: int = 0

    def __post_init__(self) -> None:
        if self.format_id <= 0:
            raise ValueError("An iTHMB location requires a positive format ID")
        if self.offset < 0:
            raise ValueError("An iTHMB byte-range offset must not be negative")
        if self.byte_length <= 0:
            raise ValueError("An iTHMB location requires a bounded byte range")
        if self.width < 0 or self.height < 0:
            raise ValueError("iTHMB image dimensions must not be negative")


@dataclass(frozen=True, slots=True)
class ArtworkItem:
    """One ArtworkDB image and its available iTHMB representations."""

    image_id: int
    db_track_id_ref: int
    source_image_size: int
    locations: tuple[IthmbLocation, ...]
    display_times: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ArtworkIndex:
    """O(1) immutable lookup index built once from an ArtworkDB document."""

    items: tuple[ArtworkItem, ...]
    _by_image_id: Mapping[int, ArtworkItem] = field(init=False, repr=False)
    _by_db_track_id: Mapping[int, ArtworkItem | None] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        by_image_id: dict[int, ArtworkItem] = {}
        by_db_track_id: dict[int, ArtworkItem | None] = {}
        for item in self.items:
            if item.image_id in by_image_id:
                raise ValueError(f"Duplicate ArtworkDB image ID: {item.image_id}")
            by_image_id[item.image_id] = item
            if item.db_track_id_ref:
                if item.db_track_id_ref in by_db_track_id:
                    # Native list and sorted-index searches do not establish a
                    # stable duplicate winner. Preserve direct lookup, but do
                    # not invent a reverse-owner association.
                    if by_db_track_id[item.db_track_id_ref] is not None:
                        _LOGGER.warning(
                            "Ambiguous ArtworkDB reverse Track identity %#x; "
                            "retaining images without choosing a reverse owner",
                            item.db_track_id_ref,
                        )
                    by_db_track_id[item.db_track_id_ref] = None
                else:
                    by_db_track_id[item.db_track_id_ref] = item
        object.__setattr__(self, "_by_image_id", MappingProxyType(by_image_id))
        object.__setattr__(
            self,
            "_by_db_track_id",
            MappingProxyType(by_db_track_id),
        )

    def item_for_image_id(self, image_id: int) -> ArtworkItem | None:
        return self._by_image_id.get(image_id)

    def item_for_db_track_id(self, db_track_id: int) -> ArtworkItem | None:
        return self._by_db_track_id.get(db_track_id)


EMPTY_ARTWORK_INDEX = ArtworkIndex(())


def thumbnail_payload(
    chunk: ParsedChunk[ChunkHeader],
) -> MhodContainerPayload | None:
    """Return a recognized type-2 thumbnail, excluding other MHNI containers."""
    if (
        isinstance(chunk.header, MhodHeader)
        and chunk.header.mhod_type == ArtworkMhodType.THUMBNAIL_IMAGE
        and isinstance(chunk.payload, MhodContainerPayload)
    ):
        return chunk.payload
    return None


def build_artwork_index(
    database: DatabaseDocument[MhfdHeader],
) -> ArtworkIndex:
    """Project display lookups without changing the lossless database document."""

    items: list[ArtworkItem] = []
    for selection in database.find_chunks(MhiiHeader):
        header = selection.chunk.header
        containers = tuple(
            payload
            for child in selection.chunk.children
            if (payload := thumbnail_payload(child)) is not None
        )
        locations: list[IthmbLocation] = []
        for container in containers:
            location = _location_from_container(container)
            if location is not None:
                locations.append(location)
        items.append(
            ArtworkItem(
                image_id=header.image_id,
                db_track_id_ref=header.db_track_id_ref,
                source_image_size=header.source_image_size,
                locations=tuple(locations),
                display_times=tuple(
                    sorted(
                        {
                            container.child.header.image_time_key
                            for container in containers
                        }
                    )
                ),
            )
        )
    return ArtworkIndex(tuple(items))


def _location_from_container(
    payload: MhodContainerPayload,
) -> IthmbLocation | None:
    image_name = payload.child
    header = image_name.header
    if header.format_id <= 0:
        # Keep the image identity and lossless MHNI, while allowing independent
        # representations and other covers to remain available. A single damaged
        # format must not turn the entire Artwork Index into a load failure.
        _LOGGER.warning(
            "Retained ArtworkDB MHNI at %#x has invalid format ID %s; "
            "omitting only this display location",
            image_name.offset,
            header.format_id,
        )
        return None
    # +0x18 is the native read count. The separate +0x28 allocation field
    # cannot supply missing pixel length or authorize a larger ranged read.
    byte_length = header.image_size
    if byte_length <= 0:
        # A location without an encoded size cannot authorize a Storage ranged
        # read. Preserve the lossless document, but omit this unsafe projection.
        return None
    return IthmbLocation(
        format_id=header.format_id,
        file_name=_file_name(image_name),
        offset=header.ithmb_offset,
        byte_length=byte_length,
        width=header.image_width,
        height=header.image_height,
        horizontal_padding=header.horizontal_padding,
        vertical_padding=header.vertical_padding,
        display_time_ms=header.image_time_key,
    )


def _file_name(image_name: ParsedChunk[MhniHeader]) -> str:
    for child in image_name.children:
        if not isinstance(child.header, MhodHeader):
            continue
        if child.header.mhod_type != ArtworkMhodType.FILE_NAME:
            continue
        if isinstance(child.payload, MhodStringPayload):
            return child.payload.value
    return ""


__all__ = [
    "EMPTY_ARTWORK_INDEX",
    "ArtworkIndex",
    "ArtworkItem",
    "IthmbLocation",
    "build_artwork_index",
    "thumbnail_payload",
]
