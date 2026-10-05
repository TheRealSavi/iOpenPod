"""SQLite iPod database generation without filesystem access.

Late iPod nano firmware reads five SQLite databases plus a checksum book.  The
binary iTunesCDB remains the sole readable editing authority; these databases
are a disposable, firmware-facing projection of the checked CDB generation.
"""

from __future__ import annotations

import hashlib
import sqlite3
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from iPodDB.device_time import unix_to_core_data
from iPodDB.iTunesDB.shared.constants import (
    FILE_EXTENSION_INT,
    MEDIA_TYPE_AUDIO,
    MEDIA_TYPE_AUDIOBOOK,
    MEDIA_TYPE_EPUB_BOOK,
    MEDIA_TYPE_ITUNES_U,
    MEDIA_TYPE_MEMO,
    MEDIA_TYPE_MUSIC_VIDEO,
    MEDIA_TYPE_PDF_BOOK,
    MEDIA_TYPE_PODCAST,
    MEDIA_TYPE_RENTAL,
    MEDIA_TYPE_RINGTONE,
    MEDIA_TYPE_TV_SHOW,
    MEDIA_TYPE_VIDEO,
    MEDIA_TYPE_VIDEO_MASK,
)
from iPodDB.library._native_values import (
    encode_media_types,
    normalization_gain_to_native,
    volume_adjustment_to_native,
)
from iPodDB.library.models import (
    ContentAdvisory,
    LibrarySnapshot,
    Track,
    TrackChapter,
)
from iPodDB.library.playlists import PlaylistKind, SmartPlaylist
from iPodDB.SQLiteDB.artifacts import SQLiteDatabaseSet
from iPodDB.SQLiteDB.checksum import build_locations_cbk, verify_locations_cbk

if TYPE_CHECKING:
    from collections.abc import Mapping

    from iPodDB.library.writing import WriteChecksum


type _AlbumKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class _NativeFileFacts:
    extension: int
    audio_format: int
    kind_id: int


def _open(data: bytes) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.deserialize(data)
        result = connection.execute("PRAGMA quick_check").fetchone()
        if result is None or result[0] != "ok":
            raise sqlite3.DatabaseError("SQLite quick_check failed")
    except (sqlite3.DatabaseError, OverflowError) as error:
        connection.close()
        raise ValueError("Invalid SQLite iPod database") from error
    return connection


def _new(schema: str) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA encoding='UTF-8'")
    connection.executescript(schema)
    return connection


def _serialize(connection: sqlite3.Connection) -> bytes:
    connection.commit()
    result = connection.serialize()
    connection.close()
    return result


def _s64(value: int) -> int:
    return value - (1 << 64) if value >= (1 << 63) else value


def _core_data(value: int) -> int:
    return unix_to_core_data(value)


def _track_pid(track: Track) -> int:
    details = track.ipod
    return int(
        details.db_track_id
        if details is not None and details.db_track_id
        else track.track_id
    )


def _stable_pid(kind: str, *parts: str) -> int:
    payload = "\x1f".join((kind, *parts)).encode("utf-8")
    return int.from_bytes(hashlib.sha1(payload).digest()[:8], "little") or 1


def _allocate_pids(
    kind: str,
    candidates: tuple[tuple[tuple[str, ...], int], ...],
) -> tuple[int, ...]:
    """Retain unique native IDs and deterministically replace collisions."""

    native_counts: dict[int, int] = {}
    for _parts, native in candidates:
        if native:
            native_counts[native] = native_counts.get(native, 0) + 1
    used: set[int] = set()
    result: list[int] = []
    for parts, native in candidates:
        candidate = (
            native
            if native and native_counts[native] == 1
            else _stable_pid(kind, *parts)
        )
        salt = 0
        while candidate in used:
            salt += 1
            candidate = _stable_pid(kind, *parts, str(salt))
        used.add(candidate)
        result.append(candidate)
    return tuple(result)


def _album_key(track: Track) -> _AlbumKey:
    return (track.album, track.album_artist or track.artist, track.show)


def _group_tracks_by_album(
    tracks: tuple[Track, ...],
) -> dict[_AlbumKey, tuple[Track, ...]]:
    """Group Tracks in snapshot order while computing each album key once."""

    grouped: dict[_AlbumKey, list[Track]] = {}
    for track in tracks:
        grouped.setdefault(_album_key(track), []).append(track)
    return {key: tuple(members) for key, members in grouped.items()}


def _album_name_for_sorting(name: str) -> str:
    """Supply the Original iOpenPod fallback when no Sort Album tag exists."""

    for article in ("the ", "an ", "a "):
        if name.casefold().startswith(article):
            return name[len(article) :]
    return name


def _album_name_ranks(names: set[str]) -> dict[str, int]:
    """Assign firmware ranks, shared by equivalent names, in steps of 100.

    The captured Nano 7 Library orders numeric names after letters and unknown
    albums last. This deterministic fallback does not claim locale collation;
    device postprocessing can replace it when commands are available.
    """

    keys = sorted(
        {name.casefold() for name in names},
        key=lambda name: (2 if not name else int(name[0].isdigit()), name),
    )
    ranks = {name: (index + 1) * 100 for index, name in enumerate(keys)}
    return {name: ranks[name.casefold()] for name in names}


def _media_kind(track: Track) -> int:
    details = track.ipod
    if details is not None:
        return details.media_type_code
    return encode_media_types(track.media_types)


