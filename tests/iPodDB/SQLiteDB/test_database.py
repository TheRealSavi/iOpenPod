from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest
from tests.iPodDB.library.test_browse_relationships import browse_source

from iPodDB.iTunesDB.cdb import compress_iTunesCDB
from iPodDB.iTunesDB.shared.constants import FILE_EXTENSION_INT
from iPodDB.library import (
    AudioEncoding,
    FileDependency,
    IPodLibrary,
    IPodTrackDetails,
    LibrarySnapshot,
    MediaType,
    PreparedMedia,
    Track,
    TrackChapter,
    TrackMetadata,
    WriteResources,
    prepared_audio,
)
from iPodDB.library.playlists import Playlist, playlist_entries
from iPodDB.library.writing import WriteChecksum
from iPodDB.SQLiteDB.checksum import (
    build_locations_cbk,
    recover_hash72_cbk_material,
    verify_locations_cbk,
)
from iPodDB.SQLiteDB.database import build_sqlite_databases

if TYPE_CHECKING:
    from pathlib import Path


def _snapshot() -> LibrarySnapshot:
    track = Track(
        7,
        "Title",
        "Artist",
        "Album",
        12_345,
        genre="Genre",
        year=2020,
        track_number=2,
        size_bytes=123_456,
        bitrate_kbps=256,
        play_count=3,
        rating=80,
        metadata=TrackMetadata(
            file_format="m4a",
            date_added=1_700_000_000,
            sample_rate_hz=44_100,
            location=":iPod_Control:Music:F03:ABCD.m4a",
            lyrics="words",
            chapters=(TrackChapter("Opening", 0),),
        ),
        ipod=IPodTrackDetails(db_track_id=0xF123456789ABCDEF, app_rating=60),
    )
    return LibrarySnapshot(
        (track,),
        (Playlist(23, "Favorites", entries=playlist_entries((7,))),),
        "Test iPod",
    )


def _value(data: bytes, query: str) -> object:
    connection = sqlite3.connect(":memory:")
    connection.deserialize(data)
    result = connection.execute(query).fetchone()[0]
    connection.close()
    return result


def _rows(data: bytes, query: str) -> tuple[tuple[object, ...], ...]:
    connection = sqlite3.connect(":memory:")
    connection.deserialize(data)
    result = tuple(connection.execute(query))
    connection.close()
    return result


def test_builds_complete_sqlite_projection_from_cdb_snapshot() -> None:
    snapshot = _snapshot()
    databases = build_sqlite_databases(
        snapshot,
        database_id=42,
        checksum=WriteChecksum.NONE,
    )

    assert tuple(name for name, _data in databases.artifacts()) == (
        "Library.itdb",
        "Locations.itdb",
        "Dynamic.itdb",
        "Extras.itdb",
        "Genius.itdb",
        "Locations.itdb.cbk",
    )
    assert verify_locations_cbk(databases, WriteChecksum.NONE)
    assert _value(databases.library, "SELECT title FROM item") == "Title"
    assert _value(databases.library, "SELECT year FROM item") == 2020
    assert _value(databases.library, "SELECT name FROM container WHERE pid=23") == (
        "Favorites"
    )
    assert _value(databases.locations, "SELECT location FROM location") == (
        "F03/ABCD.m4a"
    )
    assert _value(databases.dynamic, "SELECT play_count_user FROM item_stats") == 3
    assert _value(databases.dynamic, "SELECT user_rating FROM item_stats") == 80
    chapter_size = _value(databases.extras, "SELECT length(data) FROM chapter")
    assert isinstance(chapter_size, int) and chapter_size > 0


@pytest.mark.parametrize("reverse", (False, True))
def test_album_browse_ranks_put_b_before_z_without_device_postprocessing(
    reverse: bool,
) -> None:
    base = _snapshot().tracks[0]
    tracks = tuple(
        replace(
            base,
            track_id=index,
            album=name,
            ipod=IPodTrackDetails(db_track_id=index, album_id=index),
        )
        for index, name in enumerate(("Zimbo Trio", "Blink 182"), start=1)
    )
    if reverse:
        tracks = tuple(reversed(tracks))
    databases = build_sqlite_databases(
        LibrarySnapshot(tracks), database_id=42, checksum=WriteChecksum.NONE
    )

    assert _rows(
        databases.library,
        "SELECT name,name_order,sort_order FROM album ORDER BY sort_order,pid",
    ) == (("Blink 182", 100, 100), ("Zimbo Trio", 200, 200))
    assert _rows(
        databases.library,
        "SELECT album,album_order FROM item ORDER BY album_order,pid",
    ) == (("Blink 182", 100), ("Zimbo Trio", 200))
    assert _rows(
        databases.library, "SELECT pid FROM item ORDER BY physical_order"
    ) == tuple((track.track_id,) for track in tracks)


