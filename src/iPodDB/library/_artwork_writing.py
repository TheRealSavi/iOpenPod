"""Coordinated, append-only artwork preparation over caller-supplied assets."""

import hashlib
import logging
from dataclasses import replace
from itertools import pairwise
from pathlib import PurePosixPath

from iPodDB.ArtworkDB.builder.build_ArtworkDB import (
    new_artwork_chunk,
    new_ArtworkDB,
    new_auxiliary_mhod,
    new_container_mhod,
    new_string_mhod,
)
from iPodDB.ArtworkDB.ithmb import (
    DecodedImage,
    IthmbLayout,
    IthmbPixelFormat,
    decode_ithmb,
)
from iPodDB.ArtworkDB.ithmb_writer import encode_ithmb
from iPodDB.ArtworkDB.shared.artwork_index import build_artwork_index
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import DEFINITION as MHIF
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import DEFINITION as MHII
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import DEFINITION as MHNI
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.ArtworkDB.shared.constants import ArtworkMhodType
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library._document_edit import rebuild
from iPodDB.library._resolved_write import ResolvedWrite
from iPodDB.library.artwork import CoverFormat
from iPodDB.library.writing import (
    IdentityMapping,
    PreparedFile,
    WriteResources,
    WriteTarget,
)
from iPodDB.shared.binary_struct import binary_fields
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk

logger = logging.getLogger(__name__)

_ARTWORK_LINK = next(
    f.schema for f in binary_fields(MhitHeader) if f.attribute_name == "artwork_id_ref"
)


def validated_path(value: str) -> str:
    value.encode("utf-8")
    if not value or "\\" in value or ":" in value or "\x00" in value:
        raise ValueError("A resource requires a validated device-relative path.")
    parts = value.split("/")
    if (
        any(part in ("", ".", "..") for part in parts)
        or PurePosixPath(value).is_absolute()
    ):
        raise ValueError(
            "A resource path cannot escape the device or contain empty components."
        )
    return value


def artwork_path(name: str) -> str:
    value = name[1:] if name.startswith(":") else name
    value = value.replace(":", "/")
    if "/" not in value:
        value = "iPod_Control/Artwork/" + value
    path = validated_path(value)
    if not path.startswith("iPod_Control/Artwork/") or not path.casefold().endswith(
        ".ithmb"
    ):
        raise ValueError(
            "The retained artwork filename does not identify a supported iTHMB path."
        )
    return path


def _validate_retained_artwork_format(
    artwork: DatabaseDocument[MhfdHeader],
    cover: CoverFormat,
    size: int,
    resources: WriteResources,
) -> None:
    """Establish a fixed MHIF size from every retained representation and range.

    Raw fixed-size rasters need no content-dependent decoding to establish their
    extent. Captured fingerprints bind even full shards (whose bytes need not be
    loaded for appending) to the eventual Storage Transaction.
    """
    if cover.pixel_format is IthmbPixelFormat.JPEG:
        raise ValueError("Variable-size artwork cannot establish a fixed MHIF size.")
    inventory = {f.relative_path.casefold(): f for f in resources.file_inventory or ()}
    ranges: dict[str, set[int]] = {}
    for selection in artwork.find_chunks(MhiiHeader):
        matches = 0
        for child in selection.chunk.children:
            if not isinstance(child.payload, MhodContainerPayload):
                if (
                    isinstance(child.header, MhodHeader)
                    and child.header.mhod_type == ArtworkMhodType.THUMBNAIL_IMAGE
                ):
                    raise ValueError(
                        "A retained thumbnail representation is unrecognized."
                    )
                continue
            location = child.payload.child
            header = location.header
            if header.format_id != cover.format_id:
                continue
            matches += 1
            if matches > 1:
                raise ValueError(
                    "A retained image has duplicate representations of this format."
                )
            if header.image_size != size or header.image_size_2 != size:
                raise ValueError(
                    "Retained MHNI image sizes disagree with the target layout."
                )
            for dimension, padding, expected in (
                (header.image_width, header.horizontal_padding, cover.width),
                (header.image_height, header.vertical_padding, cover.height),
            ):
                # foo_dop records the bottom/right edge of centered content;
                # other writers record the complete raster dimensions.
                if not (
                    0 <= padding < dimension <= expected
                    and (dimension == expected or dimension + padding == expected)
                ):
                    raise ValueError(
                        "Retained MHNI dimensions or padding disagree with the target layout."
                    )
            names = tuple(
                c.payload.value
                for c in location.children
                if isinstance(c.header, MhodHeader)
                and c.header.mhod_type == ArtworkMhodType.FILE_NAME
                and isinstance(c.payload, MhodStringPayload)
            )
            if len(names) != 1:
                raise ValueError(
                    "A retained image requires exactly one thumbnail filename."
                )
            path = artwork_path(names[0]).casefold()
            dependency = inventory.get(path)
            if (
                dependency is None
                or header.ithmb_offset < 0
                or header.ithmb_offset + size > dependency.size
            ):
                raise ValueError(
                    "A retained image range is missing or outside its captured thumbnail file."
                )
            ranges.setdefault(path, set()).add(header.ithmb_offset)
    if not ranges:
        raise ValueError("No retained MHNI images establish the expected size.")
    for offsets in ranges.values():
        ordered = sorted(offsets)
        if any(right < left + size for left, right in pairwise(ordered)):
            raise ValueError("Retained image ranges partially overlap.")


