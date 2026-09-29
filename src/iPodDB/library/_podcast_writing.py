"""Retain podcast group ownership while reconciling affected album groups.

The layout follows Original iOpenPod's mhyp_writer/_build_podcast_grouped_mhips:
group MHIPs use flag 0x100; episode positions contain their own group_id.
"""

import logging
from dataclasses import replace
from itertools import groupby

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library._document_edit import rebuild
from iPodDB.library._playlist_datasets import is_podcasts, is_visible, playlist_rows
from iPodDB.library._playlist_writing import position_item
from iPodDB.library._track_writing import edit_text
from iPodDB.library.models import LibrarySnapshot, MediaKind
from iPodDB.library.playlists import Playlist, PlaylistEntry, PlaylistKind
from iPodDB.library.writing import IssueSeverity, WriteIssue
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk

logger = logging.getLogger(__name__)


def normalize_podcast_order(
    document: DatabaseDocument[MhbdHeader],
    original: LibrarySnapshot,
    desired: LibrarySnapshot,
    issues: list[WriteIssue],
) -> tuple[LibrarySnapshot, frozenset[int]]:
    """Firmware requires contiguous shows; report the resulting saved order."""
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
    if original_members != desired_members:
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
            if tuple(synced_entries) != playlist.entries:
                issues.append(
                    WriteIssue(
                        "playlist.podcast_membership",
                        "The special Podcasts playlist was updated to contain the resulting podcast Tracks.",
                        IssueSeverity.INFO,
                        "reconciliation",
                        "playlist",
                        playlist.playlist_id,
                        "entries",
                    )
                )
        desired = replace(desired, playlists=tuple(synced))
    prior = {p.playlist_id: p for p in original.playlists}
    old_albums = {t.track_id: t.album for t in original.tracks}
    albums = {t.track_id: t.album for t in desired.tracks}
    output: list[Playlist] = []
    for playlist in desired.playlists:
        previous = prior.get(playlist.playlist_id)
        if playlist.playlist_id not in grouped_ids or (
            previous is not None
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
        entries = tuple(e for group in groups.values() for e in group)
        if entries != playlist.entries:
            logger.debug(
                "Podcast order resolved playlist=%d entries=%d album_groups=%d",
                playlist.playlist_id,
                len(entries),
                len(groups),
            )
            issues.append(
                WriteIssue(
                    "playlist.podcast_group_order",
                    "Podcast episodes were grouped by show; the prepared Playlist contains the resulting order.",
                    IssueSeverity.INFO,
                    "reconciliation",
                    "playlist",
                    playlist.playlist_id,
                    "entries",
                )
            )
        output.append(replace(playlist, entries=entries))
    return replace(desired, playlists=tuple(output)), generated


def reconcile_podcasts(
    document: DatabaseDocument[MhbdHeader],
    original: LibrarySnapshot,
    desired: LibrarySnapshot,
    track_ids: dict[int, int],
    playlist_ids: dict[int, int],
    affected_playlists: frozenset[int],
) -> DatabaseDocument[MhbdHeader]:
    old_tracks = {t.track_id: t for t in original.tracks}
    albums = {track_ids[t.track_id]: t.album for t in desired.tracks}
    changed_playlists = {playlist_ids[i] for i in affected_playlists}
    edits: dict[int, ParsedChunk[ChunkHeader] | None] = {}
    for kind, selection in playlist_rows(document):
        chunk = selection.chunk
        if not is_podcasts(kind, chunk.header):
            continue
        items = tuple(s.chunk for s in selection.find_chunks(MhipHeader))
        groups = tuple(c for c in items if c.header.podcast_group_flag & 0x100)
        episodes = tuple(c for c in items if not c.header.podcast_group_flag & 0x100)
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
        cursor = max((c.header.group_id for c in items), default=0) + 1

        def identity() -> int:
            nonlocal cursor
            value, cursor = cursor, cursor + 1
            if value > 0xFFFFFFFF:
                raise ValueError("Podcast group identities are exhausted.")
            return value

        children = [c for c in chunk.children if not isinstance(c.header, MhipHeader)]
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
                    new_itunes_chunk(
                        MHIP, MhipHeader(podcast_group_flag=0x100, group_id=identity())
                    ),
                    MhodType.TITLE,
                    album,
                )
            children.append(group)
            for episode in run:
                item_id = episode.header.group_id or identity()
                episode = replace(
                    episode,
                    header=replace(
                        episode.header,
                        group_id=item_id,
                        group_id_ref=group.header.group_id,
                    ),
                )
                children.append(position_item(episode, item_id))
        # Empty or renamed original groups are retained: their private metadata
        # remains available and they cannot resurrect an episode association.
        children.extend(group for album, group in by_album.items() if album not in seen)
        edits[id(chunk)] = replace(chunk, children=tuple(children))
    return rebuild(document, edits)
