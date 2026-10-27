"""Device layouts apply to creation and every source of native Track edits."""

import hashlib
from dataclasses import replace

import pytest
from tests.iPodDB.library.test_browse_relationships import browse_source
from tests.iPodDB.library.test_sidecar_projection import short_header_library
from tests.iPodDB.library.test_write_artwork import COVER, RED

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, WriteResources, WriteTarget
from iPodDB.library._track_verification import verify_native_tracks
from iPodDB.library.models import Track
from iPodDB.library.writing import FileDependency, LibraryWriteResult, PreparedMedia


@pytest.mark.parametrize("length", [156, 328])
@pytest.mark.parametrize("version,expected", [(0x13, 328), (0x19, 328), (0x30, 624)])
def test_composer_edit_uses_device_layout(
    length: int, version: int, expected: int
) -> None:
    source = short_header_library(length)
    original = source.serialize()
    first, second = source.snapshot.tracks
    desired = replace(
        source.snapshot,
        tracks=(
            replace(first, metadata=replace(first.metadata, composer="Composer")),
            second,
        ),
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(desired), WriteTarget(database_version=version)
        )
    )
    assert result.prepared is not None, result.issues
    saved = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)
    # Older layouts keep Composer text without inventing a newer browse ID.
    assert saved[0].chunk.generic_header.header_length == (
        expected if version == 0x30 else length
    )
    assert bool(saved[0].chunk.header.composer_id) == (version == 0x30)
    assert result.prepared.snapshot.tracks[0].metadata.composer == "Composer"
    assert saved[1].chunk.generic_header.header_length == length
    assert source.serialize() == original


@pytest.mark.parametrize("version,expected", [(0x13, 328), (0x19, 328), (0x30, 624)])
def test_artwork_alone_expands_short_header(version: int, expected: int) -> None:
    source = short_header_library()
    original = source.serialize()
    first, second = source.snapshot.tracks
    desired = replace(source.snapshot, tracks=(replace(first, artwork_id=-1), second))
    target = WriteTarget(
        database_version=version, cover_formats=(COVER,), artwork_root_value=2
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), target),
        WriteResources(artwork=(RED,), file_inventory=()),
    )
    assert result.prepared is not None, result.issues
    saved = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)
    assert saved[0].chunk.generic_header.header_length == expected
    assert saved[0].chunk.header.has_artwork == 1
    assert saved[1].chunk.generic_header.header_length == 156
    assert result.prepared.snapshot.tracks[0].artwork_id > 0
    assert source.serialize() == original


def add_audio(
    source: IPodLibrary, version: int | None, *, last_skipped: int = 0
) -> LibraryWriteResult:
    track = Track(
        -1,
        "New audio",
        "",
        "",
        1000,
        size_bytes=4,
        metadata=replace(
            source.snapshot.tracks[0].metadata,
            composer="Composer",
            location="iPod_Control/Music/F00/new.mp3",
            sample_rate_hz=44100,
            file_format="MP3 audio file",
            last_skipped=last_skipped,
        ),
    )
    media = PreparedMedia(
        -1,
        FileDependency(track.metadata.location, 4, hashlib.sha256(b"test").hexdigest()),
        filetype=int.from_bytes(b"MP3 ", "big"),
        mp3_flag=1,
        audio_format_flag=0,
        mpeg_audio_type=0,
        gapless_audio_payload_size=0,
    )
    desired = replace(source.snapshot, tracks=(*source.snapshot.tracks, track))
    return source.prepare(
        source.analyze(
            source.begin_draft(desired), WriteTarget(database_version=version)
        ),
        WriteResources(media=(media,), pending_playback_sidecars=False),
    )


