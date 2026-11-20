"""Classic Mix records in the first type-2/3 iTunesDB Playlist dataset.

The MHYP distinguished-kind byte routes these records outside ordinary Playlists.
Members are native Track IDs; playback obtains their Genius IDs from MHIT and
uses Extras.itdb to generate a queue. No MHOD54 single-seed record is needed.
"""

from collections import Counter, defaultdict, deque
from dataclasses import replace

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.library._identities import IdentityAllocator
from iPodDB.library._playlist_datasets import playlist_rows, structure_issues
from iPodDB.library._playlist_writing import edit_playlist, position_item
from iPodDB.library.genius import GeniusMix, GeniusUpdate
from iPodDB.library.genius_browse import (
    CLASSIC_GENIUS_MIX_LIMIT,
    GeniusBrowse,
    GeniusBrowseIssue,
    GeniusCollection,
    GeniusCollectionKind,
)
from iPodDB.library.playlists import Playlist, PlaylistEntry
from iPodDB.library.writing import IssueSeverity
from iPodDB.shared.binary_struct import binary_fields
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk, chunk_as


def _collection(chunk: ParsedChunk[MhypHeader]) -> GeniusCollection:
    identity = chunk.header.playlist_id
    if not identity or chunk.header.master_flag & 1:
        raise ValueError("A Classic Genius Mix has an invalid identity or Master flag")
    members = tuple(
        c.header for c in chunk.children if isinstance(c.header, MhipHeader)
    )
    if any(item.is_group for item in members):
        raise ValueError("A Classic Genius Mix contains grouped Podcast records")
    name = next(
        (
            c.payload.value
            for c in chunk.children
            if isinstance(c.header, MhodHeader)
            and c.header.mhod_type == 1
            and isinstance(c.payload, MhodStringPayload)
        ),
        "",
    )
    return GeniusCollection(
        f"genius-mix:{identity:016x}",
        name,
        GeniusCollectionKind.MIX,
        tuple(item.track_id for item in members),
        None,
        identity,
    )


def _collections(
    document: DatabaseDocument[MhbdHeader],
) -> tuple[GeniusCollection, ...]:
    datasets = tuple(
        s
        for s in document.find_chunks(MhsdHeader)
        if s.chunk.header.dataset_type in (2, 3)
    )
    if len({s.chunk.header.dataset_type for s in datasets}) != len(datasets):
        raise ValueError("Classic Genius Mix dataset ownership is ambiguous")
    tracks = Counter(s.chunk.header.track_id for s in document.find_chunks(MhitHeader))
    copies: list[tuple[GeniusCollection, ...]] = []
    for dataset in datasets:
        rows = dataset.find_chunks(MhypHeader)
        identities = Counter(s.chunk.header.playlist_id for s in rows)
        mixes = tuple(
            _collection(s.chunk) for s in rows if s.chunk.header.is_genius_mix
        )
        for mix in mixes:
            assert mix.native_playlist_id is not None
            if identities[mix.native_playlist_id] != 1:
                raise ValueError(
                    "A Classic Genius Mix identity collides with another Playlist"
                )
            if any(tracks[tid] != 1 for tid in mix.track_ids):
                raise ValueError(
                    "A Classic Genius Mix references a missing or ambiguous Track"
                )
        copies.append(mixes)
    if copies and any(copy != copies[0] for copy in copies[1:]):
        raise ValueError(
            "Classic Genius Mix records disagree between Playlist datasets"
        )
    return copies[0] if copies else ()


def project_classic_mixes(document: DatabaseDocument[MhbdHeader]) -> GeniusBrowse:
    try:
        return GeniusBrowse(_collections(document))
    except ValueError as error:
        return GeniusBrowse(
            issues=(GeniusBrowseIssue("genius.invalid_classic_mixes", str(error)),)
        )


