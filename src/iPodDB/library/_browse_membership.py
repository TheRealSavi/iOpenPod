"""Resolve membership edits against source browse records and Track links."""

from collections import Counter, defaultdict
from collections.abc import Mapping, Set
from dataclasses import dataclass, field

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library._artist_groups import native_artist_name, shared_artist_changes
from iPodDB.library._browse_groups import album_values, group_text, native_browse_groups
from iPodDB.library.models import LibrarySnapshot, MediaKind, Track
from iPodDB.shared.chunk import DatabaseDocument, ParsedChunk


@dataclass(frozen=True, slots=True)
class RetainedBrowseGroup:
    links: dict[int, int]
    choices: dict[int, tuple[int, ...]]
    album_text_edits: dict[int, dict[MhodType, str]] = field(
        default_factory=dict[int, dict[MhodType, str]]
    )
    new_albums: dict[int, tuple[int, str]] = field(
        default_factory=dict[int, tuple[int, str]]
    )
    detail: str = ""


def browse_reference(track: Track, *, album: bool) -> int:
    if track.ipod is None:
        return 0
    return track.ipod.album_id if album else track.ipod.artist_id_ref


def _store_album(track: Track | None) -> int:
    return track.ipod.store_album_id if track and track.ipod else 0


def _album_destinations(
    joining: tuple[Track, ...],
    candidates: set[int],
    albums: dict[int, list[ParsedChunk[MhiaHeader]]],
    album_members: dict[int, list[Track]],
    old: dict[int, Track],
) -> tuple[dict[int, set[int]], str]:
    values = album_values(joining)
    compatible: dict[int, set[int]] = {}
    for identity in sorted(candidates):
        row = albums[identity][0]
        if (
            row.header.content_type_flag == values.content_type
            and row.header.album_compilation_flag == int(values.compilation)
            and row.header.season_number == values.season
            and group_text(row, MhodType.ALBUM_ITEM_ALBUM) == values.title
            and group_text(row, MhodType.ALBUM_ITEM_ARTIST) == values.artist
            and group_text(row, MhodType.ALBUM_ITEM_SHOW) == values.show
        ):
            compatible[identity] = {
                release
                for member in album_members[identity]
                if (release := _store_album(member))
            }
    joining_releases = {t.track_id: _store_album(old.get(t.track_id)) for t in joining}
    new_releases = set(joining_releases.values()) - {0}
    known = {release for store_ids in compatible.values() for release in store_ids}
    destinations: dict[int, set[int]] = {}
    fallback = False
    for t in joining:
        options: set[int]
        release = joining_releases[t.track_id]
        feed = t.metadata.podcast_rss_url
        eligible = {
            identity
            for identity, store_ids in compatible.items()
            if len(store_ids) <= 1
            and (
                not feed
                or group_text(albums[identity][0], MhodType.ALBUM_ITEM_PODCAST_URL)
                in ("", feed)
            )
        }
        if release and known:
            options = {
                identity for identity in eligible if compatible[identity] == {release}
            }
        elif known:
            options = {
                identity for identity in eligible if compatible[identity]
            } or eligible
        else:
            options = eligible if len(new_releases) <= 1 else set()
        feeds = {
            group_text(albums[identity][0], MhodType.ALBUM_ITEM_PODCAST_URL)
            for identity in options
        }
        fallback |= not options or (
            len(options) > 1 and (len(feeds) > 1 or len(known) > 1)
        )
        destinations[t.track_id] = options
    evidence = {identity: sorted(ids) for identity, ids in compatible.items()}
    return destinations, f"Candidate Store Album IDs {evidence!r}." if fallback else ""