@pytest.mark.parametrize(
    "version,expected",
    [(0x0B, 156), (0x13, 328), (0x19, 328), (0x2D, 504), (0x30, 624)],
)
def test_new_audio_uses_device_layout(version: int, expected: int) -> None:
    source = short_header_library()
    result = add_audio(source, version)
    assert result.prepared is not None, result.issues
    document = parse_iTunesDB(result.prepared.itunes)
    saved = document.find_chunks(MhitHeader)[-1].chunk
    assert saved.generic_header.header_length == expected
    assert bool(saved.header.composer_id) == (expected >= 504)
    assert saved.header.db_track_id != 0
    assert saved.header.db_track_id_2 == (
        saved.header.db_track_id if expected >= 176 else 0
    )
    assert saved.header.size_2 == (4 if expected >= 304 else 0)
    assert result.prepared.snapshot.tracks[-1].metadata.composer == "Composer"


def test_creation_uses_device_baseline_without_downgrading_newer_source() -> None:
    source = short_header_library(624)
    document = parse_iTunesDB(source.serialize().itunes)
    document = replace(document, header=replace(document.header, version=0x75))
    source = IPodLibrary(write_iTunesDB(document))
    result = add_audio(source, 0x19)
    assert result.prepared is not None, result.issues
    saved = parse_iTunesDB(result.prepared.itunes)
    assert saved.header.version == 0x75
    assert [
        s.chunk.generic_header.header_length for s in saved.find_chunks(MhitHeader)
    ] == [624, 624, 328]
    for before, after in zip(
        document.find_chunks(MhitHeader), saved.find_chunks(MhitHeader), strict=False
    ):
        assert before.chunk.raw_header == after.chunk.raw_header
        assert before.chunk.raw_body == after.chunk.raw_body


def test_creation_without_device_capability_keeps_generic_default() -> None:
    source = short_header_library()
    result = add_audio(source, None)
    assert result.prepared is not None, result.issues
    saved = parse_iTunesDB(result.prepared.itunes)
    assert saved.find_chunks(MhitHeader)[-1].chunk.generic_header.header_length == 624
    assert (
        saved.header.version == parse_iTunesDB(source.serialize().itunes).header.version
    )


def test_creation_rejects_history_outside_selected_layout() -> None:
    source = short_header_library()
    original = source.serialize()
    result = add_audio(source, 0x0B, last_skipped=1_700_000_000)
    assert result.prepared is None
    assert any(
        i.code == "binary.short_header" and i.field == "last_skipped"
        for i in result.issues
    )
    assert source.serialize() == original


@pytest.mark.parametrize("version", [None, 0x0B])
def test_artwork_without_sufficient_capability_is_blocked(version: int | None) -> None:
    source = short_header_library()
    original = source.serialize()
    first, second = source.snapshot.tracks
    desired = replace(source.snapshot, tracks=(replace(first, artwork_id=-1), second))
    result = source.prepare(
        source.analyze(
            source.begin_draft(desired),
            WriteTarget(
                database_version=version, cover_formats=(COVER,), artwork_root_value=2
            ),
        ),
        WriteResources(artwork=(RED,), file_inventory=()),
    )
    assert result.prepared is None
    assert any(
        i.code == "binary.short_header" and i.field == "has_artwork"
        for i in result.issues
    )
    assert source.serialize() == original


@pytest.mark.parametrize("length", [504, 584, 624, 640])
def test_older_target_preserves_larger_layout_and_authors_composer_identity(
    length: int,
) -> None:
    document = parse_iTunesDB(browse_source().serialize().itunes)
    for selection in document.find_chunks(MhitHeader):
        chunk = selection.chunk
        document = document.replace_chunk(
            selection,
            replace(
                chunk,
                generic_header=replace(chunk.generic_header, header_length=length),
                raw_header=chunk.raw_header[:length].ljust(length, b"\xa5"),
            ),
        )
    source = IPodLibrary(write_iTunesDB(document))
    original = source.serialize()
    target = WriteTarget(database_version=0x19)
    noop = source.prepare(source.analyze(source.begin_draft(), target))
    assert noop.prepared is not None, noop.issues
    assert noop.prepared.itunes == original.itunes
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, metadata=replace(t.metadata, composer="Renamed composer"))
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired), target))
    assert result.prepared is not None, result.issues
    saved = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)
    assert all(s.chunk.generic_header.header_length == length for s in saved)
    assert len({s.chunk.header.composer_id for s in saved}) == 1
    assert saved[0].chunk.header.composer_id != 0
    if length > 624:
        assert all(s.chunk.raw_header[624:] == b"\xa5" * (length - 624) for s in saved)
    assert source.serialize() == original


