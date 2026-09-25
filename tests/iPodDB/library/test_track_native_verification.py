"""Native Track facts must be checked independently of semantic projection."""

import math
import struct
from collections.abc import Callable
from dataclasses import replace

import pytest
from tests.iPodDB.library.test_browse_relationships import browse_source
from tests.iPodDB.library.test_media_lifecycle import prepared_media

from iPodDB.iTunesDB.builder.build_iTunesDB import new_string_mhod
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    IPodLibrary,
    Track,
    TrackFieldEdit,
    TrackMetadata,
    _write_preparation,
    edit_track_metadata,
)
from iPodDB.library._reconcile import reconcile
from iPodDB.library._resolved_write import ResolvedWrite
from iPodDB.library.writing import IdentityMapping, WriteIssue, WriteResources
from iPodDB.shared.binary_struct import binary_fields
from iPodDB.shared.chunk import DatabaseDocument

CORRUPTIONS: tuple[tuple[str, Callable[[MhitHeader], MhitHeader]], ...] = (
    ("filetype", lambda h: replace(h, filetype=999)),
    ("mp3_flag", lambda h: replace(h, mp3_flag=9)),
    ("av_flag", lambda h: replace(h, av_flag=999)),
    ("mpeg_audio_type", lambda h: replace(h, mpeg_audio_type=999)),
    (
        "gapless_audio_payload_size",
        lambda h: replace(h, gapless_audio_payload_size=999),
    ),
    ("size_2", lambda h: replace(h, size_2=999)),
    ("sample_rate_2", lambda h: replace(h, sample_rate_2=12345.0)),
    ("sample_rate_1", lambda h: replace(h, sample_rate_1=h.sample_rate_1 ^ 1)),
    ("media_type", lambda h: replace(h, media_type=h.media_type ^ 0x80000000)),
    ("video_flag", lambda h: replace(h, video_flag=9)),
    ("not_played_flag", lambda h: replace(h, not_played_flag=0)),
    ("explicit_flag", lambda h: replace(h, explicit_flag=9)),
    ("unk_mhit_0x84", lambda h: replace(h, unk_mhit_0x84=999)),
    ("db_track_id_2", lambda h: replace(h, db_track_id_2=999)),
)


@pytest.mark.parametrize("operation", ["metadata", "addition", "replacement"])
@pytest.mark.parametrize(
    "field, mutate", CORRUPTIONS, ids=[field for field, _ in CORRUPTIONS]
)
def test_preparation_rejects_native_track_corruption(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    field: str,
    mutate: Callable[[MhitHeader], MhitHeader],
) -> None:
    source = browse_source()
    addition = operation == "addition"
    has_media = operation != "metadata"
    track = (
        Track(
            -1,
            "Imported",
            "Artist",
            "Album",
            1000,
            size_bytes=5,
            metadata=TrackMetadata(
                location="iPod_Control/Music/F00/new.m4a",
                sample_rate_hz=44100,
                file_format="AAC audio file",
            ),
        )
        if addition
        else replace(source.snapshot.tracks[0], title="Edited title")
    )
    if operation == "replacement":
        track = replace(
            track,
            length_ms=1500,
            size_bytes=5,
            metadata=replace(
                track.metadata,
                location="iPod_Control/Music/F00/replaced.m4a",
                sample_rate_hz=48000,
                file_format="AAC audio file",
            ),
        )
    desired = replace(
        source.snapshot,
        tracks=(*source.snapshot.tracks, track)
        if addition
        else (track, *source.snapshot.tracks[1:]),
    )
    resources = WriteResources(
        media=(prepared_media(track, b"media"),) if has_media else (),
        pending_playback_sidecars=False,
    )
    baseline = source.prepare(source.analyze(source.begin_draft(desired)), resources)
    assert baseline.prepared is not None, baseline.issues

    def corrupt(
        document: DatabaseDocument[MhbdHeader],
        resolved: ResolvedWrite,
        supplied: WriteResources,
        issues: list[WriteIssue],
    ) -> tuple[DatabaseDocument[MhbdHeader], tuple[IdentityMapping, ...]]:
        candidate, mappings = reconcile(document, resolved, supplied, issues)
        native_id = next(
            (
                m.output_id
                for m in mappings
                if m.subject == "track" and m.draft_id == track.track_id
            ),
            track.track_id,
        )
        selection = next(
            s
            for s in candidate.find_chunks(MhitHeader)
            if s.chunk.header.track_id == native_id
        )
        return candidate.replace_chunk(
            selection,
            replace(
                selection.chunk,
                header=mutate(selection.chunk.header),
            ),
        ), mappings

    monkeypatch.setattr(_write_preparation, "reconcile", corrupt)
    result = source.prepare(source.analyze(source.begin_draft(desired)), resources)
    assert result.prepared is None
    issue = next(i for i in result.issues if i.code == "verification.track_native")
    assert issue.record_id == track.track_id and issue.field == field
    assert issue.phase == "verification" and issue.artifact == "iTunesDB"
    assert (
        issue.offset is not None
        and "expected" in issue.detail
        and "actual" in issue.detail
    )


