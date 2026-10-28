"""Retained group selection and explicit desired artwork sequences."""

from dataclasses import replace

from iPodDB.ArtworkDB.shared.artwork_index import ArtworkItem, thumbnail_payload
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.library.artwork import ArtworkPixels, CoverFormat, select_artwork
from iPodDB.library.file_content import read_content
from iPodDB.library.writing import (
    ArtworkAsset,
    ArtworkGroupReference,
    TimedArtworkAsset,
    TimedArtworkFrame,
    WriteResources,
    WriteTarget,
)
from iPodDB.shared.chunk import ChunkHeader, ParsedChunk


def artwork_formats(target: WriteTarget, *, timed: bool) -> tuple[CoverFormat, ...]:
    """Add distinct chapter layouts without changing ordinary-cover ordering."""
    by_id: dict[int, CoverFormat] = {}
    for cover in (*target.cover_formats, *(target.chapter_formats if timed else ())):
        prior = by_id.get(cover.format_id)
        if prior is not None and prior != cover:
            raise ValueError(
                "Cover and chapter capabilities disagree about one format layout."
            )
        by_id.setdefault(cover.format_id, cover)
    return tuple(by_id.values())


def asset_formats(
    target: WriteTarget,
    asset: ArtworkAsset | TimedArtworkAsset,
    source_row: ParsedChunk[MhiiHeader] | None,
) -> tuple[CoverFormat, ...]:
    available = artwork_formats(target, timed=True)
    if isinstance(asset, TimedArtworkAsset):
        return available
    # Ordinary cover creation uses cover formats alone. Refreshing an existing
    # zero group must also update its known chapter representations.
    existing: set[int] = (
        {
            c.payload.child.header.format_id
            for c in group_children(source_row, 0)
            if isinstance(c.payload, MhodContainerPayload)
        }
        if source_row
        else set()
    )
    wanted = {f.format_id for f in target.cover_formats} | existing
    return tuple(f for f in available if f.format_id in wanted)


def checked_artwork_count(count: int) -> int:
    """MHIT has room for an unsigned 16-bit source-image count."""
    if not 0 <= count <= 0xFFFF:
        raise ValueError(
            "Artwork time-group count exceeds the unsigned 16-bit MHIT field."
        )
    return count


def retained_group_pixels(
    item: ArtworkItem | None,
    reference: ArtworkGroupReference,
    formats: tuple[CoverFormat, ...],
    resources: WriteResources,
) -> ArtworkPixels:
    """Decode the largest available representation using captured source bytes."""
    by_id = {f.format_id: f for f in formats}
    candidates = sorted(
        (
            location
            for location in item.locations
            if location.display_time_ms == reference.display_time_ms
            and location.format_id in by_id
        )
        if item
        else (),
        key=lambda location: (
            by_id[location.format_id].width * by_id[location.format_id].height
        ),
        reverse=True,
    )
    inventory = {f.relative_path.casefold(): f for f in resources.file_inventory or ()}
    sources = {f.dependency.relative_path.casefold(): f for f in resources.files}
    for location in candidates:
        assert item is not None
        read = select_artwork(
            replace(item, locations=(location,)),
            formats,
            1,
            display_time_ms=reference.display_time_ms,
        )
        if read is None:
            continue
        source = sources.get(read.relative_path.casefold())
        if source is None or source.dependency != inventory.get(
            read.relative_path.casefold()
        ):
            continue
        try:
            return read.decode(read_content(source.data, read.offset, read.length))
        except ValueError:
            continue
    raise ValueError(
        "Completing a timed artwork group requires captured bytes for a decodable retained representation."
    )


def group_children(
    row: ParsedChunk[MhiiHeader], time: int
) -> tuple[ParsedChunk[ChunkHeader], ...]:
    return tuple(
        c
        for c in row.children
        if (payload := thumbnail_payload(c)) is not None
        and payload.child.header.image_time_key == time
    )


def comparable_group(chunk: ParsedChunk[ChunkHeader]) -> ParsedChunk[ChunkHeader]:
    """Ignore source byte positions when comparing separately retained clones."""
    payload = chunk.payload
    if isinstance(payload, MhodContainerPayload):
        payload = replace(payload, child=_without_offsets(payload.child))
    return replace(
        chunk,
        offset=0,
        payload=payload,
        children=tuple(comparable_group(c) for c in chunk.children),
        original_prefix=None,
        original_payload=None,
    )


def _without_offsets[H: ChunkHeader](chunk: ParsedChunk[H]) -> ParsedChunk[H]:
    return replace(
        chunk,
        offset=0,
        children=tuple(comparable_group(c) for c in chunk.children),
        original_prefix=None,
        original_payload=None,
    )


def desired_frames(
    asset: ArtworkAsset | TimedArtworkAsset, row: ParsedChunk[MhiiHeader] | None
) -> tuple[TimedArtworkFrame, ...]:
    if isinstance(asset, TimedArtworkAsset):
        return tuple(sorted(asset.frames, key=lambda f: f.display_time_ms))
    times = (
        sorted(
            {
                payload.child.header.image_time_key
                for c in row.children
                if (payload := thumbnail_payload(c)) is not None
            }
            - {0}
        )
        if row
        else ()
    )
    return (
        TimedArtworkFrame(0, asset.pixels),
        *(
            TimedArtworkFrame(time, ArtworkGroupReference(row.header.image_id, time))
            for time in times
            if row is not None
        ),
    )


def referenced_group(
    rows: dict[int, ParsedChunk[MhiiHeader]], frame: TimedArtworkFrame
) -> tuple[ParsedChunk[ChunkHeader], ...]:
    reference = frame.source
    assert isinstance(reference, ArtworkGroupReference)
    row = rows.get(reference.artwork_id)
    children = group_children(row, reference.display_time_ms) if row is not None else ()
    if not children:
        raise ValueError(
            "A referenced artwork time group is missing from the source ArtworkDB."
        )
    return tuple(
        replace(
            c,
            payload=replace(
                c.payload,
                child=replace(
                    c.payload.child,
                    header=replace(
                        c.payload.child.header, image_time_key=frame.display_time_ms
                    ),
                ),
            ),
        )
        if isinstance(c.payload, MhodContainerPayload)
        and frame.display_time_ms != reference.display_time_ms
        else c
        for c in children
    )


def zero_source_size(
    frames: tuple[TimedArtworkFrame, ...], rows: dict[int, ParsedChunk[MhiiHeader]]
) -> int:
    zero = next(f.source for f in frames if f.display_time_ms == 0)
    if isinstance(zero, ArtworkPixels):
        return len(zero.rgb888)
    row = rows.get(zero.artwork_id)
    if row is None:
        raise ValueError(
            "A referenced artwork image is missing from the source ArtworkDB."
        )
    return row.header.source_image_size