def _media_flags(media_kind: int) -> tuple[int, ...]:
    """Project every schema flag independently from the native media bitmask."""

    return (
        int(bool(media_kind & MEDIA_TYPE_AUDIO)),
        int(bool(media_kind & MEDIA_TYPE_AUDIOBOOK)),
        int(bool(media_kind & MEDIA_TYPE_MUSIC_VIDEO)),
        int(bool(media_kind & MEDIA_TYPE_VIDEO)),
        int(bool(media_kind & MEDIA_TYPE_TV_SHOW)),
        0,  # No evidenced semantic flag for is_home_video.
        int(bool(media_kind & MEDIA_TYPE_RINGTONE)),
        0,  # Ringtone is represented separately from the unevidenced is_tone flag.
        int(bool(media_kind & MEDIA_TYPE_MEMO)),
        int(bool(media_kind & (MEDIA_TYPE_EPUB_BOOK | MEDIA_TYPE_PDF_BOOK))),
        int(bool(media_kind & MEDIA_TYPE_RENTAL)),
        int(bool(media_kind & MEDIA_TYPE_ITUNES_U)),
        int(bool(media_kind & MEDIA_TYPE_PDF_BOOK)),
        int(bool(media_kind & MEDIA_TYPE_PODCAST)),
    )


def _stable_text_ids(values: set[str]) -> dict[str, int]:
    """Assign distinct semantic strings stable IDs using a total sort key."""

    return {
        value: index + 1
        for index, value in enumerate(
            sorted(values, key=lambda value: (value.casefold(), value))
        )
    }


def _content_rating(advisory: ContentAdvisory) -> int:
    return {
        ContentAdvisory.UNSPECIFIED: 0,
        ContentAdvisory.EXPLICIT: 1,
        ContentAdvisory.CLEAN: 2,
    }[advisory]


def _file_location(location: str) -> str:
    parts = location.strip(":/").replace("\\", "/").replace(":", "/").split("/")
    if len(parts) >= 4 and parts[:2] == ["iPod_Control", "Music"]:
        return "/".join(parts[2:])
    return "/".join(parts[-2:]) if len(parts) >= 2 else "/".join(parts)


