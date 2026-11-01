"""Dataset 3 owns Playlist relationships; dataset 2 is its flat companion."""

from collections import Counter, defaultdict, deque
from dataclasses import replace

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library._identities import IdentityAllocator
from iPodDB.library._playlist_projection import project_playlist
from iPodDB.library._playlist_writing import position_item
from iPodDB.shared.chunk import (
    ChunkHeader,
    ChunkSelection,
    DatabaseDocument,
    ParsedChunk,
    chunk_as,
)


def _members(
    row: ChunkSelection[MhbdHeader, MhypHeader],
) -> tuple[tuple[int, int | None], ...]:
    return tuple(
        (
            item.chunk.header.track_id,
            next(
                (
                    c.prefix.position
                    for c in item.chunk.children
                    if isinstance(c.prefix, MhodPlaylistPositionPrefix)
                ),
                None,
            ),
        )
        for item in row.find_chunks(MhipHeader)
        if not item.chunk.header.is_group
    )


def _matches(
    source: ChunkSelection[MhbdHeader, MhypHeader],
    target: ChunkSelection[MhbdHeader, MhypHeader],
    tracks: frozenset[int],
) -> bool:
    left, right = source.chunk, target.chunk
    if replace(project_playlist(source, tracks), entries=()) != replace(
        project_playlist(target, tracks), entries=()
    ):
        return False
    if (
        left.header.master_flag != right.header.master_flag
        or left.header.playlist_kind_flags != right.header.playlist_kind_flags
        or left.header.phase_game_flag != right.header.phase_game_flag
        or left.header.sort_order != right.header.sort_order
        or left.header.mhsd_5_type != right.header.mhsd_5_type
        or left.header.parent_folder_playlist_id
        != right.header.parent_folder_playlist_id
    ):
        return False
    left_members, right_members = _members(source), _members(target)
    if len(left_members) != len(right_members) or any(
        left_id != right_id
        or (left_position is not None and left_position != right_position)
        for (left_id, left_position), (right_id, right_position) in zip(
            left_members, right_members, strict=True
        )
    ):
        return False

    # Unsupported Smart definitions and Genius seeds must agree too: their
    # semantic projection intentionally cannot express every retained operand.
    def definitions(row: ParsedChunk[MhypHeader]) -> tuple[object, ...]:
        return tuple(
            (c.header, c.prefix, c.payload)
            for c in row.children
            if isinstance(c.header, MhodHeader)
            and c.header.mhod_type
            in (
                MhodType.SMART_PLAYLIST_PREFERENCES,
                MhodType.SMART_PLAYLIST_RULES,
                MhodType.GENIUS_PLAYLIST_SEED,
            )
        )

    if definitions(left) != definitions(right):
        return False
    if any(
        s.chunk.header.is_group or s.chunk.header.group_id_ref
        for s in target.find_chunks(MhipHeader)
    ):
        return False
    if left.header.playlist_kind_flags & 1:
        return tuple(
            s.chunk.header.group_id
            for s in source.find_chunks(MhipHeader)
            if not s.chunk.header.is_group
        ) == tuple(s.chunk.header.group_id for s in target.find_chunks(MhipHeader))
    return True


def counterparts_match(document: DatabaseDocument[MhbdHeader]) -> bool:
    """Compare native identities, order, definitions and every Track occurrence."""
    datasets = document.find_chunks(MhsdHeader)
    sources = [s for s in datasets if s.chunk.header.dataset_type == 3]
    targets = [s for s in datasets if s.chunk.header.dataset_type == 2]
    if not sources or not targets:
        return True  # Whole-dataset creation follows the target's existing policy.
    if len(sources) != 1 or len(targets) != 1:
        return False
    source, target = sources[0], targets[0]
    left, right = source.find_chunks(MhypHeader), target.find_chunks(MhypHeader)
    if [s.chunk.header.playlist_id for s in left] != [
        s.chunk.header.playlist_id for s in right
    ]:
        return False
    tracks = frozenset(
        s.chunk.header.track_id for s in document.find_chunks(MhitHeader)
    )
    return all(_matches(a, b, tracks) for a, b in zip(left, right, strict=True))