def _authored(
    mix: GeniusMix,
    source: ParsedChunk[MhypHeader] | None,
    pids: dict[int, int],
    database_id: int,
    allocator: IdentityAllocator,
) -> ParsedChunk[MhypHeader]:
    old = None
    entries: list[PlaylistEntry] = []
    if source is not None:
        collection = _collection(source)
        old = Playlist(
            mix.container_id,
            collection.name,
            entries=tuple(
                PlaylistEntry(str(i), tid) for i, tid in enumerate(collection.track_ids)
            ),
        )
    available: dict[int, deque[PlaylistEntry]] = defaultdict(deque)
    for entry in old.entries if old is not None else ():
        available[entry.track_id].append(entry)
    for index, tid in enumerate(mix.track_ids):
        prior = available[tid].popleft() if available[tid] else None
        entries.append(prior or PlaylistEntry(f"new:{index}", tid))
    desired = (
        replace(old, name=mix.name, entries=tuple(entries))
        if old
        else Playlist(mix.container_id, mix.name, entries=tuple(entries))
    )
    chunk = edit_playlist(
        source,
        old,
        desired,
        {mix.container_id: mix.container_id},
        {tid: tid for tid in mix.track_ids},
        pids,
        db_id_2=database_id,
    )
    return replace(
        chunk,
        children=tuple(
            replace(
                child, header=replace(child.header, mhip_persistent_id=allocator.take())
            )
            if isinstance(child.header, MhipHeader)
            and not child.raw_header
            and not child.header.mhip_persistent_id
            else child
            for child in chunk.children
        ),
        header=replace(
            chunk.header, phase_game_flag=(chunk.header.phase_game_flag & ~0xFF) | 32
        ),
    )


