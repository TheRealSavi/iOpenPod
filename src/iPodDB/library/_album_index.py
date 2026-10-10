"""MHOD 52/36 album traversal, measured against captured iTunesDB indexes.

Indices address Master Playlist occurrences. Albums are contiguous, ordered by
their representative's album-artist/album sort values; members use disc/track
numbers. Source order breaks ties. See docs/research/itunesdb-sort-36.md.
"""

import unicodedata
from collections import defaultdict
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Literal

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPayload,
    MhodLibraryIndexPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.library._document_edit import rebuild
from iPodDB.library._playlist_datasets import is_master, playlist_rows
from iPodDB.library._projection import project_tracks
from iPodDB.library.models import Track
from iPodDB.library.writing import IssueSeverity, WriteIssue
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk

SORT_TYPE = 36
type AlbumIdentity = tuple[str, ...]
type TextKey = tuple[int, str]
type Punctuation = Literal[
    "punctuation_retained", "artist_hyphens_ignored", "punctuation_ignored"
]


@dataclass(frozen=True)
class CollationProfile:
    punctuation: Punctuation
    literal_sort_overrides: bool
    empty_albums_last: bool
    compilations_last: bool


# An unrecognized source order uses this policy with a warning (ADR-0137).
# Keep the fallback explicit even if captured-profile preference changes later.
DEFAULT_PROFILE = CollationProfile("punctuation_retained", True, True, True)


# Prefer the more discriminating capture's rules when both families fit. Keep
# the historical profiles for sources whose retained order requires them.
PROFILES = tuple(
    CollationProfile(punctuation, revised, revised, revised)
    for revised in (True, False)
    for punctuation in (
        "punctuation_retained",
        "artist_hyphens_ignored",
        "punctuation_ignored",
    )
)


def is_album_index(chunk: ParsedChunk[ChunkHeader]) -> bool:
    return (
        isinstance(chunk.prefix, MhodLibraryIndexPrefix)
        and chunk.prefix.sort_type == SORT_TYPE
        and isinstance(chunk.payload, MhodLibraryIndexPayload)
    )


def master_tracks(
    master: ParsedChunk[MhypHeader], tracks: tuple[Track, ...]
) -> tuple[Track, ...]:
    by_id = {t.track_id: t for t in tracks}
    return tuple(
        by_id[c.header.track_id]
        for c in master.children
        if isinstance(c.header, MhipHeader) and c.header.track_id in by_id
    )


def _identity(track: Track) -> AlbumIdentity:
    if track.ipod and track.ipod.album_id:
        return ("native", str(track.ipod.album_id))
    # Older layouts can omit the album table/reference altogether.
    return ("unreferenced", track.album, track.album_artist or track.artist, track.show)


def _numbers(track: Track) -> tuple[int, int]:
    return (
        track.metadata.disc_number or 0x100000000,
        track.track_number or 0x100000000,
    )


@dataclass(frozen=True)
class AlbumGroup:
    identity: AlbumIdentity
    artist: str
    album: str
    members: tuple[Track, ...]
    artist_override: bool
    album_override: bool
    compilation_without_album_artist: bool

    @property
    def sort_values(self) -> tuple[str, str, bool, bool, bool]:
        return (
            self.artist,
            self.album,
            self.artist_override,
            self.album_override,
            self.compilation_without_album_artist,
        )


def groups(
    document: DatabaseDocument[MhbdHeader], tracks: tuple[Track, ...]
) -> tuple[AlbumGroup, ...]:
    representatives: dict[int, int] = {}
    for row in document.find_chunks(MhiaHeader):
        header = row.chunk.header
        if header.album_id in representatives:
            raise ValueError("Sort 36 requires unambiguous native album records.")
        representatives[header.album_id] = header.album_track_db_id
    members: dict[AlbumIdentity, list[Track]] = defaultdict(list)
    for track in tracks:
        members[_identity(track)].append(track)
    result: list[AlbumGroup] = []
    for identity, values in members.items():
        reference = (
            representatives.get(int(identity[1]), 0) if identity[0] == "native" else 0
        )
        representative = next(
            (
                t
                for t in values
                if reference and t.ipod and t.ipod.db_track_id == reference
            ),
            None,
        )
        if reference and representative is None:
            raise ValueError("Sort 36's album representative is outside its album.")
        representative = representative or min(values, key=_numbers)
        meta = representative.metadata
        result.append(
            AlbumGroup(
                identity,
                meta.sort_album_artist
                or representative.album_artist
                or meta.sort_artist
                or representative.artist,
                meta.sort_album or representative.album,
                tuple(values),
                bool(
                    meta.sort_album_artist
                    or (not representative.album_artist and meta.sort_artist)
                ),
                bool(meta.sort_album),
                meta.compilation
                and not (meta.sort_album_artist or representative.album_artist),
            )
        )
    return tuple(result)


