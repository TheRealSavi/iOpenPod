"""Independent evidence and edge cases for the semantic write contract."""

import base64
import hashlib
import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.builder.build_iTunesDB import (
    new_itunes_chunk,
    new_iTunesDB,
    new_string_mhod,
)
from iPodDB.iTunesDB.cdb import is_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import DEFINITION as MHIT
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhlt import DEFINITION as MHLT
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPayload,
    MhodLibraryIndexPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.shared.device_time import MAC_EPOCH_UNIX_OFFSET
from iPodDB.iTunesDB.writer.signature import sign_hash58
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, Playlist, PlaylistEntry, PlaylistKind
from iPodDB.library._identities import allocate
from iPodDB.library.writing import (
    IssueSeverity,
    WriteChecksum,
    WriteResources,
    WriteTarget,
)
from iPodDB.shared.chunk import DatabaseDocument, EmptyChunkHeader
from iPodDB.shared.errors import iPodDBWriteError

FIXTURES = Path(__file__).parents[2] / "fixtures"


def test_hash58_matches_captured_original_project_vectors() -> None:
    fixture = json.loads((FIXTURES / "writing/hash58-original.json").read_text())
    data = bytearray((i * 37 + 11) % 256 for i in range(1024))
    data[:12] = struct.pack("<4sII", b"mhbd", 244, 1024)
    for vector in fixture["vectors"]:
        signed = sign_hash58(bytes(data), bytes.fromhex(vector["guid"]))
        assert signed[0x58:0x6C].hex() == vector["hash58"]
        assert hashlib.sha256(signed).hexdigest() == vector["output_sha256"]
        assert signed[0x18:0x20] == data[0x18:0x20]
        assert signed[0x32:0x46] == data[0x32:0x46]


def test_original_both_database_fixtures_prepare_exactly() -> None:
    itunes = base64.b64decode((FIXTURES / "iTunesDB/original-empty.b64").read_bytes())
    artwork = base64.b64decode(
        (FIXTURES / "ArtworkDB/original-with-unknown-data.b64").read_bytes()
    )
    source = IPodLibrary(itunes).with_artwork(artwork)
    result = source.prepare(source.analyze(source.begin_draft()))
    assert result.prepared is not None, result.issues
    assert (result.prepared.itunes, result.prepared.artwork) == (itunes, artwork)


def test_short_root_noop_and_contextual_packing_failure() -> None:
    data = struct.pack("<4sIIIII", b"mhbd", 24, 24, 0, 0, 0)
    source = IPodLibrary(data)
    result = source.prepare(source.analyze(source.begin_draft()))
    assert result.prepared and result.prepared.itunes == data
    from iPodDB.shared.errors import iPodDBWriteError

    document = parse_iTunesDB(data)
    with pytest.raises(iPodDBWriteError) as caught:
        write_iTunesDB(replace(document, header=replace(document.header, db_id=123)))
    assert caught.value.field == "db_id"
    assert caught.value.code == "binary.short_header"
    assert caught.value.marker == b"mhbd"


def test_track_order_is_a_change_and_reconciles_zero_based_positions() -> None:
    source = library()
    desired = replace(source.snapshot, tracks=tuple(reversed(source.snapshot.tracks)))
    plan = source.analyze(source.begin_draft(desired))
    assert plan.changes and plan.requires_sidecar_inventory
    result = source.prepare(plan, WriteResources(pending_playback_sidecars=False))
    assert result.prepared is not None, result.issues
    assert tuple(t.track_id for t in result.prepared.snapshot.tracks) == (2, 1)
    master = next(
        s
        for s in parse_iTunesDB(result.prepared.itunes).find_chunks(MhypHeader)
        if s.chunk.header.master_flag
    )
    positions = [
        c.prefix.position
        for s in master.find_chunks(MhipHeader)
        for c in s.chunk.children
        if isinstance(c.prefix, MhodPlaylistPositionPrefix)
    ]
    assert positions == [0, 1]


def test_additions_extend_established_mirrors_and_allocate_occurrences() -> None:
    source = library(mirrored=True)
    addition = Playlist(
        -1, "New", entries=(PlaylistEntry("one", 1), PlaylistEntry("two", 1))
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(
                replace(
                    source.snapshot, playlists=(*source.snapshot.playlists, addition)
                )
            )
        )
    )
    assert result.prepared is not None, result.issues
    document = parse_iTunesDB(result.prepared.itunes)
    for dataset in document.find_chunks(MhsdHeader):
        if dataset.chunk.header.dataset_type in (2, 3):
            assert len(dataset.find_chunks(MhypHeader)) == 3
    new_items = [
        s.chunk.header
        for s in document.find_chunks(MhipHeader)
        if s.chunk.header.mhip_persistent_id > 302
    ]
    assert len(new_items) == 4
    assert len({h.mhip_persistent_id for h in new_items}) == 4