def short_browse_source(length: int) -> IPodLibrary:
    document = parse_iTunesDB(browse_source().serialize().itunes)
    for selection in document.find_chunks(MhitHeader):
        chunk = selection.chunk
        document = document.replace_chunk(
            selection,
            replace(
                chunk,
                header=replace(
                    chunk.header,
                    album_id=0 if length == 156 else chunk.header.album_id,
                    artist_id_ref=0,
                    composer_id=0,
                ),
                generic_header=replace(chunk.generic_header, header_length=length),
                raw_header=chunk.raw_header[:length],
            ),
        )
    return IPodLibrary(write_iTunesDB(document))


@pytest.mark.parametrize(
    "field,length,version,expected",
    [("album", 156, 0x19, 328), ("artist", 328, 0x30, 624)],
)
def test_browse_membership_expands_affected_members_including_unchanged_track(
    field: str, length: int, version: int, expected: int
) -> None:
    source = short_browse_source(length)
    original = source.serialize()
    first, second = source.snapshot.tracks
    changed = (
        replace(first, album="Split")
        if field == "album"
        else replace(first, artist="Split")
    )
    desired = replace(source.snapshot, tracks=(changed, second))
    result = source.prepare(
        source.analyze(
            source.begin_draft(desired), WriteTarget(database_version=version)
        )
    )
    assert result.prepared is not None, result.issues
    saved = parse_iTunesDB(result.prepared.itunes)
    chunks = [s.chunk for s in saved.find_chunks(MhitHeader)]
    assert [c.generic_header.header_length for c in chunks] == [expected, expected]
    native = "album_id" if field == "album" else "artist_id_ref"
    assert all(getattr(c.header, native) != 0 for c in chunks)
    assert result.prepared.snapshot.tracks[1].title == second.title
    assert source.serialize() == original


def test_required_artist_dataset_reference_cannot_be_silently_omitted() -> None:
    source = short_browse_source(328)
    first, second = source.snapshot.tracks
    desired = replace(source.snapshot, tracks=(replace(first, artist="Split"), second))
    result = source.prepare(
        source.analyze(source.begin_draft(desired), WriteTarget(database_version=0x19))
    )
    assert result.prepared is None
    assert any(
        i.code == "binary.short_header" and i.field == "artist_id_ref"
        for i in result.issues
    )


@pytest.mark.parametrize("length", [504, 640])
def test_verifier_rejects_wrong_extent_even_when_composer_id_fits(length: int) -> None:
    source = short_header_library(328)
    first, second = source.snapshot.tracks
    desired = replace(
        source.snapshot,
        tracks=(
            replace(first, metadata=replace(first.metadata, composer="Composer")),
            second,
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), WriteTarget(database_version=0x30))
    )
    assert result.prepared is not None, result.issues
    saved = parse_iTunesDB(result.prepared.itunes)
    selection = saved.find_chunks(MhitHeader)[0]
    saved = saved.replace_chunk(
        selection,
        replace(
            selection.chunk,
            generic_header=replace(
                selection.chunk.generic_header, header_length=length
            ),
            raw_header=selection.chunk.raw_header[:length].ljust(length, b"\0"),
        ),
    )
    issues = verify_native_tracks(
        parse_iTunesDB(source.serialize().itunes),
        parse_iTunesDB(write_iTunesDB(saved)),
        source.snapshot,
        desired,
        result.prepared.identities,
        WriteResources(),
        database_version=0x30,
    )
    assert any(i.field == "header_length" for i in issues)
