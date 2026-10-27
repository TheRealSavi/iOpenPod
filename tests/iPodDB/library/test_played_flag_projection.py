"""An explicit played marker can override a nonzero lifetime play count."""

import hashlib
import struct
from dataclasses import replace

import pytest
from tests.iPodDB.library.test_sidecar_projection import short_header_library
from tests.iPodDB.sidecars.test_sidecar_readers import counts

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library import (
    IPodLibrary,
    Track,
    TrackFieldEdit,
    WriteResources,
    WriteTarget,
    edit_track_metadata,
)
from iPodDB.library.writing import FileDependency, PreparedMedia
from iPodDB.sidecars import PlaybackSidecar


def marked_library(length: int, play_count: int, marker: int) -> IPodLibrary:
    data = bytearray(short_header_library(length).serialize().itunes)
    offset = parse_iTunesDB(data).find_chunks(MhitHeader)[0].chunk.offset
    struct.pack_into("<I", data, offset + 0x50, play_count)
    if length > 0xB2:
        data[offset + 0xB2] = marker
    return IPodLibrary(bytes(data))


@pytest.mark.parametrize("length", [156, 178, 179, 624])
@pytest.mark.parametrize("play_count", [0, 9])
@pytest.mark.parametrize("marker", [0, 1, 2, 3])
def test_only_present_explicit_marker_overrides_play_count(
    length: int, play_count: int, marker: int
) -> None:
    source = marked_library(length, play_count, marker)
    expected = marker == 1 if length > 0xB2 and marker in (1, 2) else play_count > 0
    assert source.snapshot.tracks[0].metadata.played is expected
    original = source.serialize().itunes
    assert IPodLibrary(original).serialize().itunes == original


def test_mark_unplayed_preserves_lifetime_play_count() -> None:
    source = marked_library(624, 9, 1)
    first, *rest = source.snapshot.tracks
    desired = replace(
        source.snapshot,
        tracks=(
            edit_track_metadata(first, (TrackFieldEdit("metadata.played", False),)),
            *rest,
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    saved = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    assert int.from_bytes(saved.raw_header[0x50:0x54], "little") == 9
    assert saved.raw_header[0xB2] == 2
    assert result.prepared.snapshot.tracks[0].metadata.played is False


def test_unrelated_metadata_edit_does_not_override_explicit_unplayed_marker() -> None:
    first = marked_library(624, 9, 2).snapshot.tracks[0]
    edited = edit_track_metadata(first, (TrackFieldEdit("title", "Renamed"),))
    assert edited.metadata.played is False
    assert edited.play_count == 9


@pytest.mark.parametrize("marker", [0, 3])
@pytest.mark.parametrize("before,after", [(0, 5), (5, 0)])
def test_count_edit_writes_marker_only_to_preserve_requested_played_state(
    marker: int, before: int, after: int
) -> None:
    source = marked_library(624, before, marker)
    first, *rest = source.snapshot.tracks
    desired = replace(source.snapshot, tracks=(replace(first, play_count=after), *rest))
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    saved = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    assert saved.raw_header[0xB2] == (1 if before else 2)
    assert int.from_bytes(saved.raw_header[0x50:0x54], "little") == after
    assert result.prepared.snapshot.tracks[0].metadata.played is (before > 0)


@pytest.mark.parametrize("marker", [0, 3])
@pytest.mark.parametrize("play_count", [0, 5])
def test_unknown_marker_survives_noop_and_unrelated_edit(
    marker: int, play_count: int
) -> None:
    source = marked_library(624, play_count, marker)
    original = source.serialize().itunes
    noop = source.prepare(source.analyze(source.begin_draft()))
    assert noop.prepared is not None, noop.issues
    assert noop.prepared.itunes == original
    first, *rest = source.snapshot.tracks
    desired = replace(source.snapshot, tracks=(replace(first, title="Renamed"), *rest))
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    saved = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    assert saved.raw_header[0xB2] == marker


def test_short_header_grows_to_store_explicit_unplayed_state_with_positive_plays() -> (
    None
):
    source = marked_library(156, 0, 0)
    first, *rest = source.snapshot.tracks
    desired = replace(source.snapshot, tracks=(replace(first, play_count=5), *rest))
    result = source.prepare(
        source.analyze(source.begin_draft(desired), WriteTarget(database_version=0x13))
    )
    assert result.prepared is not None, result.issues
    saved = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    assert saved.generic_header.header_length == 328
    assert saved.raw_header[0xB2] == 2
    assert int.from_bytes(saved.raw_header[0x50:0x54], "little") == 5
    assert not result.prepared.snapshot.tracks[0].metadata.played


def test_new_short_header_rejects_unrepresentable_played_state_before_verification() -> (
    None
):
    source = marked_library(156, 0, 0)
    track = Track(
        -1,
        "New",
        "",
        "",
        1000,
        size_bytes=4,
        play_count=5,
        metadata=replace(
            source.snapshot.tracks[0].metadata,
            location="iPod_Control/Music/F00/new.mp3",
            sample_rate_hz=44100,
            file_format="MP3 audio file",
            played=False,
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
    result = source.prepare(
        source.analyze(source.begin_draft(desired), WriteTarget(database_version=0x0B)),
        WriteResources(media=(media,), pending_playback_sidecars=False),
    )
    assert result.prepared is None
    assert any(
        issue.code == "track.unstorable" and issue.field == "metadata.played"
        for issue in result.issues
    )
    assert not any(issue.code.startswith("verification.") for issue in result.issues)


def test_binary_unplayed_marker_expands_short_header_despite_default_value() -> None:
    source = marked_library(156, 5, 0)
    loaded = source.with_sidecars(
        (PlaybackSidecar("Play Counts", counts(((0, 0, 0, 0xFFFFFFFF, 512, 0, 0),))),)
    )
    assert not loaded.snapshot.tracks[0].metadata.played
    result = loaded.prepare(
        loaded.analyze(loaded.begin_draft(), WriteTarget(database_version=0x13)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    saved = parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)[0].chunk
    assert saved.generic_header.header_length == 328
    assert saved.raw_header[0xB2] == 2
    assert int.from_bytes(saved.raw_header[0x50:0x54], "little") == 5
    assert not result.prepared.snapshot.tracks[0].metadata.played