def test_identity_wraparound_never_collides_and_exhaustion_is_explicit() -> None:
    assert allocate((7,), (-1, -2), 3) == {-1: 1, -2: 2}
    assert allocate((1,), (2, 3, -1), 3) == {2: 2, 3: 3, -1: 4}
    with pytest.raises(ValueError, match="No unused"):
        allocate(range(1, 8), (-1,), 3)


@pytest.mark.parametrize(
    "value", [-MAC_EPOCH_UNIX_OFFSET + 1, -1, 0xFFFFFFFF - MAC_EPOCH_UNIX_OFFSET]
)
def test_date_extremes_roundtrip_without_clamping(value: int) -> None:
    source = library()
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, metadata=replace(t.metadata, last_modified=value))
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert all(
        t.metadata.last_modified == value for t in result.prepared.snapshot.tracks
    )


def test_invalid_dates_encodings_ranges_and_readonly_fields_are_reported() -> None:
    source = library()
    t = source.snapshot.tracks[0]
    cases = (
        replace(t, title="bad\ud800"),
        replace(t, year=2**32),
        replace(t, ipod=None),
        replace(t, metadata=replace(t.metadata, last_modified=2**40)),
    )
    for edited in cases:
        result = source.prepare(
            source.analyze(
                source.begin_draft(
                    replace(source.snapshot, tracks=(edited, source.snapshot.tracks[1]))
                )
            )
        )
        assert result.prepared is None and result.issues
    assert source.snapshot.tracks[0] is t


