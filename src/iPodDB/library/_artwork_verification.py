"""Verify native artwork metadata against requested assets and cover capabilities."""

from dataclasses import replace

from iPodDB.ArtworkDB.ithmb import IthmbLayout, IthmbPixelFormat, decode_ithmb
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.artwork_index import build_artwork_index
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library._artwork_timing import (
    artwork_formats,
    desired_frames,
    group_children,
    zero_source_size,
)
from iPodDB.library._artwork_timing import (
    asset_formats as requested_formats,
)
from iPodDB.library._artwork_writing import (
    artwork_path,
    effective_cover_format,
    retained_artwork_extents,
    superseded_artwork,
)
from iPodDB.library._resolved_write import ResolvedWrite
from iPodDB.library.file_content import read_content
from iPodDB.library.writing import (
    ArtworkGroupReference,
    IdentityMapping,
    PreparedFile,
    TimedArtworkAsset,
    WriteResources,
)
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
    original_bytes: bytes | None,
    artwork_bytes: bytes | None,
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
    if outputs:
        reserved = {
            artwork_path(path).casefold() for path in resources.reserved_artwork_paths
        }
        inventory = {
            item.relative_path.casefold(): item
            for item in resources.file_inventory or ()
        }
        if original is not None:
            reserved.update(
                path.casefold()
                for _, path, extent in retained_artwork_extents(original)
                if (dependency := inventory.get(path.casefold())) is None
                or extent > dependency.size
            )
        if reserved & outputs.keys():
            raise ValueError("Created artwork overwrites an unavailable reserved path.")
    assets = {a.artwork_id: a for a in resources.artwork}
    source_document = parse_ArtworkDB(original_bytes) if original_bytes else None
    source_rows = (
        {
            s.chunk.header.image_id: s.chunk
            for s in source_document.find_chunks(MhiiHeader)
        }
        if source_document
        else {}
    )
    original_tracks = {t.track_id: t for t in resolved.original.tracks}
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
                original,
                f,
                resources,
                original_sizes.get(f.format_id),
                superseded_artwork(original, resolved, resources),
            )
            if generated
            else f
        )
        for f in artwork_formats(target, timed=True)
    }
    time_schema = next(
        f.schema
        for f in binary_fields(MhniHeader)
        if f.attribute_name == "unk_mhni_0x24"
    )
    desired_tracks = {t.track_id: t for t in resolved.desired.tracks}
    first_asset_track = {t.artwork_id: t for t in reversed(resolved.desired.tracks)}
    for mapping in generated:
        asset = assets.get(mapping.draft_id)
        if asset is None:
            continue  # A per-Track clone can reuse verified retained ranges.
        track = (
            desired_tracks[mapping.track_id]
            if mapping.track_id is not None
            else first_asset_track[mapping.draft_id]
        )
        old_track = original_tracks.get(track.track_id)
        asset_formats = {
            f.format_id
            for f in requested_formats(
                target,
                asset,
                source_rows.get(old_track.artwork_id) if old_track else None,
            )
        }
        frames = desired_frames(
            asset, source_rows.get(old_track.artwork_id) if old_track else None
        )
        row = rows.get(mapping.output_id)
        if row is None or row.header.source_image_size != zero_source_size(
            frames, source_rows
        ):
            raise ValueError(
                "Created image size does not match its zero-time artwork source."
            )
        locations = tuple(
            c.payload.child.header
            for c in row.children
            if isinstance(c.payload, MhodContainerPayload)
        )
        times = tuple(location.unk_mhni_0x24 for location in locations)
        if times != tuple(sorted(times)) or set(times) != {
            f.display_time_ms for f in frames
        }:
            raise ValueError(
                "Created artwork time groups differ from the desired ascending sequence."
            )
        item = index.item_for_image_id(mapping.output_id)
        assert item is not None
        generated_pairs: set[tuple[int, int]] = set()
        for frame in frames:
            wrappers = group_children(row, frame.display_time_ms)
            if isinstance(frame.source, ArtworkGroupReference):
                source_row = source_rows.get(frame.source.artwork_id)
                retained = (
                    group_children(source_row, frame.source.display_time_ms)
                    if source_row
                    else ()
                )
                if not retained or len(retained) > len(wrappers):
                    raise ValueError("Created artwork omitted a retained time group.")
                assert original_bytes is not None and artwork_bytes is not None
                for source_child, checked_child in zip(
                    retained, wrappers[: len(retained)], strict=True
                ):
                    assert isinstance(source_child.payload, MhodContainerPayload)
                    expected_bytes = bytearray(
                        original_bytes[
                            source_child.offset : source_child.offset
                            + source_child.generic_header.length_or_child_count
                        ]
                    )
                    time_offset = (
                        source_child.payload.child.offset
                        - source_child.offset
                        + time_schema.offset
                    )
                    expected_bytes[time_offset : time_offset + time_schema.size] = (
                        frame.display_time_ms.to_bytes(4, "little")
                    )
                    actual = artwork_bytes[
                        checked_child.offset : checked_child.offset
                        + checked_child.generic_header.length_or_child_count
                    ]
                    if actual != bytes(expected_bytes):
                        raise ValueError(
                            "Created artwork changed a referenced group's retained bytes."
                        )
                retained_formats = {
                    c.payload.child.header.format_id
                    for c in retained
                    if isinstance(c.payload, MhodContainerPayload)
                }
                missing: set[int] = (
                    asset_formats - retained_formats
                    if isinstance(asset, TimedArtworkAsset)
                    and frame.display_time_ms != 0xFFFFFFFF
                    else set()
                )
                added = tuple(
                    c.payload.child.header
                    for c in wrappers[len(retained) :]
                    if isinstance(c.payload, MhodContainerPayload)
                )
                if (
                    len(added) != len(missing)
                    or {h.format_id for h in added} != missing
                ):
                    raise ValueError(
                        "Created artwork did not complete exactly the missing timed representations."
                    )
                generated_pairs.update(
                    (frame.display_time_ms, format_id) for format_id in missing
                )
                continue
            created = tuple(
                c.payload.child.header
                for c in wrappers
                if isinstance(c.payload, MhodContainerPayload)
            )
            if (
                len(created) != len(asset_formats)
                or {location.format_id for location in created} != asset_formats
            ):
                raise ValueError(
                    "Created artwork does not contain exactly the target cover formats."
                )
            generated_pairs.update(
                (frame.display_time_ms, format_id) for format_id in asset_formats
            )
        for location in locations:
            if (location.unk_mhni_0x24, location.format_id) not in generated_pairs:
                continue
            bounded = next(
                (
                    b
                    for b in item.locations
                    if b.format_id == location.format_id
                    and b.display_time_ms == location.unk_mhni_0x24
                ),
                None,
            )
            if bounded is None:
                raise ValueError("Created artwork has an unbounded raster.")
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
            "artwork_count": len(item.display_times) if item is not None else 0,
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
