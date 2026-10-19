"""Explicit Podcast Sync normalization; lossless loading never enters this path.

The 12.6 reference supplies relationships and creation defaults, not identities
to copy or a license to overwrite unrelated/unknown fields. See ADR-0152.
"""

from collections import defaultdict
from dataclasses import replace

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhia import DEFINITION as MHIA
from iPodDB.iTunesDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
    MhodStringPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library._browse_groups import podcast_groups
from iPodDB.library._document_edit import rebuild
from iPodDB.library._identities import IdentityAllocator
from iPodDB.library._playlist_datasets import playlist_rows
from iPodDB.library._projection import project_tracks
from iPodDB.library._track_header_expansion import field_fits
from iPodDB.library._track_writing import edit_text
from iPodDB.shared.binary_struct import binary_fields
from iPodDB.shared.chunk import (
    ChunkHeader,
    DatabaseDocument,
    GenericHeader,
    ParsedChunk,
)


def album_text(row: ParsedChunk[ChunkHeader], kind: MhodType) -> str:
    return next(
        (
            c.payload.value
            for c in row.children
            if isinstance(c.header, MhodHeader)
            and c.header.mhod_type == kind
            and isinstance(c.payload, MhodStringPayload)
        ),
        "",
    )


def _merge_album(
    canonical: ParsedChunk[MhiaHeader], other: ParsedChunk[MhiaHeader]
) -> ParsedChunk[MhiaHeader]:
    """Carry private header bytes and metadata into the surviving album row.

    Conflicting private bytes cannot safely share a slot: reject the operation,
    rather than discard either source. Known album identities are explicitly merged.
    """
    size = max(len(canonical.raw_header), len(other.raw_header))
    merged = bytearray(canonical.raw_header.ljust(size, b"\0"))
    known = {
        i
        for header in (GenericHeader, MhiaHeader)
        for f in binary_fields(header)
        for i in range(f.schema.offset, f.schema.offset + f.schema.size)
    }
    for offset, value in enumerate(other.raw_header):
        if offset in known or not value:
            continue
        if merged[offset] not in (0, value):
            raise ValueError(
                "Duplicate Podcast albums have conflicting private header data."
            )
        merged[offset] = value
    header = canonical.header
    # Ratings and flags belong to the user. A duplicate may carry the only
    # populated value; conflicting retained values need an explicit decision.
    values: dict[str, int] = {}
    for name in (
        "album_compilation_flag",
        "album_rating",
        "rating_flag",
        "season_number",
    ):
        retained_value = getattr(header, name)
        other_value = getattr(other.header, name)
        if not other.raw_header and name == "season_number":
            continue  # A new Episode's season does not redefine its show.
        if retained_value and other_value and retained_value != other_value:
            raise ValueError("Duplicate Podcast albums have conflicting header values.")
        values[name] = retained_value or other_value
    header = replace(header, **values)
    children = list(canonical.children)
    for child in other.children:
        matching = [
            c
            for c in children
            if c.header == child.header
            and c.prefix == child.prefix
            and c.payload == child.payload
            and c.raw_header == child.raw_header
            and c.raw_body == child.raw_body
        ]
        if matching:
            continue
        if (
            isinstance(child.header, MhodHeader)
            and 200 <= child.header.mhod_type <= 204
        ):
            retained = next(
                (
                    c
                    for c in children
                    if isinstance(c.header, MhodHeader)
                    and c.header.mhod_type == child.header.mhod_type
                ),
                None,
            )
            # Preserve full metadata records with private differences. Conflicting
            # text cannot be normalized implicitly.
            if retained is not None:
                if not child.raw_header and child.header.mhod_type in (201, 202, 204):
                    # A new Episode may have a different artist or season. Show
                    # identity comes from the feed, not those display fields.
                    continue
                if retained.payload != child.payload:
                    raise ValueError(
                        "Duplicate Podcast albums have conflicting metadata."
                    )
                if (
                    not child.raw_header
                    and retained.header == child.header
                    and isinstance(retained.prefix, MhodStringPrefix)
                    and isinstance(child.prefix, MhodStringPrefix)
                    and replace(retained.prefix, string_length=0)
                    == replace(child.prefix, string_length=0)
                ):
                    # String length is serialized from the payload; a freshly
                    # authored duplicate has no private source bytes to retain.
                    continue
        children.append(child)
    return replace(
        canonical,
        header=header,
        raw_header=bytes(merged),
        generic_header=replace(
            canonical.generic_header,
            header_length=max(
                canonical.generic_header.header_length,
                other.generic_header.header_length,
            ),
        ),
        children=tuple(children),
    )