def _text(
    value: str, profile: CollationProfile, *, artist: bool, override: bool
) -> TextKey:
    # The observed profiles differ even for equal MHBD platform/language values;
    # select only a profile consistent with the retained index, never by Host OS.
    if not (
        override and profile.literal_sort_overrides
    ) and value.casefold().startswith("the "):
        value = value[4:]
    value = (
        "".join(
            c
            for c in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(c)
        )
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )
    if profile.punctuation == "punctuation_ignored":
        value = "".join(c for c in value if not unicodedata.category(c).startswith("P"))
    elif profile.punctuation == "artist_hyphens_ignored" and artist:
        value = value.replace("-", "")
    empty_bucket = 2 if artist or profile.empty_albums_last else -1
    bucket = empty_bucket if not value else int(value[0].isdigit())
    return bucket, value


def _key(group: AlbumGroup, profile: CollationProfile) -> tuple[bool, TextKey, TextKey]:
    compilation = profile.compilations_last and group.compilation_without_album_artist
    return (
        compilation,
        _text(
            "" if compilation else group.artist,
            profile,
            artist=True,
            override=group.artist_override,
        ),
        _text(group.album, profile, artist=False, override=group.album_override),
    )


def _source_order(
    payload: MhodLibraryIndexPayload, tracks: tuple[Track, ...]
) -> tuple[Track, ...]:
    if sorted(payload.indices) != list(range(len(tracks))):
        raise ValueError(
            "Sort 36 must cover each Master Playlist position exactly once."
        )
    if len({t.track_id for t in tracks}) != len(tracks):
        raise ValueError("Sort 36 requires unique Master Playlist Track occurrences.")
    return tuple(tracks[i] for i in payload.indices)


def _group_order(tracks: tuple[Track, ...]) -> tuple[AlbumIdentity, ...]:
    order: list[AlbumIdentity] = []
    seen: set[AlbumIdentity] = set()
    for track in tracks:
        identity = _identity(track)
        if not order or identity != order[-1]:
            if identity in seen:
                raise ValueError("Sort 36 contains a noncontiguous native album.")
            seen.add(identity)
            order.append(identity)
    return tuple(order)


def _profile(groups_in_order: tuple[AlbumGroup, ...]) -> CollationProfile | None:
    for profile in PROFILES:
        keys = tuple(_key(g, profile) for g in groups_in_order)
        if all(a <= b for a, b in pairwise(keys)):
            return profile
    return None


def _group_keys_changed(
    before: tuple[AlbumGroup, ...], after: tuple[AlbumGroup, ...]
) -> bool:
    old = {g.identity: g.sort_values for g in before}
    return any(old.get(g.identity) != g.sort_values for g in after)


def _dependencies(
    document: DatabaseDocument[MhbdHeader], tracks: tuple[Track, ...]
) -> tuple[object, ...]:
    return (
        tuple(
            (
                t.track_id,
                t.ipod.album_id if t.ipod else 0,
                t.ipod.db_track_id if t.ipod else 0,
                t.artist,
                t.metadata.sort_artist,
                t.album_artist,
                t.metadata.sort_album_artist,
                t.album,
                t.metadata.sort_album,
                t.metadata.compilation,
                t.show,
                _numbers(t),
            )
            for t in tracks
        ),
        tuple(
            (s.chunk.header.album_id, s.chunk.header.album_track_db_id)
            for s in document.find_chunks(MhiaHeader)
        ),
    )


@dataclass(frozen=True)
class PreparedAlbumIndex:
    payload: MhodLibraryIndexPayload
    used_default_order: bool = False


def prepare_album_index(
    source: DatabaseDocument[MhbdHeader],
    candidate: DatabaseDocument[MhbdHeader],
    previous: tuple[Track, ...],
    desired: tuple[Track, ...],
    payload: MhodLibraryIndexPayload,
) -> PreparedAlbumIndex:
    if _dependencies(source, previous) == _dependencies(candidate, desired):
        return PreparedAlbumIndex(payload)
    ordered_source = _source_order(payload, previous)
    old_groups = groups(source, ordered_source)
    old_order = _group_order(ordered_source)
    old_identities = set(old_order)
    new_groups = groups(candidate, desired)
    new = {g.identity: g for g in new_groups}
    order = [new[i] for i in old_order if i in new]
    order.extend(g for g in new_groups if g.identity not in old_identities)
    used_default_order = False
    if _group_keys_changed(old_groups, new_groups):
        profile = _profile(old_groups)
        used_default_order = profile is None
        selected = profile or DEFAULT_PROFILE
        order.sort(key=lambda g: _key(g, selected))
    ranks = {t.track_id: i for i, t in enumerate(ordered_source)}
    positions = {t.track_id: i for i, t in enumerate(desired)}
    indices: list[int] = []
    for group in order:
        members = sorted(
            group.members,
            key=lambda t: (
                *_numbers(t),
                ranks.get(t.track_id, len(ranks) + positions[t.track_id]),
            ),
        )
        indices.extend(positions[t.track_id] for t in members)
    return PreparedAlbumIndex(
        replace(payload, indices=tuple(indices)), used_default_order
    )


