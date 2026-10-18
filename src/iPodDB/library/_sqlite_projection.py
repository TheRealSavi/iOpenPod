"""Project native firmware metadata from the independently checked CDB."""

from dataclasses import replace
from typing import cast

from iPodDB.device_time import TimeConversion, project_mac
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    MhodChapterDataPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_prefs_mhod import (
    MhodSmartPrefsPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartRulesPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodPayloadKind
from iPodDB.iTunesDB.writer.mhod_encoder import encode_mhod_body
from iPodDB.library._playlist_projection import project_playlist
from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.playlists import Playlist, PlaylistKind
from iPodDB.shared.chunk import ChunkSelection, DatabaseDocument, ParsedChunk
from iPodDB.SQLiteDB.inputs import (
    SQLiteChapter,
    SQLiteContainer,
    SQLiteNativeMetadata,
    SQLiteSmartPreferences,
)


def _container(
    selection: ChunkSelection[MhbdHeader, MhypHeader],
    dataset: int,
    playlists: dict[int, Playlist],
    track_ids: frozenset[int],
    device_time: TimeConversion,
) -> SQLiteContainer:
    header = selection.chunk.header
    if dataset == 5:
        # Dataset-5 flag 0x100 does not mean Folder. Preserve native membership;
        # firmware categories are not application Smart Playlists to reevaluate.
        selection = replace(
            selection,
            chunk=replace(
                selection.chunk,
                header=replace(header, playlist_kind_flags=0),
            ),
        )
        playlist = replace(
            project_playlist(selection, track_ids, device_time), parent_id=None
        )
    else:
        playlist = playlists[header.playlist_id]
    prefs = next(
        (
            c.prefix
            for c in selection.chunk.children
            if isinstance(c.prefix, MhodSmartPrefsPrefix)
        ),
        None,
    )
    rules = next(
        (
            c
            for c in selection.chunk.children
            if isinstance(c.payload, MhodSmartRulesPayload)
        ),
        None,
    )
    criteria = None
    if rules is not None:
        criteria, _ = encode_mhod_body(
            cast("ParsedChunk[MhodHeader]", rules), MhodPayloadKind.SMART_RULES
        )
    preferences = None
    if prefs is not None:
        preferences = SQLiteSmartPreferences(
            prefs.live_update,
            prefs.check_rules,
            prefs.check_limits,
            prefs.limit_type,
            prefs.limit_sort,
            prefs.limit_value,
            prefs.match_checked_only,
            prefs.reverse_sort,
        )
    elif dataset == 5:
        preferences = SQLiteSmartPreferences()
    if dataset == 5:
        playlist = replace(playlist, kind=PlaylistKind.SMART)
    return SQLiteContainer(
        playlist,
        dataset,
        header.mhsd_5_type if dataset == 5 else 0,
        bool(header.master_flag) if dataset == 5 else False,
        project_mac(header.timestamp, device_time),
        project_mac(header.timestamp_2 or header.timestamp, device_time),
        preferences,
        criteria,
        podcast=dataset in (2, 3)
        and bool(header.playlist_kind_flags & 1)
        and not bool(header.playlist_kind_flags & 0x100),
    )


def project_sqlite_metadata(
    document: DatabaseDocument[MhbdHeader],
    snapshot: LibrarySnapshot,
    device_time: TimeConversion,
) -> SQLiteNativeMetadata:
    """Keep dataset ownership, native rules and chapter Unknown Data intact."""

    datasets = document.find_chunks(MhsdHeader)
    canonical = next(
        (d for kind in (3, 2) for d in datasets if d.chunk.header.dataset_type == kind),
        None,
    )
    selected = (() if canonical is None else (canonical,)) + tuple(
        d for d in datasets if d.chunk.header.dataset_type == 5
    )
    playlists = {p.playlist_id: p for p in snapshot.playlists}
    track_ids = frozenset(t.track_id for t in snapshot.tracks)
    containers: list[SQLiteContainer] = []
    identities: set[tuple[int, int]] = set()
    for dataset in selected:
        kind = dataset.chunk.header.dataset_type
        for selection in dataset.find_chunks(MhypHeader):
            header = selection.chunk.header
            if kind != 5 and (
                header.master_flag & 1
                or header.mhsd_5_type
                or header.playlist_id not in playlists
            ):
                continue
            identity = kind, header.playlist_id
            if identity in identities:
                raise ValueError(
                    "SQLite container identity is ambiguous within a native dataset"
                )
            identities.add(identity)
            containers.append(
                _container(selection, kind, playlists, track_ids, device_time)
            )
    chapters: list[SQLiteChapter] = []
    for track in document.find_chunks(MhitHeader):
        for child in reversed(track.chunk.children):
            if isinstance(child.header, MhodHeader) and isinstance(
                child.payload, MhodChapterDataPayload
            ):
                data, _ = encode_mhod_body(
                    cast("ParsedChunk[MhodHeader]", child), MhodPayloadKind.CHAPTER_DATA
                )
                chapters.append(SQLiteChapter(track.chunk.header.track_id, data))
                break
    master = (
        next(
            (
                s.chunk.header
                for s in canonical.find_chunks(MhypHeader)
                if s.chunk.header.master_flag & 1
            ),
            None,
        )
        if canonical is not None
        else None
    )
    return SQLiteNativeMetadata(
        tuple(containers),
        tuple(chapters),
        document.header.db_persistent_id or document.header.db_id,
        master.playlist_id if master is not None else 0,
        document.header.version,
        project_mac(master.timestamp, device_time) if master is not None else 0,
        project_mac(master.timestamp_2 or master.timestamp, device_time)
        if master is not None
        else 0,
    )
