"""Mix-owned images, separate from Track artwork and its identities.

Classic uses F1069 and Nano 7 uses F1010, with reverse lookup by the Mix ID.
Retired images keep their immutable pixels/ranges, as with Track cover changes;
only their reverse link is cleared. No unrelated record or file is removed.
"""

from dataclasses import replace

from iPodDB.ArtworkDB.builder.build_ArtworkDB import (
    new_artwork_chunk,
    new_ArtworkDB,
    new_container_mhod,
    new_string_mhod,
)
from iPodDB.ArtworkDB.ithmb import DecodedImage, IthmbLayout, IthmbPixelFormat
from iPodDB.ArtworkDB.ithmb_writer import encode_ithmb
from iPodDB.ArtworkDB.shared.artwork_index import build_artwork_index
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import DEFINITION as MHIF
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import DEFINITION as MHII
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import DEFINITION as MHNI
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.ArtworkDB.shared.constants import ArtworkMhodType
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.library._artwork_paths import artwork_path
from iPodDB.library._document_edit import rebuild
from iPodDB.library.artwork import CoverFormat
from iPodDB.library.file_content import read_content
from iPodDB.library.writing import (
    GeniusMixArtwork,
    PreparedFile,
    WriteResources,
    WriteTarget,
)
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk


def reconcile_mix_artwork(
    original_itunes: DatabaseDocument[MhbdHeader],
    itunes: DatabaseDocument[MhbdHeader],
    artwork: DatabaseDocument[MhfdHeader] | None,
    updates: tuple[GeniusMixArtwork, ...],
    target: WriteTarget,
    resources: WriteResources,
    files: tuple[PreparedFile, ...],
    *,
    sqlite_mix_ids: tuple[frozenset[int], frozenset[int]] | None = None,
) -> tuple[DatabaseDocument[MhfdHeader] | None, tuple[PreparedFile, ...], set[int]]:
    if not updates:
        return artwork, files, set()
    cover = target.genius_mix_artwork_format
    expected = (
        CoverFormat(1010, 240, 240, 480, IthmbPixelFormat.RGB565_LE)
        if target.sqlite_database
        else CoverFormat(1069, 142, 142, 284, IthmbPixelFormat.RGB565_LE)
    )
    if (
        cover is None
        or cover != expected
        or not (target.classic_genius_mixes or target.sqlite_database)
    ):
        raise ValueError("Mix artwork requires a qualified native image format")
    payload_size = cover.row_bytes * cover.height
    if resources.file_inventory is None:
        raise ValueError("Mix artwork requires a captured artwork inventory")
    ids = [u.mix_id for u in updates]
    if len(set(ids)) != len(ids) or any(
        type(i) is not int or not 0 < i < 1 << 64 for i in ids
    ):
        raise ValueError("Mix artwork requires unique nonzero 64-bit Mix identities")
    mixes = {
        s.chunk.header.playlist_id
        for s in itunes.find_chunks(MhypHeader)
        if s.chunk.header.is_genius_mix
    }
    old_mixes = {
        s.chunk.header.playlist_id
        for s in original_itunes.find_chunks(MhypHeader)
        if s.chunk.header.is_genius_mix
    }
    if target.sqlite_database:
        if sqlite_mix_ids is None:
            raise ValueError(
                "Nano Mix artwork requires captured and prepared SQLite Mix identities"
            )
        old_mixes, mixes = map(set, sqlite_mix_ids)
    if not target.sqlite_database and len({i & 0xFFFFFFFF for i in mixes}) != len(
        mixes
    ):
        raise ValueError(
            "Mix identities collide in the firmware's 32-bit artwork cache"
        )
    tracks = {
        s.chunk.header.db_track_id for s in original_itunes.find_chunks(MhitHeader)
    }
    tracks.update(s.chunk.header.db_track_id for s in itunes.find_chunks(MhitHeader))
    if set(ids) & tracks:
        raise ValueError("A Mix artwork identity collides with a Track identity")
    if any(u.mix_id not in mixes | old_mixes for u in updates):
        raise ValueError("Mix artwork refers to an unknown native Mix")
    if artwork is None:
        if not any(u.pixels is not None and u.mix_id in mixes for u in updates):
            return None, files, set()
        if target.artwork_root_value is None:
            raise ValueError("Mix artwork needs an explicit ArtworkDB creation policy")
        artwork = new_ArtworkDB(
            next_mhii_id=100, unk_mhfd_0x10=target.artwork_root_value
        )
    images = tuple(s.chunk for s in artwork.find_chunks(MhiiHeader))
    if len({row.header.image_id for row in images}) != len(images):
        raise ValueError("ArtworkDB contains duplicate image identities")
    datasets = {
        kind: tuple(
            s.chunk
            for s in artwork.find_chunks(MhsdHeader)
            if s.chunk.header.dataset_type == kind
        )
        for kind in (1, 3)
    }
    if any(len(rows) != 1 or len(rows[0].children) != 1 for rows in datasets.values()):
        raise ValueError("Mix covers require one image and file-format dataset")
    linked = {
        pid: tuple(row for row in images if row.header.db_track_id_ref == pid)
        for pid in ids
    }
    if any(len(rows) > 1 for rows in linked.values()):
        raise ValueError("Mix artwork reverse identity is ambiguous")
    direct = {s.chunk.header.artwork_id_ref for s in itunes.find_chunks(MhitHeader)}
    if any(row.header.image_id in direct for rows in linked.values() for row in rows):
        raise ValueError(
            "Mix cover is also referenced by a Track; preserve its ownership"
        )
    index = build_artwork_index(artwork)
    source_files = {
        f.dependency.relative_path.casefold(): f.data for f in resources.files
    }
    source_files.update({f.relative_path.casefold(): f.data for f in files})
    reserved = {f.relative_path.casefold() for f in resources.file_inventory}
    reserved.update(f.relative_path.casefold() for f in files)
    reserved.update(
        artwork_path(p).casefold() for p in resources.reserved_artwork_paths
    )
    reserved.update(
        artwork_path(loc.file_name).casefold()
        for item in index.items
        for loc in item.locations
    )
    next_id = max(
        artwork.header.next_mhii_id,
        max((r.header.image_id for r in images), default=99) + 1,
        max(direct, default=0) + 1,
    )
    changes: dict[int, ParsedChunk[ChunkHeader] | None] = {}
    additions: list[ParsedChunk[ChunkHeader]] = []
    output: list[PreparedFile] = []
    generated: set[int] = set()
    layout = IthmbLayout(cover.width, cover.height, cover.row_bytes, cover.pixel_format)
    for update in updates:
        prior = next(iter(linked[update.mix_id]), None)
        pixels = update.pixels if update.mix_id in mixes else None
        encoded = (
            None
            if pixels is None
            else encode_ithmb(
                DecodedImage(pixels.width, pixels.height, pixels.rgb888),
                layout,
            )
        )
        if prior is not None and encoded is not None:
            item = index.item_for_image_id(prior.header.image_id)
            location = (
                next(
                    (
                        loc
                        for loc in item.locations
                        if loc.format_id == cover.format_id and loc.display_time_ms == 0
                    ),
                    None,
                )
                if item
                else None
            )
            data = (
                source_files.get(artwork_path(location.file_name).casefold())
                if location
                else None
            )
            if (
                location is not None
                and data is not None
                and (
                    location.width,
                    location.height,
                    location.horizontal_padding,
                    location.vertical_padding,
                )
                == (cover.width, cover.height, 0, 0)
                and location.byte_length == len(encoded)
                and (location.offset + location.byte_length <= len(data))
                and read_content(data, location.offset, location.byte_length) == encoded
            ):
                continue
        if prior is not None:
            changes[id(prior)] = replace(
                prior, header=replace(prior.header, db_track_id_ref=0)
            )
        if encoded is None:
            continue
        if len(encoded) > target.max_artwork_file_bytes or next_id >= 0xFFFFFFFF:
            raise ValueError("Mix artwork exceeds the target's file or identity limit")
        shard = 1
        while (
            path := f"iPod_Control/Artwork/F{cover.format_id}_{shard}.ithmb"
        ).casefold() in reserved:
            shard += 1
        reserved.add(path.casefold())
        output.append(PreparedFile(path, encoded))
        thumbnail = new_artwork_chunk(
            MHNI,
            MhniHeader(
                format_id=cover.format_id,
                image_width=cover.width,
                image_height=cover.height,
                image_size=len(encoded),
                image_size_2=len(encoded),
            ),
            children=(
                new_string_mhod(
                    ArtworkMhodType.FILE_NAME, f":F{cover.format_id}_{shard}.ithmb"
                ),
            ),
        )
        additions.append(
            new_artwork_chunk(
                MHII,
                MhiiHeader(
                    image_id=next_id,
                    db_track_id_ref=update.mix_id,
                    source_image_size=len(pixels.rgb888) if pixels else 0,
                ),
                children=(
                    new_container_mhod(ArtworkMhodType.THUMBNAIL_IMAGE, thumbnail),
                ),
            )
        )
        generated.add(next_id)
        next_id += 1
    result = rebuild(artwork, changes)
    if additions:
        # Rebuild the list after clearing retired reverse links.
        image_list = next(
            s.chunk
            for s in result.find_chunks(MhsdHeader)
            if s.chunk.header.dataset_type == 1
        ).children[0]
        result = rebuild(
            result,
            {
                id(image_list): replace(
                    image_list, children=(*image_list.children, *additions)
                )
            },
        )
        format_rows = tuple(
            s.chunk
            for s in result.find_chunks(MhifHeader)
            if s.chunk.header.format_id == cover.format_id
        )
        if len(format_rows) > 1 or (
            format_rows and format_rows[0].header.image_size != payload_size
        ):
            raise ValueError("Retained Mix file-format metadata is inconsistent")
        if not format_rows:
            file_list = next(
                s.chunk
                for s in result.find_chunks(MhsdHeader)
                if s.chunk.header.dataset_type == 3
            ).children[0]
            result = rebuild(
                result,
                {
                    id(file_list): replace(
                        file_list,
                        children=(
                            *file_list.children,
                            new_artwork_chunk(
                                MHIF,
                                MhifHeader(
                                    format_id=cover.format_id, image_size=payload_size
                                ),
                            ),
                        ),
                    )
                },
            )
        result = replace(result, header=replace(result.header, next_mhii_id=next_id))
    return result, (*files, *output), generated