def test_unrelated_inconsistency_is_preserved_with_warning_and_quantization_is_explicit() -> (
    None
):
    source = library()
    document = parse_iTunesDB(source.serialize().itunes)
    playlist = next(
        s for s in document.find_chunks(MhypHeader) if not s.chunk.header.master_flag
    )
    document = document.replace_chunk(
        playlist,
        replace(
            playlist.chunk,
            header=replace(playlist.chunk.header, parent_folder_playlist_id=999),
        ),
    )
    track = document.find_chunks(MhitHeader)[0]
    document = document.replace_chunk(
        track,
        replace(track.chunk, header=replace(track.chunk.header, stop_time=999999)),
    )
    source = IPodLibrary(write_iTunesDB(document))
    t = source.snapshot.tracks[0]
    desired = replace(
        source.snapshot,
        tracks=(
            replace(t, metadata=replace(t.metadata, volume_adjustment_percent=33)),
            source.snapshot.tracks[1],
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert {i.code for i in result.issues} >= {
        "source.repaired_hierarchy",
        "track.quantized",
    }
    assert all(i.severity is IssueSeverity.WARNING for i in result.issues)
    assert result.prepared.snapshot.tracks[0].metadata.stop_time_ms == 999999


def test_unknown_index_is_retained_until_an_edit_affects_its_dependencies() -> None:
    source = library()
    document = parse_iTunesDB(source.serialize().itunes)
    master = next(
        s for s in document.find_chunks(MhypHeader) if s.chunk.header.master_flag
    )
    index = new_itunes_chunk(
        MHOD,
        MhodHeader(mhod_type=52),
        prefix=MhodLibraryIndexPrefix(sort_type=999),
        payload=MhodLibraryIndexPayload(indices=(1, 0), trailing_data=b"private"),
    )
    source = IPodLibrary(
        write_iTunesDB(document.replace_chunk(master, master.chunk.append_child(index)))
    )
    for title, succeeds in ((None, True), ("Changed", False)):
        edited = replace(
            source.snapshot.tracks[0],
            rating=80,
            title=title or source.snapshot.tracks[0].title,
        )
        result = source.prepare(
            source.analyze(
                source.begin_draft(
                    replace(source.snapshot, tracks=(edited, source.snapshot.tracks[1]))
                )
            )
        )
        assert (result.prepared is not None) == succeeds, result.issues


def test_folder_cycle_collects_errors_and_does_not_mutate_source() -> None:
    source = library()
    a = Playlist(-1, "A", PlaylistKind.FOLDER, parent_id=-2)
    b = Playlist(-2, "B", PlaylistKind.FOLDER, parent_id=-1)
    plan = source.analyze(
        source.begin_draft(replace(source.snapshot, playlists=(a, b)))
    )
    assert any(i.code == "playlist.folder_cycle" for i in plan.issues)
    assert source.prepare(plan).prepared is None


def test_unsupported_artwork_signature_blocks_changes() -> None:
    source = library()
    desired = replace(
        source.snapshot, playlists=(replace(source.snapshot.playlists[0], name="Edit"),)
    )
    assert (
        source.prepare(
            source.analyze(
                source.begin_draft(desired),
                WriteTarget(artwork_checksum=WriteChecksum.HASH58),
            )
        ).prepared
        is None
    )


@pytest.mark.parametrize(
    "target",
    [WriteTarget(compressed_database=True), WriteTarget(sqlite_database=True)],
)
def test_late_ipod_artifacts_are_prepared(target: WriteTarget) -> None:
    source = library()
    desired = replace(
        source.snapshot, playlists=(replace(source.snapshot.playlists[0], name="Edit"),)
    )

    result = source.prepare(source.analyze(source.begin_draft(desired), target))

    assert result.prepared is not None, result.issues
    assert is_iTunesCDB(result.prepared.itunes) is target.compressed_database
    assert (result.prepared.sqlite is not None) is target.sqlite_database


def test_noop_does_not_generate_or_retain_sqlite_projection() -> None:
    source = library()

    result = source.prepare(
        source.analyze(
            source.begin_draft(),
            WriteTarget(sqlite_database=True),
        )
    )

    assert result.prepared is not None, result.issues
    assert result.prepared.sqlite is None


def test_failed_reparse_verification_never_returns_a_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = library()
    import iPodDB.library._write_preparation as preparation

    def omit_edit(_candidate: DatabaseDocument[MhbdHeader]) -> bytes:
        return source.serialize().itunes

    monkeypatch.setattr(preparation, "write_iTunesDB", omit_edit)
    desired = replace(
        source.snapshot,
        playlists=(replace(source.snapshot.playlists[0], name="Lost edit"),),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None
    assert any(i.phase == "verification" for i in result.issues)


def test_writer_errors_on_additions_retain_draft_identity_and_binary_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import iPodDB.library._write_preparation as preparation

    source = library()
    original = source.serialize().itunes
    addition = Playlist(-1, "New")
    draft = source.begin_draft(
        replace(source.snapshot, playlists=(*source.snapshot.playlists, addition))
    )

    def fail_new_playlist(candidate: DatabaseDocument[MhbdHeader]) -> bytes:
        selection = next(
            s
            for s in candidate.find_chunks(MhypHeader)
            if s.chunk.header.playlist_id not in (10, 1000)
        )
        raise iPodDBWriteError(
            "Cannot encode this field.",
            code="binary.invalid_value",
            field="name",
            chunk_path=(*selection.path.child_indexes, 0),
            offset=42,
            marker=b"mhod",
        )

    monkeypatch.setattr(preparation, "write_iTunesDB", fail_new_playlist)
    result = source.prepare(source.analyze(draft))
    assert result.prepared is None
    issue = next(i for i in result.issues if i.code == "binary.invalid_value")
    assert (issue.subject, issue.record_id) == ("playlist", -1)
    assert (issue.artifact, issue.field, issue.offset) == ("iTunesDB", "name", 42)
    assert issue.phase == "serialization" and issue.chunk_path
    assert source.serialize().itunes == original
    assert draft.snapshot.playlists[-1] is addition


def test_ten_thousand_track_library_prepares_a_selective_edit() -> None:
    tracks = tuple(
        new_itunes_chunk(
            MHIT,
            MhitHeader(track_id=i, db_track_id=100000 + i, media_type=1),
            children=(new_string_mhod(MhodType.TITLE, f"Track {i}"),),
        )
        for i in range(1, 10001)
    )
    document = new_iTunesDB(
        MhbdHeader(),
        datasets=(
            new_itunes_chunk(
                MHSD,
                MhsdHeader(dataset_type=1),
                children=(new_itunes_chunk(MHLT, EmptyChunkHeader(), children=tracks),),
            ),
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    desired = replace(
        source.snapshot,
        tracks=(
            *source.snapshot.tracks[:-1],
            replace(source.snapshot.tracks[-1], rating=100),
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert len(result.prepared.snapshot.tracks) == 10000
    assert result.prepared.snapshot.tracks[-1].rating == 100
    assert source.snapshot.tracks[-1].rating == 0