def test_album_ranks_respect_sort_tags_articles_case_and_separate_artists() -> None:
    base = _snapshot().tracks[0]
    tracks = tuple(
        replace(
            base,
            track_id=index,
            album=name,
            artist=f"Artist {index}",
            metadata=replace(base.metadata, sort_album=sort_name),
            ipod=IPodTrackDetails(db_track_id=index, album_id=index),
        )
        for index, (name, sort_name) in enumerate(
            (
                ("Zimbo Trio", ""),
                ("The Blink Album", ""),
                ("blink album", ""),
                ("Zebra", "Alpha"),
                ("9", ""),
                ("", ""),
            ),
            start=1,
        )
    )
    databases = build_sqlite_databases(
        LibrarySnapshot(tracks), database_id=42, checksum=WriteChecksum.NONE
    )

    assert _rows(
        databases.library,
        "SELECT name,sort_name,name_order,sort_order FROM album ORDER BY pid",
    ) == (
        ("Zimbo Trio", "Zimbo Trio", 300, 300),
        ("The Blink Album", "Blink Album", 100, 200),
        ("blink album", "blink album", 100, 200),
        ("Zebra", "Alpha", 200, 100),
        ("9", "9", 400, 400),
        (None, None, 500, 500),
    )
    assert _rows(
        databases.library,
        "SELECT album,sort_album,album_order FROM item ORDER BY pid",
    ) == (
        ("Zimbo Trio", "Zimbo Trio", 300),
        ("The Blink Album", "Blink Album", 200),
        ("blink album", "blink album", 200),
        ("Zebra", "Alpha", 100),
        ("9", "9", 400),
        ("", None, 500),
    )


def test_device_postprocessing_can_replace_generated_album_ranks() -> None:
    databases = build_sqlite_databases(
        _snapshot(),
        database_id=42,
        checksum=WriteChecksum.NONE,
        postprocess_commands=(
            "UPDATE album SET name_order=700,sort_order=800;"
            "UPDATE item SET album_order=800;",
        ),
    )

    assert _rows(databases.library, "SELECT name_order,sort_order FROM album") == (
        (700, 800),
    )
    assert _value(databases.library, "SELECT album_order FROM item") == 800


@pytest.mark.parametrize(
    ("media_type", "native", "set_flags", "video_rows", "podcast_rows", "rental_rows"),
    (
        (MediaType.AUDIO_VIDEO, 0, set[str](), 0, 0, 0),
        (MediaType.AUDIO, 0x1, {"is_song"}, 0, 0, 0),
        (MediaType.VIDEO, 0x2, {"is_movie"}, 1, 0, 0),
        (MediaType.PODCAST, 0x4, {"is_podcast"}, 0, 1, 0),
        (
            MediaType.VIDEO_PODCAST,
            0x6,
            {"is_movie", "is_podcast"},
            1,
            1,
            0,
        ),
        (MediaType.AUDIOBOOK, 0x8, {"is_audio_book"}, 0, 0, 0),
        (MediaType.MUSIC_VIDEO, 0x20, {"is_music_video"}, 1, 0, 0),
        (MediaType.TV_SHOW, 0x40, {"is_tv_show"}, 1, 0, 0),
        (MediaType.RINGTONE, 0x4000, {"is_ringtone"}, 0, 0, 0),
        (MediaType.RENTAL, 0x8000, {"is_rental"}, 0, 0, 1),
        (MediaType.ITUNES_EXTRA, 0x10000, set[str](), 0, 0, 0),
        (MediaType.MEMO, 0x100000, {"is_voice_memo"}, 0, 0, 0),
        (MediaType.ITUNES_U, 0x200000, {"is_itunes_u"}, 0, 0, 0),
        (MediaType.EPUB_BOOK, 0x400000, {"is_book"}, 0, 0, 0),
        (
            MediaType.PDF_BOOK,
            0x800000,
            {"is_book", "is_digital_booklet"},
            0,
            0,
            0,
        ),
    ),
)
def test_semantic_media_types_encode_native_bitmasks_and_flags(
    media_type: MediaType,
    native: int,
    set_flags: set[str],
    video_rows: int,
    podcast_rows: int,
    rental_rows: int,
) -> None:
    track = replace(_snapshot().tracks[0], media_types=(media_type,), ipod=None)
    databases = build_sqlite_databases(
        LibrarySnapshot((track,)), database_id=42, checksum=WriteChecksum.NONE
    )
    flag_names = (
        "is_song",
        "is_audio_book",
        "is_music_video",
        "is_movie",
        "is_tv_show",
        "is_home_video",
        "is_ringtone",
        "is_tone",
        "is_voice_memo",
        "is_book",
        "is_rental",
        "is_itunes_u",
        "is_digital_booklet",
        "is_podcast",
    )
    row = _rows(
        databases.library,
        "SELECT media_kind," + ",".join(flag_names) + " FROM item",
    )[0]

    assert row[0] == native
    assert {name for name, value in zip(flag_names, row[1:], strict=True) if value} == (
        set_flags
    )
    assert _value(databases.library, "SELECT count(*) FROM video_info") == video_rows
    assert _value(databases.library, "SELECT count(*) FROM podcast_info") == (
        podcast_rows
    )
    assert _value(databases.dynamic, "SELECT count(*) FROM rental_info") == rental_rows


