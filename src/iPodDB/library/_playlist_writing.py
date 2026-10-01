"""Occurrence-aware Playlist edits over retained dataset-specific records."""

from dataclasses import replace

from iPodDB.device_time import TimeConversion
from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    DEFAULT_PLAYLIST_PREFERENCES,
    MhodPlaylistPositionPayload,
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.opaque_mhod import (
    MhodOpaquePayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.plist_mhod import MhodPlistPayload
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import DEFINITION as MHYP
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library._smart_writing import smart_chunks
from iPodDB.library._track_writing import edit_text
from iPodDB.library.playlists import Playlist, PlaylistKind, playlist_sort_value
from iPodDB.shared.chunk import ChunkHeader, ParsedChunk, chunk_as


def playlist_preferences() -> ParsedChunk[MhodHeader]:
    return new_itunes_chunk(
        MHOD,
        MhodHeader(mhod_type=100),
        payload=MhodOpaquePayload(DEFAULT_PLAYLIST_PREFERENCES),
    )


def position_item(
    chunk: ParsedChunk[MhipHeader], position: int
) -> ParsedChunk[MhipHeader]:
    children = list(chunk.children)
    found = False
    for index, child in enumerate(children):
        if isinstance(child.prefix, MhodPlaylistPositionPrefix):
            children[index] = replace(
                child, prefix=replace(child.prefix, position=position)
            )
            found = True
    if not found:
        children.append(
            new_itunes_chunk(
                MHOD,
                MhodHeader(mhod_type=100),
                prefix=MhodPlaylistPositionPrefix(position=position),
                payload=MhodPlaylistPositionPayload(),
            )
        )
    return replace(chunk, children=tuple(children))


def edit_playlist(
    chunk: ParsedChunk[MhypHeader] | None,
    old: Playlist | None,
    new: Playlist,
    playlist_ids: dict[int, int],
    track_ids: dict[int, int],
    persistent_ids: dict[int, int],
    timezone_offset: TimeConversion = 0,
    db_id_2: int = 0,
) -> ParsedChunk[MhypHeader]:
    source_string_count = (
        0
        if chunk is None
        else sum(isinstance(c.payload, MhodStringPayload) for c in chunk.children)
    )
    is_new = chunk is None
    if chunk is None:
        chunk = new_itunes_chunk(
            MHYP,
            MhypHeader(
                playlist_id=playlist_ids[new.playlist_id],
                playlist_id_2=playlist_ids[new.playlist_id],
                db_id_2=db_id_2,
                sort_order=playlist_sort_value(new.sort_order),
            ),
            children=(playlist_preferences(),),
        )
    if old is None or old.name != new.name:
        chunk = edit_text(chunk, MhodType.TITLE, new.name, first=True)
    if old is None or old.description != new.description:
        children = list(chunk.children)
        contributor = next(
            (
                i
                for i, c in enumerate(children)
                if isinstance(c.payload, MhodPlistPayload)
                and c.payload.properties is not None
                and isinstance(c.payload.properties.get("description"), str)
            ),
            None,
        )
        if contributor is None:
            if new.description or old is not None:
                chunk = edit_text(chunk, MhodType.ALBUM, new.description, first=True)
        else:
            child = children[contributor]
            assert (
                isinstance(child.payload, MhodPlistPayload)
                and child.payload.properties is not None
            )
            children[contributor] = replace(
                child,
                payload=replace(
                    child.payload,
                    properties={
                        **child.payload.properties,
                        "description": new.description,
                    },
                ),
            )
            chunk = replace(chunk, children=tuple(children))
    header = chunk.header
    if old is None or old.parent_id != new.parent_id:
        header = replace(
            header,
            parent_folder_playlist_id=playlist_ids[new.parent_id]
            if new.parent_id is not None
            else 0,
        )
    if old is None or old.kind != new.kind:
        header = replace(
            header,
            playlist_kind_flags=(header.playlist_kind_flags & ~0x100)
            | (0x100 if new.kind is PlaylistKind.FOLDER else 0),
        )
    if old is None or old.sort_order != new.sort_order:
        header = replace(header, sort_order=playlist_sort_value(new.sort_order))
    chunk = replace(chunk, header=header)
    if old is None or old.smart != new.smart:
        if old and old.smart and not old.smart.editable:
            raise ValueError("Unsupported Smart Playlist rules must remain unchanged.")
        metadata = tuple(
            chunk_as(c, MhodHeader)
            for c in chunk.children
            if isinstance(c.header, MhodHeader)
        )
        replacements = (
            ()
            if new.smart is None
            else smart_chunks(
                new.smart,
                metadata,
                timezone_offset,
                playlist_ids=playlist_ids,
            )
        )
        children = list(chunk.children)
        positions = [
            i
            for i, c in enumerate(children)
            if isinstance(c.header, MhodHeader)
            and c.header.mhod_type
            in (MhodType.SMART_PLAYLIST_PREFERENCES, MhodType.SMART_PLAYLIST_RULES)
        ]
        insert = (
            positions[0]
            if positions
            else next(
                (i for i, c in enumerate(children) if isinstance(c.header, MhipHeader)),
                len(children),
            )
        )
        children = [c for i, c in enumerate(children) if i not in positions]
        children[insert:insert] = replacements
        chunk = replace(chunk, children=tuple(children))
    if old is not None and old.entries == new.entries:
        return _string_count(chunk, source_string_count, is_new)
    items = tuple(
        chunk_as(c, MhipHeader)
        for c in chunk.children
        if isinstance(c.header, MhipHeader)
    )
    bindings = {str(i): item for i, item in enumerate(items)}
    known_entries = (
        {} if old is None else {entry.entry_id: entry for entry in old.entries}
    )
    # Group headers and unresolved source references are retained. Membership
    # changes in grouped podcasts need a dedicated group reconciliation below.
    replacement_items: list[ParsedChunk[ChunkHeader]] = []
    for index, entry in enumerate(new.entries):
        previous = known_entries.get(entry.entry_id)
        if previous is not None:
            if previous.track_id != entry.track_id:
                raise ValueError(
                    "A Playlist Entry identity cannot be reassigned to another Track."
                )
            item = bindings[entry.entry_id]
        else:
            item = new_itunes_chunk(
                MHIP,
                MhipHeader(
                    track_id=track_ids[entry.track_id],
                    track_persistent_id=persistent_ids[entry.track_id],
                ),
            )
        # Entries can carry source-native Podcast row IDs or positions from before
        # a generated regroup. Rebuild ordinary positions from the resulting order;
        # the dataset-3 Podcast pass assigns episode row IDs afterward.
        replacement_items.append(position_item(item, index))
    visible_ids = set(known_entries)
    hidden = [item for index, item in enumerate(items) if str(index) not in visible_ids]
    hidden = [
        item
        if item.header.podcast_group_flag & 0x100
        else position_item(item, len(replacement_items) + index)
        for index, item in enumerate(hidden)
    ]
    metadata_children = tuple(
        c for c in chunk.children if not isinstance(c.header, MhipHeader)
    )
    return _string_count(
        replace(chunk, children=(*metadata_children, *replacement_items, *hidden)),
        source_string_count,
        is_new,
    )


def _string_count(
    chunk: ParsedChunk[MhypHeader], prior: int, is_new: bool
) -> ParsedChunk[MhypHeader]:
    count = sum(isinstance(c.payload, MhodStringPayload) for c in chunk.children)
    if is_new or count != prior:
        return replace(
            chunk,
            header=replace(
                chunk.header,
                string_mhod_child_count=count
                if is_new
                else chunk.header.string_mhod_child_count + count - prior,
            ),
        )
    return chunk
