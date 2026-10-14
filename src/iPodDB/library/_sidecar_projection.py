"""Project captured firmware evidence without changing retained database bytes."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace

from iPodDB.device_time import DeviceTimeContext, mac_to_unix
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library._field_policy import DATE_FIELDS, METADATA_FIELDS
from iPodDB.library.models import LibrarySnapshot, Track
from iPodDB.library.playlists import Playlist, PlaylistEntry, PlaylistSortOrder
from iPodDB.library.writing import WriteIssue
from iPodDB.shared.binary_struct import binary_fields
from iPodDB.sidecars import (
    PlaybackDateKind,
    PlaybackDocument,
    PlaybackEntry,
    PlaybackSidecar,
    otg_number,
    parse_otg_playlist,
    parse_playback,
)

logger = logging.getLogger(__name__)

_FIELD_ENDS = {
    f.attribute_name: f.schema.offset + f.schema.size for f in binary_fields(MhitHeader)
}
# Metadata merged from playback evidence, keyed to its native MHIT field.
# Original-format headers (e.g. 156 bytes) end before the skip fields.
_MERGED_METADATA = {
    name: METADATA_FIELDS.get(name) or DATE_FIELDS[name]
    for name in (
        "unscrobbled_play_count",
        "skip_count",
        "last_played",
        "last_skipped",
        "bookmark_time_ms",
    )
}


@dataclass(frozen=True, slots=True)
class SidecarProjection:
    snapshot: LibrarySnapshot
    consumed: tuple[PlaybackSidecar, ...] = ()
    issues: tuple[WriteIssue, ...] = ()


def _merge(
    track: Track,
    entry: PlaybackEntry,
    context: DeviceTimeContext,
    header_length: int | None,
) -> Track:
    def date(value: int, previous: int) -> int:
        if not value:
            return previous
        decoded = (
            mac_to_unix(value, context)
            if entry.date_kind is PlaybackDateKind.LOCAL_MAC
            else value
        )
        return max(decoded, previous) if previous else decoded

    meta = track.metadata
    plays = track.play_count + entry.play_count
    skips = meta.skip_count + entry.skip_count
    pending = meta.unscrobbled_play_count + entry.play_count
    if max(plays, skips, pending) > 0xFFFFFFFF:
        raise ValueError("Playback totals exceed the iTunesDB field range.")
    merged = replace(
        meta,
        unscrobbled_play_count=pending,
        skip_count=skips,
        last_played=date(entry.last_played, meta.last_played),
        last_skipped=date(entry.last_skipped, meta.last_skipped),
        bookmark_time_ms=entry.bookmark_time_ms or meta.bookmark_time_ms,
        played=meta.played or plays > 0,
    )
    if header_length is not None:
        # The retained header has nowhere to store this evidence; keep the
        # Track's current value rather than block loading the whole Library.
        dropped = {
            name: getattr(meta, name)
            for name, native in _MERGED_METADATA.items()
            if _FIELD_ENDS[native] > header_length
            and getattr(merged, name) != getattr(meta, name)
        }
        if dropped:
            logger.info(
                "Playback evidence %s for Track %d not imported: its %d-byte "
                "MHIT header predates those fields",
                ", ".join(sorted(dropped)),
                track.track_id,
                header_length,
            )
            merged = replace(merged, **dropped)
    return replace(
        track,
        play_count=plays,
        rating=track.rating if entry.rating is None else entry.rating,
        metadata=merged,
    )


def _tracks(
    tracks: tuple[Track, ...],
    document: PlaybackDocument,
    context: DeviceTimeContext,
    header_lengths: Mapping[int, int],
) -> tuple[Track, ...]:
    def merge(track: Track, entry: PlaybackEntry) -> Track:
        return _merge(track, entry, context, header_lengths.get(track.track_id))

    if document.format == "PlayCounts.plist":
        identities = [t.ipod.db_track_id if t.ipod else 0 for t in tracks]
        if len({identity for identity in identities if identity}) != sum(
            bool(identity) for identity in identities
        ):
            raise ValueError("Playback needs unique persistent Track identities.")
        entries = {e.persistent_id: e for e in document.entries}
        if not entries.keys() <= set(identities):
            raise ValueError("PlayCounts.plist references an unavailable Track.")
        return tuple(
            merge(track, entries[identity]) if identity in entries else track
            for track, identity in zip(tracks, identities, strict=True)
        )
    if len(document.entries) > len(tracks):
        raise ValueError("Playback sidecar has more rows than the Track table.")
    return tuple(
        merge(track, document.entries[index])
        if index < len(document.entries)
        else track
        for index, track in enumerate(tracks)
    )


def project_sidecars(
    original: LibrarySnapshot,
    sidecars: tuple[PlaybackSidecar, ...],
    context: DeviceTimeContext,
    header_lengths: Mapping[int, int] | None = None,
) -> SidecarProjection:
    """Overlay firmware evidence; ``header_lengths`` maps Track IDs to MHIT sizes."""
    by_name = {s.name.casefold(): s for s in sidecars}
    issues: list[WriteIssue] = []
    consumed: list[PlaybackSidecar] = []
    tracks = original.tracks
    playlists = list(original.playlists)

    def error(name: str, detail: str) -> None:
        issues.append(
            WriteIssue(
                "source.playback_sidecar",
                f"{name}: {detail} Reload after resolving this sidecar; its original bytes were preserved.",
                phase="source",
                artifact=name,
            )
        )

    if len(by_name) != len(sidecars):
        error("Playback sidecars", "Duplicate filenames are ambiguous.")
        return SidecarProjection(original, issues=tuple(issues))
    counts = [
        by_name[n]
        for n in ("play counts", "itunesstats", "playcounts.plist")
        if n in by_name
    ]
    if len(counts) > 1:
        error(
            "Playback sidecars",
            "Multiple playback sources could count the same plays twice.",
        )
    elif counts:
        sidecar = counts[0]
        try:
            tracks = _tracks(
                tracks,
                parse_playback(sidecar.name, sidecar.data),
                context,
                header_lengths or {},
            )
            consumed.append(sidecar)
        except ValueError as exc:
            error(sidecar.name, str(exc))

    # The base file is the firmware semaphore. Orphan numbered files are inactive.
    if "otgplaylistinfo" in by_name:
        numbered = sorted(
            (number, sidecar.name.casefold())
            for sidecar in sidecars
            if (number := otg_number(sidecar.name)) is not None
        )
        identity = min((0, *(p.playlist_id for p in playlists))) - 1
        for number, name in numbered:
            sidecar = by_name[name]
            try:
                document = parse_otg_playlist(sidecar.data)
                if any(p >= len(tracks) for p in document.positions):
                    raise ValueError(
                        "On-The-Go Playlist references an unavailable Track position."
                    )
                if document.positions:
                    playlists.append(
                        Playlist(
                            identity,
                            f"On-The-Go {number + 1}",
                            entries=tuple(
                                # OTG has no stored MHOD Playlist position yet.
                                # Derive it during preparation after draft edits.
                                PlaylistEntry(f"sidecar:{name}:{i}", tracks[p].track_id)
                                for i, p in enumerate(document.positions)
                            ),
                            sort_order=PlaylistSortOrder.MANUAL,
                        )
                    )
                    identity -= 1
                consumed.append(sidecar)
            except ValueError as exc:
                error(sidecar.name, str(exc))
    return SidecarProjection(
        replace(original, tracks=tracks, playlists=tuple(playlists)),
        tuple(consumed),
        tuple(issues),
    )
