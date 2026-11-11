"""Resolve membership edits against source browse records and Track links."""

from collections import Counter, defaultdict
from dataclasses import dataclass

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library._artist_groups import native_artist_name, shared_artist_changes
from iPodDB.library._browse_groups import album_values, group_text, native_browse_groups
from iPodDB.library.models import LibrarySnapshot, Track
from iPodDB.shared.chunk import DatabaseDocument, ParsedChunk


@dataclass(frozen=True, slots=True)
class RetainedBrowseGroup:
    links: dict[int, int]
    choices: dict[int, tuple[int, ...]]
    ambiguous: bool = False


def browse_reference(track: Track, *, album: bool) -> int:
    if track.ipod is None:
        return 0
    return track.ipod.album_id if album else track.ipod.artist_id_ref


def _album_description(row: ParsedChunk[MhiaHeader]) -> tuple[int | str, ...]:
    return (
        row.header.content_type_flag,
        row.header.album_compilation_flag,
        row.header.season_number,
        row.header.album_rating,
        row.header.rating_flag,
        *(
            group_text(row, kind)
            for kind in (
                MhodType.ALBUM_ITEM_ALBUM,
                MhodType.ALBUM_ITEM_ARTIST,
                MhodType.ALBUM_ITEM_SORT_ARTIST,
                MhodType.ALBUM_ITEM_PODCAST_URL,
                MhodType.ALBUM_ITEM_SHOW,
            )
        ),
    )


def _same_browse_values(old: Track, new: Track, *, album: bool) -> bool:
    if album:
        return album_values((old,)) == album_values((new,))
    return (old.artist, old.effective_album_artist) == (
        new.artist,
        new.effective_album_artist,
    )


def retained_browse_memberships(
    document: DatabaseDocument[MhbdHeader],
    before: LibrarySnapshot,
    desired: LibrarySnapshot,
) -> tuple[
    dict[bool, dict[tuple[str, ...], RetainedBrowseGroup]],
    dict[str, frozenset[int]],
]:
    """Use source membership for duplicates and for evidenced Album Artist links.

    Album choices supply context for new artist links. Explicit retagging and
    inconsistent shared records use the existing reconciliation rules.
    """
    old = {t.track_id: t for t in before.tracks}
    new = {t.track_id: t for t in desired.tracks}
    albums: dict[int, list[ParsedChunk[MhiaHeader]]] = defaultdict(list)
    artists: dict[int, list[ParsedChunk[MhiiHeader]]] = defaultdict(list)
    album_members: dict[int, list[Track]] = defaultdict(list)
    artist_members: dict[int, list[Track]] = defaultdict(list)
    for selection in document.find_chunks(MhiaHeader):
        albums[selection.chunk.header.album_id].append(selection.chunk)
    for artist in document.find_chunks(MhiiHeader):
        artists[artist.chunk.header.artist_id].append(artist.chunk)
    for t in before.tracks:
        album_members[browse_reference(t, album=True)].append(t)
        artist_members[browse_reference(t, album=False)].append(t)
    labels = {
        identity: native_artist_name(rows[0])
        for identity, rows in artists.items()
        if len(rows) == 1
    }
    album_artist_ids = {
        identity
        for identity, members in artist_members.items()
        if identity in labels
        and all(labels[identity] == t.effective_album_artist for t in members)
        and any(labels[identity] != t.artist for t in members)
        and all(
            t.track_id not in new
            or _same_browse_values(t, new[t.track_id], album=False)
            for t in members
        )
    }
    artist_changes = shared_artist_changes(
        before.tracks, desired.tracks, album_artist_ids
    )
    plans: dict[bool, dict[tuple[str, ...], RetainedBrowseGroup]] = {
        True: {},
        False: {},
    }
    album_context: dict[int, int] = {}

    for album in (True, False):
        prior_groups = native_browse_groups(before.tracks, album=album)
        for key, members in native_browse_groups(desired.tracks, album=album).items():
            prior = prior_groups.get(key, ())
            prior_ids = {t.track_id for t in prior}
            member_ids = {t.track_id for t in members}
            incoming = tuple(t for t in members if t.track_id not in old)
            if (
                prior_ids == member_ids
                or any(i in new for i in prior_ids - member_ids)
                or any(
                    t.track_id in old
                    and (
                        t.track_id not in prior_ids
                        or not _same_browse_values(old[t.track_id], t, album=album)
                    )
                    for t in members
                )
            ):
                continue
            candidates = {browse_reference(t, album=album) for t in prior} - {0}
            if album and len(candidates) == 1:
                album_context.update(
                    (t.track_id, next(iter(candidates))) for t in incoming
                )
            context = (
                {
                    t.track_id: {
                        browse_reference(member, album=False)
                        for member in album_members.get(
                            album_context.get(t.track_id, 0), ()
                        )
                        if album_context.get(t.track_id)
                        and (
                            member.artist == t.artist
                            or browse_reference(member, album=False) in album_artist_ids
                        )
                        and labels.get(browse_reference(member, album=False))
                        in (t.artist, t.effective_album_artist)
                    }
                    for t in incoming
                }
                if not album
                else {}
            )
            if (
                (album and key[0] == "podcast")
                or (not album and members[0].artist in artist_changes)
                or not (
                    not incoming
                    or len(candidates) > 1
                    or (
                        not album
                        and (
                            candidates & album_artist_ids
                            or any(ids & album_artist_ids for ids in context.values())
                        )
                    )
                )
            ):
                continue

            links = {
                t.track_id: browse_reference(old[t.track_id], album=album)
                for t in members
                if t.track_id in old
            }
            surviving = Counter(links.values())
            choices: dict[int, tuple[int, ...]] = {}
            ambiguous = False
            for t in incoming:
                if album:
                    compatible = (
                        len(
                            {
                                _album_description(albums[i][0])
                                for i in candidates
                                if len(albums.get(i, [])) == 1
                            }
                        )
                        == 1
                        and all(len(albums.get(i, [])) == 1 for i in candidates)
                        and all(
                            group_text(albums[i][0], MhodType.ALBUM_ITEM_ALBUM)
                            == t.album
                            and group_text(albums[i][0], MhodType.ALBUM_ITEM_ARTIST)
                            == t.effective_album_artist
                            and albums[i][0].header.album_compilation_flag
                            == int(t.metadata.compilation)
                            and albums[i][0].header.season_number == t.season_number
                            for i in candidates
                        )
                    )
                    release_ids = {
                        m.ipod.store_album_id
                        for i in candidates
                        for m in album_members[i]
                        if m.ipod and m.ipod.store_album_id
                    }
                    options: set[int] = (
                        candidates if compatible and len(release_ids) <= 1 else set()
                    )
                    if not options:
                        ambiguous = True
                        break
                else:
                    options = context[t.track_id] or {
                        identity
                        for identity in candidates
                        if labels.get(identity) == t.artist
                    }
                    if context[t.track_id]:
                        exact = {
                            identity
                            for identity in options
                            if labels[identity] == t.artist
                        }
                        options = exact or options
                    if len({labels[i] for i in options}) > 1:
                        ambiguous = True
                        break
                winner = max(sorted(options), key=lambda i: surviving[i], default=0)
                links[t.track_id] = winner
                if len(options) > 1:
                    choices[t.track_id] = tuple(sorted(options))
                if album:
                    album_context[t.track_id] = winner
            plans[album][key] = RetainedBrowseGroup(links, choices, ambiguous)
    return plans, artist_changes
