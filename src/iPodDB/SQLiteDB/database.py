"""SQLite iPod database generation without filesystem access.

Late iPod nano firmware reads five SQLite databases plus a checksum book.  The
binary iTunesCDB remains the editing authority. Its checked projection updates
captured firmware schemas while retaining version and unrepresented metadata.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import ExitStack, closing
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
)
from iPodDB.library.playlists import PlaylistKind, SmartPlaylist
from iPodDB.SQLiteDB.artifacts import SQLiteDatabaseSet
from iPodDB.SQLiteDB.browse import complete_browse_metadata, name_ranks, sort_name
from iPodDB.SQLiteDB.chapters import chapter_blob
from iPodDB.SQLiteDB.checksum import build_locations_cbk, verify_locations_cbk
from iPodDB.SQLiteDB.inputs import (
    SQLiteContainer,
    SQLiteNativeMetadata,
    SQLiteSmartPreferences,
    SQLiteSource,
)
from iPodDB.SQLiteDB.retention import retain_database
from iPodDB.SQLiteDB.schema import (
    DYNAMIC_SCHEMA,
    EXTRAS_SCHEMA,
    GENIUS_SCHEMA,
    LIBRARY_SCHEMA,
    LOCATIONS_SCHEMA,
)
from iPodDB.SQLiteDB.validation import SQLiteRelationships, validate_databases

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
    # The memdb VFS updates the on-disk header bookkeeping while keeping every
    # byte in memory. A plain :memory: database serializes zero writer-version
    # and change-counter fields, unlike Original iOpenPod's file-backed output.
    # No leading slash: memdb names beginning with '/' share their contents.
    connection = sqlite3.connect("file:iopenpod-sqlite?vfs=memdb", uri=True)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA encoding='UTF-8'")
        connection.executescript(schema)
    except Exception:
        connection.close()
        raise
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


def _combined_media_kinds(track_ids: tuple[int, ...], kinds: dict[int, int]) -> int:
    result = 0
    for identity in track_ids:
        result |= kinds.get(identity, 0)
    return result


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
    *,
    reserved: frozenset[int] = frozenset(),
) -> tuple[int, ...]:
    """Retain unique native IDs and deterministically replace collisions."""

    native_counts: dict[int, int] = {}
    for _parts, native in candidates:
        if native:
            native_counts[native] = native_counts.get(native, 0) + 1
    used = set(reserved)
    retained = {native for native, count in native_counts.items() if count == 1} - used
    result: list[int] = []
    for parts, native in candidates:
        candidate = native if native in retained else _stable_pid(kind, *parts)
        salt = 0
        while candidate in used or (candidate in retained and candidate != native):
            salt += 1
            candidate = _stable_pid(kind, *parts, str(salt))
        used.add(candidate)
        result.append(candidate)
    return tuple(result)


def _album_key(track: Track) -> _AlbumKey:
    return (
        track.album.strip(),
        track.album_artist.strip() or track.artist.strip(),
        track.show.strip(),
    )


@dataclass(frozen=True, slots=True)
class _BrowseIds:
    albums: dict[_AlbumKey, int]
    artists: dict[str, int]
    track_artists: dict[str, int]
    composers: dict[str, int]


def _browse_ids(
    tracks: tuple[Track, ...], album_keys: Mapping[int, _AlbumKey]
) -> _BrowseIds:
    """Allocate the Original SQLite group namespace in first-Track order.

    These are projection-local IDs, independent of the CDB's browse IDs. Missing
    artists and composers use zero references rather than invented group rows.
    """

    ids = _BrowseIds({}, {}, {}, {})
    next_pid = 101
    for track in tracks:
        album = album_keys[track.track_id]
        if album not in ids.albums:
            ids.albums[album] = next_pid
            next_pid += 1
        artist = album[1]
        if artist and artist not in ids.artists:
            ids.artists[artist] = next_pid
            next_pid += 1
        if track.artist and track.artist not in ids.track_artists:
            ids.track_artists[track.artist] = next_pid
            next_pid += 1
        composer = track.metadata.composer
        if composer and composer not in ids.composers:
            ids.composers[composer] = next_pid
            next_pid += 1
    return ids


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
    native: SQLiteNativeMetadata | None = None,
    retained: tuple[SQLiteSource, ...] = (),
    cleared_lyrics: frozenset[int] = frozenset(),
    cleared_chapters: frozenset[int] = frozenset(),
    replaced_tracks: frozenset[int] = frozenset(),
) -> SQLiteDatabaseSet:
    """Project a verified Library Snapshot into all firmware SQLite artifacts."""

    with ExitStack() as connections:
        try:
            return _build_sqlite_databases(
                snapshot,
                database_id=database_id,
                checksum=checksum,
                firewire_guid=firewire_guid,
                hash72_iv=hash72_iv,
                hash72_random=hash72_random,
                postprocess_commands=postprocess_commands,
                smart_criteria=smart_criteria,
                native=native or SQLiteNativeMetadata(),
                retained=retained,
                cleared_lyrics=cleared_lyrics,
                cleared_chapters=cleared_chapters,
                replaced_tracks=replaced_tracks,
                connections=connections,
            )
        except sqlite3.DatabaseError as error:
            raise ValueError("SQLite Library generation failed") from error


def _build_sqlite_databases(
    snapshot: LibrarySnapshot,
    *,
    database_id: int,
    checksum: WriteChecksum,
    firewire_guid: bytes,
    hash72_iv: bytes,
    hash72_random: bytes,
    postprocess_commands: tuple[str, ...],
    smart_criteria: Mapping[int, bytes] | None,
    native: SQLiteNativeMetadata,
    retained: tuple[SQLiteSource, ...],
    cleared_lyrics: frozenset[int],
    cleared_chapters: frozenset[int],
    replaced_tracks: frozenset[int],
    connections: ExitStack,
) -> SQLiteDatabaseSet:
    library = connections.enter_context(closing(_new(LIBRARY_SCHEMA)))
    locations = connections.enter_context(closing(_new(LOCATIONS_SCHEMA)))
    dynamic = connections.enter_context(closing(_new(DYNAMIC_SCHEMA)))
    extras = connections.enter_context(closing(_new(EXTRAS_SCHEMA)))
    genius = connections.enter_context(closing(_new(GENIUS_SCHEMA)))
    library.execute(
        "INSERT INTO version_info VALUES (1,1,?,0,0,1104,2)", (native.database_version,)
    )
    database_id = native.database_id or database_id
    containers = (
        native.containers
        if native.containers is not None
        else tuple(SQLiteContainer(p) for p in snapshot.playlists)
    )
    user_ids = frozenset(c.playlist.playlist_id for c in containers if c.dataset != 5)
    # Native Smart rules can refer to user Playlist IDs. Keep those identities
    # even when a category or the database's master seed uses the same value.
    master_pid = _allocate_pids(
        "master",
        (((str(database_id),), native.master_id or database_id or 1),),
        reserved=user_ids,
    )[0]
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
    title_names = {
        t.track_id: t.metadata.sort_title or sort_name(t.title) for t in snapshot.tracks
    }
    artist_names = {
        t.track_id: t.metadata.sort_artist or sort_name(t.artist)
        for t in snapshot.tracks
    }
    composer_names = {
        t.track_id: t.metadata.sort_composer or sort_name(t.metadata.composer)
        for t in snapshot.tracks
    }
    album_artist_names = {
        t.track_id: t.metadata.sort_album_artist
        or (sort_name(t.album_artist) if t.album_artist else artist_names[t.track_id])
        for t in snapshot.tracks
    }
    series_names = {
        t.track_id: t.metadata.sort_show or sort_name(t.show) for t in snapshot.tracks
    }
    title_ranks = name_ranks(title_names.values())
    artist_ranks = name_ranks(artist_names.values())
    composer_ranks = name_ranks(composer_names.values())
    genre_ranks = name_ranks(t.genre for t in snapshot.tracks)
    album_artist_ranks = name_ranks(album_artist_names.values())
    series_ranks = name_ranks(series_names.values())
    browse_ids = _browse_ids(snapshot.tracks, album_keys_by_track_id)
    album_ids = browse_ids.albums
    artist_ids = browse_ids.artists
    track_artist_ids = browse_ids.track_artists
    composer_ids = browse_ids.composers

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
                artist_ids.get(album_key[1], 0),
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
    native_chapters = {chapter.track_id: chapter.data for chapter in native.chapters}
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
        artist_pid = artist_ids.get(album_key[1], 0)
        track_artist_pid = track_artist_ids.get(track.artist, 0)
        composer_pid = composer_ids.get(metadata.composer, 0)
        item_values = (
            _s64(pid),
            media_kind,
            *flags,
            _core_data(metadata.last_modified or metadata.date_added),
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
            title_names[track.track_id] or None,
            artist_names[track.track_id] or None,
            track_album_sort_names[track.track_id] or None,
            album_artist_names[track.track_id] or None,
            composer_names[track.track_id] or None,
            title_ranks[title_names[track.track_id]],
            artist_ranks[artist_names[track.track_id]],
            album_sort_ranks[track_album_sort_names[track.track_id]],
            genre_ranks[track.genre],
            composer_ranks[composer_names[track.track_id]],
            artist_ranks[artist_names[track.track_id]],
            album_artist_ranks[album_artist_names[track.track_id]],
            series_ranks[series_names[track.track_id]],
            metadata.comment or None,
            metadata.grouping or None,
            (metadata.subtitle or metadata.description[:255] or None)
            if media_kind & MEDIA_TYPE_PODCAST
            else metadata.description or None,
            metadata.description or None if media_kind & MEDIA_TYPE_PODCAST else None,
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
              sort_album,sort_album_artist,sort_composer,title_order,artist_order,album_order,
              genre_order,composer_order,album_artist_order,album_by_artist_order,series_name_order,comment,grouping,description,description_long,
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
                metadata.sample_count
                or track.length_ms * metadata.sample_rate_hz // 1000,
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
                "INSERT INTO video_info (item_pid,season_number,series_name,sort_series_name,episode_id,episode_sort_id,network_name) VALUES (?,?,?,?,?,?,?)",
                (
                    _s64(pid),
                    track.season_number,
                    track.show,
                    series_names[track.track_id] or None,
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
                    metadata.podcast_guid or track.episode or None,
                    metadata.podcast_rss_url,
                    metadata.track_keywords,
                ),
            )
        # Original leaves store_info empty. Dates alone do not describe a complete
        # Store record; release dates already belong to item and podcast_info.
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
                int(metadata.played or track.play_count > 0),
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
        if metadata.chapters or track.track_id in native_chapters:
            extras.execute(
                "INSERT INTO chapter VALUES (?,?)",
                (
                    _s64(pid),
                    native_chapters[track.track_id]
                    if track.track_id in native_chapters
                    else chapter_blob(metadata.chapters),
                ),
            )

    complete_browse_metadata(library)
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
        _core_data(native.master_date_created) if native.master_date_created else now,
        modified=_core_data(native.master_date_modified)
        if native.master_date_modified
        else now,
        hidden=True,
        media_kinds=_combined_media_kinds(tuple(media_kinds), media_kinds),
    )
    membership: list[tuple[int, int, int]] = []
    for position, track in enumerate(snapshot.tracks):
        membership.append((_s64(pids[track.track_id]), _s64(master_pid), position))
        library.execute(
            "INSERT INTO item_to_container VALUES (?,?,?,NULL)",
            (_s64(pids[track.track_id]), _s64(master_pid), position),
        )
    container_pids = [master_pid]
    allocated = _allocate_pids(
        "container",
        tuple(
            (
                (str(c.dataset), str(c.playlist.playlist_id)),
                0
                if c.dataset == 5 and c.playlist.playlist_id in user_ids
                else c.playlist.playlist_id,
            )
            for c in containers
        ),
        reserved=frozenset((master_pid,)),
    )
    user_container_ids = {
        c.playlist.playlist_id: pid
        for c, pid in zip(containers, allocated, strict=True)
        if c.dataset != 5
    }
    for container, playlist_pid in zip(containers, allocated, strict=True):
        playlist = container.playlist
        container_pids.append(playlist_pid)
        _insert_container(
            library,
            playlist_pid,
            playlist.name,
            user_container_ids.get(playlist.parent_id)
            if playlist.parent_id is not None
            else None,
            playlist.kind,
            _core_data(container.date_created) if container.date_created else now,
            modified=_core_data(container.date_modified)
            if container.date_modified
            else now,
            name_order=len(container_pids) * 100,
            distinguished_kind=11
            if container.podcast
            else container.category
            if container.category in (4, 5)
            else 0,
            media_kinds=_combined_media_kinds(playlist.track_ids, media_kinds)
            if container.podcast
            else 0
            if container.category == 5
            else 1,
            hidden=container.hidden,
            description=playlist.description,
            smart=playlist.smart,
            criteria=container.criteria
            if container.criteria is not None
            else (smart_criteria or {}).get(playlist.playlist_id),
            preferences=container.preferences,
        )
        for position, track_id in enumerate(playlist.track_ids):
            if track_id in pids:
                membership.append((_s64(pids[track_id]), _s64(playlist_pid), position))
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
            connections,
        )
    generated = {
        "Library.itdb": library,
        "Locations.itdb": locations,
        "Dynamic.itdb": dynamic,
        "Extras.itdb": extras,
        "Genius.itdb": genius,
    }
    if len({s.name for s in retained}) != len(retained) or any(
        s.name not in generated for s in retained
    ):
        raise ValueError("Retained SQLite sources must have unique supported names")
    track_pids = frozenset(_s64(pid) for pid in pids.values())
    for source in retained:
        generated[source.name] = connections.enter_context(
            closing(
                retain_database(
                    generated[source.name],
                    source.data,
                    artifact=source.name,
                    tracks=track_pids,
                    containers=frozenset(_s64(pid) for pid in container_pids),
                    cleared_lyrics=frozenset(_s64(pid) for pid in cleared_lyrics),
                    cleared_chapters=frozenset(_s64(pid) for pid in cleared_chapters),
                    replaced_tracks=frozenset(_s64(pid) for pid in replaced_tracks),
                )
            )
        )
    library, locations, dynamic, extras, genius = (
        generated[name]
        for name in (
            "Library.itdb",
            "Locations.itdb",
            "Dynamic.itdb",
            "Extras.itdb",
            "Genius.itdb",
        )
    )
    chapter_pids = frozenset(
        int(row[0]) for row in extras.execute("SELECT item_pid FROM chapter")
    )
    lyrics_pids = frozenset(
        int(row[0]) for row in extras.execute("SELECT item_pid FROM lyrics")
    )
    if not (chapter_pids | lyrics_pids) <= track_pids:
        raise ValueError("Retained Extras reference missing Tracks")
    required_chapters = frozenset(
        _s64(pids[t.track_id])
        for t in snapshot.tracks
        if t.metadata.chapters or t.track_id in native_chapters
    )
    required_lyrics = frozenset(
        _s64(pids[t.track_id]) for t in snapshot.tracks if t.metadata.lyrics
    )
    if not required_chapters <= chapter_pids or not required_lyrics <= lyrics_pids:
        raise ValueError("Retained schema lost authored chapters or lyrics")
    library.executemany(
        "UPDATE item SET has_lyrics=1 WHERE pid=?", ((pid,) for pid in lyrics_pids)
    )
    validate_databases(
        library,
        locations,
        dynamic,
        extras,
        genius,
        SQLiteRelationships(
            frozenset(_s64(pid) for pid in pids.values()),
            frozenset(_s64(pid) for pid in container_pids),
            tuple(membership),
            chapter_pids,
            lyrics_pids,
        ),
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
    connections: ExitStack,
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
    locations = connections.enter_context(
        closing(_open(library.serialize(name="Locations.itdb")))
    )
    dynamic = connections.enter_context(
        closing(_open(library.serialize(name="Dynamic.itdb")))
    )
    extras = connections.enter_context(
        closing(_open(library.serialize(name="Extras.itdb")))
    )
    genius = connections.enter_context(
        closing(_open(library.serialize(name="Genius.itdb")))
    )
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
    preferences: SQLiteSmartPreferences | None = None,
    distinguished_kind: int = 0,
    media_kinds: int = 1,
    name_order: int = 100,
    modified: int | None = None,
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
        VALUES (?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            _s64(pid),
            distinguished_kind,
            timestamp,
            timestamp if modified is None else modified,
            name,
            name_order,
            _s64(parent or 0),
            media_kinds,
            int(hidden),
            int(kind is PlaylistKind.FOLDER),
            None if smart is None else int(smart.live_update),
            None if smart is None else int(smart.match_rules),
            0,
            0 if smart is None else int(smart.checked_only),
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
    if preferences is not None:
        connection.execute(
            "UPDATE container SET smart_is_dynamic=?,smart_is_filtered=?,smart_enabled_only=?,smart_is_limited=?,smart_limit_kind=?,smart_limit_order=?,smart_evaluation_order=1,smart_limit_value=?,smart_reverse_limit_order=? WHERE pid=?",
            (
                preferences.live_update,
                preferences.check_rules,
                preferences.checked_only,
                preferences.check_limits,
                preferences.limit_type,
                preferences.limit_sort,
                preferences.limit_value,
                preferences.reverse_sort,
                _s64(pid),
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
    if extension == m4p:
        kind_id = 2
    elif extension in mpeg4:
        kind_id = 3
    else:
        kind_id = 1
    return _NativeFileFacts(extension, audio_format, kind_id)