def _duplicate_album_membership(
    prior: tuple[Track, ...],
    members: tuple[Track, ...],
    candidates: set[int],
    albums: dict[int, list[ParsedChunk[MhiaHeader]]],
    album_members: dict[int, list[Track]],
    old: dict[int, Track],
) -> RetainedBrowseGroup | None:
    prior_ids = {t.track_id for t in prior}
    if (
        prior_ids == {t.track_id for t in members}
        and album_values(prior) == album_values(members)
        and all(album_values((old[t.track_id],)) == album_values((t,)) for t in members)
    ):
        return None
    usable = {
        i
        for i in candidates
        if len(albums.get(i, ())) == 1
        and all(t.track_id in prior_ids for t in album_members[i])
    }

    links: dict[int, int] = {}
    staying: dict[int, list[Track]] = defaultdict(list)
    for track in members:
        if track.track_id in prior_ids:
            identity = browse_reference(old[track.track_id], album=True)
            if identity in usable or not identity:
                links[track.track_id] = identity
                staying[identity].append(track)

    choices: dict[int, tuple[int, ...]] = {}
    joining = tuple(t for t in members if t.track_id not in links)
    destinations, detail = (
        _album_destinations(joining, usable, albums, album_members, old)
        if joining
        else ({}, "")
    )
    new_albums: dict[int, tuple[int, str]] = {}
    for track in joining:
        track_id = track.track_id
        options = destinations[track_id]
        if options:
            links[track_id] = min(options, key=lambda i: (-len(staying[i]), i))
        else:
            links[track_id] = 0
            new_albums[track_id] = (
                _store_album(old.get(track_id)),
                track.metadata.podcast_rss_url,
            )
        if len(options) > 1:
            choices[track_id] = tuple(sorted(options))

    edits: dict[int, dict[MhodType, str]] = {}
    for identity in usable:
        survivors = staying[identity]
        if not survivors:
            continue
        ids = {t.track_id for t in survivors}
        before = album_values([t for t in album_members[identity] if t.track_id in ids])
        after = album_values(survivors)
        changes = {}
        if before.sort_artist != after.sort_artist:
            changes[MhodType.ALBUM_ITEM_SORT_ARTIST] = after.sort_artist
        if before.podcast_url != after.podcast_url:
            changes[MhodType.ALBUM_ITEM_PODCAST_URL] = after.podcast_url
        if changes:
            edits[identity] = changes
    if not edits and not joining and prior_ids == links.keys():
        return None
    return RetainedBrowseGroup(
        links, choices, album_text_edits=edits, new_albums=new_albums, detail=detail
    )


def retained_album_representative(
    pid: int, before: Set[int], after: Set[int], deleted: set[int]
) -> int:
    if pid in deleted or (pid in before and pid not in after):
        return min(after, default=0)
    return pid


def select_browse_id(
    candidates: set[int],
    rows: Mapping[int, tuple[int, str | None]],
    owners: Mapping[int, set[int]],
    members: Set[int],
    *,
    excluded: Set[int] = frozenset(),
    artist: str | None = None,
) -> int:
    options = (
        i
        for i in candidates
        if i
        and i in rows
        and rows[i][0] == 1
        and i not in excluded
        and (artist is None or rows[i][1] == artist)
    )
    return min(options, key=lambda i: (-len(owners[i] & members), i), default=0)


def _same_browse_values(
    old: Track, new: Track, *, artist_label: str | None = None
) -> bool:
    return old.artist == new.artist and (
        artist_label == old.artist
        or old.effective_album_artist == new.effective_album_artist
    )