@pytest.mark.parametrize("sample_rate", [12345.0, float("nan")])
def test_metadata_edit_preserves_noncanonical_native_media_and_secondary_identity(
    sample_rate: float,
) -> None:
    document = parse_iTunesDB(browse_source().serialize().itunes)
    selection = document.find_chunks(MhitHeader)[0]
    retained = replace(
        selection.chunk.header,
        mp3_flag=9,
        av_flag=19,
        mpeg_audio_type=29,
        gapless_audio_payload_size=999,
        size_2=123,
        sample_rate_2=sample_rate,
        db_track_id_2=777,
        sample_rate_1=(44100 << 16) | 0x1234,
        media_type=selection.chunk.header.media_type | 0x80000000,
        video_flag=9,
        not_played_flag=0,
        explicit_flag=9,
        checked_flag=2,
        compilation_flag=2,
        vbr_flag=7,
        unk_mhit_0x84=711,
        unk_mhit_0x104=bytes(range(20)),
    )
    raw = bytearray(selection.chunk.raw_header)
    raw[0x18C:0x190] = b"\xa5\x04\x7f\xee"
    source = IPodLibrary(
        write_iTunesDB(
            document.replace_chunk(
                selection,
                replace(selection.chunk, header=retained, raw_header=bytes(raw)),
            )
        )
    )
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], title="Edited"),
            *source.snapshot.tracks[1:],
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    chunk = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    output = chunk.header
    assert chunk.raw_header[0x18C:0x190] == raw[0x18C:0x190]
    assert replace(output, sample_rate_2=0) == replace(retained, sample_rate_2=0)
    if math.isnan(sample_rate):
        assert math.isnan(output.sample_rate_2)
    else:
        assert output.sample_rate_2 == sample_rate


@pytest.mark.parametrize(
    "index,name,kind",
    [
        (0, "sort_title", MhodType.SORT_TITLE),
        (1, "sort_album", MhodType.SORT_ALBUM),
        (2, "sort_artist", MhodType.SORT_ARTIST),
        (3, "sort_album_artist", MhodType.SORT_ALBUM_ARTIST),
        (4, "sort_composer", MhodType.SORT_COMPOSER),
        (5, "sort_show", MhodType.SORT_SHOW),
    ],
)
@pytest.mark.parametrize("value", ["Updated override", ""])
def test_sort_override_edit_preserves_other_indicator_bits(
    index: int, name: str, kind: MhodType, value: str
) -> None:
    document = parse_iTunesDB(browse_source().serialize().itunes)
    selection = document.find_chunks(MhitHeader)[0]
    indicators = bytes((0xA1,) * 6 + (0xFE, 0xFC))
    original = write_iTunesDB(
        document.replace_chunk(
            selection,
            replace(
                selection.chunk,
                header=replace(selection.chunk.header, sort_mhod_indicators=indicators),
                children=(
                    *selection.chunk.children,
                    new_string_mhod(kind, "Old override"),
                ),
            ),
        )
    )
    source = IPodLibrary(original)
    track = source.snapshot.tracks[0]
    desired = replace(
        source.snapshot,
        tracks=(
            edit_track_metadata(track, (TrackFieldEdit("metadata." + name, value),)),
            *source.snapshot.tracks[1:],
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    header = (
        parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk.header
    )
    expected = bytearray(indicators)
    expected[index] = 0xA0 | bool(value)
    assert header.sort_mhod_indicators == bytes(expected)
    assert source.serialize().itunes == original


def test_preparation_rejects_changed_unmodeled_header_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = browse_source()
    original = source.serialize()
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], title="Edited"),
            *source.snapshot.tracks[1:],
        ),
    )

    def corrupt(document: DatabaseDocument[MhbdHeader]) -> bytes:
        data = bytearray(write_iTunesDB(document))
        parsed = parse_iTunesDB(bytes(data))
        track = parsed.find_chunks(MhitHeader)[0].chunk
        # A retained MHIT header gap, outside every modeled field.
        data[track.offset + 0x18C] |= 1
        return bytes(data)

    monkeypatch.setattr(_write_preparation, "write_iTunesDB", corrupt)
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None
    assert any(
        i.code == "verification.track_native" and i.field == "raw_header"
        for i in result.issues
    ), result.issues
    assert source.serialize() == original


