"""Dataset-aware, read-only projection of iTunesDB playlist relationships."""

from dataclasses import replace

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.plist_mhod import MhodPlistPayload
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library._smart_projection import project_smart
from iPodDB.library.playlists import (
    Playlist,
    PlaylistEntry,
    PlaylistKind,
    playlist_sort_from_value,
)
from iPodDB.shared.chunk import ChunkSelection, DatabaseDocument, ParsedChunk


def _metadata(
    selection: ChunkSelection[MhbdHeader, MhypHeader],
) -> tuple[ParsedChunk[MhodHeader], ...]:
    # Playlist-item titles describe podcast groups, never the parent playlist.
    return tuple(
        selection.chunk.child_as(index, MhodHeader)
        for index, child in enumerate(selection.chunk.children)
        if isinstance(child.header, MhodHeader)
    )


def _text(metadata: tuple[ParsedChunk[MhodHeader], ...], kind: MhodType) -> str:
    return next(
        (
            row.payload.value
            for row in metadata
            if row.header.mhod_type == kind
            and isinstance(row.payload, MhodStringPayload)
        ),
        "",
    )


def _description(metadata: tuple[ParsedChunk[MhodHeader], ...]) -> str:
    for row in metadata:
        if (
            isinstance(row.payload, MhodPlistPayload)
            and row.payload.properties is not None
        ):
            description = row.payload.properties.get("description")
            if isinstance(description, str):
                return description
    # MHOD 3 means album for Tracks, but playlist description under MHYP.
    return _text(metadata, MhodType.ALBUM)


def _position(item: ParsedChunk[MhipHeader]) -> int | None:
    """Read the occurrence position only from an MHIP-context type-100 child."""

    return next(
        (
            child.prefix.position
            for child in item.children
            if isinstance(child.prefix, MhodPlaylistPositionPrefix)
        ),
        None,
    )


def project_playlist(
    selection: ChunkSelection[MhbdHeader, MhypHeader],
    track_ids: frozenset[int],
    timezone_offset: int = 0,
) -> Playlist:
    header = selection.chunk.header
    metadata = _metadata(selection)
    has_smart = any(
        row.header.mhod_type
        in (MhodType.SMART_PLAYLIST_PREFERENCES, MhodType.SMART_PLAYLIST_RULES)
        for row in metadata
    )
    if header.playlist_kind_flags & 0x0100:
        kind = PlaylistKind.FOLDER
    elif has_smart:
        kind = PlaylistKind.SMART
    else:
        kind = PlaylistKind.PLAYLIST
    return Playlist(
        playlist_id=header.playlist_id,
        name=_text(metadata, MhodType.TITLE),
        kind=kind,
        parent_id=header.parent_folder_playlist_id or None,
        entries=tuple(
            PlaylistEntry(
                str(index),
                item.chunk.header.track_id,
                _position(item.chunk),
            )
            for index, item in enumerate(selection.find_chunks(MhipHeader))
            if kind is not PlaylistKind.FOLDER
            and not item.chunk.header.podcast_group_flag & 0x0100
            and item.chunk.header.track_id in track_ids
        ),
        smart=project_smart(metadata, timezone_offset)
        if kind is PlaylistKind.SMART
        else None,
        description=_description(metadata),
        sort_order=playlist_sort_from_value(header.sort_order),
        # Bit zero identifies the firmware-maintained Podcasts Playlist. Keep
        # that native interpretation in iPodDB and expose only its semantics.
        system_managed=bool(header.playlist_kind_flags & 1),
    )


def _repair_hierarchy(playlists: tuple[Playlist, ...]) -> tuple[Playlist, ...]:
    """Detach invalid edges in the projection, without changing retained bytes.

    Every cycle member is detached. Traversal is iterative and linear even for
    a folder chain deeper than Python's recursion limit.
    """

    folders = {
        item.playlist_id for item in playlists if item.kind is PlaylistKind.FOLDER
    }
    parents = {
        item.playlist_id: item.parent_id
        if item.parent_id in folders and item.parent_id != item.playlist_id
        else None
        for item in playlists
    }
    visited: set[int] = set()
    for folder_id in folders:
        if folder_id in visited:
            continue
        path: list[int] = []
        path_indexes: dict[int, int] = {}
        current: int | None = folder_id
        while current is not None and current not in visited:
            if current in path_indexes:
                for member in path[path_indexes[current] :]:
                    parents[member] = None
                break
            path_indexes[current] = len(path)
            path.append(current)
            current = parents[current]
        visited.update(path)
    return tuple(
        replace(item, parent_id=parents[item.playlist_id]) for item in playlists
    )


def project_playlists(
    database: DatabaseDocument[MhbdHeader], track_ids: frozenset[int]
) -> tuple[tuple[Playlist, ...], str]:
    """Read one canonical dataset (3, otherwise 2); never merge firmware categories."""

    datasets = database.find_chunks(MhsdHeader)
    selected = next(
        (
            dataset
            for kind in (3, 2)
            for dataset in datasets
            if dataset.chunk.header.dataset_type == kind
        ),
        None,
    )
    if selected is None:
        return (), ""
    selections = selected.find_chunks(MhypHeader)
    ids: set[int] = set()
    for selection in selections:
        identity = selection.chunk.header.playlist_id
        if identity in ids:
            raise ValueError(
                f"Duplicate Playlist ID in iPod playlist dataset: {identity}"
            )
        ids.add(identity)
    masters = tuple(
        selection
        for selection in selections
        if selection.chunk.header.master_flag & 1
        and selection.chunk.header.mhsd_5_type == 0
    )
    device_name = (
        _text(_metadata(masters[0]), MhodType.TITLE) if len(masters) == 1 else ""
    )
    playlists = tuple(
        project_playlist(selection, track_ids, database.header.timezone_offset)
        for selection in selections
        if not selection.chunk.header.master_flag & 1
        and selection.chunk.header.mhsd_5_type == 0
    )
    return _repair_hierarchy(playlists), device_name