_LIBRARY_SCHEMA = """
CREATE TABLE version_info (id INTEGER PRIMARY KEY, major INTEGER, minor INTEGER,
 compatibility INTEGER DEFAULT 0, update_level INTEGER DEFAULT 0,
 device_update_level INTEGER DEFAULT 0, platform INTEGER DEFAULT 0);
CREATE TABLE db_info (pid INTEGER PRIMARY KEY, primary_container_pid INTEGER,
 media_folder_url TEXT, audio_language INTEGER, subtitle_language INTEGER,
 genius_cuid TEXT, bib BLOB, rib BLOB);
CREATE TABLE genre_map (id INTEGER PRIMARY KEY, genre TEXT UNIQUE, genre_order INTEGER,
 is_unknown INTEGER DEFAULT 0, has_music INTEGER DEFAULT 0,
 artist_count_calc INTEGER DEFAULT 0, album_count_calc INTEGER DEFAULT 0,
 compilation_count_calc INTEGER DEFAULT 0);
CREATE TABLE location_kind_map (id INTEGER PRIMARY KEY, kind TEXT UNIQUE);
CREATE TABLE category_map (id INTEGER PRIMARY KEY, category TEXT UNIQUE);
CREATE TABLE item (pid INTEGER PRIMARY KEY, revision_level INTEGER,
 media_kind INTEGER DEFAULT 0, is_song INTEGER DEFAULT 0,
 is_audio_book INTEGER DEFAULT 0, is_music_video INTEGER DEFAULT 0,
 is_movie INTEGER DEFAULT 0, is_tv_show INTEGER DEFAULT 0,
 is_home_video INTEGER DEFAULT 0, is_ringtone INTEGER DEFAULT 0,
 is_tone INTEGER DEFAULT 0, is_voice_memo INTEGER DEFAULT 0,
 is_book INTEGER DEFAULT 0, is_rental INTEGER DEFAULT 0,
 is_itunes_u INTEGER DEFAULT 0, is_digital_booklet INTEGER DEFAULT 0,
 is_podcast INTEGER DEFAULT 0, date_modified INTEGER DEFAULT 0,
 year INTEGER DEFAULT 0, content_rating INTEGER DEFAULT 0,
 content_rating_level INTEGER DEFAULT 0, is_compilation INTEGER,
 is_user_disabled INTEGER DEFAULT 0, remember_bookmark INTEGER DEFAULT 0,
 exclude_from_shuffle INTEGER DEFAULT 0, part_of_gapless_album INTEGER DEFAULT 0,
 chosen_by_auto_fill INTEGER DEFAULT 0, artwork_status INTEGER,
 artwork_cache_id INTEGER DEFAULT 0, start_time_ms REAL DEFAULT 0,
 stop_time_ms REAL DEFAULT 0, total_time_ms REAL DEFAULT 0,
 total_burn_time_ms REAL, track_number INTEGER DEFAULT 0,
 track_count INTEGER DEFAULT 0, disc_number INTEGER DEFAULT 0,
 disc_count INTEGER DEFAULT 0, bpm INTEGER DEFAULT 0, relative_volume INTEGER,
 eq_preset TEXT, radio_stream_status TEXT, genius_id INTEGER DEFAULT 0,
 genre_id INTEGER DEFAULT 0, category_id INTEGER DEFAULT 0,
 album_pid INTEGER DEFAULT 0, artist_pid INTEGER DEFAULT 0,
 composer_pid INTEGER DEFAULT 0, title TEXT, artist TEXT, album TEXT,
 album_artist TEXT, composer TEXT, sort_title TEXT, sort_artist TEXT,
 sort_album TEXT, sort_album_artist TEXT, sort_composer TEXT,
 title_order INTEGER, artist_order INTEGER, album_order INTEGER,
 genre_order INTEGER, composer_order INTEGER, album_artist_order INTEGER,
 album_by_artist_order INTEGER, series_name_order INTEGER, comment TEXT,
 grouping TEXT, description TEXT, description_long TEXT,
 collection_description TEXT, copyright TEXT, track_artist_pid INTEGER DEFAULT 0,
 physical_order INTEGER, has_lyrics INTEGER DEFAULT 0,
 date_released INTEGER DEFAULT 0);
CREATE TABLE album (pid INTEGER PRIMARY KEY, kind INTEGER, artwork_status INTEGER,
 artwork_item_pid INTEGER, artist_pid INTEGER, user_rating INTEGER, name TEXT,
 name_order INTEGER, all_compilations INTEGER, feed_url TEXT, season_number INTEGER,
 is_unknown INTEGER DEFAULT 0, has_songs INTEGER DEFAULT 0,
 has_music_videos INTEGER DEFAULT 0, sort_order INTEGER DEFAULT 0,
 artist_order INTEGER DEFAULT 0, has_any_compilations INTEGER DEFAULT 0,
 sort_name TEXT, artist_count_calc INTEGER DEFAULT 0, has_movies INTEGER DEFAULT 0,
 item_count INTEGER DEFAULT 0);
CREATE TABLE artist (pid INTEGER PRIMARY KEY, kind INTEGER, artwork_status INTEGER,
 artwork_album_pid INTEGER, name TEXT, name_order INTEGER, sort_name TEXT,
 is_unknown INTEGER DEFAULT 0, has_songs INTEGER DEFAULT 0,
 has_music_videos INTEGER DEFAULT 0);
CREATE TABLE track_artist (pid INTEGER PRIMARY KEY, name TEXT, name_order INTEGER,
 sort_name TEXT, has_songs INTEGER DEFAULT 0, has_music_videos INTEGER DEFAULT 0,
 has_non_compilation_tracks INTEGER DEFAULT 0, is_unknown INTEGER DEFAULT 0,
 album_count INTEGER DEFAULT 0);
CREATE TABLE composer (pid INTEGER PRIMARY KEY, name TEXT, name_order INTEGER,
 sort_name TEXT, is_unknown INTEGER DEFAULT 0, has_music INTEGER DEFAULT 0);
CREATE TABLE avformat_info (item_pid INTEGER NOT NULL, sub_id INTEGER NOT NULL DEFAULT 0,
 audio_format INTEGER, bit_rate INTEGER DEFAULT 0, channels INTEGER DEFAULT 0,
 sample_rate REAL DEFAULT 0, duration INTEGER, gapless_heuristic_info INTEGER,
 gapless_encoding_delay INTEGER, gapless_encoding_drain INTEGER,
 gapless_last_frame_resynch INTEGER, analysis_inhibit_flags INTEGER,
 audio_fingerprint INTEGER, volume_normalization_energy INTEGER,
 PRIMARY KEY (item_pid, sub_id));
CREATE TABLE container (pid INTEGER PRIMARY KEY, distinguished_kind INTEGER,
 date_created INTEGER, date_modified INTEGER, name TEXT, name_order INTEGER,
 parent_pid INTEGER, media_kinds INTEGER, workout_template_id INTEGER,
 is_hidden INTEGER, smart_is_folder INTEGER, smart_is_dynamic INTEGER,
 smart_is_filtered INTEGER, smart_is_genius INTEGER, smart_enabled_only INTEGER,
 smart_is_limited INTEGER, smart_limit_kind INTEGER, smart_limit_order INTEGER,
 smart_evaluation_order INTEGER, smart_limit_value INTEGER,
 smart_reverse_limit_order INTEGER, smart_criteria BLOB, description TEXT);
CREATE TABLE item_to_container (item_pid INTEGER, container_pid INTEGER,
 physical_order INTEGER, shuffle_order INTEGER);
CREATE TABLE container_seed (container_pid INTEGER NOT NULL, item_pid INTEGER NOT NULL,
 seed_order INTEGER DEFAULT 0, UNIQUE (container_pid, item_pid));
CREATE TABLE video_info (item_pid INTEGER PRIMARY KEY, has_alternate_audio INTEGER,
 has_subtitles INTEGER, characteristics_valid INTEGER, has_closed_captions INTEGER,
 is_self_contained INTEGER, is_compressed INTEGER, is_anamorphic INTEGER,
 is_hd INTEGER, season_number INTEGER, audio_language INTEGER,
 audio_track_index INTEGER, audio_track_id INTEGER, subtitle_language INTEGER,
 subtitle_track_index INTEGER, subtitle_track_id INTEGER, series_name TEXT,
 sort_series_name TEXT, episode_id TEXT, episode_sort_id INTEGER,
 network_name TEXT, extended_content_rating TEXT, movie_info TEXT);
CREATE TABLE video_characteristics (item_pid INTEGER, sub_id INTEGER DEFAULT 0,
 track_id INTEGER, height INTEGER, width INTEGER, depth INTEGER, codec INTEGER,
 frame_rate REAL, percentage_encrypted REAL, bit_rate INTEGER,
 peak_bit_rate INTEGER, buffer_size INTEGER, profile INTEGER, level INTEGER,
 complexity_level INTEGER, UNIQUE (item_pid, sub_id, track_id));
CREATE TABLE podcast_info (item_pid INTEGER PRIMARY KEY, date_released INTEGER DEFAULT 0,
 external_guid TEXT, feed_url TEXT, feed_keywords TEXT);
CREATE TABLE store_info (item_pid INTEGER PRIMARY KEY, store_kind INTEGER,
 date_purchased INTEGER DEFAULT 0, date_released INTEGER DEFAULT 0,
 account_id INTEGER, key_versions INTEGER, key_platform_id INTEGER, key_id INTEGER,
 key_id2 INTEGER, store_item_id INTEGER, artist_id INTEGER, composer_id INTEGER,
 genre_id INTEGER, playlist_id INTEGER, storefront_id INTEGER,
 store_link_id INTEGER, relevance REAL, popularity REAL, xid TEXT, flavor TEXT);
CREATE TABLE store_link (id INTEGER PRIMARY KEY, url TEXT);
CREATE TABLE track_size_calc (pid INTEGER PRIMARY KEY, kind TEXT UNIQUE, size INTEGER);
CREATE INDEX idx_item_album_pid ON item (album_pid);
CREATE INDEX idx_item_track_artist_pid ON item (track_artist_pid);
CREATE INDEX item_to_container_container_pid_idx
 ON item_to_container (container_pid, physical_order, item_pid);
"""

