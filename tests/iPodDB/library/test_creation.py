"""Empty Libraries use the existing binary definitions and publication pipeline."""

from dataclasses import replace

import pytest

from iPodDB.iTunesDB.cdb import decompress_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.writer.signature import verify_hash58, verify_hash72, verify_hashab
from iPodDB.library import (
    AudioEncoding,
    FileDependency,
    Hash72Material,
    IPodLibrary,
    Track,
    TrackMetadata,
    WriteChecksum,
    WriteResources,
    WriteTarget,
    content_sha256,
    create_empty_library,
    prepared_audio,
)
from iPodDB.SQLiteDB.checksum import verify_locations_cbk

GUID = bytes.fromhex("000A270012345678")
MATERIAL = Hash72Material(GUID + bytes(12), bytes(range(12)), bytes(range(16)))


@pytest.mark.parametrize("version", [0x13, 0x19, 0x30])
@pytest.mark.parametrize("podcasts", [False, True])
@pytest.mark.parametrize("mac_formatted", [False, True])
def test_empty_library_has_device_version_named_master_and_no_media(
    version: int, podcasts: bool, mac_formatted: bool
) -> None:
    result = create_empty_library(
        "John's iPod",
        WriteTarget(database_version=version),
        supports_podcasts=podcasts,
        mac_formatted=mac_formatted,
    )
    assert result.prepared is not None, result.issues
    data = result.prepared.itunes
    document = parse_iTunesDB(data)
    assert document.header.version == version
    assert document.header.platform == (1 if mac_formatted else 2)
    assert document.header.db_id and document.header.db_id_2
    assert document.header.db_persistent_id
    kinds = tuple(s.chunk.header.dataset_type for s in document.find_chunks(MhsdHeader))
    assert kinds == (
        1,
        *((3,) if podcasts else ()),
        2,
        4,
        *((8, 6, 10) if version > 0x19 else ()),
        5,
    )
    masters = document.find_chunks(MhypHeader)
    assert len(masters) == (2 if podcasts else 1)
    assert all(
        s.chunk.header.master_flag == 1 and s.chunk.header.playlist_id for s in masters
    )
    assert all(s.chunk.header.unk_mhyp_0x28 == 1 for s in masters)
    library = IPodLibrary.parse(data)
    assert library.snapshot.device_name == "John's iPod"
    assert library.snapshot.tracks == ()
    assert library.snapshot.playlists == ()
    assert library.serialize().itunes == data
    assert library.prepare(library.analyze(library.begin_draft())).prepared is not None


@pytest.mark.parametrize(
    "checksum", [WriteChecksum.HASH58, WriteChecksum.HASH72, WriteChecksum.HASHAB]
)
@pytest.mark.parametrize("sqlite", [False, True])
def test_empty_signed_library_and_sqlite_artifacts_verify(
    checksum: WriteChecksum, sqlite: bool
) -> None:
    target = WriteTarget(
        database_version=0x30,
        checksum=checksum,
        firewire_guid=GUID,
        compressed_database=sqlite,
        sqlite_database=sqlite,
        sqlite_checksum=checksum if sqlite else WriteChecksum.NONE,
        hash72_material=MATERIAL,
    )
    result = create_empty_library("iPod", target, supports_podcasts=True)
    assert result.prepared is not None, result.issues
    data = result.prepared.itunes
    if checksum is WriteChecksum.HASH58:
        assert verify_hash58(data, GUID)
    elif checksum is WriteChecksum.HASH72:
        assert verify_hash58(data, GUID)
        assert verify_hash72(data, MATERIAL.iv, MATERIAL.random_part, hashing_scheme=1)
    else:
        assert verify_hashab(data, GUID)
    if sqlite:
        assert (
            parse_iTunesDB(decompress_iTunesCDB(data).logical_bytes).header.version
            == 0x30
        )
        artifacts = result.prepared.sqlite
        assert artifacts is not None
        assert len(tuple(artifacts.artifacts())) == 6
        assert verify_locations_cbk(
            artifacts,
            checksum,
            GUID,
            MATERIAL.iv,
            MATERIAL.random_part,
        )
    else:
        assert result.prepared.sqlite is None


@pytest.mark.parametrize(
    "target",
    [
        WriteTarget(database_version=0x30, checksum=WriteChecksum.HASH58),
        WriteTarget(
            database_version=0x30, checksum=WriteChecksum.HASH72, firewire_guid=GUID
        ),
        WriteTarget(database_version=0x30, max_database_bytes=1),
    ],
)
def test_creation_never_returns_unsigned_or_oversized_output(
    target: WriteTarget,
) -> None:
    result = create_empty_library("iPod", target, supports_podcasts=True)
    assert result.prepared is None
    assert result.issues


def test_creation_requires_explicit_version_and_nonempty_name() -> None:
    with pytest.raises(ValueError, match="version"):
        create_empty_library("iPod", WriteTarget(), supports_podcasts=True)
    with pytest.raises(ValueError, match="name"):
        create_empty_library(
            " ", replace(WriteTarget(), database_version=0x13), supports_podcasts=True
        )


@pytest.mark.parametrize("version", [0x13, 0x19, 0x30])
def test_first_track_can_be_added_to_initialized_library(version: int) -> None:
    target = WriteTarget(database_version=version)
    created = create_empty_library("iPod", target, supports_podcasts=True)
    assert created.prepared is not None
    source = IPodLibrary.parse(created.prepared.itunes)
    data = b"captured audio content"
    path = "iPod_Control/Music/F00/first.m4a"
    track = Track(
        -1,
        "First Track",
        "Artist",
        "Album",
        120000,
        size_bytes=len(data),
        bitrate_kbps=128,
        metadata=TrackMetadata(
            location=path, file_format="AAC audio file", sample_rate_hz=44100
        ),
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(replace(source.snapshot, tracks=(track,))), target
        ),
        WriteResources(
            media=(
                prepared_audio(
                    -1,
                    FileDependency(path, len(data), content_sha256(data)),
                    AudioEncoding.AAC,
                ),
            ),
            pending_playback_sidecars=False,
        ),
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.tracks[0].title == "First Track"
    assert (
        IPodLibrary.parse(result.prepared.itunes).snapshot == result.prepared.snapshot
    )
