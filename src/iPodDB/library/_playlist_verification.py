"""Check reparsed playlist artifacts, including structures hidden by the projection."""

from collections import Counter
from dataclasses import replace

from iPodDB.device_time import TimeConversion
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPayload,
    MhodLibraryIndexPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_jump_table_mhod import (
    MhodLibraryJumpTablePayload,
    MhodLibraryJumpTablePrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartNumericRuleData,
    MhodSmartRulesPayload,
    MhodSmartRulesPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.library._album_index import master_tracks, verify_album_index
from iPodDB.library._hierarchy import folder_hierarchy
from iPodDB.library._index_verification import verify_index
from iPodDB.library._playlist_datasets import (
    affected_datasets,
    is_master,
    is_podcasts,
    is_visible,
    playlist_rows,
    structure_issues,
)
from iPodDB.library._playlist_projection import project_playlist
from iPodDB.library._projection import project_tracks
from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.writing import IdentityMapping, IssueSeverity, WriteIssue
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk


def _bytes(chunk: ParsedChunk[ChunkHeader], data: bytes) -> bytes:
    return data[
        chunk.offset : chunk.offset + chunk.generic_header.length_or_child_count
    ]


def verify_playlists(
    original: DatabaseDocument[MhbdHeader],
    checked: DatabaseDocument[MhbdHeader],
    before: LibrarySnapshot,
    desired: LibrarySnapshot,
    mappings: tuple[IdentityMapping, ...],
    original_bytes: bytes,
    output_bytes: bytes,
    generated_podcasts: frozenset[int] = frozenset(),
    device_time: TimeConversion = 0,
) -> tuple[WriteIssue, ...]:
    issues = list(
        structure_issues(
            checked,
            affected=True,
            affected_kinds=affected_datasets(before, desired),
            phase="verification",
        )
    )
    issues = [i for i in issues if i.severity is IssueSeverity.ERROR]
    source_anomalies = {
        (i.code, i.record_id, i.detail) for i in structure_issues(original)
    }
    seen = {(i.code, i.record_id, i.detail) for i in issues}
    for issue in structure_issues(checked, affected=True, phase="verification"):
        issue_key = (issue.code, issue.record_id, issue.detail)
        if (
            issue.severity is IssueSeverity.ERROR
            and issue_key not in source_anomalies
            and issue_key not in seen
        ):
            issues.append(issue)
            seen.add(issue_key)
    ids = {m.draft_id: m.output_id for m in mappings if m.subject == "playlist"}
    tracks = {m.draft_id: m.output_id for m in mappings if m.subject == "track"}
    track_ids = frozenset(tracks.get(t.track_id, t.track_id) for t in desired.tracks)
    deleted = {t.track_id for t in before.tracks} - {t.track_id for t in desired.tracks}
    old = {
        (k, s.chunk.header.playlist_id): s
        for k, s in playlist_rows(original, (2, 3, 5))
    }
    output = {
        (k, s.chunk.header.playlist_id): s for k, s in playlist_rows(checked, (2, 3, 5))
    }
    prior = {p.playlist_id: p for p in before.playlists}
    wanted = {ids.get(p.playlist_id, p.playlist_id): p for p in desired.playlists}
    ordered, aggregates, children = folder_hierarchy(desired)
    _, old_aggregates, old_children = folder_hierarchy(before)
    changed_folders = {
        p.playlist_id
        for p in desired.playlists
        if p.kind.value == "folder"
        and (
            aggregates[p.playlist_id] != old_aggregates.get(p.playlist_id)
            or tuple(c.playlist_id for c in children[p.playlist_id])
            != tuple(c.playlist_id for c in old_children[p.playlist_id])
        )
    }
    structural_tracks = tuple(t.track_id for t in before.tracks) != tuple(
        t.track_id for t in desired.tracks
    )
    old_albums = {t.track_id: t.album for t in before.tracks}
    albums = {tracks.get(t.track_id, t.track_id): t.album for t in desired.tracks}

    def fail(
        code: str,
        message: str,
        kind: int,
        chunk: ParsedChunk[MhypHeader] | None = None,
        *,
        detail: str = "",
        item: ParsedChunk[MhipHeader] | None = None,
    ) -> None:
        issues.append(
            WriteIssue(
                f"verification.{code}",
                message,
                phase="verification",
                subject="playlist" if chunk else "library",
                record_id=chunk.header.playlist_id if chunk else None,
                detail=f"Dataset {kind}. "
                + (f"{detail} " if detail else "")
                + "The candidate was withheld; the source remains unchanged.",
                offset=item.offset if item else chunk.offset if chunk else None,
                artifact="iTunesDB",
            )
        )

    kinds = [s.chunk.header.dataset_type for s in checked.find_chunks(MhsdHeader)]
    if not deleted:
        original_firmware = tuple(
            _bytes(s.chunk, original_bytes)
            for s in original.find_chunks(MhsdHeader)
            if s.chunk.header.dataset_type == 5
        )
        checked_firmware = tuple(
            _bytes(s.chunk, output_bytes)
            for s in checked.find_chunks(MhsdHeader)
            if s.chunk.header.dataset_type == 5
        )
        if original_firmware != checked_firmware:
            fail(
                "firmware_dataset", "An unrelated firmware category dataset changed.", 5
            )
    if (
        affected_datasets(before, desired).intersection((2, 3))
        and 3 in kinds
        and (2 not in kinds or kinds.index(3) > kinds.index(2))
    ):
        fail(
            "playlist_dataset_order",
            "The podcast-aware dataset requires a following standard playlist dataset.",
            3,
        )
    for key, selection in old.items():
        kind, identity = key
        chunk = selection.chunk
        if is_visible(kind, chunk.header) and identity in wanted and key not in output:
            fail(
                "playlist_missing_mirror",
                "A retained Playlist disappeared from its counterpart dataset.",
                kind,
                chunk,
            )
        if (is_visible(kind, chunk.header) and identity in prior) or is_master(
            kind, chunk.header
        ):
            continue
        retained = output.get(key)
        if retained is None:
            fail(
                "hidden_playlist",
                "A retained firmware Playlist disappeared.",
                kind,
                chunk,
            )
            continue
        if not deleted:
            if _bytes(chunk, original_bytes) != _bytes(retained.chunk, output_bytes):
                fail(
                    "hidden_playlist",
                    "An unrelated firmware Playlist changed.",
                    kind,
                    retained.chunk,
                )
        else:
            old_metadata = tuple(
                _bytes(c, original_bytes)
                for c in chunk.children
                if not isinstance(c.header, MhipHeader)
            )
            new_metadata = tuple(
                _bytes(c, output_bytes)
                for c in retained.chunk.children
                if not isinstance(c.header, MhipHeader)
            )
            expected_items = tuple(
                s.chunk.header.track_id
                for s in selection.find_chunks(MhipHeader)
                if s.chunk.header.track_id not in deleted
            )
            actual_items = tuple(
                s.chunk.header.track_id for s in retained.find_chunks(MhipHeader)
            )
            expected_header = replace(
                chunk.header, mhip_child_count=retained.chunk.header.mhip_child_count
            )
            if (
                old_metadata != new_metadata
                or expected_items != actual_items
                or expected_header != retained.chunk.header
            ):
                fail(
                    "hidden_playlist",
                    "A firmware Playlist changed beyond removing deleted Track references.",
                    kind,
                    retained.chunk,
                )

    for (kind, identity), selection in output.items():
        chunk = selection.chunk
        baseline = old.get((kind, identity))
        items = tuple(s.chunk for s in selection.find_chunks(MhipHeader))
        if is_master(kind, chunk.header):
            if before.device_name != desired.device_name or baseline is None:
                master_title = next(
                    (
                        c.payload.value
                        for c in chunk.children
                        if isinstance(c.payload, MhodStringPayload)
                    ),
                    "",
                )
                if master_title != desired.device_name:
                    fail(
                        "master_name",
                        "A Master Playlist does not contain the desired device name.",
                        kind,
                        chunk,
                    )
            if structural_tracks or baseline is None:
                if desired.tracks:
                    present_indexes = {
                        (c.header.mhod_type, c.prefix.sort_type)
                        for c in chunk.children
                        if isinstance(c.header, MhodHeader)
                        and isinstance(
                            c.prefix,
                            MhodLibraryIndexPrefix | MhodLibraryJumpTablePrefix,
                        )
                    }
                    if any(
                        (payload_type, sort) not in present_indexes
                        for payload_type in (52, 53)
                        for sort in (3, 4, 5, 7, 0x12)
                    ):
                        fail(
                            "playlist_index",
                            "A new or structurally edited Master is missing required browse indexes.",
                            kind,
                            chunk,
                        )
                expected = tuple(
                    tracks.get(t.track_id, t.track_id) for t in desired.tracks
                )
                retained_missing = (
                    ()
                    if baseline is None
                    else tuple(
                        s.chunk.header.track_id
                        for s in baseline.find_chunks(MhipHeader)
                        if s.chunk.header.track_id
                        not in {t.track_id for t in before.tracks}
                    )
                )
                if tuple(c.header.track_id for c in items) != (
                    *expected,
                    *retained_missing,
                ):
                    fail(
                        "master_membership",
                        "Master Playlist membership does not match the resulting library.",
                        kind,
                        chunk,
                    )
            for child in chunk.children:
                retained_index = baseline is not None and any(
                    _bytes(child, output_bytes) == _bytes(c, original_bytes)
                    for c in baseline.chunk.children
                    if not isinstance(c.header, MhipHeader)
                )
                if isinstance(
                    child.payload, MhodLibraryIndexPayload | MhodLibraryJumpTablePayload
                ):
                    if not isinstance(
                        child.prefix,
                        MhodLibraryIndexPrefix | MhodLibraryJumpTablePrefix,
                    ):
                        fail(
                            "playlist_index",
                            "A library index has no supported sort prefix.",
                            kind,
                            chunk,
                        )
                        continue
                    prior_tracks = (
                        master_tracks(baseline.chunk, before.tracks) if baseline else ()
                    )
                    final_tracks = master_tracks(
                        chunk,
                        tuple(
                            replace(t, track_id=tracks.get(t.track_id, t.track_id))
                            for t in desired.tracks
                        ),
                    )
                    if child.prefix.sort_type == 36 and isinstance(
                        child.payload, MhodLibraryIndexPayload
                    ):
                        source_master = (
                            baseline or old.get((3, identity)) or old.get((2, identity))
                        )
                        original_indexes = (
                            []
                            if source_master is None
                            else [
                                c.payload
                                for c in source_master.chunk.children
                                if isinstance(c.prefix, MhodLibraryIndexPrefix)
                                and c.prefix.sort_type == 36
                                and isinstance(c.payload, MhodLibraryIndexPayload)
                            ]
                        )
                        error: str | None = (
                            "Sort 36 has no unambiguous retained source index."
                        )
                        if source_master is not None and len(original_indexes) == 1:
                            error = verify_album_index(
                                original,
                                checked,
                                master_tracks(source_master.chunk, before.tracks),
                                master_tracks(chunk, project_tracks(checked)),
                                original_indexes[0],
                                child.payload,
                            )
                    else:
                        if len(prior_tracks) != len(before.tracks):
                            prior_tracks = before.tracks
                        if len(final_tracks) != len(desired.tracks):
                            final_tracks = desired.tracks
                        error = verify_index(
                            child.payload,
                            child.prefix.sort_type,
                            prior_tracks,
                            final_tracks,
                            retained=retained_index,
                        )
                    if error:
                        fail("playlist_index", error, kind, chunk)
            continue
        if not is_visible(kind, chunk.header):
            continue
        playlist = wanted.get(identity)
        if playlist is None:
            if baseline and identity in prior:
                fail(
                    "playlist_deleted",
                    "A deleted visible Playlist remains in a counterpart dataset.",
                    kind,
                    chunk,
                )
            continue
        previous = prior.get(playlist.playlist_id)
        if (
            playlist.playlist_id in generated_podcasts
            and not chunk.header.playlist_kind_flags & 1
        ):
            fail(
                "podcast_marker",
                "The generated special Podcasts playlist is missing its native marker.",
                kind,
                chunk,
            )
        if (
            baseline is None
            and playlist.playlist_id not in prior
            and (
                chunk.header.playlist_id_2 != identity
                or chunk.header.db_id_2 != checked.header.db_id_2
                or chunk.header.timestamp != chunk.header.timestamp_2
            )
        ):
            fail(
                "playlist_native_identity",
                "A new Playlist has inconsistent extended identity or timestamp fields.",
                kind,
                chunk,
            )
        affected = playlist != previous or playlist.playlist_id in changed_folders
        if affected or baseline is None:
            expected_playlist = replace(
                playlist,
                playlist_id=identity,
                parent_id=ids.get(playlist.parent_id, playlist.parent_id)
                if playlist.parent_id is not None
                else None,
                entries=(),
            )
            actual = project_playlist(selection, track_ids, device_time)
            if previous and previous.parent_id == playlist.parent_id:
                parent_source = (
                    baseline or old.get((3, identity)) or old.get((2, identity))
                )
                if parent_source:
                    expected_playlist = replace(
                        expected_playlist,
                        parent_id=parent_source.chunk.header.parent_folder_playlist_id
                        or None,
                    )
            expected_tracks = tuple(
                tracks.get(e.track_id, e.track_id) for e in playlist.entries
            )
            matches_membership = actual.track_ids == expected_tracks
            if (
                previous
                and previous.entries == playlist.entries
                and chunk.header.playlist_kind_flags & 1
            ):
                matches_membership = Counter(actual.track_ids) == Counter(
                    expected_tracks
                )
            if (
                replace(actual, entries=()) != expected_playlist
                or not matches_membership
            ):
                fail(
                    "playlist_mirror",
                    "A Playlist counterpart does not contain the desired semantic values and membership.",
                    kind,
                    chunk,
                )
        membership_changed = previous is None or previous.entries != playlist.entries
        if is_podcasts(kind, chunk.header) and (
            membership_changed
            or any(
                old_albums.get(e.track_id)
                != albums.get(tracks.get(e.track_id, e.track_id))
                for e in playlist.entries
            )
        ):
            groups: dict[int, str] = {}
            native_ids: set[int] = set()
            active_group = 0
            for item in items:
                h = item.header
                if not h.group_id or h.group_id in native_ids:
                    fail(
                        "podcast_group",
                        "Podcast row identifiers are missing or repeated.",
                        kind,
                        chunk,
                    )
                native_ids.add(h.group_id)
                if h.podcast_group_flag & 0x100:
                    title = next(
                        (
                            c.payload.value
                            for c in item.children
                            if isinstance(c.payload, MhodStringPayload)
                        ),
                        None,
                    )
                    if h.track_id or title is None or title in groups.values():
                        fail(
                            "podcast_group",
                            "Podcast group headers have invalid Tracks or show titles.",
                            kind,
                            chunk,
                        )
                    groups[h.group_id] = title or ""
                    active_group = h.group_id
                elif h.group_id_ref != active_group or groups.get(
                    h.group_id_ref
                ) != albums.get(h.track_id):
                    fail(
                        "podcast_group",
                        "A podcast episode does not belong to its preceding show group.",
                        kind,
                        chunk,
                    )
                else:
                    positions = [
                        c.prefix.position
                        for c in item.children
                        if isinstance(c.prefix, MhodPlaylistPositionPrefix)
                    ]
                    if not positions or any(value != h.group_id for value in positions):
                        fail(
                            "podcast_position",
                            "Podcast episode position metadata must reference its native row identifier.",
                            kind,
                            chunk,
                            detail=f"Track {h.track_id}, row ID {h.group_id}, expected position {h.group_id}, actual positions {positions}.",
                            item=item,
                        )
        elif membership_changed or playlist.playlist_id in changed_folders:
            for position, item in enumerate(items):
                if item.header.podcast_group_flag & 0x100 or item.header.group_id_ref:
                    fail(
                        "podcast_dataset",
                        "Podcast grouping occurs outside dataset 3's special Podcasts playlist.",
                        kind,
                        chunk,
                        detail=f"Occurrence {position}, Track {item.header.track_id}, group flag {item.header.podcast_group_flag}, group reference {item.header.group_id_ref}.",
                        item=item,
                    )
                    break
                positions = [
                    c.prefix.position
                    for c in item.children
                    if isinstance(c.prefix, MhodPlaylistPositionPrefix)
                ]
                if not positions or any(value != position for value in positions):
                    fail(
                        "playlist_position",
                        "A changed Playlist has inconsistent ordinary occurrence positions.",
                        kind,
                        chunk,
                        detail=f"Occurrence {position}, Track {item.header.track_id}, expected position {position}, actual positions {positions}.",
                        item=item,
                    )
                    break
        if playlist.playlist_id in changed_folders:
            expected_members = tuple(
                tracks.get(i, i) for i in aggregates[playlist.playlist_id]
            )
            rules = [
                c
                for c in chunk.children
                if isinstance(c.payload, MhodSmartRulesPayload)
            ]
            expected_children = tuple(
                ids.get(p.playlist_id, p.playlist_id)
                for p in children[playlist.playlist_id]
            )
            if (
                tuple(c.header.track_id for c in items) != expected_members
                or len(rules) != 1
            ):
                fail(
                    "folder_membership",
                    "Folder membership or direct-child rules are inconsistent.",
                    kind,
                    chunk,
                )
            elif isinstance(rules[0].payload, MhodSmartRulesPayload):
                row = rules[0]
                assert isinstance(row.payload, MhodSmartRulesPayload)
                actual_children = tuple(
                    r.data.from_value
                    for r in row.payload.rules
                    if r.field_id == 0x28
                    and r.action_id == 1
                    and isinstance(r.data, MhodSmartNumericRuleData)
                )
                if (
                    actual_children != expected_children
                    or len(actual_children) != len(row.payload.rules)
                    or not isinstance(row.prefix, MhodSmartRulesPrefix)
                    or row.prefix.conjunction != 1
                ):
                    fail(
                        "folder_rules",
                        "Folder rules do not describe its ordered direct children.",
                        kind,
                        chunk,
                    )
    for kind in (2, 3):
        if kind not in kinds:
            continue
        for identity, playlist in wanted.items():
            if playlist.playlist_id not in prior and (kind, identity) not in output:
                fail(
                    "playlist_missing_mirror",
                    "A new Playlist is absent from a required counterpart dataset.",
                    kind,
                )
        if tuple((p.playlist_id, p.parent_id) for p in before.playlists) != tuple(
            (p.playlist_id, p.parent_id) for p in desired.playlists
        ):
            actual_order = tuple(
                s.chunk.header.playlist_id
                for k, s in playlist_rows(checked)
                if k == kind
                and s.chunk.header.playlist_id in wanted
                and is_visible(k, s.chunk.header)
            )
            expected_order = tuple(
                ids.get(p.playlist_id, p.playlist_id)
                for p in ordered
                if (kind, ids.get(p.playlist_id, p.playlist_id)) in output
            )
            if actual_order != expected_order:
                fail(
                    "folder_order",
                    "Visible Playlists are not in the desired folder preorder.",
                    kind,
                )
    return tuple(issues)