_LOCATIONS_SCHEMA = """
CREATE TABLE base_location (id INTEGER PRIMARY KEY, path TEXT);
CREATE TABLE location (item_pid INTEGER NOT NULL, sub_id INTEGER NOT NULL DEFAULT 0,
 base_location_id INTEGER DEFAULT 0, location_type INTEGER, location TEXT,
 extension INTEGER, kind_id INTEGER DEFAULT 0, date_created INTEGER DEFAULT 0,
 file_size INTEGER DEFAULT 0, file_creator INTEGER, file_type INTEGER,
 num_dir_levels_file INTEGER, num_dir_levels_lib INTEGER,
 PRIMARY KEY (item_pid, sub_id));
"""

_DYNAMIC_SCHEMA = """
CREATE TABLE item_stats (item_pid INTEGER PRIMARY KEY, has_been_played INTEGER DEFAULT 0,
 date_played INTEGER DEFAULT 0, play_count_user INTEGER DEFAULT 0,
 play_count_recent INTEGER DEFAULT 0, date_skipped INTEGER DEFAULT 0,
 skip_count_user INTEGER DEFAULT 0, skip_count_recent INTEGER DEFAULT 0,
 bookmark_time_ms REAL, bookmark_time_ms_common REAL, user_rating INTEGER DEFAULT 0,
 user_rating_common INTEGER DEFAULT 0, rental_expired INTEGER DEFAULT 0,
 play_count_user_original INTEGER DEFAULT 0, skip_count_user_original INTEGER DEFAULT 0,
 genius_id INTEGER DEFAULT 0);
CREATE TABLE container_ui (container_pid INTEGER PRIMARY KEY, play_order INTEGER DEFAULT 0,
 is_reversed INTEGER DEFAULT 0, album_field_order INTEGER DEFAULT 0,
 repeat_mode INTEGER DEFAULT 0, shuffle_items INTEGER DEFAULT 0,
 has_been_shuffled INTEGER DEFAULT 0);
CREATE TABLE rental_info (item_pid INTEGER PRIMARY KEY,
 rental_date_started INTEGER DEFAULT 0, rental_duration INTEGER DEFAULT 0,
 rental_playback_date_started INTEGER DEFAULT 0,
 rental_playback_duration INTEGER DEFAULT 0, is_demo INTEGER DEFAULT 0);
"""

_EXTRAS_SCHEMA = """
CREATE TABLE chapter (item_pid INTEGER PRIMARY KEY, data BLOB);
CREATE TABLE lyrics (item_pid INTEGER PRIMARY KEY, checksum INTEGER, lyrics TEXT);
"""

_GENIUS_SCHEMA = """
CREATE TABLE genius_config (id INTEGER PRIMARY KEY, version INTEGER UNIQUE,
 default_num_results INTEGER DEFAULT 0, min_num_results INTEGER DEFAULT 0, data BLOB);
CREATE TABLE genius_metadata (genius_id INTEGER PRIMARY KEY, version INTEGER, data BLOB);
CREATE TABLE genius_similarities (genius_id INTEGER PRIMARY KEY, version INTEGER, data BLOB);
"""


