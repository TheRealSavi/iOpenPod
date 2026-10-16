"""Firmware rows captured from Original iOpenPod using synthetic inputs."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iPodDB.SQLiteDB.test_database import (
    _rows,  # pyright: ignore[reportPrivateUsage]
)

from iPodDB.iTunesDB.shared.constants import FILE_EXTENSION_INT
from iPodDB.library import IPodTrackDetails, LibrarySnapshot, Track, TrackMetadata
from iPodDB.library.playlists import (
    Playlist,
    PlaylistKind,
    SmartPlaylist,
    playlist_entries,
)
from iPodDB.library.writing import WriteChecksum
from iPodDB.SQLiteDB.database import build_sqlite_databases

_REFERENCE = json.loads(
    (
        Path(__file__).parents[2] / "fixtures/SQLiteDB/original-row-compatibility.json"
    ).read_text(encoding="utf-8")
)


def _snapshot(*, native_ids: bool = True) -> LibrarySnapshot:
    names = (
        ("Artist", "Album", "Album Artist", "Composer"),
        ("Another Singer", "Album", "Album Artist", "Composer"),
        ("", "", "", ""),
        ("Artist", "Another", "", "Other Composer"),
        ("artist", "album", "Album Artist", "composer"),
        (" Artist ", " Album ", " Album Artist ", "Composer"),
        (" ", " ", " ", ""),
    )
    tracks = tuple(
        Track(
            index,
            f"Track {index}",
            artist,
            album,
            1000,
            album_artist=album_artist,
            metadata=TrackMetadata(
                composer=composer,
                location=f"iPod_Control/Music/F00/T00{index}.m4a",
                date_added=1_700_000_000,
                release_date=1_699_999_990,
            ),
            ipod=IPodTrackDetails(
                db_track_id=1000 + index,
                filetype_code=FILE_EXTENSION_INT["m4a"],
                mpeg_audio_type=51,
                purchased_aac_flag=1,
                date_added_to_itunes=1_699_999_980,
                store_track_id=2000 + index,
                album_id=9000 + index if native_ids else 0,
                artist_id_ref=9100 + index if native_ids else 0,
                composer_id=9200 + index if native_ids else 0,
            ),
        )
        for index, (artist, album, album_artist, composer) in enumerate(names, 1)
    )
    return LibrarySnapshot(
        tracks,
        (Playlist(23, "Playlist", entries=playlist_entries((1, 2))),),
    )


@pytest.mark.parametrize("native_ids", (False, True))
@pytest.mark.parametrize(
    "table", ("item", "album", "artist", "track_artist", "composer")
)
def test_browse_ids_and_missing_references_match_original_rows(
    native_ids: bool, table: str
) -> None:
    data = build_sqlite_databases(
        _snapshot(native_ids=native_ids), database_id=42, checksum=WriteChecksum.NONE
    ).library

    assert [list(row) for row in _rows(data, _REFERENCE["queries"][table])] == (
        _REFERENCE["rows"][table]
    )


def test_store_dates_do_not_create_incomplete_store_rows() -> None:
    data = build_sqlite_databases(
        _snapshot(), database_id=42, checksum=WriteChecksum.NONE
    ).library

    assert (
        list(_rows(data, _REFERENCE["queries"]["store_info"]))
        == (_REFERENCE["rows"]["store_info"])
    )
    assert _rows(data, "SELECT DISTINCT date_released FROM item") == ((721692790,),)


def test_ordinary_container_checked_flags_match_original_rows() -> None:
    data = build_sqlite_databases(
        _snapshot(), database_id=42, checksum=WriteChecksum.NONE
    ).library

    assert [
        list(row) for row in _rows(data, _REFERENCE["queries"]["container"])
    ] == _REFERENCE["rows"]["container"]


def test_checked_only_smart_playlist_retains_its_explicit_flag() -> None:
    snapshot = _snapshot()
    smart = Playlist(
        24,
        "Checked Smart",
        kind=PlaylistKind.SMART,
        smart=SmartPlaylist(checked_only=True),
    )
    data = build_sqlite_databases(
        replace(snapshot, playlists=(*snapshot.playlists, smart)),
        database_id=42,
        checksum=WriteChecksum.NONE,
    ).library

    assert _rows(
        data, "SELECT smart_enabled_only FROM container WHERE name='Checked Smart'"
    ) == ((1,),)


def test_location_kinds_match_original_without_discarding_codec_evidence() -> None:
    codecs = (
        ("m4a", 51, 1),
        ("m4a", 51, 0),
        ("m4a", 0, 0),
        ("m4p", 51, 0),
        ("m4b", 51, 1),
        ("mp3", 12, 1),
    )
    tracks = tuple(
        Track(
            index,
            f"Codec {index}",
            "",
            "",
            1000,
            metadata=TrackMetadata(
                location=f"iPod_Control/Music/F00/C00{index}.{extension}",
                date_added=1_700_000_000,
            ),
            ipod=IPodTrackDetails(
                db_track_id=2000 + index,
                filetype_code=FILE_EXTENSION_INT[extension],
                mpeg_audio_type=mpeg,
                purchased_aac_flag=purchased,
            ),
        )
        for index, (extension, mpeg, purchased) in enumerate(codecs, 1)
    )
    data = build_sqlite_databases(
        LibrarySnapshot(tracks), database_id=42, checksum=WriteChecksum.NONE
    )

    assert [
        list(row)
        for row in _rows(
            data.locations,
            "SELECT item_pid,extension,kind_id FROM location ORDER BY item_pid",
        )
    ] == _REFERENCE["rows"]["location"]
    assert _rows(
        data.library, "SELECT audio_format FROM avformat_info ORDER BY item_pid"
    ) == ((502,), (502,), (503,), (502,), (502,), (301,))
