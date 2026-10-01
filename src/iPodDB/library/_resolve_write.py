"""Resolve desired edits and their consequences before changing retained documents."""

import math
from dataclasses import replace

from iPodDB.device_time import DeviceTimeContext
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_jump_table_mhod import (
    MhodLibraryJumpTablePrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.library._browse_index import resolve_indexes
from iPodDB.library._folder_validation import folder_issues
from iPodDB.library._hierarchy import folder_hierarchy
from iPodDB.library._identities import IdentityAllocator, allocate
from iPodDB.library._playlist_datasets import (
    affected_datasets,
    is_master,
    is_podcasts,
    playlist_rows,
    structure_issues,
)
from iPodDB.library._podcast_writing import normalize_podcast_order
from iPodDB.library._resolved_write import FolderWrite, ResolvedWrite
from iPodDB.library._source_warnings import source_warnings
from iPodDB.library._write_analysis import analyze
from iPodDB.library._write_effects import compare_generated_values, describe_effects
from iPodDB.library.models import LibrarySnapshot, Track
from iPodDB.library.playlists import PlaylistKind
from iPodDB.library.writing import (
    IssueSeverity,
    LibraryDraft,
    LibraryResolution,
    WriteIssue,
    WriteTarget,
)
from iPodDB.shared.chunk import DatabaseDocument

PRESERVATION = (
    "Unchanged semantic values retain their native representation and Unknown Data.",
    "Unrelated datasets, photo data, and retained artwork byte ranges remain intact.",
    "Retained Playlist occurrences keep their private metadata.",
    "Unsupported untouched Smart rules and saved membership remain unchanged.",
)


def _values(
    before: LibrarySnapshot, desired: LibrarySnapshot, issues: list[WriteIssue]
) -> LibrarySnapshot:
    original = {t.track_id: t for t in before.tracks}
    tracks: list[Track] = []
    for track in desired.tracks:
        prior = original.get(track.track_id)
        meta = track.metadata
        if prior is None or prior.metadata.lyrics != meta.lyrics:
            meta = replace(meta, has_lyrics=bool(meta.lyrics))
        if (
            prior is None
            or prior.play_count != track.play_count
            or prior.metadata.played != meta.played
        ):
            meta = replace(meta, played=track.play_count > 0 or meta.played)
        for attr in ("volume_adjustment_percent", "normalization_gain_db"):
            value = getattr(meta, attr)
            if prior is not None and value == getattr(prior.metadata, attr):
                continue
            try:
                if attr == "volume_adjustment_percent":
                    actual = round(value * 255 / 100) / 255 * 100
                elif value is None:
                    continue
                else:
                    encoded = round(1000 * 10 ** (-value / 10))
                    if not 0 < encoded <= 0xFFFFFFFF:
                        raise ValueError(
                            "Normalization gain is outside the representable range."
                        )
                    actual = 10 * math.log10(1000 / encoded)
                if attr == "volume_adjustment_percent" and not math.isclose(
                    value, actual, abs_tol=1e-9
                ):
                    issues.append(
                        WriteIssue(
                            "track.quantized",
                            f"The iPod will store {actual:.6g} for {attr}.",
                            IssueSeverity.WARNING,
                            "resolution",
                            "track",
                            track.track_id,
                            "metadata." + attr,
                        )
                    )
                meta = replace(meta, **{attr: actual})
            except (ValueError, OverflowError) as error:
                issues.append(
                    WriteIssue(
                        "track.cannot_encode",
                        str(error),
                        phase="resolution",
                        subject="track",
                        record_id=track.track_id,
                        field="metadata." + attr,
                    )
                )
        tracks.append(replace(track, metadata=meta))
    return replace(desired, tracks=tuple(tracks))


def resolve(
    document: DatabaseDocument[MhbdHeader],
    original: LibrarySnapshot,
    draft: LibraryDraft,
    target: WriteTarget,
    source_revision: str,
    device_time: DeviceTimeContext,
) -> ResolvedWrite:
    plan = analyze(source_revision, original, draft, target, device_time)
    issues = [*plan.issues, *source_warnings(document, original)]
    requested = draft.snapshot
    desired = requested
    generated = frozenset[int]()
    # Invalid parent graphs and malformed draft values must not enter derivation.
    if not plan.blocked:
        desired, generated = normalize_podcast_order(
            document, original, requested, issues
        )
        desired = _values(original, desired, issues)
    if plan.blocked:
        return ResolvedWrite(
            replace(plan, issues=tuple(issues)),
            original,
            desired,
            frozenset(),
            False,
            frozenset(),
            generated,
            frozenset(),
            (),
            False,
            (),
            (),
            (),
            (),
            (),
        )
    affected = affected_datasets(original, desired)
    if plan.changes_itunes:
        datasets = document.find_chunks(MhsdHeader)
        issues.extend(
            WriteIssue(
                "library.ambiguous_dataset",
                f"Dataset {kind} occurs more than once; semantic correspondence is ambiguous.",
                phase="resolution",
                field="datasets",
            )
            for kind in (1, 2, 3, 4, 8)
            if sum(s.chunk.header.dataset_type == kind for s in datasets) > 1
        )
    issues.extend(
        i
        for i in structure_issues(
            document, affected=True, affected_kinds=affected, phase="resolution"
        )
        if i.severity is IssueSeverity.ERROR
    )
    ordered, aggregates, children = folder_hierarchy(desired)
    _, old_aggregates, old_children = folder_hierarchy(original)
    folders = tuple(
        FolderWrite(
            p.playlist_id,
            aggregates[p.playlist_id],
            tuple(c.playlist_id for c in children[p.playlist_id]),
            tuple(c.playlist_id for c in old_children[p.playlist_id]),
        )
        for p in ordered
        if p.kind is PlaylistKind.FOLDER
        and (
            aggregates[p.playlist_id] != old_aggregates.get(p.playlist_id)
            or tuple(c.playlist_id for c in children[p.playlist_id])
            != tuple(c.playlist_id for c in old_children[p.playlist_id])
        )
    )
    issues.extend(folder_issues(document, folders))
    structural = tuple(t.track_id for t in original.tracks) != tuple(
        t.track_id for t in desired.tracks
    )
    topology = tuple((p.playlist_id, p.parent_id) for p in original.playlists) != tuple(
        (p.playlist_id, p.parent_id) for p in desired.playlists
    )
    old_playlists = {p.playlist_id: p for p in original.playlists}
    new_playlists = {p.playlist_id: p for p in desired.playlists}
    changed = frozenset(
        i
        for i in old_playlists.keys() | new_playlists.keys()
        if old_playlists.get(i) != new_playlists.get(i)
    ) | frozenset(f.playlist_id for f in folders)
    rows = playlist_rows(document)
    old_tracks = {t.track_id: t for t in original.tracks}
    albums_changed = {
        t.track_id
        for t in desired.tracks
        if t.track_id not in old_tracks or old_tracks[t.track_id].album != t.album
    }
    podcasts = generated | frozenset(
        s.chunk.header.playlist_id
        for kind, s in rows
        if is_podcasts(kind, s.chunk.header)
        and (
            s.chunk.header.playlist_id in new_playlists
            and (
                s.chunk.header.playlist_id not in old_playlists
                or old_playlists[s.chunk.header.playlist_id].entries
                != new_playlists[s.chunk.header.playlist_id].entries
                or albums_changed.intersection(
                    new_playlists[s.chunk.header.playlist_id].track_ids
                )
            )
        )
    )
    indexes = (
        resolve_indexes(original.tracks, desired.tracks) if plan.changes_itunes else ()
    )
    index_map = {index.sort_type: index for index in indexes}
    if any(index.affected for index in indexes):
        for kind, row in rows:
            if not is_master(kind, row.chunk.header):
                continue
            for selection in row.find_chunks(MhodHeader):
                prefix = selection.chunk.prefix
                if (
                    isinstance(
                        prefix, MhodLibraryIndexPrefix | MhodLibraryJumpTablePrefix
                    )
                    and prefix.sort_type not in index_map
                    and not (
                        isinstance(prefix, MhodLibraryIndexPrefix)
                        and prefix.sort_type == 36
                    )
                ):
                    issues.append(
                        WriteIssue(
                            "library.unsupported_index",
                            f"Library index sort type {prefix.sort_type} is not understood.",
                            phase="resolution",
                            subject="playlist",
                            record_id=row.chunk.header.playlist_id,
                            offset=selection.chunk.offset,
                        )
                    )
    native_tracks = document.find_chunks(MhitHeader)
    native_playlists = document.find_chunks(MhypHeader)
    track_ids: dict[int, int] = {}
    playlist_ids: dict[int, int] = {}
    persistent_ids = {
        t.track_id: t.ipod.db_track_id if t.ipod else 0 for t in original.tracks
    }
    hidden = {
        s.chunk.header.playlist_id for s in native_playlists
    } - old_playlists.keys()
    issues.extend(
        WriteIssue(
            "playlist.hidden_identity",
            "A new Playlist identity collides with a hidden source Playlist.",
            phase="resolution",
            subject="playlist",
            record_id=identity,
        )
        for identity in hidden.intersection(new_playlists)
    )
    for subject, existing, desired_ids, bits, output in (
        (
            "track",
            tuple(s.chunk.header.track_id for s in native_tracks),
            tuple(t.track_id for t in desired.tracks),
            32,
            track_ids,
        ),
        (
            "playlist",
            tuple(s.chunk.header.playlist_id for s in native_playlists),
            tuple(new_playlists),
            64,
            playlist_ids,
        ),
    ):
        try:
            output.update(allocate(existing, desired_ids, bits))
        except ValueError as error:
            issues.append(
                WriteIssue(
                    "library.identity_exhausted",
                    str(error),
                    phase="resolution",
                    subject=subject,
                )
            )
    try:
        allocator = IdentityAllocator(
            (
                identity
                for s in native_tracks
                for identity in (
                    s.chunk.header.db_track_id,
                    s.chunk.header.db_track_id_2,
                )
            ),
            64,
        )
        for track in desired.tracks:
            if track.track_id not in persistent_ids:
                persistent_ids[track.track_id] = allocator.take()
    except ValueError as error:
        issues.append(
            WriteIssue(
                "library.identity_exhausted",
                str(error),
                phase="resolution",
                subject="track",
                field="ipod.db_track_id",
            )
        )
    resolved = ResolvedWrite(
        replace(plan, issues=tuple(issues)),
        original,
        desired,
        affected,
        structural,
        changed,
        generated,
        podcasts,
        tuple(p.playlist_id for p in ordered),
        topology,
        folders,
        indexes,
        tuple(track_ids.items()),
        tuple(playlist_ids.items()),
        tuple(persistent_ids.items()),
        artwork_tracks=tuple(
            t.track_id
            for t in desired.tracks
            if t.artwork_id
            != (old_tracks[t.track_id].artwork_id if t.track_id in old_tracks else 0)
        ),
        deleted_tracks=frozenset(old_tracks)
        - frozenset(t.track_id for t in desired.tracks),
    )
    generated_changes = compare_generated_values(requested, desired)
    resolution = LibraryResolution(
        desired,
        generated_changes,
        describe_effects(document, resolved, generated_changes),
        PRESERVATION,
    )
    return replace(resolved, plan=replace(resolved.plan, resolution=resolution))