def build_sqlite_databases(
    snapshot: LibrarySnapshot,
    *,
    database_id: int,
    checksum: WriteChecksum,
    firewire_guid: bytes = b"",
    hash72_iv: bytes = b"",
    hash72_random: bytes = b"",
    postprocess_commands: tuple[str, ...] = (),
    smart_criteria: Mapping[int, bytes] | None = None,
) -> SQLiteDatabaseSet:
    """Project a verified Library Snapshot into all firmware SQLite artifacts."""

    library = _new(_LIBRARY_SCHEMA)
    locations = _new(_LOCATIONS_SCHEMA)
    dynamic = _new(_DYNAMIC_SCHEMA)
    extras = _new(_EXTRAS_SCHEMA)
    genius = _new(_GENIUS_SCHEMA)
    library.execute("INSERT INTO version_info VALUES (1,1,111,0,0,1104,2)")
    master_pid = database_id or 1
    library.execute(
        "INSERT INTO db_info VALUES (?,?,NULL,-1,-1,NULL,NULL,NULL)",
        (_s64(database_id), _s64(master_pid)),
    )
    library.executemany(
        "INSERT INTO location_kind_map VALUES (?,?)",
        (
            (1, "MPEG audio file"),
            (2, "Purchased AAC audio file"),
            (3, "AAC audio file"),
        ),
    )
    locations.execute("INSERT INTO base_location VALUES (1,'iPod_Control/Music')")

    genres = _stable_text_ids({t.genre for t in snapshot.tracks if t.genre})
    categories = _stable_text_ids(
        {t.metadata.category for t in snapshot.tracks if t.metadata.category}
    )
    library.executemany(
        "INSERT INTO genre_map VALUES (?,?,?,0,1,0,0,0)",
        ((value, key, value) for key, value in genres.items()),
    )
    library.executemany(
        "INSERT INTO category_map VALUES (?,?)",
        ((value, key) for key, value in categories.items()),
    )

    album_groups = _group_tracks_by_album(snapshot.tracks)
    album_names = {key: _album_name_for_sorting(key[0]) for key in album_groups}
    album_name_ranks = _album_name_ranks(set(album_names.values()))
    track_album_sort_names = {
        track.track_id: track.metadata.sort_album
        or _album_name_for_sorting(track.album)
        for track in snapshot.tracks
    }
    album_sort_ranks = _album_name_ranks(set(track_album_sort_names.values()))
    album_keys_by_track_id = {
        track.track_id: key
        for key, members in album_groups.items()
        for track in members
    }
    album_candidates: dict[_AlbumKey, int] = {
        key: members[0].ipod.album_id
        if members[0].ipod is not None and members[0].ipod.album_id
        else 0
        for key, members in album_groups.items()
    }
    artist_candidates: dict[str, int] = {}
    track_artist_candidates: dict[str, int] = {}
    composer_candidates: dict[str, int] = {}
    for track in snapshot.tracks:
        details = track.ipod
        album_key = album_keys_by_track_id[track.track_id]
        album_artist = album_key[1]
        artist_candidates.setdefault(
            album_artist,
            details.artist_id_ref
            if details is not None and details.artist_id_ref
            else 0,
        )
        track_artist_candidates.setdefault(track.artist, 0)
        composer_candidates.setdefault(
            track.metadata.composer,
            details.composer_id if details is not None and details.composer_id else 0,
        )
    album_ids = dict(
        zip(
            album_candidates,
            _allocate_pids(
                "album",
                tuple((key, native) for key, native in album_candidates.items()),
            ),
            strict=True,
        )
    )
    artist_ids = dict(
        zip(
            artist_candidates,
            _allocate_pids(
                "artist",
                tuple(((key,), native) for key, native in artist_candidates.items()),
            ),
            strict=True,
        )
    )
    track_artist_ids = dict(
        zip(
            track_artist_candidates,
            _allocate_pids(
                "track_artist",
                tuple(
                    ((key,), native) for key, native in track_artist_candidates.items()
                ),
            ),
            strict=True,
        )
    )
    composer_ids = dict(
        zip(
            composer_candidates,
            _allocate_pids(
                "composer",
                tuple(((key,), native) for key, native in composer_candidates.items()),
            ),
            strict=True,
        )
    )

    for album_key, album_pid in album_ids.items():
        members = album_groups[album_key]
        album_sort_name = track_album_sort_names[members[0].track_id]
        artwork_track = next((track for track in members if track.artwork_id), None)
        library.execute(
            """INSERT INTO album (pid,kind,artwork_status,artwork_item_pid,
            artist_pid,user_rating,name,name_order,all_compilations,feed_url,
            season_number,is_unknown,has_songs,has_music_videos,sort_order,
            artist_order,has_any_compilations,sort_name,artist_count_calc,
            has_movies,item_count) VALUES (?,2,?,?,?,?,?,?,?, ?,?, ?,1,0,?,
            100,?,?,0,0,?)""",
            (
                _s64(album_pid),
                int(artwork_track is not None),
                _s64(_track_pid(artwork_track)) if artwork_track is not None else 0,
                _s64(artist_ids[album_key[1]]),
                0,
                album_key[0] or None,
                album_name_ranks[album_names[album_key]],
                int(all(track.metadata.compilation for track in members)),
                next(
                    (
                        track.metadata.podcast_rss_url
                        for track in members
                        if track.metadata.podcast_rss_url
                    ),
                    None,
                ),
                next((track.season_number for track in members if track.show), 0),
                int(not album_key[0]),
                album_sort_ranks[album_sort_name],
                int(any(track.metadata.compilation for track in members)),
                album_sort_name or None,
                len(members),
            ),
        )
    for name, artist_pid in artist_ids.items():
        library.execute(
            "INSERT INTO artist VALUES (?,2,0,0,?,100,?, ?,1,0)",
            (_s64(artist_pid), name or None, name or None, int(not name)),
        )
    for name, artist_pid in track_artist_ids.items():
        library.execute(
            "INSERT INTO track_artist VALUES (?,?,100,?,1,0,1,?,0)",
            (_s64(artist_pid), name or None, name or None, int(not name)),
        )
    for name, composer_pid in composer_ids.items():
        library.execute(
            "INSERT INTO composer VALUES (?,?,100,?,?,1)",
            (_s64(composer_pid), name or None, name or None, int(not name)),
        )

    pids: dict[int, int] = {}
    media_kinds: dict[int, int] = {}
    for order, track in enumerate(snapshot.tracks):
        pid = _track_pid(track)
        pids[track.track_id] = pid
        metadata = track.metadata
        media_kind = _media_kind(track)
        media_kinds[track.track_id] = media_kind
        flags = _media_flags(media_kind)
        details = track.ipod
        album_key = album_keys_by_track_id[track.track_id]
        album_pid = album_ids[album_key]
        artist_pid = artist_ids[album_key[1]]
        track_artist_pid = track_artist_ids[track.artist]
        composer_pid = composer_ids[metadata.composer]
        item_values = (
            _s64(pid),
            media_kind,
            *flags,
            _core_data(metadata.last_modified),
            track.year,
            _content_rating(metadata.content_advisory),
            int(metadata.compilation),
            int(not metadata.checked),
            int(metadata.remember_position),
            int(metadata.skip_shuffle),
            int(metadata.gapless_album),
            int(bool(track.artwork_id)),
            track.artwork_id,
            float(metadata.start_time_ms),
            float(metadata.stop_time_ms),
            float(track.length_ms),
            track.track_number,
            metadata.total_tracks,
            metadata.disc_number,
            metadata.total_discs,
            metadata.bpm,
            volume_adjustment_to_native(metadata.volume_adjustment_percent),
            metadata.equalizer or None,
            genres.get(track.genre, 0),
            categories.get(metadata.category, 0),
            _s64(album_pid),
            _s64(artist_pid),
            _s64(composer_pid),
            track.title,
            track.artist,
            track.album,
            track.album_artist,
            metadata.composer,
            metadata.sort_title or None,
            metadata.sort_artist or None,
            track_album_sort_names[track.track_id] or None,
            metadata.sort_album_artist or None,
            metadata.sort_composer or None,
            album_sort_ranks[track_album_sort_names[track.track_id]],
            metadata.comment or None,
            metadata.grouping or None,
            metadata.description or None,
            metadata.copyright or None,
            _s64(track_artist_pid),
            order,
            int(metadata.has_lyrics or bool(metadata.lyrics)),
            _core_data(metadata.release_date),
        )
        library.execute(
            """INSERT INTO item (
              pid,media_kind,is_song,is_audio_book,is_music_video,is_movie,is_tv_show,
              is_home_video,is_ringtone,is_tone,is_voice_memo,is_book,is_rental,
              is_itunes_u,is_digital_booklet,is_podcast,date_modified,year,
              content_rating,is_compilation,
              is_user_disabled,remember_bookmark,exclude_from_shuffle,
              part_of_gapless_album,artwork_status,artwork_cache_id,start_time_ms,
              stop_time_ms,total_time_ms,track_number,track_count,disc_number,disc_count,
              bpm,relative_volume,eq_preset,genre_id,category_id,album_pid,artist_pid,
              composer_pid,title,artist,album,album_artist,composer,sort_title,sort_artist,
              sort_album,sort_album_artist,sort_composer,album_order,comment,grouping,description,
              copyright,track_artist_pid,physical_order,has_lyrics,date_released)
              VALUES ("""
            + ",".join("?" for _value in item_values)
            + ")",
            item_values,
        )
        file_facts = _native_file_facts(track)
        library.execute(
            "INSERT INTO avformat_info VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                _s64(pid),
                0,
                file_facts.audio_format,
                track.bitrate_kbps,
                0,
                float(metadata.sample_rate_hz),
                metadata.sample_count,
                int(metadata.gapless),
                metadata.pregap,
                metadata.postgap,
                details.gapless_audio_payload_size if details is not None else 0,
                0,
                0,
                normalization_gain_to_native(metadata.normalization_gain_db),
            ),
        )
        if media_kind & MEDIA_TYPE_VIDEO_MASK:
            library.execute(
                "INSERT INTO video_info (item_pid,season_number,series_name,episode_id,episode_sort_id,network_name) VALUES (?,?,?,?,?,?)",
                (
                    _s64(pid),
                    track.season_number,
                    track.show,
                    track.episode,
                    track.episode_number,
                    metadata.tv_network,
                ),
            )
        if media_kind & MEDIA_TYPE_PODCAST:
            library.execute(
                "INSERT INTO podcast_info VALUES (?,?,?,?,?)",
                (
                    _s64(pid),
                    _core_data(metadata.release_date),
                    None,
                    metadata.podcast_rss_url,
                    metadata.track_keywords,
                ),
            )
        purchased = details.date_added_to_itunes if details is not None else 0
        if purchased or metadata.release_date:
            library.execute(
                "INSERT INTO store_info (item_pid,date_purchased,date_released) VALUES (?,?,?)",
                (_s64(pid), _core_data(purchased), _core_data(metadata.release_date)),
            )
        locations.execute(
            "INSERT INTO location VALUES (?,0,1,?,?,?,?,?,?,NULL,NULL,NULL,NULL)",
            (
                _s64(pid),
                0x46494C45,
                _file_location(metadata.location),
                file_facts.extension,
                file_facts.kind_id,
                _core_data(metadata.date_added),
                track.size_bytes,
            ),
        )
        if media_kind & MEDIA_TYPE_RENTAL:
            dynamic.execute(
                "INSERT INTO rental_info (item_pid) VALUES (?)", (_s64(pid),)
            )
        dynamic.execute(
            "INSERT INTO item_stats VALUES (?,?,?,?,0,?,?,0,?,?,?,?,0,?,?,0)",
            (
                _s64(pid),
                int(track.play_count > 0),
                _core_data(metadata.last_played),
                track.play_count,
                _core_data(metadata.last_skipped),
                metadata.skip_count,
                float(metadata.bookmark_time_ms),
                float(metadata.bookmark_time_ms),
                track.rating,
                details.app_rating if details is not None else track.rating,
                track.play_count,
                metadata.skip_count,
            ),
        )
        if metadata.lyrics:
            lyrics = metadata.lyrics
            extras.execute(
                "INSERT INTO lyrics VALUES (?,?,?)",
                (_s64(pid), sum(lyrics.encode("utf-8")) & 0xFFFFFFFF, lyrics),
            )
        if metadata.chapters:
            extras.execute(
                "INSERT INTO chapter VALUES (?,?)",
                (_s64(pid), _chapter_blob(metadata.chapters)),
            )

    library.executemany(
        "INSERT INTO track_size_calc VALUES (?,?,?)",
        (
            (
                1,
                "audio",
                sum(
                    t.size_bytes
                    for t in snapshot.tracks
                    if not (media_kinds[t.track_id] & MEDIA_TYPE_VIDEO_MASK)
                ),
            ),
            (
                2,
                "video",
                sum(
                    t.size_bytes
                    for t in snapshot.tracks
                    if media_kinds[t.track_id] & (MEDIA_TYPE_VIDEO | MEDIA_TYPE_TV_SHOW)
                ),
            ),
            (
                3,
                "music_video",
                sum(
                    t.size_bytes
                    for t in snapshot.tracks
                    if media_kinds[t.track_id] & MEDIA_TYPE_MUSIC_VIDEO
                ),
            ),
        ),
    )
    now = _core_data(max((t.metadata.date_added for t in snapshot.tracks), default=0))
    _insert_container(
        library,
        master_pid,
        snapshot.device_name or "iPod",
        None,
        PlaylistKind.PLAYLIST,
        now,
        hidden=True,
    )
    for position, track in enumerate(snapshot.tracks):
        library.execute(
            "INSERT INTO item_to_container VALUES (?,?,?,NULL)",
            (_s64(pids[track.track_id]), _s64(master_pid), position),
        )
    container_pids = [master_pid]
    for playlist in snapshot.playlists:
        playlist_pid = playlist.playlist_id
        container_pids.append(playlist_pid)
        _insert_container(
            library,
            playlist_pid,
            playlist.name,
            playlist.parent_id,
            playlist.kind,
            now,
            description=playlist.description,
            smart=playlist.smart,
            criteria=(smart_criteria or {}).get(playlist.playlist_id),
        )
        for position, track_id in enumerate(playlist.track_ids):
            if track_id in pids:
                library.execute(
                    "INSERT INTO item_to_container VALUES (?,?,?,NULL)",
                    (_s64(pids[track_id]), _s64(playlist_pid), position),
                )
    dynamic.executemany(
        "INSERT INTO container_ui VALUES (?,0,0,1,0,0,0)",
        ((_s64(pid),) for pid in container_pids),
    )

    if postprocess_commands:
        library, locations, dynamic, extras, genius = _postprocess(
            library,
            locations,
            dynamic,
            extras,
            genius,
            postprocess_commands,
        )
    library_bytes = _serialize(library)
    locations_bytes = _serialize(locations)
    dynamic_bytes = _serialize(dynamic)
    extras_bytes = _serialize(extras)
    genius_bytes = _serialize(genius)
    cbk = build_locations_cbk(
        locations_bytes, checksum, firewire_guid, hash72_iv, hash72_random
    )
    result = SQLiteDatabaseSet(
        library_bytes, locations_bytes, dynamic_bytes, extras_bytes, genius_bytes, cbk
    )
    if not verify_locations_cbk(
        result, checksum, firewire_guid, hash72_iv, hash72_random
    ):
        raise ValueError("Generated Locations.itdb checksum book failed verification")
    return result