def verify_mix_artwork(
    itunes: DatabaseDocument[MhbdHeader],
    artwork: DatabaseDocument[MhfdHeader] | None,
    updates: tuple[GeniusMixArtwork, ...],
    resources: WriteResources,
    files: tuple[PreparedFile, ...],
    cover: CoverFormat | None,
    *,
    sqlite_mix_ids: frozenset[int] | None = None,
) -> None:
    """Reparse verification of identity, exact format and requested packed pixels."""
    if not updates:
        return
    if cover is None:
        raise ValueError("Mix artwork has no qualified format")
    mixes = {
        s.chunk.header.playlist_id
        for s in itunes.find_chunks(MhypHeader)
        if s.chunk.header.is_genius_mix
    }
    if sqlite_mix_ids is not None:
        mixes = set(sqlite_mix_ids)
    index = build_artwork_index(artwork) if artwork is not None else None
    data = {f.dependency.relative_path.casefold(): f.data for f in resources.files}
    data.update({f.relative_path.casefold(): f.data for f in files})
    for update in updates:
        item = index.item_for_db_track_id(update.mix_id) if index else None
        if update.pixels is None or update.mix_id not in mixes:
            if item is not None:
                raise ValueError("Removed Mix artwork retained its reverse link")
            continue
        locations = (
            tuple(
                loc
                for loc in item.locations
                if loc.format_id == cover.format_id and loc.display_time_ms == 0
            )
            if item
            else ()
        )
        if len(locations) != 1:
            raise ValueError("Mix cover has no unambiguous image")
        loc = locations[0]
        if (
            loc.format_id,
            loc.width,
            loc.height,
            loc.display_time_ms,
            loc.byte_length,
        ) != (
            cover.format_id,
            cover.width,
            cover.height,
            0,
            cover.row_bytes * cover.height,
        ):
            raise ValueError("Mix cover does not match its native layout")
        encoded = encode_ithmb(
            DecodedImage(
                update.pixels.width, update.pixels.height, update.pixels.rgb888
            ),
            IthmbLayout(cover.width, cover.height, cover.row_bytes, cover.pixel_format),
        )
        content = data.get(artwork_path(loc.file_name).casefold())
        if (
            content is None
            or loc.offset + loc.byte_length > len(content)
            or read_content(content, loc.offset, loc.byte_length) != encoded
        ):
            raise ValueError("Mix cover pixels do not match the requested artwork")