@pytest.mark.parametrize(
    "before_bits,after_bits", [(0x80000000, 0), (0x7FC12345, 0x7FC54321)]
)
def test_preparation_preserves_retained_float_encoding(
    monkeypatch: pytest.MonkeyPatch, before_bits: int, after_bits: int
) -> None:
    schema = next(
        f.schema
        for f in binary_fields(MhitHeader)
        if f.attribute_name == "sample_rate_2"
    )
    original = bytearray(browse_source().serialize().itunes)
    selection = parse_iTunesDB(bytes(original)).find_chunks(MhitHeader)[0]
    struct.pack_into(
        "<I", original, selection.chunk.offset + schema.offset, before_bits
    )
    source = IPodLibrary(bytes(original))
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], title="Edited"),
            *source.snapshot.tracks[1:],
        ),
    )
    baseline = source.prepare(source.analyze(source.begin_draft(desired)))
    assert baseline.prepared is not None, baseline.issues
    chunk = parse_iTunesDB(baseline.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    assert struct.unpack_from("<I", chunk.raw_header, schema.offset)[0] == before_bits

    def corrupt(document: DatabaseDocument[MhbdHeader]) -> bytes:
        data = bytearray(write_iTunesDB(document))
        track = parse_iTunesDB(bytes(data)).find_chunks(MhitHeader)[0].chunk
        struct.pack_into("<I", data, track.offset + schema.offset, after_bits)
        return bytes(data)

    monkeypatch.setattr(_write_preparation, "write_iTunesDB", corrupt)
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None
    assert any(
        i.code == "verification.track_native" and i.field == "sample_rate_2"
        for i in result.issues
    ), result.issues


@pytest.mark.parametrize("persistent_id", [0, 101, 102, 103])
def test_new_track_rejects_zero_or_reused_persistent_identity(
    monkeypatch: pytest.MonkeyPatch, persistent_id: int
) -> None:
    source = browse_source()
    added = tuple(
        Track(
            identity,
            "Import",
            "New artist",
            "New album",
            1000,
            size_bytes=5,
            metadata=TrackMetadata(
                file_format="AAC audio file",
                sample_rate_hz=44100,
                location=f"iPod_Control/Music/F00/new{-identity}.m4a",
            ),
        )
        for identity in (-1, -2)
    )
    desired = replace(source.snapshot, tracks=(*source.snapshot.tracks, *added))
    resources = WriteResources(
        media=tuple(prepared_media(t, b"media") for t in added),
        pending_playback_sidecars=False,
    )
    baseline = source.prepare(source.analyze(source.begin_draft(desired)), resources)
    assert baseline.prepared is not None, baseline.issues

    def corrupt(
        document: DatabaseDocument[MhbdHeader],
        resolved: ResolvedWrite,
        supplied: WriteResources,
        issues: list[WriteIssue],
    ) -> tuple[DatabaseDocument[MhbdHeader], tuple[IdentityMapping, ...]]:
        candidate, mappings = reconcile(document, resolved, supplied, issues)
        native_id = next(
            m.output_id for m in mappings if m.subject == "track" and m.draft_id == -2
        )
        selection = next(
            s
            for s in candidate.find_chunks(MhitHeader)
            if s.chunk.header.track_id == native_id
        )
        return candidate.replace_chunk(
            selection,
            replace(
                selection.chunk,
                header=replace(
                    selection.chunk.header,
                    db_track_id=persistent_id,
                    db_track_id_2=persistent_id,
                ),
            ),
        ), mappings

    monkeypatch.setattr(_write_preparation, "reconcile", corrupt)
    result = source.prepare(source.analyze(source.begin_draft(desired)), resources)
    assert result.prepared is None
    assert any(
        i.code == "verification.track_native"
        and i.field == "db_track_id"
        and i.record_id == -2
        for i in result.issues
    )