def _postprocess(
    library: sqlite3.Connection,
    locations: sqlite3.Connection,
    dynamic: sqlite3.Connection,
    extras: sqlite3.Connection,
    genius: sqlite3.Connection,
    commands: tuple[str, ...],
) -> tuple[
    sqlite3.Connection,
    sqlite3.Connection,
    sqlite3.Connection,
    sqlite3.Connection,
    sqlite3.Connection,
]:
    """Run the profile-supplied Apple SQL command set entirely in memory."""

    companions = {
        "Locations.itdb": locations,
        "Dynamic.itdb": dynamic,
        "Extras.itdb": extras,
        "Genius.itdb": genius,
    }
    library.commit()
    for name, connection in companions.items():
        connection.commit()
        library.execute(f"ATTACH ':memory:' AS \"{name}\"")
        library.deserialize(connection.serialize(), name=name)
        connection.close()
    library.commit()
    library.create_function("iPhoneSortKey", 1, _iphone_sort_key)
    library.create_function("iPhoneSortSection", 1, _iphone_sort_section)
    if hasattr(sqlite3, "SQLITE_DBCONFIG_DEFENSIVE"):
        library.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)

    def authorize(
        action: int,
        _argument_1: str | None,
        _argument_2: str | None,
        _database: str | None,
        _trigger: str | None,
    ) -> int:
        # SysInfoExtended is device input.  It may transform the already
        # attached in-memory generation, but it may never name a Host path.
        if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    library.set_authorizer(authorize)
    try:
        script = ["BEGIN;"]
        for command in commands:
            script.append(command)
            if not sqlite3.complete_statement(command):
                script.append(";")
        script.append("COMMIT;")
        library.executescript("\n".join(script))
        for name in companions:
            result = library.execute(f'PRAGMA "{name}".quick_check').fetchone()
            if result is None or result[0] != "ok":
                raise ValueError(f"SQLite postprocessing damaged {name}")
        result = library.execute("PRAGMA main.quick_check").fetchone()
        if result is None or result[0] != "ok":
            raise ValueError("SQLite postprocessing damaged Library.itdb")
    except sqlite3.DatabaseError as error:
        library.rollback()
        raise ValueError("Device SQLite postprocessing failed") from error
    finally:
        library.set_authorizer(None)
    locations = _open(library.serialize(name="Locations.itdb"))
    dynamic = _open(library.serialize(name="Dynamic.itdb"))
    extras = _open(library.serialize(name="Extras.itdb"))
    genius = _open(library.serialize(name="Genius.itdb"))
    for name in companions:
        library.execute(f'DETACH DATABASE "{name}"')
    return library, locations, dynamic, extras, genius


