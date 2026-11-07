"""Artist case is significant; shared native IDs are a separate source condition."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_browse_relationships import browse_source, text

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.opaque_mhod import (
    MhodOpaquePayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary
from iPodDB.library._group_verification import verify_browse_groups
from iPodDB.library._track_writing import edit_text
from iPodDB.library.models import Track
from iPodDB.library.writing import (
    FileDependency,
    LibraryWriteResult,
    PreparedMedia,
    WriteResources,
)
from iPodDB.shared.chunk import DatabaseDocument


def artist_source(
    names: tuple[str, str] = ("Paul van Dyk", "Paul Van Dyk"),
    *,
    shared: bool = False,
    label: str | None = None,
) -> IPodLibrary:
    document = parse_iTunesDB(browse_source().serialize().itunes)
    for n, (selection, name) in enumerate(
        zip(document.find_chunks(MhitHeader), names, strict=True)
    ):
        chunk = edit_text(selection.chunk, MhodType.ARTIST, name)
        chunk = replace(
            chunk,
            header=replace(chunk.header, artist_id_ref=6 if shared or n == 0 else 9),
        )
        # Keep album ownership independent of artist identity in these fixtures.
        chunk = edit_text(chunk, MhodType.ALBUM_ARTIST, "Artist")
        document = document.replace_chunk(selection, chunk)
    for n, row in enumerate(document.find_chunks(MhiiHeader)):
        artist_row = edit_text(
            row.chunk,
            MhodType.ARTIST_ITEM_ARTIST,
            label if n == 0 and label is not None else names[n],
        )
        if n == 0:
            # Private header bytes and opaque children must survive cloning.
            artist_row = replace(
                artist_row, raw_header=artist_row.raw_header[:-4] + b"KEEP"
            )
            artist_row = artist_row.append_child(
                new_itunes_chunk(
                    MHOD,
                    MhodHeader(mhod_type=0xFFFF),
                    payload=MhodOpaquePayload(b"Private artist data"),
                )
            )
        document = document.replace_chunk(row, artist_row)
    return IPodLibrary(write_iTunesDB(document))


def add_track(source: IPodLibrary, artist: str) -> LibraryWriteResult:
    first = source.snapshot.tracks[0]
    dependency = FileDependency("iPod_Control/Music/F00/new.mp3", 1024, "a" * 64)
    added = replace(
        first,
        track_id=-1,
        title="New Track",
        artist=artist,
        size_bytes=dependency.size,
        ipod=None,
        metadata=replace(
            first.metadata, location=dependency.relative_path, sample_rate_hz=44100
        ),
    )
    desired = replace(source.snapshot, tracks=(*source.snapshot.tracks, added))
    return source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(
            media=(PreparedMedia(-1, dependency, 0, 1, 0xFFFF, 0x0C, 0),),
            pending_playback_sidecars=False,
        ),
    )


@pytest.mark.parametrize("artist", ["Paul van Dyk", "Paul Van Dyk", "PAUL VAN DYK"])
def test_case_distinct_artists_accept_additions_without_ambiguity(artist: str) -> None:
    source = artist_source()
    result = add_track(source, artist)
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    rows = {
        s.chunk.header.artist_id: text(s.chunk, MhodType.ARTIST_ITEM_ARTIST)
        for s in checked.find_chunks(MhiiHeader)
    }
    tracks = checked.find_chunks(MhitHeader)
    assert [t.chunk.header.artist_id_ref for t in tracks[:2]] == [6, 9]
    for track in tracks:
        assert rows[track.chunk.header.artist_id_ref] == text(
            track.chunk, MhodType.ARTIST
        )
    assert len({t.chunk.header.artist_id_ref for t in tracks}) == (
        3 if artist == "PAUL VAN DYK" else 2
    )


@pytest.mark.parametrize("changed", [0, 1])
def test_case_only_rename_splits_one_artist_into_distinct_records(changed: int) -> None:
    source = artist_source(("Paul van Dyk", "Paul van Dyk"), shared=True)
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, artist="PAUL VAN DYK") if n == changed else t
            for n, t in enumerate(source.snapshot.tracks)
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    tracks = checked.find_chunks(MhitHeader)
    assert tracks[1 - changed].chunk.header.artist_id_ref == 6
    assert tracks[changed].chunk.header.artist_id_ref not in (0, 6, 9)
    rows = {
        s.chunk.header.artist_id: text(s.chunk, MhodType.ARTIST_ITEM_ARTIST)
        for s in checked.find_chunks(MhiiHeader)
    }
    assert rows[tracks[changed].chunk.header.artist_id_ref] == "PAUL VAN DYK"
    assert rows[6] == "Paul van Dyk"


@pytest.mark.parametrize("second", ["Paul Van Dyk", "Someone else"])
@pytest.mark.parametrize("added_group", [0, 1])
@pytest.mark.parametrize("label", ["Paul van Dyk", "Unmatched source label"])
def test_addition_splits_shared_artist_and_preserves_source_data(
    second: str,
    added_group: int,
    label: str,
) -> None:
    names = ("Paul van Dyk", second)
    source = artist_source(names, shared=True, label=label)
    result = add_track(source, names[added_group])
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    rows = {s.chunk.header.artist_id: s.chunk for s in checked.find_chunks(MhiiHeader)}
    identities: dict[str, set[int]] = {}
    for track in checked.find_chunks(MhitHeader):
        name = text(track.chunk, MhodType.ARTIST)
        identity = track.chunk.header.artist_id_ref
        identities.setdefault(name, set()).add(identity)
        assert text(rows[identity], MhodType.ARTIST_ITEM_ARTIST) == name
        assert rows[identity].raw_header[-4:] == b"KEEP"
        assert rows[identity].children[-1].payload == MhodOpaquePayload(
            b"Private artist data"
        )
        assert identity == 6 if name == label else identity not in (0, 6, 9)
    assert len(identities) == 2
    assert all(len(values) == 1 for values in identities.values())
    assert identities[names[0]].isdisjoint(identities[names[1]])
    sql_ids = [r.header.sql_id for r in rows.values()]
    assert len(sql_ids) == len(set(sql_ids))
    assert all(
        r.header.sql_id not in (0, 50, 60, 80, 90)
        for i, r in rows.items()
        if i not in (6, 9)
    )
    assert_original_artist_rows(source.serialize().itunes, result.prepared.itunes)
    # The repaired relationships are stable on subsequent Syncs and no-op writes.
    repaired = IPodLibrary(result.prepared.itunes)
    noop = repaired.prepare(repaired.analyze(repaired.begin_draft(repaired.snapshot)))
    assert noop.prepared is not None, noop.issues
    assert noop.prepared.itunes == result.prepared.itunes


def assert_original_artist_rows(original: bytes, output: bytes) -> None:
    rows = {
        s.chunk.header.artist_id: s.chunk
        for s in parse_iTunesDB(output).find_chunks(MhiiHeader)
    }
    for selection in parse_iTunesDB(original).find_chunks(MhiiHeader):
        prior = selection.chunk
        saved = rows[prior.header.artist_id]
        assert (
            original[
                prior.offset : prior.offset + prior.generic_header.length_or_child_count
            ]
            == output[
                saved.offset : saved.offset + saved.generic_header.length_or_child_count
            ]
        )


def test_unrelated_edit_and_noop_preserve_shared_artist_relationships() -> None:
    source = artist_source(shared=True)
    # Reading or changing an unrelated field does not implicitly repair the source.
    original = source.serialize().itunes
    noop = source.prepare(source.analyze(source.begin_draft(source.snapshot)))
    assert noop.prepared is not None, noop.issues
    assert noop.prepared.itunes == original
    first, second_track = source.snapshot.tracks
    desired = replace(
        source.snapshot, tracks=(replace(first, title="Edited"), second_track)
    )
    edited = source.prepare(source.analyze(source.begin_draft(desired)))
    assert edited.prepared is not None, edited.issues
    assert [t.ipod for t in edited.prepared.snapshot.tracks] == [
        t.ipod for t in source.snapshot.tracks
    ]
    assert_original_artist_rows(original, edited.prepared.itunes)


def prepare_tracks(
    source: IPodLibrary, tracks: tuple[Track, ...]
) -> LibraryWriteResult:
    ids = {t.track_id for t in tracks}
    desired = replace(
        source.snapshot,
        tracks=tracks,
        playlists=tuple(
            replace(p, entries=tuple(e for e in p.entries if e.track_id in ids))
            for p in source.snapshot.playlists
        ),
    )
    return source.prepare(
        source.analyze(source.begin_draft(desired, delete_omissions=True)),
        WriteResources(pending_playback_sidecars=False),
    )


@pytest.mark.parametrize(
    "names",
    [
        ("PAUL VAN DYK", "Paul Van Dyk"),
        ("Paul van Dyk", "Paul van Dyk"),
        ("Paul Van Dyk", "Paul Van Dyk"),
        ("NEW ARTIST", "New Artist"),
        ("Paul Van Dyk", "Paul van Dyk"),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_renames_split_or_join_exact_names_independently_of_track_order(
    names: tuple[str, str],
    reverse: bool,
) -> None:
    source = artist_source(shared=True)
    tracks = tuple(
        replace(t, artist=name)
        for t, name in zip(source.snapshot.tracks, names, strict=True)
    )
    result = prepare_tracks(source, tuple(reversed(tracks)) if reverse else tracks)
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    assert_exact_artist_references(checked)
    ids = {s.chunk.header.artist_id_ref for s in checked.find_chunks(MhitHeader)}
    assert len(ids) == len(set(names))
    assert (6 in ids) == ("Paul van Dyk" in names)
    assert_original_artist_rows(source.serialize().itunes, result.prepared.itunes)


def assert_exact_artist_references(document: DatabaseDocument[MhbdHeader]) -> None:
    rows = {s.chunk.header.artist_id: s.chunk for s in document.find_chunks(MhiiHeader)}
    for track in document.find_chunks(MhitHeader):
        assert text(
            rows[track.chunk.header.artist_id_ref], MhodType.ARTIST_ITEM_ARTIST
        ) == text(track.chunk, MhodType.ARTIST)


@pytest.mark.parametrize("retained", [0, 1])
def test_deletion_reconciles_the_remaining_shared_artist(retained: int) -> None:
    source = artist_source(shared=True)
    result = prepare_tracks(source, (source.snapshot.tracks[retained],))
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    assert_exact_artist_references(checked)
    assert (checked.find_chunks(MhitHeader)[0].chunk.header.artist_id_ref == 6) == (
        retained == 0
    )
    assert_original_artist_rows(source.serialize().itunes, result.prepared.itunes)


@pytest.mark.parametrize("anomaly", ["missing", "duplicate"])
def test_shared_artist_split_rejects_missing_or_repeated_source_records(
    anomaly: str,
) -> None:
    document = parse_iTunesDB(artist_source(shared=True).serialize().itunes)
    dataset = next(
        s for s in document.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 8
    )
    container = dataset.chunk.children[0]
    children = (
        container.children[1:]
        if anomaly == "missing"
        else (*container.children, container.children[0])
    )
    document = document.replace_chunk(
        dataset,
        replace(dataset.chunk, children=(replace(container, children=children),)),
    )
    result = add_track(IPodLibrary(write_iTunesDB(document)), "Paul van Dyk")
    assert result.prepared is None
    assert any(
        i.code
        == (
            "library.missing_group"
            if anomaly == "missing"
            else "library.ambiguous_group"
        )
        and i.field == "artist"
        for i in result.issues
    )


@pytest.mark.parametrize("label_present", [False, True])
def test_missing_native_label_does_not_claim_empty_artist_name(
    label_present: bool,
) -> None:
    document = parse_iTunesDB(
        artist_source(("", "Named artist"), shared=True).serialize().itunes
    )
    if not label_present:
        row = document.find_chunks(MhiiHeader)[0]
        document = document.replace_chunk(
            row,
            replace(
                row.chunk,
                children=tuple(
                    c
                    for c in row.chunk.children
                    if not isinstance(c.header, MhodHeader)
                    or c.header.mhod_type != MhodType.ARTIST_ITEM_ARTIST
                ),
            ),
        )
    source = IPodLibrary(write_iTunesDB(document))
    result = add_track(source, "Named artist")
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    assert_exact_artist_references(checked)
    assert (
        checked.find_chunks(MhitHeader)[0].chunk.header.artist_id_ref == 6
    ) == label_present
    assert_original_artist_rows(source.serialize().itunes, result.prepared.itunes)


def test_shared_artist_rename_can_join_an_existing_independent_artist() -> None:
    original = add_track(artist_source(shared=True), "Independent artist")
    assert original.prepared is not None, original.issues
    source = IPodLibrary(original.prepared.itunes)
    first, second, third = source.snapshot.tracks
    result = prepare_tracks(
        source, (replace(first, artist=third.artist), second, third)
    )
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    assert_exact_artist_references(checked)
    tracks = checked.find_chunks(MhitHeader)
    assert tracks[0].chunk.header.artist_id_ref == tracks[2].chunk.header.artist_id_ref
    assert third.ipod is not None
    assert tracks[2].chunk.header.artist_id_ref == third.ipod.artist_id_ref
    assert tracks[1].chunk.header.artist_id_ref not in (
        0,
        6,
        9,
        third.ipod.artist_id_ref,
    )
    assert_original_artist_rows(source.serialize().itunes, result.prepared.itunes)


@pytest.mark.parametrize(
    "fault", ["shared", "source_id", "source_sql", "album_sql", "new_sql", "label"]
)
def test_verifier_rejects_invalid_artist_splits(fault: str) -> None:
    source = artist_source(shared=True)
    first, second = source.snapshot.tracks
    desired = replace(
        source.snapshot, tracks=(replace(first, artist="PAUL VAN DYK"), second)
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    tracks = checked.find_chunks(MhitHeader)
    if fault in ("shared", "source_id"):
        checked = checked.replace_chunk(
            tracks[0],
            replace(
                tracks[0].chunk,
                header=replace(
                    tracks[0].chunk.header,
                    artist_id_ref=6
                    if fault == "source_id"
                    else tracks[1].chunk.header.artist_id_ref,
                ),
            ),
        )
    else:
        clones = [
            s
            for s in checked.find_chunks(MhiiHeader)
            if s.chunk.header.artist_id not in (6, 9)
        ]
        row = clones[0]
        changed = (
            edit_text(row.chunk, MhodType.ARTIST_ITEM_ARTIST, "Wrong")
            if fault == "label"
            else replace(
                row.chunk,
                header=replace(
                    row.chunk.header,
                    sql_id={
                        "source_sql": 60,
                        "album_sql": 50,
                        "new_sql": clones[1].chunk.header.sql_id,
                    }[fault],
                ),
            )
        )
        checked = checked.replace_chunk(row, changed)
    issues = verify_browse_groups(
        parse_iTunesDB(source.serialize().itunes),
        parse_iTunesDB(write_iTunesDB(checked)),
        source.snapshot,
        desired,
        result.prepared.identities,
    )
    assert any(i.code.startswith("verification.browse_") for i in issues), issues