def normalize_albums(
    document: DatabaseDocument[MhbdHeader],
) -> DatabaseDocument[MhbdHeader]:
    """One album per unambiguous Podcast show, with a valid representative."""
    tracks = project_tracks(document)
    groups = podcast_groups(tracks)
    if not groups:
        return document
    dataset = next(
        (
            s
            for s in document.find_chunks(MhsdHeader)
            if s.chunk.header.dataset_type == 4
        ),
        None,
    )
    if dataset is None:
        return document  # Album datasets are optional on older devices.
    rows = [s.chunk for s in dataset.find_chunks(MhiaHeader)]
    by_id = {r.header.album_id: r for r in rows}
    if len(by_id) != len(rows):
        raise ValueError(
            "Podcast album normalization requires unique native album IDs."
        )
    owners: dict[int, set[int]] = defaultdict(set)
    for track in tracks:
        if track.ipod:
            owners[track.ipod.album_id].add(track.track_id)
    allocator = IdentityAllocator(by_id, 32)
    sql = IdentityAllocator((r.header.sql_id for r in rows), 64)
    edits: dict[int, ParsedChunk[ChunkHeader] | None] = {}
    additions: list[ParsedChunk[MhiaHeader]] = []
    assigned: dict[int, int] = {}
    for title, members in groups.items():
        member_ids = {t.track_id for t in members}
        references = {t.ipod.album_id for t in members if t.ipod and t.ipod.album_id}
        if any(owners[ref] - member_ids for ref in references):
            raise ValueError("A Podcast album also belongs to another browse group.")
        if references - by_id.keys():
            raise ValueError("A Podcast Track references a missing album record.")
        feed = next(
            (t.metadata.podcast_rss_url for t in members if t.metadata.podcast_rss_url),
            "",
        )
        candidates = [
            r
            for r in rows
            if r.header.album_id in references
            or (
                not owners[r.header.album_id]
                and album_text(r, MhodType.ALBUM_ITEM_ALBUM) == title
                and album_text(r, MhodType.ALBUM_ITEM_PODCAST_URL) in ("", feed)
                and (
                    album_text(r, MhodType.ALBUM_ITEM_PODCAST_URL)
                    or all(
                        isinstance(c.header, MhodHeader) and c.header.mhod_type == 200
                        for c in r.children
                    )
                )
                and not r.header.album_track_db_id
            )
        ]
        persistent = {t.ipod.db_track_id for t in members if t.ipod}
        if not persistent or 0 in persistent:
            raise ValueError(
                "Podcast album representatives require persistent Track identities."
            )
        if candidates:
            candidates.sort(
                key=lambda r: (
                    not bool(album_text(r, MhodType.ALBUM_ITEM_PODCAST_URL)),
                    r.header.album_id not in references,
                    r.header.album_id,
                )
            )
            canonical = candidates[0]
            for other in candidates[1:]:
                canonical = _merge_album(canonical, other)
                edits[id(other)] = None
        else:
            canonical = new_itunes_chunk(
                MHIA, MhiaHeader(album_id=allocator.take(), sql_id=sql.take())
            )
        canonical = edit_text(canonical, MhodType.ALBUM_ITEM_ALBUM, title)
        if feed:
            canonical = edit_text(canonical, MhodType.ALBUM_ITEM_PODCAST_URL, feed)
        canonical = replace(
            canonical,
            header=replace(
                canonical.header,
                content_type_flag=3,
                album_track_db_id=canonical.header.album_track_db_id
                if canonical.header.album_track_db_id in persistent
                else min(persistent),
            ),
        )
        if candidates:
            edits[id(candidates[0])] = canonical
        else:
            additions.append(canonical)
        assigned.update((t.track_id, canonical.header.album_id) for t in members)
    for selection in document.find_chunks(MhitHeader):
        row = selection.chunk
        if row.header.track_id in assigned:
            edits[id(row)] = replace(
                row, header=replace(row.header, album_id=assigned[row.header.track_id])
            )
    document = rebuild(document, edits)
    if additions:
        dataset = next(
            s
            for s in document.find_chunks(MhsdHeader)
            if s.chunk.header.dataset_type == 4
        )
        container = dataset.chunk.children[0]
        document = document.replace_chunk(
            dataset,
            replace(
                dataset.chunk,
                children=(
                    replace(container, children=(*container.children, *additions)),
                ),
            ),
        )
    return document


