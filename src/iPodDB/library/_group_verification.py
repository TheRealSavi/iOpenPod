"""Verify native browse relationships against source identities and desired values.

This never calls reconciliation or trusts a candidate's projected iPod diagnostics.
Shared semantic grouping inputs do not specify or bless its native record IDs.
"""

from collections import Counter, defaultdict
from dataclasses import replace

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
    MhodStringPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library._artist_groups import native_artist_name
from iPodDB.library._browse_groups import (
    album_values,
    group_text,
    native_browse_groups,
    unchanged_podcast_album_fields,
)
from iPodDB.library._browse_membership import (
    retained_album_representative,
    retained_browse_memberships,
    select_browse_id,
)
from iPodDB.library._track_header_expansion import optional_field_available
from iPodDB.library.models import LibrarySnapshot, MediaKind, Track
from iPodDB.library.writing import IdentityMapping, WriteIssue
from iPodDB.shared.binary_struct import binary_struct_extent, write_binary_struct_into
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk


def _matches_album_edit(
    source: ParsedChunk[ChunkHeader],
    output: ParsedChunk[ChunkHeader],
    header: MhiaHeader,
    edits: dict[MhodType, str],
) -> bool:
    def text_positions(row: ParsedChunk[ChunkHeader]) -> dict[int, int]:
        return {
            child.header.mhod_type: index
            for index, child in enumerate(row.children)
            if isinstance(child.header, MhodHeader)
            and isinstance(child.payload, MhodStringPayload)
        }

    source_positions = text_positions(source)
    output_positions = text_positions(output)
    changed: dict[int, int] = {}
    inserted: set[int] = set()
    for mhod, value in edits.items():
        index = output_positions.get(mhod)
        if index is None or output.children[index].payload != MhodStringPayload(value):
            return False
        if mhod in source_positions:
            changed[source_positions[mhod]] = index
        else:
            inserted.add(index)

    expected_header = bytearray(source.raw_header)
    write_binary_struct_into(
        expected_header,
        replace(
            source.generic_header,
            length_or_child_count=output.generic_header.length_or_child_count,
        ),
    )
    write_binary_struct_into(
        expected_header,
        replace(header, child_count=len(source.children) + len(inserted)),
    )
    if (
        bytes(expected_header) != output.raw_header
        or source.raw_trailing_data != output.raw_trailing_data
    ):
        return False

    retained = [index for index in range(len(output.children)) if index not in inserted]
    if len(retained) != len(source.children):
        return False
    for source_index, output_index in enumerate(retained):
        before = source.children[source_index]
        after = output.children[output_index]
        if source_index not in changed:
            if (before.raw_header, before.raw_body) != (
                after.raw_header,
                after.raw_body,
            ):
                return False
            continue
        if changed[source_index] != output_index or not (
            isinstance(before.prefix, MhodStringPrefix)
            and isinstance(after.prefix, MhodStringPrefix)
        ):
            return False
        expected_child_header = bytearray(before.raw_header)
        write_binary_struct_into(
            expected_child_header,
            replace(
                before.generic_header,
                length_or_child_count=after.generic_header.length_or_child_count,
            ),
        )
        prefix_extent = binary_struct_extent(MhodStringPrefix)
        before_end = (
            prefix_extent - len(before.raw_header) + before.prefix.string_length
        )
        after_end = prefix_extent - len(after.raw_header) + after.prefix.string_length
        if (
            bytes(expected_child_header) != after.raw_header
            or replace(before.prefix, string_length=after.prefix.string_length)
            != after.prefix
            or before.raw_body[before_end:] != after.raw_body[after_end:]
        ):
            return False
    return True


def _rows(
    document: DatabaseDocument[MhbdHeader], kind: int
) -> dict[int, list[ParsedChunk[MhiaHeader | MhiiHeader]]]:
    rows: dict[int, list[ParsedChunk[MhiaHeader | MhiiHeader]]] = defaultdict(list)
    for dataset in document.find_chunks(MhsdHeader):
        if dataset.chunk.header.dataset_type != kind:
            continue
        if kind == 4:
            for album in dataset.find_chunks(MhiaHeader):
                rows[album.chunk.header.album_id].append(album.chunk)
        else:
            for artist in dataset.find_chunks(MhiiHeader):
                rows[artist.chunk.header.artist_id].append(artist.chunk)
    return rows


