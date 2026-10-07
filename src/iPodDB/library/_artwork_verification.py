"""Verify native artwork metadata against requested assets and cover capabilities."""

from dataclasses import replace

from iPodDB.ArtworkDB.ithmb import IthmbLayout, IthmbPixelFormat, decode_ithmb
from iPodDB.ArtworkDB.shared.artwork_index import build_artwork_index
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library._artwork_writing import artwork_path, effective_cover_format
from iPodDB.library._resolved_write import ResolvedWrite
from iPodDB.library.file_content import read_content
from iPodDB.library.writing import IdentityMapping, PreparedFile, WriteResources
from iPodDB.shared.binary_struct import binary_fields
from iPodDB.shared.chunk import DatabaseDocument


def verify_artwork(
    original: DatabaseDocument[MhfdHeader] | None,
    artwork: DatabaseDocument[MhfdHeader] | None,
    itunes: DatabaseDocument[MhbdHeader],
    original_itunes: DatabaseDocument[MhbdHeader],
    resolved: ResolvedWrite,
    mappings: tuple[IdentityMapping, ...],
    resources: WriteResources,
    files: tuple[PreparedFile, ...],
) -> None:
    if not resolved.artwork_tracks and not resolved.deleted_tracks:
        return
    target = resolved.plan.target
    if artwork is None:
        if any(
            t.artwork_id
            for t in resolved.desired.tracks
            if t.track_id in resolved.artwork_tracks
        ):
            raise ValueError("Changed artwork is missing its ArtworkDB.")
        return
    if original is None:
        if artwork.header.unk_mhfd_0x10 != target.artwork_root_value:
            raise ValueError("Created ArtworkDB does not match the target root policy.")
    elif (
        replace(artwork.header, next_mhii_id=original.header.next_mhii_id)
        != original.header
    ):
        raise ValueError("Retained ArtworkDB root fields changed unexpectedly.")
    rows = {s.chunk.header.image_id: s.chunk for s in artwork.find_chunks(MhiiHeader)}
    generated = tuple(m for m in mappings if m.subject == "artwork")
    reserved_ids = {
        s.chunk.header.artwork_id_ref for s in original_itunes.find_chunks(MhitHeader)
    }
    if any(mapping.output_id in reserved_ids for mapping in generated):
        raise ValueError("Created artwork reused a retained Track artwork reference.")
    if generated and artwork.header.next_mhii_id <= max(rows):
        raise ValueError("ArtworkDB next image identity would reuse an existing image.")
    index = build_artwork_index(artwork)
    outputs = {f.relative_path.casefold(): f.data for f in files}
    assets = {a.artwork_id: a.pixels for a in resources.artwork}
    file_formats = tuple(s.chunk.header for s in artwork.find_chunks(MhifHeader))
    original_sizes = (
        {
            s.chunk.header.format_id: s.chunk.header.image_size
            for s in original.find_chunks(MhifHeader)
        }
        if original is not None
        else {}
    )
    formats = {
        f.format_id: (
            effective_cover_format(
                original, f, resources, original_sizes.get(f.format_id)
            )
            if generated
            else f
        )
        for f in target.cover_formats
    }
    for mapping in generated:
        pixels = assets.get(mapping.draft_id)
        if pixels is None:
            continue  # A per-Track clone can reuse verified retained ranges.
        row = rows.get(mapping.output_id)
        if row is None or row.header.source_image_size != len(pixels.rgb888):
            raise ValueError(
                "Created image size does not match its supplied artwork pixels."
            )
        locations = tuple(
            c.payload.child.header
            for c in row.children
            if isinstance(c.payload, MhodContainerPayload)
        )
        if len(locations) != len(formats) or {
            location.format_id for location in locations
        } != set(formats):
            raise ValueError(
                "Created artwork does not contain exactly the target cover formats."
            )
        item = index.item_for_image_id(mapping.output_id)
        assert item is not None
        for location, bounded in zip(locations, item.locations, strict=True):
            cover = formats[location.format_id]
            if (
                location.image_width,
                location.image_height,
                location.horizontal_padding,
                location.vertical_padding,
            ) != (cover.width, cover.height, 0, 0):
                raise ValueError(
                    "Created artwork dimensions or padding differ from the target layout."
                )
            if location.image_size != location.image_size_2 or location.image_size <= 0:
                raise ValueError("Created artwork size fields disagree.")
            size = location.image_size
            if cover.pixel_format is not IthmbPixelFormat.JPEG:
                rotated = cover.pixel_format is IthmbPixelFormat.RGB565_BE_90
                expected_size = (
                    cover.width * cover.height * 2
                    if cover.pixel_format is IthmbPixelFormat.I420_LE
                    else (
                        cover.row_bytes
                        or (cover.height if rotated else cover.width) * 2
                    )
                    * (cover.width if rotated else cover.height)
                )
                if size != expected_size or location.ithmb_offset % size:
                    raise ValueError(
                        "Created artwork range does not match its raster size or alignment."
                    )
            entries = tuple(f for f in file_formats if f.format_id == cover.format_id)
            if len(entries) != 1 or entries[0].image_size != size:
                raise ValueError(
                    "Created artwork disagrees with its MHIF file-format entry."
                )
            data = outputs.get(artwork_path(bounded.file_name).casefold())
            if data is None:
                raise ValueError("Created artwork has no prepared pixel file.")
            decoded = decode_ithmb(
                read_content(data, bounded.offset, size),
                IthmbLayout(
                    cover.width, cover.height, cover.row_bytes, cover.pixel_format
                ),
            )
            if (decoded.width, decoded.height) != (cover.width, cover.height):
                raise ValueError(
                    "Created artwork cannot decode to its target dimensions."
                )
    track_ids = {m.draft_id: m.output_id for m in mappings if m.subject == "track"}
    image_ids = {m.draft_id: m.output_id for m in generated if m.track_id is None}
    per_track = {m.track_id: m.output_id for m in generated if m.track_id is not None}
    native = {s.chunk.header.track_id: s.chunk for s in itunes.find_chunks(MhitHeader)}
    schemas = {f.attribute_name: f.schema for f in binary_fields(MhitHeader)}
    for track in resolved.desired.tracks:
        if track.track_id not in resolved.artwork_tracks:
            continue
        image_id = per_track.get(
            track.track_id, image_ids.get(track.artwork_id, track.artwork_id)
        )
        chunk = native[track_ids.get(track.track_id, track.track_id)]
        item = index.item_for_image_id(image_id)
        if image_id and item is None:
            raise ValueError("Changed Track references missing artwork.")
        expected = {
            "artwork_id_ref": image_id,
            "artwork_count": len(item.locations) if item else 0,
            "artwork_size": item.source_image_size if item else 0,
            "has_artwork": int(item is not None),
        }
        for name, value in expected.items():
            schema = schemas[name]
            if (
                schema.offset + schema.size <= chunk.generic_header.header_length
                and getattr(chunk.header, name) != value
            ):
                raise ValueError(f"Changed Track has an inconsistent native {name}.")
        link = schemas["artwork_id_ref"]
        if (
            image_id
            and (
                not target.supports_sparse_artwork
                or link.offset + link.size > chunk.generic_header.header_length
            )
            and (item is None or item.db_track_id_ref != chunk.header.db_track_id)
        ):
            raise ValueError("This Track requires its own reverse ArtworkDB link.")