def reconcile_album_indexes(
    source: DatabaseDocument[MhbdHeader],
    candidate: DatabaseDocument[MhbdHeader],
    issues: list[WriteIssue],
) -> DatabaseDocument[MhbdHeader]:
    rows = [
        (k, s)
        for k, s in playlist_rows(candidate)
        if is_master(k, s.chunk.header)
        and any(is_album_index(c) for c in s.chunk.children)
    ]
    if not rows:
        return candidate
    before, desired = project_tracks(source), project_tracks(candidate)
    old = {
        (k, s.chunk.header.playlist_id): s.chunk
        for k, s in playlist_rows(source)
        if is_master(k, s.chunk.header)
    }
    edits: dict[int, ParsedChunk[ChunkHeader] | None] = {}
    for kind, row in rows:
        master = row.chunk
        baseline = old.get((kind, master.header.playlist_id))
        if baseline is None:
            baseline = old.get((3, master.header.playlist_id)) or old.get(
                (2, master.header.playlist_id)
            )
        if baseline is None:
            issues.append(
                WriteIssue(
                    "library.album_index", "Sort 36 has no retained source index."
                )
            )
            continue
        sources = [c for c in baseline.children if is_album_index(c)]
        targets = [c for c in master.children if is_album_index(c)]
        try:
            if len(sources) != 1 or len(targets) != 1:
                raise ValueError(
                    "Sort 36 requires one unambiguous index per Master Playlist."
                )
            payload = sources[0].payload
            assert isinstance(payload, MhodLibraryIndexPayload)
            updated = prepare_album_index(
                source,
                candidate,
                master_tracks(baseline, before),
                master_tracks(master, desired),
                payload,
            )
            edits[id(targets[0])] = replace(targets[0], payload=updated.payload)
            if updated.used_default_order:
                issues.append(
                    WriteIssue(
                        "library.album_index",
                        "The retained sort-36 album collation is unrecognized. "
                        "A default album order was used; album browsing order may change.",
                        severity=IssueSeverity.WARNING,
                        phase="reconciliation",
                        subject="playlist",
                        record_id=master.header.playlist_id,
                    )
                )
        except ValueError as error:
            issues.append(
                WriteIssue(
                    "library.album_index",
                    str(error),
                    phase="reconciliation",
                    subject="playlist",
                    record_id=master.header.playlist_id,
                )
            )
    return rebuild(candidate, edits)


def verify_album_index(
    source: DatabaseDocument[MhbdHeader],
    candidate: DatabaseDocument[MhbdHeader],
    previous: tuple[Track, ...],
    desired: tuple[Track, ...],
    original: MhodLibraryIndexPayload,
    output: MhodLibraryIndexPayload,
) -> str | None:
    """Check permutation, group traversal and member/tie order without the writer."""
    if original.trailing_data != output.trailing_data:
        return "Sort 36's retained trailing data was modified."
    if _dependencies(source, previous) == _dependencies(candidate, desired):
        return (
            None if original == output else "An unchanged sort-36 index was modified."
        )
    try:
        old_tracks, new_tracks = (
            _source_order(original, previous),
            _source_order(output, desired),
        )
        old_groups, new_groups = (
            groups(source, old_tracks),
            groups(candidate, new_tracks),
        )
        old_order, new_order = _group_order(old_tracks), _group_order(new_tracks)
        new_identities = set(new_order)
        if _group_keys_changed(old_groups, new_groups):
            profile = _profile(old_groups) or DEFAULT_PROFILE
            keys = tuple(_key(g, profile) for g in new_groups)
            if any(a > b for a, b in pairwise(keys)):
                return "Sort 36's album groups have the wrong browse order."
            ranks = {identity: i for i, identity in enumerate(old_order)}
            for track in desired:
                identity = _identity(track)
                if identity not in ranks:
                    ranks[identity] = len(ranks)
            for left_group, right_group in pairwise(new_groups):
                if (
                    _key(left_group, profile) == _key(right_group, profile)
                    and ranks[left_group.identity] > ranks[right_group.identity]
                ):
                    return "Sort 36 changed the retained order of tied album groups."
        elif new_order != tuple(i for i in old_order if i in new_identities):
            return "Sort 36 changed the retained order of unchanged album groups."
        old_ranks = {t.track_id: i for i, t in enumerate(old_tracks)}
        new_positions = {t.track_id: i for i, t in enumerate(desired)}
        for group in new_groups:
            for a, b in pairwise(group.members):
                if _numbers(a) > _numbers(b):
                    return "Sort 36's album members have the wrong disc/track order."
                if _numbers(a) == _numbers(b) and old_ranks.get(
                    a.track_id, len(old_ranks) + new_positions[a.track_id]
                ) > old_ranks.get(
                    b.track_id, len(old_ranks) + new_positions[b.track_id]
                ):
                    return "Sort 36 changed the retained order of tied album members."
    except ValueError as error:
        return str(error)
    return None
