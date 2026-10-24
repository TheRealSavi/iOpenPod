"""Source ownership affected by splitting a shared native artist record."""

from collections import defaultdict
from collections.abc import Sequence

from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library.models import Track
from iPodDB.shared.chunk import ChunkHeader, ParsedChunk


def native_artist_name(row: ParsedChunk[ChunkHeader]) -> str | None:
    """A missing native label does not establish ownership, even for an empty name."""
    return next(
        (
            c.payload.value
            for c in reversed(row.children)
            if isinstance(c.header, MhodHeader)
            and c.header.mhod_type == MhodType.ARTIST_ITEM_ARTIST
            and isinstance(c.payload, MhodStringPayload)
        ),
        None,
    )


def shared_artist_changes(
    before: Sequence[Track], desired: Sequence[Track]
) -> dict[str, frozenset[int]]:
    """Find exact-name groups needing reconciliation after shared ownership changes.

    A membership change touches the old shared record, including when an entire
    group disappears. Reconcile its remaining groups too, so a formerly unchanged
    name cannot retain a record labelled for another artist. Unrelated edits do
    not repair source relationships. Values are source candidates, not output IDs.
    """
    prior: dict[str, set[int]] = defaultdict(set)
    current: dict[str, set[int]] = defaultdict(set)
    references: dict[str, set[int]] = defaultdict(set)
    names: dict[int, set[str]] = defaultdict(set)
    track_refs: dict[int, int] = {}
    for track in before:
        prior[track.artist].add(track.track_id)
        if track.ipod and track.ipod.artist_id_ref:
            identity = track.ipod.artist_id_ref
            references[track.artist].add(identity)
            names[identity].add(track.artist)
            track_refs[track.track_id] = identity
    for track in desired:
        current[track.artist].add(track.track_id)
    touched = {
        identity
        for name, members in prior.items()
        if members != current.get(name, set())
        for identity in references[name]
        if len(names[identity]) > 1
    }
    affected: dict[str, frozenset[int]] = {}
    for name, members in current.items():
        # Prefer the existing exact-name group when a rename joins it. Otherwise
        # the retained members identify the record from which a new name splits.
        candidates = references.get(name) or {
            track_refs[i] for i in members if i in track_refs
        }
        if candidates & touched:
            affected[name] = frozenset(candidates)
    return affected