def reconcile_classic_mixes(
    original: DatabaseDocument[MhbdHeader],
    candidate: DatabaseDocument[MhbdHeader],
    update: GeniusUpdate | None,
    replaced_ids: frozenset[int],
    *,
    authoring: bool,
) -> tuple[DatabaseDocument[MhbdHeader], frozenset[int]]:
    """Preserve unrelated rows; edit only explicit Mixes or affected memberships."""
    original_rows = tuple(
        (k, s) for k, s in playlist_rows(original) if s.chunk.header.is_genius_mix
    )
    tracks = {
        s.chunk.header.track_id: s.chunk.header
        for s in candidate.find_chunks(MhitHeader)
    }
    previous = {
        s.chunk.header.track_id: s.chunk.header
        for s in original.find_chunks(MhitHeader)
    }
    unavailable = (
        (previous.keys() - tracks.keys())
        | replaced_ids
        | {
            tid
            for tid, header in previous.items()
            if ((update is not None and update.data is not None) or header.genius_id)
            and tid in tracks
            and not tracks[tid].genius_id
        }
    )
    explicit = update is not None and (
        update.mixes is not None or bool(update.mix_additions or update.mix_removals)
    )
    affected = any(
        item.chunk.header.track_id in unavailable
        for _, row in original_rows
        for item in row.find_chunks(MhipHeader)
    )
    if not affected and not explicit:
        return candidate, frozenset()
    if explicit and not authoring:
        # An empty replacement is harmless on a source with no Mixes.
        assert update is not None
        if original_rows or update.mixes or update.mix_additions or update.mix_removals:
            raise ValueError("Classic Genius Mix authoring requires a supported target")
        return candidate, frozenset()
    existing = _collections(original)
    for issue in structure_issues(
        original, affected=True, affected_kinds=frozenset((2, 3))
    ):
        if issue.severity is IssueSeverity.ERROR:
            raise ValueError(issue.message)
    old_ids = {m.native_playlist_id for m in existing}
    additions = (
        ()
        if update is None
        else (update.mixes if update.mixes is not None else update.mix_additions)
    )
    removals = set(() if update is None else update.mix_removals)
    if not removals <= old_ids:
        raise ValueError("A selected Classic Genius Mix is no longer present")
    if update is not None and update.mixes is not None:
        removals.update(
            identity
            for identity in old_ids
            if identity is not None
            and identity not in {m.container_id for m in additions}
        )
    elif old_ids.intersection(m.container_id for m in additions):
        raise ValueError("A new Classic Genius Mix collides with a retained Mix")
    occupied = {
        s.chunk.header.playlist_id
        for s in candidate.find_chunks(MhypHeader)
        if not s.chunk.header.is_genius_mix
    }
    if occupied.intersection(m.container_id for m in additions):
        raise ValueError("A Classic Genius Mix identity collides with another Playlist")
    for mix in additions:
        if not mix.track_ids or any(
            tid not in tracks or not tracks[tid].genius_id for tid in mix.track_ids
        ):
            raise ValueError(
                "Classic Genius Mix candidates require assigned Genius identities"
            )
    if additions and (
        not candidate.header.genius_target_count
        or not candidate.header.genius_minimum_count
    ):
        assert update is not None and update.data is not None
        configs = update.data.configs
        if len(configs) != 1:
            raise ValueError(
                "Classic Mix initialization requires one Genius configuration"
            )
        target, minimum = configs[0].default_num_results, configs[0].min_num_results
        if target is None or minimum is None or not 0 < minimum <= target <= 0xFFFF:
            raise ValueError(
                "Classic Mix result thresholds must be positive 16-bit counts"
            )
        required_header = max(
            f.schema.offset + f.schema.size
            for f in binary_fields(MhbdHeader)
            if f.attribute_name in {"genius_target_count", "genius_minimum_count"}
        )
        if candidate.generic_header.header_length < required_header:
            raise ValueError(
                "Classic Mix authoring requires a database header with Genius result thresholds"
            )
        candidate = replace(
            candidate,
            header=replace(
                candidate.header,
                genius_target_count=candidate.header.genius_target_count or target,
                genius_minimum_count=candidate.header.genius_minimum_count or minimum,
            ),
        )
    edited = {m.container_id: m for m in additions}
    depleted = {
        m.native_playlist_id
        for m in existing
        if m.track_ids
        and not any(tid not in unavailable for tid in m.track_ids)
        and m.native_playlist_id not in edited
    }
    removals.update(identity for identity in depleted if identity is not None)
    final_ids = (old_ids - removals) | edited.keys()
    if additions and len(final_ids) > CLASSIC_GENIUS_MIX_LIMIT:
        raise ValueError(
            "Classic firmware displays at most 12 Genius Mixes. Remove a Mix before adding another."
        )
    changed = frozenset(
        removals
        | edited.keys()
        | {
            m.native_playlist_id
            for m in existing
            if m.native_playlist_id is not None
            and any(tid in unavailable for tid in m.track_ids)
        }
    )
    datasets = tuple(
        s
        for s in candidate.find_chunks(MhsdHeader)
        if s.chunk.header.dataset_type in (2, 3)
    )
    if additions and not datasets:
        raise ValueError("Classic Mix authoring requires a retained Playlist dataset")
    pids = {tid: h.db_track_id for tid, h in tracks.items()}
    allocator = IdentityAllocator(
        (s.chunk.header.mhip_persistent_id for s in candidate.find_chunks(MhipHeader)),
        64,
    )
    for dataset in datasets:
        if len(dataset.chunk.children) != 1:
            raise ValueError("Classic Mix Playlist container is ambiguous")
        container = dataset.chunk.children[0]
        children: list[ParsedChunk[ChunkHeader]] = []
        present: set[int] = set()
        for child in container.children:
            if (
                not isinstance(child.header, MhypHeader)
                or not child.header.is_genius_mix
            ):
                children.append(child)
                continue
            row = chunk_as(child, MhypHeader)
            identity = row.header.playlist_id
            present.add(identity)
            if identity in removals:
                continue
            if identity in edited:
                row = _authored(
                    edited[identity], row, pids, candidate.header.db_id_2, allocator
                )
            elif identity in changed:
                metadata = tuple(
                    c for c in row.children if not isinstance(c.header, MhipHeader)
                )
                items = tuple(
                    chunk_as(c, MhipHeader)
                    for c in row.children
                    if isinstance(c.header, MhipHeader)
                    and c.header.track_id not in unavailable
                )
                row = replace(
                    row,
                    children=(
                        *metadata,
                        *(position_item(item, i) for i, item in enumerate(items)),
                    ),
                )
            children.append(row)
        children.extend(
            _authored(mix, None, pids, candidate.header.db_id_2, allocator)
            for mix in additions
            if mix.container_id not in present
        )
        candidate = candidate.replace_chunk(
            dataset,
            replace(
                dataset.chunk, children=(replace(container, children=tuple(children)),)
            ),
        )
    return candidate, changed