def _exact_artist_membership(
    prior: tuple[Track, ...],
    members: tuple[Track, ...],
    sources: Set[int],
    labels: dict[int, str | None],
    *,
    splitting: bool,
) -> RetainedBrowseGroup | None:
    if len(sources) < 2 or not sources <= labels.keys():
        return None
    exact = {i for i in sources if labels[i] == members[0].artist}
    if not exact or (not splitting and exact != sources):
        return None

    member_ids = {t.track_id for t in members}
    links = {
        t.track_id: identity
        for t in prior
        if t.track_id in member_ids
        and (
            (identity := browse_reference(t, album=False)) in exact
            or (not identity and not splitting)
        )
    }
    surviving = Counter(links.values())
    winner = min(exact, key=lambda i: (-surviving[i], i))
    relinked = member_ids - links.keys()
    links.update(dict.fromkeys(relinked, winner))
    return RetainedBrowseGroup(
        links, dict.fromkeys(relinked, tuple(sorted(exact))) if len(exact) > 1 else {}
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

    Album choices supply context for new artist links. An exact Artist label
    remains valid through an Album Artist edit. During a split, an established
    exact-name record can also receive Tracks that need a different link.
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
            t.track_id not in new or _same_browse_values(t, new[t.track_id])
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
            candidates = {browse_reference(t, album=album) for t in prior} - {0}
            if album:
                incoming = tuple(t for t in members if t.track_id not in old)
                pure_membership_change = (
                    prior_ids != member_ids
                    and not ((prior_ids - member_ids) & new.keys())
                    and all(
                        t.track_id not in old
                        or (
                            t.track_id in prior_ids
                            and album_values((old[t.track_id],)) == album_values((t,))
                        )
                        for t in members
                    )
                )
                if len(candidates) == 1 and pure_membership_change:
                    identity = next(iter(candidates))
                    album_context.update((t.track_id, identity) for t in incoming)
                if not incoming and pure_membership_change and key[0] != "podcast":
                    plans[True][key] = RetainedBrowseGroup(
                        {
                            t.track_id: browse_reference(old[t.track_id], album=True)
                            for t in members
                        },
                        {},
                    )
                    continue
                if len(candidates) > 1 and not any(
                    t.media_kind is MediaKind.PODCAST or t.metadata.podcast
                    for t in (*prior, *members)
                ):
                    album_plan = _duplicate_album_membership(
                        prior, members, candidates, albums, album_members, old
                    )
                    if album_plan is not None:
                        plans[album][key] = album_plan
                        album_context.update(
                            (t.track_id, album_plan.links[t.track_id]) for t in incoming
                        )
                continue
            moved = bool(
                (prior_ids - member_ids) & new.keys()
                or (member_ids - prior_ids) & old.keys()
            )
            split_sources = artist_changes.get(members[0].artist)
            if prior and (split_sources or moved):
                sources = split_sources or candidates
                if sources.isdisjoint(album_artist_ids):
                    artist_plan = _exact_artist_membership(
                        prior, members, sources, labels, splitting=bool(split_sources)
                    )
                    if artist_plan is not None:
                        plans[album][key] = artist_plan
                        continue
            incoming = tuple(t for t in members if t.track_id not in old)
            if (
                prior_ids == member_ids
                or moved
                or any(
                    t.track_id in old
                    and not _same_browse_values(
                        old[t.track_id],
                        t,
                        artist_label=labels.get(
                            browse_reference(old[t.track_id], album=False)
                        ),
                    )
                    for t in members
                )
            ):
                continue
            context = {
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
            if split_sources or not (
                not incoming
                or len(candidates) > 1
                or candidates & album_artist_ids
                or any(ids & album_artist_ids for ids in context.values())
            ):
                continue

            links = {
                t.track_id: browse_reference(old[t.track_id], album=album)
                for t in members
                if t.track_id in old
            }
            surviving = Counter(links.values())
            choices: dict[int, tuple[int, ...]] = {}
            for t in incoming:
                options = context[t.track_id] or {
                    identity
                    for identity in candidates
                    if labels.get(identity) == t.artist
                }
                if context[t.track_id]:
                    exact = {
                        identity for identity in options if labels[identity] == t.artist
                    }
                    options = exact or options
                winner = max(sorted(options), key=lambda i: surviving[i], default=0)
                links[t.track_id] = winner
                if len(options) > 1:
                    choices[t.track_id] = tuple(sorted(options))
            plans[album][key] = RetainedBrowseGroup(links, choices)
    return plans, artist_changes