def reconcile_artwork(
    itunes: DatabaseDocument[MhbdHeader],
    artwork: DatabaseDocument[MhfdHeader] | None,
    resolved: ResolvedWrite,
    mappings: tuple[IdentityMapping, ...],
    target: WriteTarget,
    resources: WriteResources,
) -> tuple[
    DatabaseDocument[MhbdHeader],
    DatabaseDocument[MhfdHeader] | None,
    tuple[PreparedFile, ...],
    tuple[IdentityMapping, ...],
]:
    original, desired = resolved.original, resolved.desired
    before = {t.track_id: t for t in original.tracks}
    assets = {a.artwork_id: a.pixels for a in resources.artwork}
    tracks = {t.track_id: t for t in desired.tracks}
    changed = [tracks[i] for i in resolved.artwork_tracks]
    deleted = resolved.deleted_tracks
    logger.debug(
        "Artwork reconciliation source=%s present=%s changed_tracks=%s deleted_tracks=%s assets=%d formats=%d",
        resolved.plan.draft.source_revision,
        artwork is not None,
        sorted(resolved.artwork_tracks),
        sorted(deleted),
        len(assets),
        len(target.cover_formats),
    )
    if not changed and not deleted:
        logger.debug(
            "ArtworkDB and iTHMB ranges retained unchanged; no artwork selection or ownership changes"
        )
        return itunes, artwork, (), ()
    if artwork is None and any(t.artwork_id for t in changed):
        if target.artwork_root_value is None:
            raise ValueError(
                "Creating an ArtworkDB requires an evidenced artwork root value in the write target."
            )
        # Original iOpenPod and libgpod start fresh album-art identities at 100.
        artwork = new_ArtworkDB(
            next_mhii_id=100, unk_mhfd_0x10=target.artwork_root_value
        )
    native_ids = {m.draft_id: m.output_id for m in mappings if m.subject == "track"}
    track_chunks = {
        s.chunk.header.track_id: s.chunk for s in itunes.find_chunks(MhitHeader)
    }
    if artwork is None:
        edits: dict[int, ParsedChunk[ChunkHeader] | None] = {}
        for track in changed:
            chunk = track_chunks[native_ids.get(track.track_id, track.track_id)]
            edits[id(chunk)] = replace(
                chunk,
                header=replace(
                    chunk.header,
                    artwork_id_ref=0,
                    artwork_count=0,
                    artwork_size=0,
                    has_artwork=0,
                ),
            )
        return rebuild(itunes, edits), None, (), ()
    image_datasets = tuple(
        s for s in artwork.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 1
    )
    if len(image_datasets) != 1:
        raise ValueError("Artwork changes require exactly one image dataset.")
    image_dataset = image_datasets[0]
    file_datasets = tuple(
        s for s in artwork.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 3
    )
    if assets and len(file_datasets) != 1:
        raise ValueError("Artwork encoding requires exactly one file-format dataset.")
    format_entries = (
        tuple(s.chunk.header for s in file_datasets[0].find_chunks(MhifHeader))
        if len(file_datasets) == 1
        else ()
    )
    if assets and len({f.format_id for f in format_entries}) != len(format_entries):
        raise ValueError("Artwork file-format entries contain duplicate format IDs.")
    retained_sizes = {f.format_id: f.image_size for f in format_entries}
    rows = {
        s.chunk.header.image_id: s.chunk for s in image_dataset.find_chunks(MhiiHeader)
    }
    index = build_artwork_index(artwork)
    inventory = (
        {}
        if resources.file_inventory is None
        else {f.relative_path: f for f in resources.file_inventory}
    )
    source_files = {f.dependency.relative_path: f for f in resources.files}
    output_files: dict[str, bytearray] = {}
    all_paths = set(inventory)
    if len({p.casefold() for p in all_paths}) != len(all_paths):
        raise ValueError(
            "Artwork file inventory contains case-insensitive path collisions."
        )
    formats = {f.format_id: f for f in target.cover_formats}
    next_id = max(
        artwork.header.next_mhii_id,
        max(rows, default=0) + 1,
        max((chunk.header.artwork_id_ref for chunk in track_chunks.values()), default=0)
        + 1,
        1,
    )
    art_mappings: list[IdentityMapping] = []
    resolved_assets: dict[int, int] = {}
    file_sizes: dict[int, int] = {}
    corrected_sizes: dict[int, int] = {}
    modified_owners = {
        track_chunks[native_ids.get(t.track_id, t.track_id)].header.db_track_id
        for t in changed
    }
    modified_owners.update(
        details.db_track_id for t in deleted if (details := before[t].ipod) is not None
    )
    # Clear every old reverse link; direct references of other Tracks remain.
    for identity, row in tuple(rows.items()):
        if row.header.db_track_id_ref and row.header.db_track_id_ref in modified_owners:
            rows[identity] = replace(row, header=replace(row.header, db_track_id_ref=0))

    def append_image(format_id: int, payload: bytes) -> tuple[str, int]:
        if resources.file_inventory is None:
            raise ValueError("Artwork encoding requires a captured file inventory.")
        if len(payload) > target.max_artwork_file_bytes:
            raise ValueError("One thumbnail exceeds the artwork file size limit.")
        # Use only the established F<format>_<shard>.ithmb namespace. The full
        # inventory reserves even files not referenced by the database.
        number = 1
        while True:
            path = f"iPod_Control/Artwork/F{format_id}_{number}.ithmb"
            collision = next(
                (p for p in all_paths if p.casefold() == path.casefold()), None
            )
            if collision is not None:
                path = collision
            prefix = output_files.get(path)
            if prefix is None and path in inventory:
                if aligned_offset(inventory[path].size, len(payload)) + len(
                    payload
                ) > min(target.max_artwork_file_bytes, 0xFFFFFFFF):
                    number += 1
                    continue
                source = source_files.get(path)
                if source is None:
                    raise ValueError(
                        f"Supply verified source bytes before appending to {path}."
                    )
                dependency = inventory[path]
                if (
                    source.dependency != dependency
                    or len(source.data) != dependency.size
                    or hashlib.sha256(source.data).hexdigest() != dependency.sha256
                ):
                    raise ValueError(
                        f"The captured source fingerprint changed for {path}."
                    )
                prefix = bytearray(source.data)
            if prefix is None:
                prefix = bytearray()
            offset = aligned_offset(len(prefix), len(payload))
            if offset + len(payload) <= min(target.max_artwork_file_bytes, 0xFFFFFFFF):
                prefix.extend(bytes(offset - len(prefix)))
                prefix.extend(payload)
                output_files[path] = prefix
                all_paths.add(path)
                return path, offset
            number += 1

    track_edits: dict[int, ParsedChunk[ChunkHeader] | None] = {}
    for track in changed:
        chunk = track_chunks[native_ids.get(track.track_id, track.track_id)]
        requested = track.artwork_id
        if requested == 0:
            track_edits[id(chunk)] = replace(
                chunk,
                header=replace(
                    chunk.header,
                    artwork_id_ref=0,
                    artwork_count=0,
                    artwork_size=0,
                    has_artwork=0,
                ),
            )
            continue
        if requested in resolved_assets:
            image_id = resolved_assets[requested]
        elif requested not in assets:
            if requested not in rows:
                raise ValueError(f"Artwork {requested} requires an RGB888 asset.")
            image_id = requested
        else:
            if not formats:
                raise ValueError("This target has no supported cover formats.")
            pixels = assets[requested]
            old_id = (
                before[track.track_id].artwork_id if track.track_id in before else 0
            )
            source_row = rows.get(old_id)
            if source_row:
                source_item = index.item_for_image_id(old_id)
                container_count = sum(
                    isinstance(c.payload, MhodContainerPayload)
                    for c in source_row.children
                )
                if (
                    source_item is None
                    or container_count != len(source_item.locations)
                    or len({location.format_id for location in source_item.locations})
                    != len(source_item.locations)
                ):
                    raise ValueError(
                        "The artwork being replaced has malformed or duplicate image representations."
                    )
                if source_item and any(
                    location.format_id not in formats
                    for location in source_item.locations
                ):
                    raise ValueError(
                        "Artwork replacement would leave an unsupported representation stale."
                    )
            image_id, next_id = next_id, next_id + 1
            if next_id > 0xFFFFFFFF:
                raise ValueError("Artwork identities are exhausted.")
            row = source_row or new_artwork_chunk(MHII, MhiiHeader())
            children = list(row.children)
            for cover in formats.values():
                layout = IthmbLayout(
                    cover.width, cover.height, cover.row_bytes, cover.pixel_format
                )
                encoded = encode_ithmb(
                    DecodedImage(pixels.width, pixels.height, pixels.rgb888), layout
                )
                if cover.format_id in retained_sizes and retained_sizes[
                    cover.format_id
                ] != len(encoded):
                    retained_size = retained_sizes[cover.format_id]
                    try:
                        _validate_retained_artwork_format(
                            artwork, cover, len(encoded), resources
                        )
                    except ValueError as error:
                        raise ValueError(
                            f"Artwork format {cover.format_id} retains MHIF image size {retained_size}; "
                            f"expected {len(encoded)}. Automatic correction is unsafe: {error}"
                        ) from error
                    corrected_sizes[cover.format_id] = len(encoded)
                    retained_sizes[cover.format_id] = len(encoded)
                    logger.info(
                        "Automatically corrected retained MHIF image size during artwork preparation: format=%d old_size=%d new_size=%d",
                        cover.format_id,
                        retained_size,
                        len(encoded),
                    )
                if cover.format_id in file_sizes and file_sizes[cover.format_id] != len(
                    encoded
                ):
                    raise ValueError(
                        "Artwork files require a consistent image size for each format."
                    )
                decoded = decode_ithmb(encoded, layout)
                if (decoded.width, decoded.height) != (cover.width, cover.height):
                    raise ValueError("Encoded artwork failed raster verification.")
                path, offset = append_image(cover.format_id, encoded)
                logger.debug(
                    "Artwork encoded id=%d format=%d path=%r offset=%d bytes=%d",
                    image_id,
                    cover.format_id,
                    path,
                    offset,
                    len(encoded),
                )
                file_sizes[cover.format_id] = len(encoded)
                match = next(
                    (
                        i
                        for i, c in enumerate(children)
                        if isinstance(c.payload, MhodContainerPayload)
                        and c.payload.child.header.format_id == cover.format_id
                    ),
                    None,
                )
                prior_child = children[match] if match is not None else None
                location = (
                    prior_child.payload.child
                    if prior_child
                    and isinstance(prior_child.payload, MhodContainerPayload)
                    else new_artwork_chunk(MHNI, MhniHeader())
                )
                names = list(location.children)
                name_index = next(
                    (
                        i
                        for i, c in enumerate(names)
                        if isinstance(c.payload, MhodStringPayload)
                        and isinstance(c.header, MhodHeader)
                        and c.header.mhod_type == ArtworkMhodType.FILE_NAME
                    ),
                    None,
                )
                file_name = ":" + path.rsplit("/", 1)[-1]
                if name_index is None:
                    names.append(new_string_mhod(ArtworkMhodType.FILE_NAME, file_name))
                else:
                    name_chunk = names[name_index]
                    assert isinstance(name_chunk.payload, MhodStringPayload)
                    names[name_index] = replace(
                        name_chunk, payload=replace(name_chunk.payload, value=file_name)
                    )
                location = replace(
                    location,
                    header=replace(
                        location.header,
                        format_id=cover.format_id,
                        ithmb_offset=offset,
                        image_size=len(encoded),
                        image_size_2=len(encoded),
                        image_width=cover.width,
                        image_height=cover.height,
                        horizontal_padding=0,
                        vertical_padding=0,
                    ),
                    children=tuple(names),
                )
                if prior_child and isinstance(
                    prior_child.payload, MhodContainerPayload
                ):
                    replacement = replace(
                        prior_child,
                        payload=replace(prior_child.payload, child=location),
                    )
                    assert match is not None
                    children[match] = replacement
                else:
                    auxiliary_index = next(
                        (
                            i
                            for i, child in enumerate(children)
                            if isinstance(child.header, MhodHeader)
                            and child.header.mhod_type
                            == ArtworkMhodType.UNKNOWN_CONTAINER_6
                            and not isinstance(child.payload, MhodContainerPayload)
                        ),
                        len(children),
                    )
                    children.insert(
                        auxiliary_index,
                        new_container_mhod(ArtworkMhodType.THUMBNAIL_IMAGE, location),
                    )
            if source_row is None:
                children.append(new_auxiliary_mhod())
            rows[image_id] = replace(
                row,
                header=replace(
                    row.header,
                    image_id=image_id,
                    db_track_id_ref=0,
                    source_image_size=len(pixels.rgb888),
                ),
                children=tuple(children),
            )
            resolved_assets[requested] = image_id
            art_mappings.append(IdentityMapping("artwork", requested, image_id))
        header_size = len(chunk.raw_header) or chunk.generic_header.header_length
        direct_link = _ARTWORK_LINK.offset + _ARTWORK_LINK.size <= header_size
        row = rows[image_id]
        owner = chunk.header.db_track_id
        if not owner:
            raise ValueError("Artwork requires a nonzero Track database identity.")
        if (
            not direct_link or not target.supports_sparse_artwork
        ) and row.header.db_track_id_ref not in (0, owner):
            # Keep the other Track's image and pixels. This Track receives its
            # own MHII identity and reverse link, sharing immutable byte ranges.
            image_id, next_id = next_id, next_id + 1
            if next_id > 0xFFFFFFFF:
                raise ValueError("Artwork identities are exhausted.")
            row = replace(
                row,
                header=replace(row.header, image_id=image_id, db_track_id_ref=owner),
            )
            art_mappings.append(
                IdentityMapping("artwork", requested, image_id, track_id=track.track_id)
            )
        elif not row.header.db_track_id_ref:
            row = replace(row, header=replace(row.header, db_track_id_ref=owner))
        rows[image_id] = row
        item_count = sum(
            isinstance(c.payload, MhodContainerPayload) for c in row.children
        )
        track_edits[id(chunk)] = replace(
            chunk,
            header=replace(
                chunk.header,
                artwork_id_ref=image_id if direct_link else 0,
                artwork_count=item_count,
                has_artwork=int(item_count > 0),
                artwork_size=rows[image_id].header.source_image_size,
            ),
        )
    itunes = rebuild(itunes, track_edits)
    container = image_dataset.chunk.children[0]
    remaining = dict(rows)
    final_children = tuple(
        remaining.pop(c.header.image_id) if isinstance(c.header, MhiiHeader) else c
        for c in container.children
    )
    artwork = artwork.replace_chunk(
        image_dataset,
        replace(
            image_dataset.chunk,
            children=(
                replace(container, children=(*final_children, *remaining.values())),
            ),
        ),
    )
    if art_mappings:
        artwork = replace(artwork, header=replace(artwork.header, next_mhii_id=next_id))
    file_dataset = next(
        (
            s
            for s in artwork.find_chunks(MhsdHeader)
            if s.chunk.header.dataset_type == 3
        ),
        None,
    )
    if file_dataset:
        existing_formats = {
            s.chunk.header.format_id for s in file_dataset.find_chunks(MhifHeader)
        }
        container = file_dataset.chunk.children[0]
        for selection in container.find_chunks(MhifHeader):
            size = corrected_sizes.get(selection.chunk.header.format_id)
            if size is not None:
                container = container.replace_chunk(
                    selection,
                    replace(
                        selection.chunk,
                        header=replace(selection.chunk.header, image_size=size),
                    ),
                )
        for format_id, size in file_sizes.items():
            if format_id not in existing_formats:
                container = container.append_child(
                    new_artwork_chunk(
                        MHIF, MhifHeader(format_id=format_id, image_size=size)
                    )
                )
        artwork = artwork.replace_chunk(
            file_dataset, replace(file_dataset.chunk, children=(container,))
        )
    folded_inventory = {p.casefold(): f for p, f in inventory.items()}
    folded_outputs = {p.casefold() for p in output_files}
    for source_item in index.items:
        for retained_location in source_item.locations:
            if not output_files:
                continue
            retained_path = artwork_path(retained_location.file_name)
            if retained_path.casefold() in folded_outputs:
                dependency = folded_inventory.get(retained_path.casefold())
                if (
                    dependency is None
                    or retained_location.offset + retained_location.byte_length
                    > dependency.size
                ):
                    raise ValueError(
                        f"A retained image range is outside the captured prefix of {retained_path}."
                    )
    return (
        itunes,
        artwork,
        tuple(PreparedFile(path, bytes(data)) for path, data in output_files.items()),
        tuple(art_mappings),
    )


def aligned_offset(size: int, frame_size: int) -> int:
    """Append complete fixed-size frames without changing a retained prefix."""
    return ((size + frame_size - 1) // frame_size) * frame_size