def verify_browse_groups(
    original: DatabaseDocument[MhbdHeader],
    checked: DatabaseDocument[MhbdHeader],
    before: LibrarySnapshot,
    desired: LibrarySnapshot,
    mappings: tuple[IdentityMapping, ...],
    *,
    database_version: int | None = None,
    normalize_podcasts: bool = False,
) -> tuple[WriteIssue, ...]:
    issues: list[WriteIssue] = []
    track_ids = {m.draft_id: m.output_id for m in mappings if m.subject == "track"}
    old_tracks = {t.track_id: t for t in before.tracks}
    old_native = {
        s.chunk.header.track_id: s.chunk for s in original.find_chunks(MhitHeader)
    }
    native = {s.chunk.header.track_id: s.chunk for s in checked.find_chunks(MhitHeader)}
    output = {
        t.track_id: native[track_ids.get(t.track_id, t.track_id)]
        for t in desired.tracks
        if track_ids.get(t.track_id, t.track_id) in native
    }
    kinds = {s.chunk.header.dataset_type for s in original.find_chunks(MhsdHeader)}
    membership, artist_changes = retained_browse_memberships(original, before, desired)
    deleted_pids = {
        c.header.db_track_id
        for i, c in old_native.items()
        if i not in output and c.header.db_track_id
    }
    source_browse_ids = (
        {
            value
            for chunk in old_native.values()
            for value in (
                chunk.header.album_id,
                chunk.header.artist_id_ref,
                chunk.header.composer_id,
            )
        }
        | set(_rows(original, 4))
        | set(_rows(original, 8))
    )
    source_sql_ids = {
        row.header.sql_id
        for kind in (4, 8)
        for rows in _rows(original, kind).values()
        for row in rows
    }
    output_sql_counts = Counter(
        row.header.sql_id
        for kind in (4, 8)
        for rows in _rows(checked, kind).values()
        for row in rows
    )
    artist_owners: dict[int, set[str]] = defaultdict(set)
    for track in desired.tracks:
        if track.track_id in output:
            artist_owners[output[track.track_id].header.artist_id_ref].add(track.artist)

    def fail(
        code: str,
        track_id: int,
        field: str,
        detail: str,
        chunk: ParsedChunk[ChunkHeader],
    ) -> None:
        issues.append(
            WriteIssue(
                "verification.browse_" + code,
                "Prepared native browse relationships do not match the source and desired Library.",
                phase="verification",
                subject="track",
                record_id=track_id,
                field=field,
                detail=detail,
                offset=chunk.offset,
                artifact="iTunesDB",
            )
        )

    for kind in (4, 8):
        album = kind == 4
        field = "ipod.album_id" if album else "ipod.artist_id_ref"
        source_rows, rows = _rows(original, kind), _rows(checked, kind)
        prior_groups = native_browse_groups(before.tracks, album=album)
        groups = native_browse_groups(desired.tracks, album=album)
        source_refs = {
            i: c.header.album_id if album else c.header.artist_id_ref
            for i, c in old_native.items()
        }
        refs = {
            i: c.header.album_id if album else c.header.artist_id_ref
            for i, c in output.items()
        }
        prior_album_pids: dict[int, set[int]] = defaultdict(set)
        album_pids: dict[int, set[int]] = defaultdict(set)
        if album:
            for i, owner in source_refs.items():
                if pid := old_native[i].header.db_track_id:
                    prior_album_pids[owner].add(pid)
            for i, owner in refs.items():
                album_pids[owner].add(output[i].header.db_track_id)
        verified_records: set[int] = set()
        prior_owners: dict[int, set[int]] = defaultdict(set)
        prior_members: dict[int, list[Track]] = defaultdict(list)
        for identity, reference in source_refs.items():
            prior_owners[reference].add(identity)
            prior_members[reference].append(old_tracks[identity])
        row_evidence = {
            identity: (len(matches), None if album else native_artist_name(matches[0]))
            for identity, matches in source_rows.items()
        }
        for key, members in groups.items():
            if (
                album
                and normalize_podcasts
                and all(
                    t.media_kind is MediaKind.PODCAST or t.metadata.podcast
                    for t in members
                )
            ):
                # The explicit per-show policy is checked independently after
                # reparse; it intentionally joins artist/season browse groups.
                continue
            retained_group = membership[album].get(key)
            if retained_group is not None and kind in kinds:
                fresh_artist_id = 0
                fresh_albums: dict[tuple[int, str], int] = {}
                new_album_members: dict[tuple[int, str], list[Track]] = defaultdict(
                    list
                )
                for track in members:
                    if track.track_id in retained_group.new_albums:
                        new_album_members[
                            retained_group.new_albums[track.track_id]
                        ].append(track)
                for t in members:
                    if t.track_id not in refs:
                        continue
                    expected_id = retained_group.links[t.track_id]
                    actual_id = refs[t.track_id]
                    chunk = output[t.track_id]
                    if t.track_id in retained_group.new_albums:
                        album_key = retained_group.new_albums[t.track_id]
                        matches = rows.get(actual_id, [])
                        if (
                            not actual_id
                            or actual_id in source_browse_ids
                            or len(matches) != 1
                            or fresh_albums.setdefault(album_key, actual_id)
                            != actual_id
                        ):
                            fail(
                                "group_identity",
                                t.track_id,
                                field,
                                f"Expected a new Album ID, actual {actual_id}.",
                                chunk,
                            )
                            continue
                        if actual_id in verified_records:
                            continue
                        verified_records.add(actual_id)
                        new_row = matches[0]
                        album_tracks = new_album_members[album_key]
                        values = album_values(album_tracks)
                        owners = {track.track_id for track in album_tracks}
                        album_header = new_row.header
                        if (
                            not isinstance(album_header, MhiaHeader)
                            or not album_header.sql_id
                            or album_header.sql_id in source_sql_ids
                            or output_sql_counts[album_header.sql_id] != 1
                            or {i for i, owner in refs.items() if owner == actual_id}
                            != owners
                            or album_header.album_track_db_id
                            != min(
                                output[i].header.db_track_id
                                for i in owners
                                if i in output
                            )
                            or album_header.content_type_flag != values.content_type
                            or album_header.album_compilation_flag
                            != int(values.compilation)
                            or album_header.season_number != values.season
                            or any(
                                group_text(new_row, mhod) != value
                                for mhod, value in (
                                    (MhodType.ALBUM_ITEM_ALBUM, values.title),
                                    (MhodType.ALBUM_ITEM_ARTIST, values.artist),
                                    (
                                        MhodType.ALBUM_ITEM_SORT_ARTIST,
                                        values.sort_artist,
                                    ),
                                    (
                                        MhodType.ALBUM_ITEM_PODCAST_URL,
                                        values.podcast_url,
                                    ),
                                    (MhodType.ALBUM_ITEM_SHOW, values.show),
                                )
                            )
                        ):
                            fail(
                                "group_metadata",
                                t.track_id,
                                field,
                                f"New Album {actual_id} does not match its Tracks.",
                                new_row,
                            )
                        continue
                    if expected_id or t.track_id in source_refs:
                        if actual_id != expected_id:
                            fail(
                                "retained_reference",
                                t.track_id,
                                field,
                                f"Dataset {kind}: expected ID {expected_id}, actual {actual_id}.",
                                chunk,
                            )
                            continue
                        if not actual_id or actual_id in verified_records:
                            continue
                        verified_records.add(actual_id)
                        source_matches, matches = (
                            source_rows.get(actual_id, []),
                            rows.get(actual_id, []),
                        )
                        matches_expected = len(matches) == len(source_matches)
                        for original_row, output_row in zip(
                            source_matches, matches, strict=False
                        ):
                            header = bytearray(original_row.raw_header)
                            native_header = original_row.header
                            if len(source_matches) == 1 and isinstance(
                                native_header, MhiaHeader
                            ):
                                representative = retained_album_representative(
                                    native_header.album_track_db_id,
                                    prior_album_pids[actual_id],
                                    album_pids[actual_id],
                                    deleted_pids,
                                )
                                updated_header = replace(
                                    native_header, album_track_db_id=representative
                                )
                                edits = retained_group.album_text_edits.get(actual_id)
                                if edits:
                                    matches_expected &= _matches_album_edit(
                                        original_row, output_row, updated_header, edits
                                    )
                                    continue
                                if representative != native_header.album_track_db_id:
                                    write_binary_struct_into(header, updated_header)
                            matches_expected &= (
                                bytes(header),
                                original_row.raw_body,
                            ) == (output_row.raw_header, output_row.raw_body)
                        if not matches_expected:
                            fail(
                                "group_metadata",
                                t.track_id,
                                field,
                                f"Dataset {kind}: retained browse record {actual_id} changed.",
                                chunk,
                            )
                    else:
                        matches = rows.get(actual_id, [])
                        if (
                            not actual_id
                            or actual_id in source_browse_ids
                            or (fresh_artist_id and actual_id != fresh_artist_id)
                            or len(matches) != 1
                            or group_text(matches[0], MhodType.ARTIST_ITEM_ARTIST)
                            != t.artist
                            or not matches[0].header.sql_id
                            or matches[0].header.sql_id in source_sql_ids
                            or output_sql_counts[matches[0].header.sql_id] != 1
                            or artist_owners[actual_id] != {t.artist}
                        ):
                            fail(
                                "group_identity",
                                t.track_id,
                                field,
                                f"Dataset {kind}: expected a fresh artist ID, actual {actual_id}.",
                                chunk,
                            )
                        fresh_artist_id = actual_id
                continue
            prior = prior_groups.get(key, ())
            member_ids = {t.track_id for t in members}
            split_artist = not album and members[0].artist in artist_changes
            affected = (
                member_ids != {t.track_id for t in prior}
                or (
                    album
                    and bool(prior)
                    and album_values(members) != album_values(prior)
                )
                or split_artist
            )
            if not affected or kind not in kinds:
                for t in members:
                    if (
                        t.track_id in source_refs
                        and t.track_id in refs
                        and refs[t.track_id] != source_refs[t.track_id]
                    ):
                        fail(
                            "retained_reference",
                            t.track_id,
                            field,
                            f"Dataset {kind}: expected retained ID {source_refs[t.track_id]}, actual {refs[t.track_id]}.",
                            output[t.track_id],
                        )
                continue
            actual_ids = {refs[i] for i in member_ids if i in refs}
            first_id = members[0].track_id
            if first_id not in output:
                continue  # The semantic verifier reports missing Tracks.
            if len(actual_ids) != 1 or 0 in actual_ids:
                fail(
                    "group_reference",
                    first_id,
                    field,
                    f"Dataset {kind}: one nonzero group ID required, actual {sorted(actual_ids)}.",
                    output[first_id],
                )
                continue
            identity = next(iter(actual_ids))
            candidates = {
                source_refs[t.track_id] for t in prior if source_refs[t.track_id]
            }
            if not candidates:
                previous_refs = {source_refs[i] for i in member_ids if i in source_refs}
                if (
                    len(previous_refs) == 1
                    and prior_owners[next(iter(previous_refs))] == member_ids
                ):
                    candidates = previous_refs - {0}
            if split_artist:
                candidates = set(artist_changes[members[0].artist])
            shared_ids: set[int] = (
                {
                    source_refs[t.track_id]
                    for t in prior
                    if prior_owners[source_refs[t.track_id]]
                    - {p.track_id for p in prior}
                }
                if album
                else set()
            )
            selected_id = select_browse_id(
                candidates if not album or len(candidates) <= 1 else set(),
                row_evidence,
                prior_owners,
                member_ids,
                excluded=shared_ids,
                artist=members[0].artist
                if split_artist or (not album and len(candidates) > 1)
                else None,
            )
            if not album and len(artist_owners[identity]) != 1:
                fail(
                    "shared_artist",
                    first_id,
                    field,
                    f"Artist {identity} is shared by distinct exact names.",
                    output[first_id],
                )
            if (selected_id and selected_id != identity) or (
                not selected_id and identity in source_browse_ids
            ):
                fail(
                    "group_identity",
                    first_id,
                    field,
                    f"Dataset {kind}: expected retained ID {selected_id} or a new identity when zero, actual {identity}.",
                    output[first_id],
                )
            matched = rows.get(identity, [])
            if len(matched) != 1:
                fail(
                    "group_reference",
                    first_id,
                    field,
                    f"Dataset {kind}: native ID {identity} resolves to {len(matched)} group records.",
                    output[first_id],
                )
                continue
            row = matched[0]
            retained = source_rows.get(identity, [])
            if len(retained) == 1:
                if row.header.sql_id != retained[0].header.sql_id:
                    fail(
                        "sql_identity",
                        first_id,
                        field,
                        f"Dataset {kind}, group {identity}: retained SQL identity changed.",
                        row,
                    )
            elif (
                not row.header.sql_id
                or row.header.sql_id in source_sql_ids
                or output_sql_counts[row.header.sql_id] != 1
            ):
                fail(
                    "sql_identity",
                    first_id,
                    field,
                    f"Dataset {kind}, new group {identity}: SQL identity is zero or collides with another record.",
                    row,
                )
            expected: tuple[tuple[MhodType, str], ...]
            if album and isinstance(row.header, MhiaHeader):
                values = album_values(members)
                source_row = retained[0] if len(retained) == 1 else None
                preserved = unchanged_podcast_album_fields(
                    prior_members.get(identity, ()),
                    members,
                )
                expected = tuple(
                    (
                        mhod,
                        group_text(source_row, mhod)
                        if name in preserved and source_row is not None
                        else value,
                    )
                    for name, mhod, value in (
                        ("title", MhodType.ALBUM_ITEM_ALBUM, values.title),
                        ("artist", MhodType.ALBUM_ITEM_ARTIST, values.artist),
                        (
                            "sort_artist",
                            MhodType.ALBUM_ITEM_SORT_ARTIST,
                            values.sort_artist,
                        ),
                        (
                            "podcast_url",
                            MhodType.ALBUM_ITEM_PODCAST_URL,
                            values.podcast_url,
                        ),
                        ("show", MhodType.ALBUM_ITEM_SHOW, values.show),
                    )
                )
                owners = {
                    output[i].header.db_track_id for i in member_ids if i in output
                }
                if row.header.album_track_db_id not in owners:
                    fail(
                        "representative",
                        first_id,
                        "album",
                        f"Album {identity}: representative {row.header.album_track_db_id} is not one of {sorted(owners)}.",
                        row,
                    )
                source_header = (
                    source_row.header
                    if source_row is not None
                    and isinstance(source_row.header, MhiaHeader)
                    else None
                )
                if (
                    row.header.album_compilation_flag,
                    row.header.season_number,
                    row.header.content_type_flag,
                ) != (
                    source_header.album_compilation_flag
                    if "compilation" in preserved and source_header is not None
                    else int(values.compilation),
                    source_header.season_number
                    if "season" in preserved and source_header is not None
                    else values.season,
                    values.content_type,
                ):
                    fail(
                        "album_flags",
                        first_id,
                        "album",
                        f"Album {identity}: compilation or season differs from its members.",
                        row,
                    )
            else:
                expected = ((MhodType.ARTIST_ITEM_ARTIST, members[0].artist),)
            for mhod, expected_value in expected:
                actual = group_text(row, mhod)
                if actual != expected_value:
                    fail(
                        "group_metadata",
                        first_id,
                        "album" if album else "artist",
                        f"Dataset {kind}, group {identity}, MHOD {int(mhod)}: expected {expected_value!r}, actual {actual!r}.",
                        row,
                    )

    # Composer IDs have no separate dataset. Check retained identities, shared
    # ownership, nonzero allocation, and collisions without predicting an allocator.
    known_composers: dict[str, set[int]] = defaultdict(set)
    for t in before.tracks:
        if t.metadata.composer and old_native[t.track_id].header.composer_id:
            known_composers[t.metadata.composer.casefold()].add(
                old_native[t.track_id].header.composer_id
            )
    old_ids = {
        value
        for c in old_native.values()
        for value in (c.header.album_id, c.header.artist_id_ref, c.header.composer_id)
    }
    group_ids = set(_rows(checked, 4)) | set(_rows(checked, 8))
    composer_owners: dict[int, set[str]] = defaultdict(set)
    for t in desired.tracks:
        if t.track_id in output and output[t.track_id].header.composer_id:
            composer_owners[output[t.track_id].header.composer_id].add(
                t.metadata.composer.casefold()
            )
    allocated: dict[str, int] = {}
    for t in desired.tracks:
        if t.track_id not in output:
            continue
        chunk = output[t.track_id]
        previous = old_tracks.get(t.track_id)
        value = chunk.header.composer_id
        if previous is not None and previous.metadata.composer == t.metadata.composer:
            if value != old_native[t.track_id].header.composer_id:
                fail(
                    "retained_reference",
                    t.track_id,
                    "ipod.composer_id",
                    "An untouched composer identity changed.",
                    chunk,
                )
            continue
        composer_key = t.metadata.composer.casefold()
        if not optional_field_available(
            old_native.get(t.track_id), "composer_id", database_version
        ):
            if value:
                fail(
                    "composer_identity",
                    t.track_id,
                    "ipod.composer_id",
                    "This layout must retain composer text without a native composer ID.",
                    chunk,
                )
            continue
        options = known_composers.get(composer_key, set())
        valid = (
            value == 0
            if not composer_key
            else bool(value)
            and (value in options if options else value not in old_ids | group_ids)
        )
        if composer_key:
            valid = (
                valid
                and composer_owners[value] == {composer_key}
                and (
                    bool(options) or allocated.setdefault(composer_key, value) == value
                )
            )
        if not valid:
            fail(
                "composer_identity",
                t.track_id,
                "ipod.composer_id",
                f"Composer {t.metadata.composer!r}: invalid or conflicting native ID {value}; retained candidates {sorted(options)}.",
                chunk,
            )
    return tuple(issues)
