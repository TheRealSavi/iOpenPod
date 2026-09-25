"""Private reconciliation of semantic changes with retained iTunesDB records."""

import logging
from collections import Counter, defaultdict, deque
from dataclasses import replace

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhlp import DEFINITION as MHLP
from iPodDB.iTunesDB.shared.chunk_defs.mhlt import DEFINITION as MHLT
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartNumericRuleData,
    MhodSmartRuleGroupData,
    MhodSmartRulesPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import DEFINITION as MHYP
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library._album_index import reconcile_album_indexes
from iPodDB.library._document_edit import rebuild
from iPodDB.library._folder_writing import reconcile_folders
from iPodDB.library._hidden_writing import ensure_master_indexes, reconcile_hidden
from iPodDB.library._identities import IdentityAllocator
from iPodDB.library._playlist_datasets import (
    ensure_companion,
    is_visible,
    playlist_rows,
)
from iPodDB.library._playlist_projection import project_playlist
from iPodDB.library._playlist_writing import (
    edit_playlist,
    playlist_preferences,
    position_item,
)
from iPodDB.library._podcast_writing import reconcile_podcasts
from iPodDB.library._resolved_write import ResolvedWrite
from iPodDB.library._track_writing import edit_text, edit_track
from iPodDB.library.writing import (
    IdentityMapping,
    WriteIssue,
    WriteResources,
)
from iPodDB.shared.chunk import (
    ChunkHeader,
    DatabaseDocument,
    EmptyChunkHeader,
    ParsedChunk,
)

logger = logging.getLogger(__name__)