def normalize_identities(
    document: DatabaseDocument[MhbdHeader],
) -> DatabaseDocument[MhbdHeader]:
    """Populate missing show identities and the retained root's Podcast references."""
    groups = podcast_groups(project_tracks(document))
    if not groups:
        return document
    podcast_ids = {t.track_id for members in groups.values() for t in members}
    used = {
        document.header.db_id,
        document.header.db_id_2,
        document.header.db_persistent_id,
    }
    for row in document.find_chunks(MhitHeader):
        used.update((row.chunk.header.db_track_id, row.chunk.header.db_track_id_2))
    for playlist in document.find_chunks(MhypHeader):
        used.add(playlist.chunk.header.playlist_id)
    for occurrence in document.find_chunks(MhipHeader):
        used.update(
            (
                occurrence.chunk.header.group_persistent_id,
                occurrence.chunk.header.mhip_persistent_id,
            )
        )
    allocator = IdentityAllocator(used, 64)
    root_id = document.header.db_id_2 or allocator.take()
    document = replace(document, header=replace(document.header, db_id_2=root_id))
    edits: dict[int, ParsedChunk[ChunkHeader] | None] = {}
    for row in document.find_chunks(MhitHeader):
        chunk = row.chunk
        if chunk.header.track_id in podcast_ids and field_fits(
            "db_id_2_ref", chunk.generic_header.header_length
        ):
            edits[id(chunk)] = replace(
                chunk, header=replace(chunk.header, db_id_2_ref=root_id)
            )
    for kind, playlist in playlist_rows(document):
        chunk_playlist = playlist.chunk
        if (
            kind not in (2, 3)
            or not chunk_playlist.header.playlist_kind_flags & 1
            or chunk_playlist.header.playlist_kind_flags & 0x100
        ):
            continue
        children: list[ParsedChunk[ChunkHeader]] = []
        for item in chunk_playlist.children:
            if (
                kind == 3
                and isinstance(item.header, MhipHeader)
                and item.header.podcast_group_flag & 0x100
            ):
                item = replace(
                    item,
                    header=replace(
                        item.header,
                        group_persistent_id=item.header.group_persistent_id
                        or allocator.take(),
                        # Observed creation seed only; preserve 0x8101 and other
                        # populated opaque values without inventing their semantics.
                        unk_mhip_0x12=item.header.unk_mhip_0x12 or 0x8001,
                    ),
                )
            children.append(item)
        edits[id(chunk_playlist)] = replace(
            chunk_playlist,
            header=replace(
                chunk_playlist.header,
                db_id_2=root_id,
                phase_game_flag=(chunk_playlist.header.phase_game_flag & ~0x1FF)
                | 0x10B,
            ),
            children=tuple(children),
        )
    return rebuild(document, edits)


def remove_empty_artists(
    document: DatabaseDocument[MhbdHeader],
) -> DatabaseDocument[MhbdHeader]:
    """Discard only unowned, content-free artist stubs; retain private evidence."""
    owners = {s.chunk.header.artist_id_ref for s in document.find_chunks(MhitHeader)}
    known = {
        i
        for header in (GenericHeader, MhiiHeader)
        for f in binary_fields(header)
        for i in range(f.schema.offset, f.schema.offset + f.schema.size)
    }
    edits: dict[int, ParsedChunk[ChunkHeader] | None] = {}
    for selection in document.find_chunks(MhiiHeader):
        row = selection.chunk
        if (
            row.header.artist_id not in owners
            and row.header.content_type_flag == 2
            and not row.children
            and not row.raw_body
            and not row.raw_trailing_data
            and not row.raw_source_suffix
            and not any(
                value for i, value in enumerate(row.raw_header) if i not in known
            )
        ):
            edits[id(row)] = None
    return rebuild(document, edits)