def test_checked_native_media_masks_retain_composites_and_drive_size_totals() -> None:
    base = _snapshot().tracks[0]
    details = base.ipod
    assert details is not None
    tracks = (
        replace(
            base,
            track_id=1,
            title="TV alternate",
            size_bytes=100,
            media_types=(MediaType.TV_SHOW,),
            ipod=replace(details, db_track_id=1, media_type_code=0x60),
        ),
        replace(
            base,
            track_id=2,
            title="Rental movie",
            size_bytes=200,
            media_types=(MediaType.VIDEO, MediaType.RENTAL),
            ipod=replace(details, db_track_id=2, media_type_code=0x8002),
        ),
        replace(
            base,
            track_id=3,
            title="Video podcast",
            size_bytes=300,
            media_types=(MediaType.VIDEO_PODCAST,),
            ipod=replace(details, db_track_id=3, media_type_code=0x6),
        ),
    )
    databases = build_sqlite_databases(
        LibrarySnapshot(tracks), database_id=42, checksum=WriteChecksum.NONE
    )

    assert _rows(
        databases.library,
        "SELECT title,media_kind,is_music_video,is_movie,is_tv_show,is_rental,"
        "is_podcast FROM item ORDER BY physical_order",
    ) == (
        ("TV alternate", 0x60, 1, 0, 1, 0, 0),
        ("Rental movie", 0x8002, 0, 1, 0, 1, 0),
        ("Video podcast", 0x6, 0, 1, 0, 0, 1),
    )
    assert _rows(
        databases.library, "SELECT kind,size FROM track_size_calc ORDER BY pid"
    ) == (("audio", 0), ("video", 600), ("music_video", 100))
    assert _value(databases.library, "SELECT count(*) FROM video_info") == 3
    assert _value(databases.library, "SELECT count(*) FROM podcast_info") == 1
    assert _value(databases.dynamic, "SELECT count(*) FROM rental_info") == 1