def reconcile(
    document: DatabaseDocument[MhbdHeader],
    resolved: ResolvedWrite,
    resources: WriteResources,
    issues: list[WriteIssue],
) -> tuple[DatabaseDocument[MhbdHeader], tuple[IdentityMapping, ...]]:
    source_document = document
    original, desired = resolved.original, resolved.desired
    logger.debug(
        "Library reconciliation source=%s datasets=%s structural_tracks=%s changed_playlists=%s podcast_playlists=%s folders=%d",
        resolved.plan.draft.source_revision,
        sorted(resolved.affected_datasets),
        resolved.structural_tracks,
        sorted(resolved.changed_playlists),
        sorted(resolved.podcast_playlists),
        len(resolved.folders),
    )
    generated_podcasts = resolved.generated_podcasts
    original_tracks = {t.track_id: t for t in original.tracks}
    desired_tracks = {t.track_id: t for t in desired.tracks}
    all_playlist_chunks = document.find_chunks(MhypHeader)
    occurrence_allocator = IdentityAllocator(
        (s.chunk.header.mhip_persistent_id for s in document.find_chunks(MhipHeader)),
        64,
    )
    existing_rows = frozenset(
        (k, s.chunk.header.playlist_id) for k, s in playlist_rows(document)
    )
    if resolved.affected_datasets.intersection((2, 3)):
        document = ensure_companion(document, occurrence_allocator)
    track_ids = dict(resolved.track_ids)
    playlist_ids = dict(resolved.playlist_ids)
    persistent_ids = dict(resolved.persistent_ids)
    media = {m.track_id: m for m in resources.media}
    lyrics = {item.track_id: item for item in resources.lyrics}
    required_media = frozenset(resolved.plan.required_media)
    datasets = document.find_chunks(MhsdHeader)
    track_dataset = next(
        (s for s in datasets if s.chunk.header.dataset_type == 1), None
    )
    source_tracks = (
        {}
        if track_dataset is None
        else {
            s.chunk.header.track_id: s.chunk
            for s in track_dataset.find_chunks(MhitHeader)
        }
    )
    track_output: list[ParsedChunk[ChunkHeader]] = []
    for track in desired.tracks:
        old = original_tracks.get(track.track_id)
        track_chunk = source_tracks.get(track.track_id)
        if (
            old == track
            and track_chunk is not None
            and track.track_id not in required_media
        ):
            track_output.append(track_chunk)
            continue
        try:
            track_output.append(
                edit_track(
                    track_chunk,
                    old,
                    track,
                    track_ids[track.track_id],
                    persistent_ids[track.track_id],
                    document.header.timezone_offset,
                    media.get(track.track_id),
                    issues,
                    lyrics=lyrics.get(track.track_id),
                )
            )
        except (ValueError, OverflowError) as error:
            issues.append(
                WriteIssue(
                    "track.cannot_encode",
                    str(error),
                    subject="track",
                    record_id=track.track_id,
                )
            )
            if track_chunk is not None:
                track_output.append(track_chunk)
    if track_dataset is not None:
        container = track_dataset.chunk.children[0]
        pending_tracks = iter(track_output)
        ordered_children: list[ParsedChunk[ChunkHeader]] = []
        for child in container.children:
            if isinstance(child.header, MhitHeader):
                next_track = next(pending_tracks, None)
                if next_track is not None:
                    ordered_children.append(next_track)
            else:
                ordered_children.append(child)
        ordered_children.extend(pending_tracks)
        replacement = replace(
            track_dataset.chunk,
            children=(replace(container, children=tuple(ordered_children)),),
        )
        document = document.replace_chunk(track_dataset, replacement)
    elif track_output:
        document = document.append_child(
            new_itunes_chunk(
                MHSD,
                MhsdHeader(dataset_type=1),
                children=(
                    new_itunes_chunk(
                        MHLT, EmptyChunkHeader(), children=tuple(track_output)
                    ),
                ),
            )
        )
    # Selections are now recreated against the current immutable tree.
    datasets = document.find_chunks(MhsdHeader)
    canonical = next(
        (s for kind in (3, 2) for s in datasets if s.chunk.header.dataset_type == kind),
        None,
    )
    if canonical is None and desired.playlists:
        master_id = IdentityAllocator(
            (
                *playlist_ids.values(),
                *(s.chunk.header.playlist_id for s in all_playlist_chunks),
            ),
            64,
        ).take()
        master = edit_text(
            new_itunes_chunk(
                MHYP,
                MhypHeader(master_flag=1, playlist_id=master_id, sort_order=5),
                children=tuple(
                    position_item(
                        new_itunes_chunk(
                            MHIP,
                            MhipHeader(
                                track_id=track_ids[t.track_id],
                                track_persistent_id=persistent_ids[t.track_id],
                            ),
                        ),
                        i,
                    )
                    for i, t in enumerate(desired.tracks)
                ),
            ),
            MhodType.TITLE,
            desired.device_name,
            first=True,
        )
        master = replace(
            master,
            children=(*master.children, playlist_preferences()),
            header=replace(master.header, string_mhod_child_count=1),
        )
        document = document.append_child(
            new_itunes_chunk(
                MHSD,
                MhsdHeader(dataset_type=2),
                children=(
                    new_itunes_chunk(MHLP, EmptyChunkHeader(), children=(master,)),
                ),
            )
        )
        datasets = document.find_chunks(MhsdHeader)
        canonical = next(s for s in datasets if s.chunk.header.dataset_type == 2)
    original_playlists = {p.playlist_id: p for p in original.playlists}
    wanted_playlists = {p.playlist_id: p for p in desired.playlists}
    changed_ids = resolved.changed_playlists
    canonical_raw = (
        {}
        if canonical is None
        else {
            s.chunk.header.playlist_id: project_playlist(
                s, frozenset(original_tracks), document.header.timezone_offset
            )
            for s in canonical.find_chunks(MhypHeader)
        }
    )
    canonical_occurrences = (
        {}
        if canonical is None
        else {
            s.chunk.header.playlist_id: tuple(
                item.chunk.header.track_id for item in s.find_chunks(MhipHeader)
            )
            for s in canonical.find_chunks(MhypHeader)
        }
    )
    replacements: dict[int, ParsedChunk[ChunkHeader] | None] = {}
    structural_tracks = resolved.structural_tracks
    podcast_ids: set[int] = (
        set()
        if canonical is None
        else {
            s.chunk.header.playlist_id
            for s in canonical.find_chunks(MhypHeader)
            if is_visible(3, s.chunk.header) and s.chunk.header.playlist_kind_flags & 1
        }
    )
    for dataset in datasets:
        kind = dataset.chunk.header.dataset_type
        if kind not in (2, 3, 5):
            continue
        is_canonical = canonical is not None and dataset.path == canonical.path
        selections = dataset.find_chunks(MhypHeader)
        present = {s.chunk.header.playlist_id for s in selections}
        for selection in selections:
            chunk = selection.chunk
            identity = chunk.header.playlist_id
            if (
                kind in (2, 3)
                and chunk.header.master_flag & 1
                and chunk.header.mhsd_5_type == 0
            ):
                if original.device_name != desired.device_name:
                    chunk = edit_text(
                        chunk, MhodType.TITLE, desired.device_name, first=True
                    )
                if structural_tracks:
                    source_items = tuple(
                        s.chunk for s in selection.find_chunks(MhipHeader)
                    )
                    source_item_ids = [c.header.track_id for c in source_items]
                    if len(set(source_item_ids)) != len(source_item_ids) or any(
                        c.header.podcast_group_flag & 0x100 for c in source_items
                    ):
                        issues.append(
                            WriteIssue(
                                "library.ambiguous_master",
                                "The affected Master Playlist has duplicate or grouped occurrences that cannot be safely reconciled.",
                                record_id=identity,
                            )
                        )
                        continue
                    by_track = {c.header.track_id: c for c in source_items}
                    items: list[ParsedChunk[MhipHeader]] = []
                    for index, track in enumerate(desired.tracks):
                        item = by_track.get(track.track_id) or new_itunes_chunk(
                            MHIP,
                            MhipHeader(
                                track_id=track_ids[track.track_id],
                                track_persistent_id=persistent_ids[track.track_id],
                            ),
                        )
                        items.append(position_item(item, index))
                    retained_start = len(items)
                    items.extend(
                        position_item(item, retained_start + index)
                        for index, item in enumerate(
                            c
                            for c in source_items
                            if c.header.track_id not in original_tracks
                        )
                    )
                    chunk = replace(
                        chunk,
                        children=(
                            *tuple(
                                c
                                for c in chunk.children
                                if not isinstance(c.header, MhipHeader)
                            ),
                            *items,
                        ),
                    )
                replacements[id(selection.chunk)] = chunk
                continue
            if identity not in changed_ids or not is_visible(kind, chunk.header):
                # Remove deleted Track references from hidden firmware lists.
                deleted = original_tracks.keys() - desired_tracks.keys()
                if deleted:
                    removed = any(
                        isinstance(c.header, MhipHeader)
                        and c.header.track_id in deleted
                        for c in chunk.children
                    )
                    chunk = replace(
                        chunk,
                        children=tuple(
                            c
                            for c in chunk.children
                            if not isinstance(c.header, MhipHeader)
                            or c.header.track_id not in deleted
                        ),
                    )
                    if removed:
                        position = 0
                        positioned: list[ParsedChunk[ChunkHeader]] = []
                        for child in chunk.children:
                            if (
                                isinstance(child.header, MhipHeader)
                                and not child.header.podcast_group_flag & 0x100
                            ):
                                from iPodDB.shared.chunk import chunk_as

                                child = position_item(
                                    chunk_as(child, MhipHeader),
                                    child.header.group_id
                                    if child.header.group_id_ref
                                    else position,
                                )
                                position += 1
                            positioned.append(child)
                        chunk = replace(chunk, children=tuple(positioned))
                    replacements[id(selection.chunk)] = chunk
                continue
            baseline = original_playlists.get(identity)
            actual = project_playlist(
                selection, frozenset(original_tracks), document.header.timezone_offset
            )
            if not is_canonical:
                reference = canonical_raw.get(identity)
                if (
                    reference is None
                    or replace(actual, entries=()) != replace(reference, entries=())
                    or (
                        Counter(actual.track_ids) != Counter(reference.track_ids)
                        if identity in podcast_ids
                        else actual.track_ids != reference.track_ids
                    )
                    or bool(chunk.header.playlist_kind_flags & 1)
                    != (identity in podcast_ids)
                    or (
                        chunk.header.playlist_kind_flags & 0x100
                        and tuple(
                            item.chunk.header.track_id
                            for item in selection.find_chunks(MhipHeader)
                        )
                        != canonical_occurrences.get(identity)
                    )
                ):
                    issues.append(
                        WriteIssue(
                            "playlist.ambiguous_mirror",
                            "The other playlist dataset disagrees with this Playlist. Its relationship cannot be rewritten safely.",
                            subject="playlist",
                            record_id=identity,
                            detail=f"Dataset {kind}",
                        )
                    )
                    continue
            wanted = wanted_playlists.get(identity)
            if wanted is None:
                replacements[id(selection.chunk)] = None
                continue
            if not is_canonical and baseline:
                occurrences: dict[int, deque[str]] = defaultdict(deque)
                for entry in actual.entries:
                    occurrences[entry.track_id].append(entry.entry_id)
                entry_map = {
                    e.entry_id: occurrences[e.track_id].popleft()
                    for e in baseline.entries
                }
                wanted = replace(
                    wanted,
                    entries=actual.entries
                    if wanted.entries == baseline.entries
                    else tuple(
                        replace(e, entry_id=entry_map.get(e.entry_id, e.entry_id))
                        for e in wanted.entries
                    ),
                )
                baseline = replace(baseline, entries=actual.entries)
            try:
                logger.debug(
                    "Playlist reconciliation dataset=%d id=%d canonical=%s entries_before=%d entries_after=%d membership_changed=%s",
                    kind,
                    identity,
                    is_canonical,
                    len(baseline.entries) if baseline else 0,
                    len(wanted.entries),
                    baseline is None or baseline.entries != wanted.entries,
                )
                replacements[id(selection.chunk)] = edit_playlist(
                    chunk,
                    baseline,
                    wanted,
                    playlist_ids,
                    track_ids,
                    persistent_ids,
                    document.header.timezone_offset,
                    document.header.db_id_2,
                )
            except ValueError as error:
                issues.append(
                    WriteIssue(
                        "playlist.cannot_encode",
                        str(error),
                        subject="playlist",
                        record_id=identity,
                    )
                )
        mirror_rows = {
            s.chunk.header.playlist_id: project_playlist(
                s, frozenset(original_tracks), document.header.timezone_offset
            )
            for s in selections
            if s.chunk.header.playlist_id in original_playlists
            and is_visible(kind, s.chunk.header)
        }
        established_mirror = (
            kind in (2, 3)
            and mirror_rows.keys() == original_playlists.keys()
            and all(
                replace(p, entries=()) == replace(canonical_raw[identity], entries=())
                and (
                    Counter(p.track_ids) == Counter(canonical_raw[identity].track_ids)
                    if identity in podcast_ids
                    else p.track_ids == canonical_raw[identity].track_ids
                )
                for identity, p in mirror_rows.items()
            )
        )
        if (
            kind in (2, 3)
            and not is_canonical
            and not established_mirror
            and wanted_playlists.keys() - original_playlists.keys()
        ):
            issues.append(
                WriteIssue(
                    "playlist.ambiguous_mirror",
                    "New Playlists require an established counterpart dataset; the existing playlist datasets disagree.",
                    detail=f"Dataset {kind}. Resolve its relationship before adding Playlists.",
                )
            )
        if is_canonical or established_mirror:
            additions = [p for p in desired.playlists if p.playlist_id not in present]
            if additions:
                container = rebuild(dataset.chunk.children[0], replacements)
                for playlist in additions:
                    try:
                        container = container.append_child(
                            edit_playlist(
                                None,
                                None,
                                playlist,
                                playlist_ids,
                                track_ids,
                                persistent_ids,
                                document.header.timezone_offset,
                                document.header.db_id_2,
                            )
                        )
                    except ValueError as error:
                        issues.append(
                            WriteIssue(
                                "playlist.cannot_encode",
                                str(error),
                                subject="playlist",
                                record_id=playlist.playlist_id,
                            )
                        )
                replacements[id(dataset.chunk)] = replace(
                    dataset.chunk, children=(container,)
                )
    document = rebuild(document, replacements)
    deleted_playlists = original_playlists.keys() - wanted_playlists.keys()
    for selection in document.find_chunks(MhypHeader):
        if selection.chunk.header.playlist_kind_flags & 0x100:
            continue  # Folder references are reconciled immediately below.
        for child in selection.chunk.children:
            if not isinstance(child.payload, MhodSmartRulesPayload):
                continue
            pending = list(child.payload.rules)
            while pending:
                rule = pending.pop()
                if isinstance(rule.data, MhodSmartRuleGroupData):
                    pending.extend(rule.data.rules)
                elif (
                    rule.field_id == 0x28
                    and isinstance(rule.data, MhodSmartNumericRuleData)
                    and rule.data.from_value in deleted_playlists
                ):
                    issues.append(
                        WriteIssue(
                            "playlist.referenced_by_rule",
                            "A retained Smart Playlist rule references the deleted Playlist. Remove that dependency before preparing.",
                            subject="playlist",
                            record_id=selection.chunk.header.playlist_id,
                            field="smart",
                            offset=child.offset,
                        )
                    )

    document = reconcile_folders(
        document, resolved, playlist_ids, track_ids, persistent_ids
    )

    document = reconcile_hidden(
        document, original, desired, track_ids, issues, resolved.indexes
    )
    document = ensure_master_indexes(
        document,
        desired,
        existing_rows,
        resolved.indexes,
        structural_tracks=structural_tracks,
    )
    document = reconcile_album_indexes(source_document, document, issues)

    for _, selection in playlist_rows(document):
        if selection.chunk.header.playlist_id in {
            playlist_ids[i] for i in generated_podcasts
        }:
            document = document.replace_chunk(
                selection,
                replace(
                    selection.chunk,
                    header=replace(
                        selection.chunk.header,
                        playlist_kind_flags=selection.chunk.header.playlist_kind_flags
                        | 1,
                    ),
                ),
            )
    document = reconcile_podcasts(
        document, original, desired, track_ids, playlist_ids, resolved.podcast_playlists
    )
    # New occurrences receive private native identities. Retained short headers
    # and even pre-existing zero IDs are left exactly as loaded.
    occurrence_edits: dict[int, ParsedChunk[ChunkHeader] | None] = {}
    for occurrence in document.find_chunks(MhipHeader):
        item = occurrence.chunk
        if item.raw_header or item.header.mhip_persistent_id:
            continue
        occurrence_edits[id(item)] = replace(
            item,
            header=replace(item.header, mhip_persistent_id=occurrence_allocator.take()),
        )
    document = rebuild(document, occurrence_edits)
    mappings = tuple(
        IdentityMapping(subject, draft_id, native_id)
        for subject, mapping in (("track", track_ids), ("playlist", playlist_ids))
        for draft_id, native_id in mapping.items()
        if draft_id != native_id
    )
    return document, mappings
