"""Verify native browse relationships against source identities and desired values.

This never calls reconciliation or trusts a candidate's projected iPod diagnostics.
Shared semantic grouping inputs do not specify or bless its native record IDs.
"""

from collections import defaultdict

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library._browse_groups import (
    album_values,
    native_browse_groups,
    unchanged_podcast_album_fields,
)
from iPodDB.library._track_header_expansion import optional_field_available
from iPodDB.library.models import LibrarySnapshot, MediaKind, Track
from iPodDB.library.writing import IdentityMapping, WriteIssue
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk


def group_text(chunk: ParsedChunk[ChunkHeader], kind: MhodType) -> str:
    return next(
        (
            c.payload.value
            for c in reversed(chunk.children)
            if isinstance(c.header, MhodHeader)
            and c.header.mhod_type == kind
            and isinstance(c.payload, MhodStringPayload)
        ),
        "",
    )


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
        prior_owners: dict[int, set[int]] = defaultdict(set)
        prior_members: dict[int, list[Track]] = defaultdict(list)
        for identity, reference in source_refs.items():
            prior_owners[reference].add(identity)
            prior_members[reference].append(old_tracks[identity])
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
            prior = prior_groups.get(key, ())
            member_ids = {t.track_id for t in members}
            affected = member_ids != {t.track_id for t in prior} or (
                album and bool(prior) and album_values(members) != album_values(prior)
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
            if (candidates and candidates != {identity}) or (
                not candidates and identity in source_rows
            ):
                fail(
                    "group_identity",
                    first_id,
                    field,
                    f"Dataset {kind}: expected retained IDs {sorted(candidates)} or a new identity when empty, actual {identity}.",
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
            elif not row.header.sql_id or any(
                row.header.sql_id == r.header.sql_id
                for rs in source_rows.values()
                for r in rs
            ):
                fail(
                    "sql_identity",
                    first_id,
                    field,
                    f"Dataset {kind}, new group {identity}: SQL identity is zero or collides with a retained record.",
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
            and (options == {value} if options else value not in old_ids | group_ids)
        )
        if composer_key:
            valid = (
                valid
                and composer_owners[value] == {composer_key}
                and allocated.setdefault(composer_key, value) == value
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
