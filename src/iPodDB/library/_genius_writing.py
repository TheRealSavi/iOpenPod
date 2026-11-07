"""Coordinate MHIT Genius identities and caller-captured firmware companions."""

from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.library._track_header_expansion import field_fits
from iPodDB.library.genius import GeniusUpdate
from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.writing import IdentityMapping
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk, RawPayload
from iPodDB.SQLiteDB.genius import (
    GeniusDatabase,
    parse_genius_database,
    prune_genius_data,
    serialize_genius_database,
)
from iPodDB.SQLiteDB.genius_projection import validate_genius_update


def mapped_update(
    update: GeniusUpdate | None, mappings: tuple[IdentityMapping, ...]
) -> GeniusUpdate | None:
    if update is None:
        return None
    ids = {m.draft_id: m.output_id for m in mappings if m.subject == "track"}
    return replace(
        update,
        tracks=tuple(
            replace(t, track_id=ids.get(t.track_id, t.track_id)) for t in update.tracks
        ),
        mixes=None
        if update.mixes is None
        else tuple(
            replace(
                mix,
                track_ids=tuple(ids.get(t, t) for t in mix.track_ids),
                seed_track_id=(
                    None
                    if mix.seed_track_id is None
                    else ids.get(mix.seed_track_id, mix.seed_track_id)
                ),
            )
            for mix in update.mixes
        ),
        mix_additions=tuple(
            replace(
                mix,
                track_ids=tuple(ids.get(t, t) for t in mix.track_ids),
                seed_track_id=(
                    None
                    if mix.seed_track_id is None
                    else ids.get(mix.seed_track_id, mix.seed_track_id)
                ),
            )
            for mix in update.mix_additions
        ),
    )


def bootstrap_classic_genius(
    document: DatabaseDocument[MhbdHeader],
    update: GeniusUpdate | None,
    source_revision: str,
) -> tuple[DatabaseDocument[MhbdHeader], bytes | None]:
    """Add only the synthetic CUID layout accepted by the Classic experiment.

    The CUID's complete firmware semantics remain opaque. Existing dataset 9
    records therefore remain untouched, including unrecognized layouts. A source
    revision supplies stable local identity so repeat preparation does not invent
    a different CUID; no account, hardware identifier, or external service is used.
    Callers invoke this only for explicit generation on a non-SQLite target.
    """

    if (
        update is None
        or not update.tracks
        or any(
            row.chunk.header.dataset_type == 9
            for row in document.find_chunks(MhsdHeader)
        )
    ):
        return document, None
    cuid = (
        uuid5(NAMESPACE_URL, f"iopenpod:genius:{source_revision}")
        .hex.upper()
        .encode("ascii")
    )
    return (
        document.append_child(
            new_itunes_chunk(MHSD, MhsdHeader(dataset_type=9), payload=RawPayload(cuid))
        ),
        cuid,
    )


def reconcile_genius_tracks(
    document: DatabaseDocument[MhbdHeader],
    update: GeniusUpdate | None,
    replaced_ids: frozenset[int],
) -> DatabaseDocument[MhbdHeader]:
    if update is None and not replaced_ids:
        return document
    selections = tuple(document.find_chunks(MhitHeader))
    pids = {s.chunk.header.track_id: s.chunk.header.db_track_id for s in selections}
    if update is not None:
        validate_genius_update(update, pids)
    assignments = (
        {} if update is None else {t.track_id: t.genius_id for t in update.tracks}
    )
    replacements: dict[int, ParsedChunk[MhitHeader]] = {}
    for selection in selections:
        chunk = selection.chunk
        header = chunk.header
        gid = (
            assignments.get(header.track_id, 0)
            if update is not None
            else (0 if header.track_id in replaced_ids else header.genius_id)
        )
        if gid == header.genius_id:
            continue
        if not field_fits("genius_id", chunk.generic_header.header_length):
            raise ValueError(
                "Genius authoring requires a Track layout containing the Genius identity field"
            )
        replacements[id(chunk)] = replace(chunk, header=replace(header, genius_id=gid))
    return _replace_track_chunks(document, replacements) if replacements else document


def _replace_track_chunks[H: ChunkHeader](
    chunk: ParsedChunk[H], replacements: dict[int, ParsedChunk[MhitHeader]]
) -> ParsedChunk[H]:
    """Rebuild each ancestor once, avoiding a Track-list copy for every edit."""

    if not chunk.children:
        return chunk
    changed = False
    children: list[ParsedChunk[ChunkHeader]] = []
    for child in chunk.children:
        replacement = replacements.get(id(child))
        updated = (
            _replace_track_chunks(child, replacements)
            if replacement is None
            else replacement
        )
        changed |= updated is not child
        children.append(updated)
    return replace(chunk, children=tuple(children)) if changed else chunk


def prepare_classic_genius(
    original: LibrarySnapshot,
    checked: LibrarySnapshot,
    source: bytes | None,
    update: GeniusUpdate | None,
) -> bytes | None:
    previous = {
        t.ipod.genius_id for t in original.tracks if t.ipod and t.ipod.genius_id
    }
    current = {t.ipod.genius_id for t in checked.tracks if t.ipod and t.ipod.genius_id}
    removed = frozenset(previous - current)
    if source is None:
        if removed or (update is not None and previous):
            raise ValueError(
                "Capture the Classic Extras.itdb before removing or replacing Genius Track identities"
            )
        return (
            None
            if update is None
            else serialize_genius_database(GeniusDatabase(update.data))
        )
    retained = parse_genius_database(source)
    data = (
        update.data if update is not None else prune_genius_data(retained.data, removed)
    )
    return serialize_genius_database(retained, data)