def synchronize_counterparts(
    document: DatabaseDocument[MhbdHeader],
    *,
    create_missing: bool = False,
) -> DatabaseDocument[MhbdHeader]:
    """Retain matching rows; replace missing/conflicting rows from dataset 3.

    Dataset-2-only rows disappear from the candidate, never the captured source.
    Matching rows retain their own private metadata and occurrence identities.
    """
    datasets = document.find_chunks(MhsdHeader)
    sources = [s for s in datasets if s.chunk.header.dataset_type == 3]
    targets = [s for s in datasets if s.chunk.header.dataset_type == 2]
    if len(sources) == 1 and not targets and create_missing:
        source = sources[0]
        new_target = new_itunes_chunk(
            MHSD,
            MhsdHeader(dataset_type=2),
            children=(replace(source.chunk.children[0], children=()),),
        )
        dataset_children = list(document.children)
        dataset_children.insert(source.path.child_indexes[0] + 1, new_target)
        document = replace(document, children=tuple(dataset_children))
        return synchronize_counterparts(document)
    if counterparts_match(document):
        return document
    if len(sources) != 1 or not targets:
        return document  # Ambiguous authority is handled by source validation.
    source, target = sources[0], targets[0]
    tracks = frozenset(
        s.chunk.header.track_id for s in document.find_chunks(MhitHeader)
    )
    source_rows = source.find_chunks(MhypHeader)
    target_rows = target.find_chunks(MhypHeader)
    counts = Counter(s.chunk.header.playlist_id for s in target_rows)
    existing = {
        s.chunk.header.playlist_id: s
        for s in target_rows
        if counts[s.chunk.header.playlist_id] == 1
    }
    allocator = IdentityAllocator(
        (s.chunk.header.mhip_persistent_id for s in document.find_chunks(MhipHeader)),
        64,
    )
    rows: list[ParsedChunk[ChunkHeader]] = []
    for selection in source_rows:
        row = selection.chunk
        retained = existing.get(row.header.playlist_id)
        if retained is not None and _matches(selection, retained, tracks):
            rows.append(retained.chunk)
            continue
        occurrences: dict[int, deque[ParsedChunk[MhipHeader]]] = defaultdict(deque)
        if retained is not None:
            for occurrence in retained.find_chunks(MhipHeader):
                if not occurrence.chunk.header.is_group:
                    occurrences[occurrence.chunk.header.track_id].append(
                        occurrence.chunk
                    )
        children: list[ParsedChunk[ChunkHeader]] = []
        for child in row.children:
            if isinstance(child.header, MhipHeader):
                if child.header.is_group:
                    continue
                item = chunk_as(child, MhipHeader)
                if occurrences[item.header.track_id]:
                    prior = occurrences[item.header.track_id].popleft()
                    updated_item = replace(
                        prior,
                        header=replace(
                            prior.header,
                            group_id_ref=0,
                            group_id=item.header.group_id
                            if row.header.playlist_kind_flags & 1
                            else prior.header.group_id,
                        ),
                    )
                    position = next(
                        (
                            c.prefix.position
                            for c in item.children
                            if isinstance(c.prefix, MhodPlaylistPositionPrefix)
                        ),
                        None,
                    )
                    child = (
                        position_item(updated_item, position)
                        if position is not None
                        else updated_item
                    )
                else:
                    child = replace(
                        item,
                        header=replace(
                            item.header,
                            group_id_ref=0,
                            mhip_persistent_id=allocator.take(),
                        ),
                    )
            children.append(child)
        rows.append(replace(row, children=tuple(children)))
    # Preserve opaque container children while replacing the complete row order.
    pending = iter(rows)
    container = target.chunk.children[0]
    children = [
        replacement
        for child in container.children
        if (
            replacement := next(pending, None)
            if isinstance(child.header, MhypHeader)
            else child
        )
        is not None
    ]
    children.extend(pending)
    updated = replace(
        target.chunk, children=(replace(container, children=tuple(children)),)
    )
    return replace(
        document,
        children=tuple(
            updated if child is target.chunk else child
            for child in document.children
            if not isinstance(child.header, MhsdHeader)
            or child.header.dataset_type != 2
            or child is target.chunk
        ),
    )