def _iphone_sort_key(value: object) -> bytes | None:
    if value is None or value == "":
        return b"\x31\x01\x01\x00"
    if not isinstance(value, str):
        return None
    source = value.encode("utf-8").upper()
    encoded = bytearray((0x30,))
    weights: list[tuple[int, int]] = []
    word_length = 0
    punctuation = {
        ord(":"): (0x07, 0xD8),
        ord("-"): (0x07, 0x90),
        ord(","): (0x07, 0xB2),
        ord("."): (0x08, 0x51),
        ord("'"): (0x07, 0x31),
    }
    for value_byte in source:
        word_length += 1
        if chr(value_byte).isalnum() and value_byte < 128:
            encoded.append((2 * value_byte - 0x55) & 0xFF)
        elif value_byte == 0x20:
            encoded.append(0x06)
            word_length -= 1
            weights.append((0x8F, (0x86 - word_length) & 0xFF))
            word_length = 0
        else:
            encoded.extend(punctuation.get(value_byte, (0x07, 0x90)))
    encoded.extend((0x01, (len(source) + 4) & 0xFF, 0x01))
    weights.append((0x8F, (3 + word_length) & 0xFF))
    for weight in weights:
        encoded.extend(weight)
    encoded.append(0)
    return bytes(encoded)


