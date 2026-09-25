"""Maintain firmware browse structures affected by semantic Track edits."""

import logging
from collections import Counter, defaultdict
from dataclasses import replace

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhia import DEFINITION as MHIA
from iPodDB.iTunesDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhii import DEFINITION as MHII
from iPodDB.iTunesDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPayload,
    MhodLibraryIndexPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_jump_table_mhod import (
    MhodLibraryJumpTablePayload,
    MhodLibraryJumpTablePrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library._album_index import master_tracks
from iPodDB.library._browse_groups import album_values, browse_groups, group_key
from iPodDB.library._browse_index import BrowseIndex, resolve_indexes
from iPodDB.library._document_edit import rebuild
from iPodDB.library._identities import IdentityAllocator
from iPodDB.library._playlist_datasets import is_master, playlist_rows
from iPodDB.library._track_writing import edit_text
from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.writing import WriteIssue
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk

logger = logging.getLogger(__name__)


def ensure_master_indexes(
    document: DatabaseDocument[MhbdHeader],
    desired: LibrarySnapshot,
    existing: frozenset[tuple[int, int]],
    indexes: tuple[BrowseIndex, ...],
    *,
    structural_tracks: bool,
) -> DatabaseDocument[MhbdHeader]:
    """Generate missing standard browse pairs for new or structurally edited Masters."""
    index_map = {i.sort_type: i for i in indexes}
    if not desired.tracks:
        return document
    for kind, selection in playlist_rows(document):
        chunk = selection.chunk
        if not is_master(kind, chunk.header) or (
            not structural_tracks and (kind, chunk.header.playlist_id) in existing
        ):
            continue
        present = {
            (c.header.mhod_type, c.prefix.sort_type)
            for c in chunk.children
            if isinstance(c.header, MhodHeader)
            and isinstance(
                c.prefix, MhodLibraryIndexPrefix | MhodLibraryJumpTablePrefix
            )
        }
        children = list(chunk.children)
        for sort_type in (3, 5, 4, 7, 0x12):
            index = index_map[sort_type]
            if (52, sort_type) not in present:
                children.append(
                    new_itunes_chunk(
                        MHOD,
                        MhodHeader(mhod_type=52),
                        prefix=MhodLibraryIndexPrefix(sort_type=sort_type),
                        payload=MhodLibraryIndexPayload(index.order, b""),
                    )
                )
            if (53, sort_type) not in present:
                children.append(
                    new_itunes_chunk(
                        MHOD,
                        MhodHeader(mhod_type=53),
                        prefix=MhodLibraryJumpTablePrefix(sort_type=sort_type),
                        payload=MhodLibraryJumpTablePayload(index.jumps, b""),
                    )
                )
        # MHODs precede MHIPs in a playlist body.
        children.sort(key=lambda c: isinstance(c.header, MhipHeader))
        document = document.replace_chunk(
            selection, replace(chunk, children=tuple(children))
        )
    return document


def reconcile_hidden(
    document: DatabaseDocument[MhbdHeader],
    original: LibrarySnapshot,
    desired: LibrarySnapshot,
    track_ids: dict[int, int],
    issues: list[WriteIssue],
    indexes: tuple[BrowseIndex, ...],
) -> DatabaseDocument[MhbdHeader]:
    if original.tracks == desired.tracks:
        return document

    replacements: dict[int, ParsedChunk[ChunkHeader] | None] = {}
    index_map = {i.sort_type: i for i in indexes}
    indexes_affected = any(i.affected for i in indexes)
    native_desired = tuple(
        replace(t, track_id=track_ids[t.track_id]) for t in desired.tracks
    )
    master_index_cache = {tuple(t.track_id for t in native_desired): index_map}
    for dataset_kind, master in playlist_rows(document):
        if not indexes_affected:
            break
        if not is_master(dataset_kind, master.chunk.header):
            continue
        ordered_tracks = master_tracks(
            master.chunk,
            native_desired,
        )
        # MHOD 52 offsets address the Master's MHIPs, not the MHIT table.
        master_key = tuple(t.track_id for t in ordered_tracks)
        if len(master_key) != len(native_desired):
            # Preserve the existing treatment of incomplete source Masters;
            # source diagnostics and structural validation own those anomalies.
            master_key = tuple(t.track_id for t in native_desired)
        if master_key not in master_index_cache:
            master_index_cache[master_key] = {
                i.sort_type: i for i in resolve_indexes((), ordered_tracks)
            }
        master_indexes = master_index_cache[master_key]
        for selection in master.find_chunks(MhodHeader):
            chunk = selection.chunk
            prefix = chunk.prefix
            if not isinstance(
                prefix, MhodLibraryIndexPrefix | MhodLibraryJumpTablePrefix
            ):
                continue
            index = index_map.get(prefix.sort_type)
            if index is None or not index.affected:
                continue  # Resolution has already rejected affected unsupported indexes.
            index = master_indexes[prefix.sort_type]
            if isinstance(chunk.payload, MhodLibraryIndexPayload):
                replacements[id(chunk)] = replace(
                    chunk, payload=replace(chunk.payload, indices=index.order)
                )
            elif isinstance(chunk.payload, MhodLibraryJumpTablePayload):
                replacements[id(chunk)] = replace(
                    chunk, payload=replace(chunk.payload, entries=index.jumps)
                )
    document = rebuild(document, replacements)
    persistent_tracks = {
        s.chunk.header.track_id: s.chunk.header.db_track_id
        for s in document.find_chunks(MhitHeader)
    }
    deleted_persistent_ids = {
        t.ipod.db_track_id
        for t in original.tracks
        if t.ipod and t.track_id not in track_ids
    }
    browse_ids = {
        value
        for s in document.find_chunks(MhitHeader)
        for value in (
            s.chunk.header.album_id,
            s.chunk.header.artist_id_ref,
            s.chunk.header.composer_id,
        )
    }
    browse_ids.update(s.chunk.header.album_id for s in document.find_chunks(MhiaHeader))
    browse_ids.update(
        s.chunk.header.artist_id for s in document.find_chunks(MhiiHeader)
    )
    browse_allocator = IdentityAllocator(browse_ids, 32)
    sql_allocator = IdentityAllocator(
        (
            *tuple(s.chunk.header.sql_id for s in document.find_chunks(MhiaHeader)),
            *tuple(s.chunk.header.sql_id for s in document.find_chunks(MhiiHeader)),
        ),
        64,
    )
    # Album and artist datasets are optional in older formats. Retain unreferenced
    # records and their Unknown Data; only referenced groups are reconciled.
    for dataset_kind in (4, 8):
        dataset = next(
            (
                s
                for s in document.find_chunks(MhsdHeader)
                if s.chunk.header.dataset_type == dataset_kind
            ),
            None,
        )
        if dataset is None:
            logger.debug(
                "Library browse dataset=%d absent; retain native references",
                dataset_kind,
            )
            continue
        album = dataset_kind == 4
        rows = {
            c.header.album_id
            if isinstance(c.header, MhiaHeader)
            else c.header.artist_id: c
            for c in dataset.chunk.children[0].children
            if isinstance(c.header, MhiaHeader | MhiiHeader)
        }
        row_counts = Counter(
            c.header.album_id
            if isinstance(c.header, MhiaHeader)
            else c.header.artist_id
            for c in dataset.chunk.children[0].children
            if isinstance(c.header, MhiaHeader | MhiiHeader)
        )
        prior_members = browse_groups(original.tracks, album=album)

        original_groups: dict[tuple[str, ...], set[int]] = defaultdict(set)
        original_members: dict[tuple[str, ...], set[int]] = defaultdict(set)
        native_members: dict[int, set[int]] = defaultdict(set)
        for track in original.tracks:
            original_members[group_key(track, album=album)].add(track.track_id)
            if track.ipod:
                reference = track.ipod.album_id if album else track.ipod.artist_id_ref
                if reference:
                    original_groups[group_key(track, album=album)].add(reference)
                    native_members[reference].add(track.track_id)
        groups = browse_groups(desired.tracks, album=album)
        assigned: dict[int, int] = {}
        updated_rows = dict(rows)
        for key, members in groups.items():
            candidates = original_groups.get(key, set())
            if not candidates:
                previous_refs = {
                    t.ipod.album_id if album else t.ipod.artist_id_ref
                    for t in members
                    if t.ipod
                }
                if len(previous_refs) == 1 and native_members.get(
                    next(iter(previous_refs))
                ) == {t.track_id for t in members}:
                    candidates = previous_refs
            if original_members.get(key, set()) == {t.track_id for t in members} and (
                not album or album_values(prior_members[key]) == album_values(members)
            ):
                # A title, rating or other unrelated edit does not normalize the
                # retained album/artist representation or repair missing links.
                logger.debug(
                    "Library browse dataset=%d members=%d action=preserve identities=%s",
                    dataset_kind,
                    len(members),
                    sorted(candidates),
                )
                continue
            if len(candidates) > 1:
                # Existing duplicate groups are harmless until their fields or
                # membership change; keep each Track's existing association.
                if all(t in original.tracks for t in members):
                    continue
                issues.append(
                    WriteIssue(
                        "library.ambiguous_group",
                        "Album or artist group has conflicting source identities.",
                        field="album" if album else "artist",
                    )
                )
                continue
            identity = next(iter(candidates), 0)
            if row_counts[identity] > 1:
                issues.append(
                    WriteIssue(
                        "library.ambiguous_group",
                        "A changed browse group has repeated native records.",
                        field="album" if album else "artist",
                        detail=f"Dataset {dataset_kind}, native group {identity}.",
                    )
                )
                continue
            if identity and identity not in rows:
                issues.append(
                    WriteIssue(
                        "library.missing_group",
                        "A changed group references a missing source record.",
                        field="album" if album else "artist",
                    )
                )
                continue
            if not identity:
                identity = browse_allocator.take()
                row: ParsedChunk[ChunkHeader] = (
                    new_itunes_chunk(
                        MHIA, MhiaHeader(album_id=identity, sql_id=sql_allocator.take())
                    )
                    if album
                    else new_itunes_chunk(
                        MHII,
                        MhiiHeader(artist_id=identity, sql_id=sql_allocator.take()),
                    )
                )
            else:
                row = rows[identity]
            exemplar = members[0]
            if album:
                values = album_values(members)
                for kind, text_value in (
                    (MhodType.ALBUM_ITEM_ALBUM, values.title),
                    (MhodType.ALBUM_ITEM_ARTIST, values.artist),
                    (MhodType.ALBUM_ITEM_SORT_ARTIST, values.sort_artist),
                    (MhodType.ALBUM_ITEM_PODCAST_URL, values.podcast_url),
                    (MhodType.ALBUM_ITEM_SHOW, values.show),
                ):
                    # Preserve absent empty optional fields, but clear stale values.
                    if text_value or any(
                        isinstance(c.header, MhodHeader) and c.header.mhod_type == kind
                        for c in row.children
                    ):
                        row = edit_text(row, kind, text_value)
                if isinstance(row.header, MhiaHeader):
                    representatives = {
                        persistent_tracks[track_ids[t.track_id]] for t in members
                    }
                    row = replace(
                        row,
                        header=replace(
                            row.header,
                            album_compilation_flag=int(exemplar.metadata.compilation),
                            season_number=exemplar.season_number,
                            album_track_db_id=row.header.album_track_db_id
                            if row.header.album_track_db_id in representatives
                            else min(representatives, default=0),
                        ),
                    )
            else:
                row = edit_text(row, MhodType.ARTIST_ITEM_ARTIST, exemplar.artist)
            updated_rows[identity] = row
            logger.debug(
                "Library browse dataset=%d id=%d members=%s action=%s sql_id=%d",
                dataset_kind,
                identity,
                tuple(t.track_id for t in members),
                "update" if identity in rows else "create",
                row.header.sql_id
                if isinstance(row.header, MhiaHeader | MhiiHeader)
                else 0,
            )
            assigned.update((t.track_id, identity) for t in members)
        for identity, retained in tuple(updated_rows.items()):
            if (
                isinstance(retained.header, MhiaHeader)
                and retained.header.album_track_db_id in deleted_persistent_ids
            ):
                updated_rows[identity] = replace(
                    retained, header=replace(retained.header, album_track_db_id=0)
                )
        container = dataset.chunk.children[0]
        children = tuple(
            updated_rows[
                c.header.album_id
                if isinstance(c.header, MhiaHeader)
                else c.header.artist_id
            ]
            if isinstance(c.header, MhiaHeader | MhiiHeader)
            and row_counts[
                c.header.album_id
                if isinstance(c.header, MhiaHeader)
                else c.header.artist_id
            ]
            == 1
            else c
            for c in container.children
        )
        document = document.replace_chunk(
            dataset,
            replace(
                dataset.chunk,
                children=(
                    replace(
                        container,
                        children=(
                            *children,
                            *(
                                row
                                for identity, row in updated_rows.items()
                                if identity not in rows
                            ),
                        ),
                    ),
                ),
            ),
        )
        replacements = {}
        inverse_ids = {native: draft for draft, native in track_ids.items()}
        for track_selection in document.find_chunks(MhitHeader):
            draft_id = inverse_ids.get(track_selection.chunk.header.track_id)
            if draft_id not in assigned:
                continue
            value = assigned[draft_id]
            header = (
                replace(track_selection.chunk.header, album_id=value)
                if album
                else replace(track_selection.chunk.header, artist_id_ref=value)
            )
            replacements[id(track_selection.chunk)] = replace(
                track_selection.chunk, header=header
            )
        document = rebuild(document, replacements)
    return _composers(document, original, desired, track_ids, issues, browse_allocator)


def _composers(
    document: DatabaseDocument[MhbdHeader],
    original: LibrarySnapshot,
    desired: LibrarySnapshot,
    track_ids: dict[int, int],
    issues: list[WriteIssue],
    allocator: IdentityAllocator,
) -> DatabaseDocument[MhbdHeader]:

    old = {t.track_id: t for t in original.tracks}
    candidates: dict[str, set[int]] = defaultdict(set)
    for track in original.tracks:
        if track.ipod and track.ipod.composer_id and track.metadata.composer:
            candidates[track.metadata.composer.casefold()].add(track.ipod.composer_id)
    native = {
        s.chunk.header.track_id: s.chunk for s in document.find_chunks(MhitHeader)
    }
    edits: dict[int, ParsedChunk[ChunkHeader] | None] = {}
    for track in desired.tracks:
        if (
            track.track_id in old
            and old[track.track_id].metadata.composer == track.metadata.composer
        ):
            continue
        key = track.metadata.composer.casefold()
        options = candidates.get(key, set())
        if len(options) > 1:
            issues.append(
                WriteIssue(
                    "library.ambiguous_composer",
                    "The changed composer has conflicting native identities.",
                    subject="track",
                    record_id=track.track_id,
                    field="metadata.composer",
                )
            )
            continue
        value = next(iter(options), 0)
        if key and not value:
            value = allocator.take()
            candidates[key] = {value}
        chunk = native[track_ids[track.track_id]]
        logger.debug(
            "Library composer track=%d old_id=%d new_id=%d",
            chunk.header.track_id,
            chunk.header.composer_id,
            value,
        )
        edits[id(chunk)] = replace(
            chunk, header=replace(chunk.header, composer_id=value)
        )
    return rebuild(document, edits)