def test_sqlite_uses_checked_native_codec_facts_after_audio_preparation() -> None:
    source = browse_source()
    specifications = (
        (AudioEncoding.MP3, "MPEG audio file", "mp3"),
        (AudioEncoding.AAC, "AAC audio file", "m4a"),
        (AudioEncoding.ALAC, "Apple Lossless audio file", "m4a"),
        (AudioEncoding.WAV, "WAV audio file", "wav"),
        (AudioEncoding.AIFF, "AIFF audio file", "aiff"),
    )
    tracks: list[Track] = []
    media: list[PreparedMedia] = []
    for index, (encoding, label, extension) in enumerate(specifications, start=1):
        payload = f"codec-{encoding.value}".encode()
        location = f"iPod_Control/Music/F00/codec-{index}.{extension}"
        track = Track(
            -index,
            f"Codec {encoding.value}",
            "Artist",
            "Album",
            1_000,
            size_bytes=len(payload),
            bitrate_kbps=256,
            metadata=TrackMetadata(
                file_format=label,
                sample_rate_hz=44_100,
                location=location,
            ),
        )
        tracks.append(track)
        media.append(
            prepared_audio(
                track.track_id,
                FileDependency(
                    location, len(payload), hashlib.sha256(payload).hexdigest()
                ),
                encoding,
            )
        )
    desired = replace(source.snapshot, tracks=(*source.snapshot.tracks, *tracks))
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(media=tuple(media), pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    checked = IPodLibrary(compress_iTunesCDB(result.prepared.itunes)).snapshot
    databases = build_sqlite_databases(
        checked, database_id=42, checksum=WriteChecksum.NONE
    )
    locations = {
        pid: (extension, kind_id)
        for pid, extension, kind_id in _rows(
            databases.locations,
            "SELECT item_pid,extension,kind_id FROM location",
        )
    }
    actual = {
        title: (audio_format, *locations[pid])
        for pid, title, audio_format in _rows(
            databases.library,
            "SELECT item.pid,item.title,avformat_info.audio_format FROM item "
            "JOIN avformat_info ON item.pid=avformat_info.item_pid "
            "WHERE item.title LIKE 'Codec %' ORDER BY item.title",
        )
    }

    assert actual == {
        "Codec mp3": (301, FILE_EXTENSION_INT["mp3"], 1),
        "Codec aac": (502, FILE_EXTENSION_INT["m4a"], 3),
        "Codec alac": (503, FILE_EXTENSION_INT["m4a"], 3),
        "Codec wav": (110, FILE_EXTENSION_INT["wav"], 1),
        "Codec aiff": (111, FILE_EXTENSION_INT["aiff"], 1),
    }


def test_purchased_aac_kind_uses_native_flag_not_filetype_label() -> None:
    track = _snapshot().tracks[0]
    details = track.ipod
    assert details is not None
    track = replace(
        track,
        metadata=replace(track.metadata, file_format="A presentation label"),
        ipod=replace(
            details,
            filetype_code=FILE_EXTENSION_INT["m4a"],
            mpeg_audio_type=51,
            purchased_aac_flag=1,
        ),
    )
    databases = build_sqlite_databases(
        LibrarySnapshot((track,)), database_id=42, checksum=WriteChecksum.NONE
    )

    library_row = _rows(
        databases.library,
        "SELECT item_pid,audio_format FROM avformat_info",
    )[0]
    location_row = _rows(
        databases.locations, "SELECT item_pid,extension,kind_id FROM location"
    )[0]
    assert library_row[0] == location_row[0]
    assert (library_row[1], *location_row[1:]) == (
        502,
        FILE_EXTENSION_INT["m4a"],
        2,
    )


def test_sqlite_uses_native_volume_and_sound_check_units() -> None:
    base = replace(_snapshot().tracks[0], ipod=None)
    values = (
        ("negative", -50.0, None, -128, 0),
        ("zero", 0.0, 0.0, 0, 1_000),
        ("attenuated", 50.0, -10.0, 128, 10_000),
        ("amplified", 25.0, 10.0, 64, 100),
    )
    tracks = tuple(
        replace(
            base,
            track_id=index,
            title=title,
            metadata=replace(
                base.metadata,
                volume_adjustment_percent=volume,
                normalization_gain_db=gain,
            ),
        )
        for index, (title, volume, gain, _native_volume, _energy) in enumerate(
            values, start=1
        )
    )
    databases = build_sqlite_databases(
        LibrarySnapshot(tracks), database_id=42, checksum=WriteChecksum.NONE
    )

    assert _rows(
        databases.library,
        "SELECT item.title,item.relative_volume,"
        "avformat_info.volume_normalization_energy FROM item JOIN avformat_info "
        "ON item.pid=avformat_info.item_pid ORDER BY item.physical_order",
    ) == tuple(
        (title, native_volume, energy) for title, _, _, native_volume, energy in values
    )


def test_hashab_checksum_book_is_device_bound() -> None:
    guid = bytes.fromhex("f832c65917da6785")
    databases = build_sqlite_databases(
        _snapshot(),
        database_id=42,
        checksum=WriteChecksum.HASHAB,
        firewire_guid=guid,
    )

    assert verify_locations_cbk(databases, WriteChecksum.HASHAB, guid)
    assert not verify_locations_cbk(databases, WriteChecksum.HASHAB, bytes(8))


def test_hash72_material_can_be_recovered_from_a_valid_retained_checksum_book() -> None:
    locations = b"retained Locations database"
    iv = bytes(range(16))
    random_part = bytes(range(20, 32))
    cbk = build_locations_cbk(
        locations, WriteChecksum.HASH72, iv=iv, random_part=random_part
    )

    assert recover_hash72_cbk_material(locations, cbk) == (iv, random_part)
    with pytest.raises(ValueError, match="checksum book"):
        recover_hash72_cbk_material(locations + b"changed", cbk)


def test_duplicate_native_artist_references_get_distinct_projection_ids() -> None:
    snapshot = _snapshot()
    first = snapshot.tracks[0]
    details = first.ipod
    assert details is not None
    first = replace(
        first,
        album_artist="First Artist",
        ipod=replace(details, artist_id_ref=17),
    )
    details = first.ipod
    assert details is not None
    second = replace(
        first,
        track_id=8,
        title="Other Title",
        artist="Other Artist",
        album="Other Album",
        album_artist="Other Artist",
        ipod=replace(details, db_track_id=0xE123456789ABCDEF),
    )

    databases = build_sqlite_databases(
        replace(snapshot, tracks=(first, second)),
        database_id=42,
        checksum=WriteChecksum.NONE,
    )

    assert _value(databases.library, "SELECT count(DISTINCT pid) FROM artist") == 2


def test_genre_and_category_ids_are_stable_across_hash_seeds() -> None:
    script = """
import json
import sqlite3
from iPodDB.library import LibrarySnapshot, Track, TrackMetadata
from iPodDB.library.writing import WriteChecksum
from iPodDB.SQLiteDB.database import build_sqlite_databases

names = ("Rock", "rock", "ROCK", "Straße", "STRASSE")
tracks = tuple(
    Track(
        index,
        name,
        "Artist",
        "Album",
        1,
        genre=name,
        metadata=TrackMetadata(
            category=name,
            location=f"iPod_Control/Music/F00/{index}.mp3",
        ),
    )
    for index, name in enumerate(names, start=1)
)
databases = build_sqlite_databases(
    LibrarySnapshot(tracks), database_id=42, checksum=WriteChecksum.NONE
)
connection = sqlite3.connect(":memory:")
connection.deserialize(databases.library)
rows = (
    tuple(connection.execute("SELECT id,genre FROM genre_map ORDER BY id")),
    tuple(connection.execute("SELECT id,category FROM category_map ORDER BY id")),
)
print(json.dumps(rows, ensure_ascii=False))
"""
    outputs: list[list[list[list[int | str]]]] = []
    for seed in ("1", "7", "101"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        outputs.append(cast("list[list[list[int | str]]]", json.loads(result.stdout)))

    assert outputs[0] == outputs[1] == outputs[2]
    assert outputs[0][0] == [
        [1, "ROCK"],
        [2, "Rock"],
        [3, "rock"],
        [4, "STRASSE"],
        [5, "Straße"],
    ]


def test_album_grouping_computes_each_track_key_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iPodDB.SQLiteDB import database as database_module

    original = database_module._album_key  # pyright: ignore[reportPrivateUsage]
    calls = 0

    def counted(track: Track) -> tuple[str, str, str]:
        nonlocal calls
        calls += 1
        return original(track)

    monkeypatch.setattr(database_module, "_album_key", counted)
    base = replace(_snapshot().tracks[0], ipod=None)
    tracks = tuple(
        replace(base, track_id=index, title=f"Track {index}", album=f"Album {index}")
        for index in range(1, 41)
    )
    databases = database_module.build_sqlite_databases(
        LibrarySnapshot(tracks), database_id=42, checksum=WriteChecksum.NONE
    )

    assert calls == len(tracks)
    assert _value(databases.library, "SELECT count(*) FROM album") == len(tracks)


def test_device_postprocess_commands_can_update_all_attached_databases() -> None:
    databases = build_sqlite_databases(
        _snapshot(),
        database_id=42,
        checksum=WriteChecksum.NONE,
        postprocess_commands=(
            "UPDATE item SET sort_title = hex(iPhoneSortKey(title))",
            'UPDATE "Locations.itdb".location SET kind_id = 9',
        ),
    )

    assert _value(databases.library, "SELECT sort_title FROM item")
    assert _value(databases.locations, "SELECT kind_id FROM location") == 9
    assert verify_locations_cbk(databases, WriteChecksum.NONE)


def test_one_postprocess_command_may_contain_multiple_statements() -> None:
    databases = build_sqlite_databases(
        _snapshot(),
        database_id=42,
        checksum=WriteChecksum.NONE,
        postprocess_commands=(
            "UPDATE item SET sort_title = 'first';"
            "UPDATE item SET sort_album = 'second';",
        ),
    )

    assert _rows(databases.library, "SELECT sort_title,sort_album FROM item") == (
        ("first", "second"),
    )


def test_device_postprocess_commands_cannot_attach_a_host_path(tmp_path: Path) -> None:
    target = tmp_path / "escaped.sqlite"

    with pytest.raises(ValueError, match="postprocessing failed"):
        build_sqlite_databases(
            _snapshot(),
            database_id=42,
            checksum=WriteChecksum.NONE,
            postprocess_commands=(f"ATTACH DATABASE '{target}' AS escaped",),
        )

    assert not target.exists()
