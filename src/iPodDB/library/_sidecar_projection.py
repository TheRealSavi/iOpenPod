"""Project captured firmware evidence without changing retained database bytes."""

from dataclasses import dataclass, replace

from iPodDB.device_time import DeviceTimeContext, mac_to_unix
from iPodDB.library.models import LibrarySnapshot, Track
from iPodDB.library.playlists import Playlist, PlaylistEntry, PlaylistSortOrder
from iPodDB.library.writing import WriteIssue
from iPodDB.sidecars import (
    PlaybackDateKind,
    PlaybackDocument,
    PlaybackEntry,
    PlaybackSidecar,
    otg_number,
    parse_otg_playlist,
    parse_playback,
)


@dataclass(frozen=True, slots=True)
class SidecarProjection:
    snapshot: LibrarySnapshot
    consumed: tuple[PlaybackSidecar, ...] = ()
    issues: tuple[WriteIssue, ...] = ()


def _merge(track: Track, entry: PlaybackEntry, context: DeviceTimeContext) -> Track:
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
    return replace(
        track,
        play_count=plays,
        rating=track.rating if entry.rating is None else entry.rating,
        metadata=replace(
            meta,
            unscrobbled_play_count=pending,
            skip_count=skips,
            last_played=date(entry.last_played, meta.last_played),
            last_skipped=date(entry.last_skipped, meta.last_skipped),
            bookmark_time_ms=entry.bookmark_time_ms or meta.bookmark_time_ms,
            played=meta.played or plays > 0,
        ),
    )


def _tracks(
    tracks: tuple[Track, ...], document: PlaybackDocument, context: DeviceTimeContext
) -> tuple[Track, ...]:
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
            _merge(track, entries[identity], context) if identity in entries else track
            for track, identity in zip(tracks, identities, strict=True)
        )
    if len(document.entries) > len(tracks):
        raise ValueError("Playback sidecar has more rows than the Track table.")
    return tuple(
        _merge(track, document.entries[index], context)
        if index < len(document.entries)
        else track
        for index, track in enumerate(tracks)
    )


def project_sidecars(
    original: LibrarySnapshot,
    sidecars: tuple[PlaybackSidecar, ...],
    context: DeviceTimeContext,
) -> SidecarProjection:
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
                tracks, parse_playback(sidecar.name, sidecar.data), context
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
