"""Retain podcast group ownership while reconciling affected album groups.

Group MHIPs use flag 0x100. Episode positions agree across dataset counterparts;
Apple captures retain these values even when native row IDs change.
"""

import logging
from collections import defaultdict, deque
from dataclasses import replace
from itertools import groupby

from iPodDB.device_time import TimeConversion, unix_to_mac
from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.settings_mhod import (
    DEFAULT_PODCAST_SETTINGS,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library._document_edit import rebuild
from iPodDB.library._playlist_datasets import is_podcasts, is_visible, playlist_rows
from iPodDB.library._playlist_writing import position_item
from iPodDB.library._track_writing import edit_text
from iPodDB.library.models import LibrarySnapshot, MediaKind
from iPodDB.library.playlists import (
    Playlist,
    PlaylistEntry,
    PlaylistKind,
    PlaylistSortOrder,
)
from iPodDB.library.writing import WriteIssue
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk

logger = logging.getLogger(__name__)


def complete_podcast_settings(
    chunk: ParsedChunk[MhypHeader],
    timestamp: int,
    device_time: TimeConversion,
) -> ParsedChunk[MhypHeader]:
    """Fill missing settings and date an affected special Playlist counterpart."""
    children = chunk.children
    if not any(
        isinstance(child.header, MhodHeader)
        and child.header.mhod_type == MhodType.PLAYLIST_SETTINGS_BINARY
        for child in children
    ):
        settings = new_itunes_chunk(
            MHOD,
            MhodHeader(mhod_type=MhodType.PLAYLIST_SETTINGS_BINARY),
            payload=DEFAULT_PODCAST_SETTINGS,
        )
        index = next(
            (
                i
                for i, child in enumerate(children)
                if isinstance(child.header, MhipHeader)
            ),
            len(children),
        )
        children = (*children[:index], settings, *children[index:])
    header = chunk.header
    if timestamp:
        modified = unix_to_mac(timestamp, device_time)
        header = replace(
            header,
            timestamp=header.timestamp or modified,
            timestamp_2=modified,
        )
    return replace(chunk, header=header, children=children)


def normalize_podcast_order(
    document: DatabaseDocument[MhbdHeader],
    original: LibrarySnapshot,
    desired: LibrarySnapshot,
    issues: list[WriteIssue],
    *,
    repair_ids: frozenset[int] = frozenset(),
    normalize: bool = False,
    sqlite: bool = False,
) -> tuple[LibrarySnapshot, frozenset[int]]:
    """Maintain podcast membership and the contiguous shows required by firmware."""
    special = {
        s.chunk.header.playlist_id
        for kind, s in playlist_rows(document)
        if is_podcasts(kind, s.chunk.header)
    }
    grouped_ids = set(special)
    if not any(kind == 3 for kind, _ in playlist_rows(document)):
        special.update(
            s.chunk.header.playlist_id
            for kind, s in playlist_rows(document)
            if is_visible(kind, s.chunk.header)
            and s.chunk.header.playlist_kind_flags & 1
            and not s.chunk.header.playlist_kind_flags & 0x100
        )
    original_members = tuple(
        t.track_id
        for t in original.tracks
        if t.media_kind is MediaKind.PODCAST or t.metadata.podcast
    )
    desired_members = tuple(
        t.track_id
        for t in desired.tracks
        if t.media_kind is MediaKind.PODCAST or t.metadata.podcast
    )
    generated: frozenset[int] = frozenset()
    if original_members != desired_members or (normalize and desired_members):
        if not special and desired_members:
            if not any(kind == 3 for kind, _ in playlist_rows(document)):
                issues.append(
                    WriteIssue(
                        "playlist.podcast_capability",
                        "Creating the special Podcasts playlist requires an established podcast-aware dataset for this target.",
                        field="playlists",
                    )
                )
            else:
                identity = min((0, *(p.playlist_id for p in desired.playlists))) - 1
                generated = frozenset((identity,))
                special.add(identity)
                grouped_ids.add(identity)
                desired = replace(
                    desired,
                    playlists=(
                        *desired.playlists,
                        Playlist(identity, "Podcasts", PlaylistKind.PLAYLIST),
                    ),
                )
        synced: list[Playlist] = []
        for playlist in desired.playlists:
            if playlist.playlist_id not in special:
                synced.append(playlist)
                continue
            entries_by_track: dict[int, PlaylistEntry] = {}
            for entry in playlist.entries:
                entries_by_track.setdefault(entry.track_id, entry)
            used = {e.entry_id for e in playlist.entries}
            synced_entries: list[PlaylistEntry] = []
            for track_id in desired_members:
                retained_entry = entries_by_track.get(track_id)
                if retained_entry is None:
                    entry_id = f"podcast:{track_id}"
                    while entry_id in used:
                        entry_id += ":new"
                    used.add(entry_id)
                    retained_entry = PlaylistEntry(entry_id, track_id)
                synced_entries.append(retained_entry)
            synced.append(replace(playlist, entries=tuple(synced_entries)))
        desired = replace(desired, playlists=tuple(synced))
    prior = {p.playlist_id: p for p in original.playlists}
    old_albums = {t.track_id: t.album for t in original.tracks}
    albums = {t.track_id: t.album for t in desired.tracks}
    dates = {t.track_id: t.metadata.release_date for t in desired.tracks}
    output: list[Playlist] = []
    for playlist in desired.playlists:
        previous = prior.get(playlist.playlist_id)
        if normalize and playlist.playlist_id in special:
            playlist = replace(playlist, sort_order=PlaylistSortOrder.RELEASE_DATE)
        if (
            playlist.playlist_id in special
            and playlist.sort_order is PlaylistSortOrder.DEFAULT
            and (
                playlist != previous
                or playlist.playlist_id in repair_ids
                or any(
                    old_albums.get(e.track_id) != albums.get(e.track_id)
                    for e in playlist.entries
                )
            )
        ):
            playlist = replace(playlist, sort_order=PlaylistSortOrder.TITLE)
        if playlist.playlist_id not in grouped_ids or (
            previous is not None
            and playlist.playlist_id not in repair_ids
            and playlist.entries == previous.entries
            and all(
                old_albums.get(e.track_id) == albums.get(e.track_id)
                for e in playlist.entries
            )
        ):
            output.append(playlist)
            continue
        groups: dict[str, list[PlaylistEntry]] = {}
        for entry in playlist.entries:
            groups.setdefault(albums.get(entry.track_id, ""), []).append(entry)
        if normalize and sqlite:
            # Nano stores ascending dates; Dynamic.itdb reverses the display.
            # Stable ties preserve occurrence identity. Undated Episodes follow.
            for members in groups.values():
                members.sort(key=lambda e: (not dates[e.track_id], dates[e.track_id]))
        entries = tuple(e for group in groups.values() for e in group)
        if entries != playlist.entries:
            logger.debug(
                "Podcast order resolved playlist=%d entries=%d album_groups=%d",
                playlist.playlist_id,
                len(entries),
                len(groups),
            )
        output.append(replace(playlist, entries=entries))
    return replace(desired, playlists=tuple(output)), generated


def _positions(item: ParsedChunk[MhipHeader]) -> tuple[int, ...]:
    return tuple(
        c.prefix.position
        for c in item.children
        if isinstance(c.prefix, MhodPlaylistPositionPrefix)
    )


def podcast_rows_need_repair(
    items: tuple[ParsedChunk[MhipHeader], ...],
    counterpart: tuple[ParsedChunk[MhipHeader], ...] | None = None,
) -> bool:
    """Explicit repair includes row numbering, links, and counterpart positions."""
    flat: dict[int, deque[ParsedChunk[MhipHeader]]] = defaultdict(deque)
    for item in counterpart or ():
        flat[item.header.track_id].append(item)
    previous = 0
    for item in items:
        header = item.header
        if header.group_id <= previous or (
            not header.is_group and not header.group_id_ref
        ):
            return True
        previous = header.group_id
        if header.is_group:
            continue
        positions = _positions(item)
        if not positions or len(set(positions)) != 1:
            return True
        if counterpart is not None:
            matches = flat[header.track_id]
            if not matches:
                return True
            other = matches.popleft()
            if (
                other.header.group_id != header.group_id
                or other.header.is_group
                or other.header.group_id_ref
                or not _positions(other)
                or set(_positions(other)) != set(positions)
            ):
                return True
    return any(flat.values())


def reconcile_podcasts(
    document: DatabaseDocument[MhbdHeader],
    original: LibrarySnapshot,
    desired: LibrarySnapshot,
    track_ids: dict[int, int],
    playlist_ids: dict[int, int],
    affected_playlists: frozenset[int],
    *,
    normalize: bool = False,
) -> DatabaseDocument[MhbdHeader]:
    if not affected_playlists:
        return document
    old_tracks = {t.track_id: t for t in original.tracks}
    albums = {track_ids[t.track_id]: t.album for t in desired.tracks}
    changed_playlists = {playlist_ids[i] for i in affected_playlists}
    edits: dict[int, ParsedChunk[ChunkHeader] | None] = {}
    cursor = (
        max(
            (s.chunk.header.group_id for s in document.find_chunks(MhipHeader)),
            default=0,
        )
        + 1
    )
    for kind, selection in playlist_rows(document):
        chunk = selection.chunk
        if not is_podcasts(kind, chunk.header):
            continue
        items = tuple(s.chunk for s in selection.find_chunks(MhipHeader))
        groups = tuple(c for c in items if c.header.is_group)
        episodes = tuple(c for c in items if not c.header.is_group)
        if chunk.header.playlist_id not in changed_playlists:
            continue
        logger.debug(
            "Podcast reconciliation dataset=%d playlist=%d retained_groups=%d episodes=%d",
            kind,
            chunk.header.playlist_id,
            len(groups),
            len(episodes),
        )
        if any(c.header.track_id not in albums for c in episodes):
            raise ValueError(
                "An affected podcast group has unresolved Track references. Its membership cannot be maintained safely."
            )
        native_ids = [c.header.group_id for c in items if c.header.group_id]
        if len(native_ids) != len(set(native_ids)) or any(
            c.header.track_id or not c.header.group_id for c in groups
        ):
            raise ValueError(
                "Affected podcast groups have invalid or duplicate native identifiers."
            )
        by_album: dict[str, ParsedChunk[MhipHeader]] = {}
        for prior_group in groups:
            title = next(
                (
                    c.payload.value
                    for c in prior_group.children
                    if isinstance(c.payload, MhodStringPayload)
                ),
                None,
            )
            if title is None or title in by_album:
                raise ValueError(
                    "Affected podcast groups have missing or ambiguous album titles."
                )
            by_album[title] = prior_group
        titles_by_id = {
            group.header.group_id: album for album, group in by_album.items()
        }
        for episode in episodes:
            reference = episode.header.group_id_ref
            old_track = old_tracks.get(episode.header.track_id)
            if reference and (
                not episode.header.group_id
                or reference not in titles_by_id
                or (
                    old_track is not None and titles_by_id[reference] != old_track.album
                )
            ):
                raise ValueError(
                    "An affected podcast episode has an ambiguous retained show relationship."
                )
        previous_id = 0

        def identity(retained: int) -> int:
            nonlocal cursor, previous_id
            # Preserve an ordered prefix. Once a new row or a moved occurrence
            # needs an ID, allocate above every existing MHIP in the document.
            # Later rows then follow it numerically as well as physically.
            value = retained
            if value <= previous_id:
                value, cursor = cursor, cursor + 1
            if value > 0xFFFFFFFF:
                raise ValueError("Podcast group identities are exhausted.")
            previous_id = value
            return value

        children = [c for c in chunk.children if not isinstance(c.header, MhipHeader)]
        counterpart = next(
            (
                row
                for _, row in playlist_rows(document, (2,))
                if row.chunk.header.playlist_id == chunk.header.playlist_id
            ),
            None,
        )
        flat: dict[int, deque[ParsedChunk[MhipHeader]]] = defaultdict(deque)
        if counterpart is not None:
            for occurrence in counterpart.find_chunks(MhipHeader):
                item = occurrence.chunk
                if item.header.is_group or item.header.group_id_ref:
                    raise ValueError(
                        "Podcast counterparts have ambiguous Episode membership."
                    )
                flat[item.header.track_id].append(item)
        seen: set[str] = set()
        for album, run in groupby(episodes, key=lambda c: albums[c.header.track_id]):
            if album in seen:
                raise ValueError(
                    "Podcast episodes from each album must remain together in the grouped playlist. Reorder its entries before preparing."
                )
            seen.add(album)
            group = by_album.get(album)
            if group is None:
                group = edit_text(
                    new_itunes_chunk(MHIP, MhipHeader(podcast_group_flag=0x100)),
                    MhodType.TITLE,
                    album,
                )
            group = replace(
                group,
                header=replace(group.header, group_id=identity(group.header.group_id)),
            )
            children.append(group)
            for episode in run:
                item_id = identity(episode.header.group_id)
                # Counterparts can have different Track orders and persistent IDs.
                # Pair repeated Tracks by occurrence order, as playlist editing does.
                other = None
                if counterpart is not None:
                    matches = flat[episode.header.track_id]
                    if not matches:
                        raise ValueError(
                            "Podcast counterparts have ambiguous Episode membership."
                        )
                    other = matches.popleft()
                # Dataset 2 retains Apple's positions during link/row repair.
                # Membership edits already regenerate its ordinary positions.
                # Use the grouped value only when the flat value is unavailable.
                positions = (() if other is None else _positions(other)) or _positions(
                    episode
                )
                if len(set(positions)) > 1:
                    raise ValueError("Podcast Episode positions are ambiguous.")
                position = positions[0] if positions else item_id
                if normalize:
                    position = item_id
                episode = replace(
                    episode,
                    header=replace(
                        episode.header,
                        group_id=item_id,
                        group_id_ref=group.header.group_id,
                    ),
                )
                children.append(position_item(episode, position))
                if other is not None:
                    edits[id(other)] = position_item(
                        replace(other, header=replace(other.header, group_id=item_id)),
                        position,
                    )
        if any(flat.values()):
            raise ValueError("Podcast counterparts have ambiguous Episode membership.")
        # Empty or renamed original groups are retained: their private metadata
        # remains available and they cannot resurrect an episode association.
        for album, group in by_album.items():
            if album not in seen:
                children.append(
                    replace(
                        group,
                        header=replace(
                            group.header, group_id=identity(group.header.group_id)
                        ),
                    )
                )
        edits[id(chunk)] = replace(
            chunk,
            header=replace(
                chunk.header,
                phase_game_flag=((chunk.header.phase_game_flag & ~0x1FF) | 0x10B)
                if normalize
                else 11,
            ),
            children=tuple(children),
        )
    return rebuild(document, edits)