def _iphone_sort_section(value: object) -> int:
    if isinstance(value, str):
        data = value.encode("utf-8")
    elif isinstance(value, bytes):
        data = value
    else:
        return 26
    if len(data) >= 2 and data[0] == 0x30 and 0x2D <= data[1] <= 0x5F:
        return (data[1] - 0x2D) // 2
    return 26


def _insert_container(
    connection: sqlite3.Connection,
    pid: int,
    name: str,
    parent: int | None,
    kind: PlaylistKind,
    timestamp: int,
    *,
    hidden: bool = False,
    description: str = "",
    smart: SmartPlaylist | None = None,
    criteria: bytes | None = None,
) -> None:
    limit = None if smart is None else smart.limit
    limit_kinds = {
        "minutes": 1,
        "megabytes": 2,
        "tracks": 3,
        "hours": 4,
        "gigabytes": 5,
    }
    limit_orders = {
        "random": 2,
        "title": 3,
        "album": 4,
        "artist": 5,
        "genre": 7,
        "date_added": 16,
        "play_count": 20,
        "last_played": 21,
        "rating": 23,
    }
    normally_descending = {"date_added", "play_count", "last_played", "rating"}
    limit_sort = "" if limit is None else limit.sort.value
    connection.execute(
        """INSERT INTO container (pid,distinguished_kind,date_created,date_modified,
        name,name_order,parent_pid,media_kinds,workout_template_id,is_hidden,
        smart_is_folder,smart_is_dynamic,smart_is_filtered,smart_is_genius,
        smart_enabled_only,smart_is_limited,smart_limit_kind,smart_limit_order,
        smart_evaluation_order,smart_limit_value,smart_reverse_limit_order,
        smart_criteria,description)
        VALUES (?,?,?,?,?,100,?,1,0,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            _s64(pid),
            0,
            timestamp,
            timestamp,
            name,
            _s64(parent or 0),
            int(hidden),
            int(kind is PlaylistKind.FOLDER),
            None if smart is None else int(smart.live_update),
            None if smart is None else int(smart.match_rules),
            0,
            None if smart is None else int(smart.checked_only),
            None if smart is None else int(limit is not None),
            None if limit is None else limit_kinds[limit.unit.value],
            None if limit is None else limit_orders[limit_sort],
            None if smart is None else 1,
            None if limit is None else limit.value,
            None
            if limit is None
            else int((limit_sort in normally_descending) != limit.descending),
            criteria,
            description or None,
        ),
    )


def _location_extension(location: str) -> str:
    normalized = location.strip().replace("\\", "/").replace(":", "/")
    filename = normalized.rsplit("/", 1)[-1]
    _stem, separator, extension = filename.rpartition(".")
    return extension.casefold() if separator else ""


def _extension_code(extension: str) -> int:
    normalized = extension.casefold().lstrip(".")
    if not normalized:
        return 0
    known = FILE_EXTENSION_INT.get(normalized)
    if known is not None:
        return known
    encoded = normalized[:4].upper().encode("ascii", "replace").ljust(4, b" ")
    return int.from_bytes(encoded, "big")


def _native_file_facts(track: Track) -> _NativeFileFacts:
    """Resolve SQLite codec/container facts without consulting a display label."""

    details = track.ipod
    if details is not None and details.filetype_code:
        native_filetype = True
        extension = details.filetype_code
    else:
        native_filetype = False
        extension = _extension_code(_location_extension(track.metadata.location))
    mp3 = FILE_EXTENSION_INT["mp3"]
    m4a = FILE_EXTENSION_INT["m4a"]
    m4p = FILE_EXTENSION_INT["m4p"]
    wav = FILE_EXTENSION_INT["wav"]
    aiff = FILE_EXTENSION_INT["aiff"]
    mpeg4 = {
        FILE_EXTENSION_INT[name] for name in ("aac", "m4a", "m4b", "m4p", "m4v", "mp4")
    }
    if extension == mp3:
        audio_format = 301
    elif extension == wav:
        audio_format = 110
    elif extension == aiff:
        audio_format = 111
    elif (
        extension == m4a
        and native_filetype
        and details is not None
        and details.mpeg_audio_type == 0
        and not details.purchased_aac_flag
    ):
        audio_format = 503
    elif extension in mpeg4:
        audio_format = 502
    else:
        audio_format = 0
    if (
        details is not None and details.purchased_aac_flag and extension in mpeg4
    ) or extension == m4p:
        kind_id = 2
    elif extension in mpeg4:
        kind_id = 3
    else:
        kind_id = 1
    return _NativeFileFacts(extension, audio_format, kind_id)


def _chapter_blob(chapters: tuple[TrackChapter, ...]) -> bytes:
    atoms = bytearray()
    for chapter in chapters:
        title = str(chapter.title)
        encoded_title = title.encode("utf-16-be")
        if len(encoded_title) // 2 > 0xFFFF:
            raise ValueError("A chapter title is too long for Extras.itdb")
        name_size = 22 + len(encoded_title)
        name = (
            struct.pack(
                ">I4sIIIH", name_size, b"name", 1, 0, 0, len(encoded_title) // 2
            )
            + encoded_title
        )
        start = int(chapter.start_ms)
        if not 0 <= start <= 0xFFFFFFFF:
            raise ValueError("A chapter position must fit an unsigned 32-bit field")
        atoms.extend(
            struct.pack(">I4sIII", 20 + name_size, b"chap", start, 1, 0) + name
        )
    atoms.extend(struct.pack(">I4sIIIII", 28, b"hedr", 1, 0, 0, 0, 1))
    sean = struct.pack(">I4sIII", 20 + len(atoms), b"sean", 1, len(chapters) + 1, 0)
    return bytes(12) + sean + atoms
