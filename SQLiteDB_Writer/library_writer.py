"""Library.itdb writer — main SQLite music library database.

Writes all track metadata, albums, artists, composers, containers (playlists),
genres, AV format info, and version/db info.

Schema matches real iTunes-written databases on iPod Nano 6G.
Reference: libgpod itdb_sqlite.c mk_Library()
"""

import sqlite3
import time
import logging
from typing import Optional

from iTunesDB_Writer.mhit_writer import TrackInfo
from iTunesDB_Shared.constants import FILETYPE_CODES
from iTunesDB_Writer.mhyp_writer import PlaylistInfo

logger = logging.getLogger(__name__)

# ── Timestamp helpers ──────────────────────────────────────────────────
# SQLite databases use Core Data timestamps: seconds since 2001-01-01 UTC
# (the Cocoa/Core Foundation reference date).
CORE_DATA_EPOCH = 978307200  # Unix timestamp of 2001-01-01 00:00:00 UTC


def _unix_to_coredata(unix_ts: int, tz_offset: int = 0) -> int:
    """Convert Unix timestamp to Core Data timestamp.

    Args:
        unix_ts: Unix timestamp (seconds since 1970-01-01)
        tz_offset: Timezone offset in seconds (positive = east of UTC)

    Returns:
        Core Data timestamp (seconds since 2001-01-01) adjusted for timezone.
        Returns 0 if input is 0.
    """
    if unix_ts == 0:
        return 0
    return unix_ts - CORE_DATA_EPOCH - tz_offset


# ── Audio format codes ─────────────────────────────────────────────────
# avformat_info.audio_format values observed in real databases
AUDIO_FORMAT_MP3 = 0x012D   # 301
AUDIO_FORMAT_AAC = 0x01F6   # 502
AUDIO_FORMAT_ALAC = 0x01F7  # 503
AUDIO_FORMAT_WAV = 0x006E   # 110
AUDIO_FORMAT_AIFF = 0x006F  # 111

_FILETYPE_TO_AUDIO_FORMAT = {
    'mp3': AUDIO_FORMAT_MP3,
    'aac': AUDIO_FORMAT_AAC,
    'm4a': AUDIO_FORMAT_AAC,
    'm4p': AUDIO_FORMAT_AAC,
    'm4b': AUDIO_FORMAT_AAC,
    'alac': AUDIO_FORMAT_ALAC,
    'wav': AUDIO_FORMAT_WAV,
    'aif': AUDIO_FORMAT_AIFF,
    'aiff': AUDIO_FORMAT_AIFF,
}

# ── Extension (file type) codes ────────────────────────────────────────
# Stored as big-endian 4-byte ASCII, same as iTunesDB filetype codes.
# These are the same values as FILETYPE_CODES from mhit_writer.
_EXTENSION_CODES = FILETYPE_CODES


# ── Media kind flags ───────────────────────────────────────────────────
# item.media_kind in the SQLite database. These differ from the binary
# iTunesDB media_type values.
MEDIA_KIND_SONG = 1
MEDIA_KIND_AUDIOBOOK = 8
MEDIA_KIND_MUSIC_VIDEO = 32
MEDIA_KIND_MOVIE = 2
MEDIA_KIND_TV_SHOW = 64
MEDIA_KIND_PODCAST = 4
MEDIA_KIND_RINGTONE = 0x4000

# Map from binary iTunesDB media_type to SQLite media_kind
_ITDB_MEDIATYPE_TO_MEDIA_KIND = {
    0x01: MEDIA_KIND_SONG,           # audio
    0x02: MEDIA_KIND_MOVIE,          # video/movie
    0x04: MEDIA_KIND_PODCAST,        # podcast
    0x06: MEDIA_KIND_PODCAST,        # video podcast
    0x08: MEDIA_KIND_AUDIOBOOK,      # audiobook
    0x20: MEDIA_KIND_MUSIC_VIDEO,    # music video
    0x40: MEDIA_KIND_TV_SHOW,        # TV show
    0x4000: MEDIA_KIND_RINGTONE,     # ringtone
}


def _media_kind(track: TrackInfo) -> int:
    """Derive SQLite media_kind from track media_type."""
    return _ITDB_MEDIATYPE_TO_MEDIA_KIND.get(track.media_type, MEDIA_KIND_SONG)


def _is_song(track: TrackInfo) -> int:
    return 1 if _media_kind(track) == MEDIA_KIND_SONG else 0


def _is_audio_book(track: TrackInfo) -> int:
    return 1 if _media_kind(track) == MEDIA_KIND_AUDIOBOOK else 0


def _is_music_video(track: TrackInfo) -> int:
    return 1 if _media_kind(track) == MEDIA_KIND_MUSIC_VIDEO else 0


def _is_movie(track: TrackInfo) -> int:
    return 1 if _media_kind(track) == MEDIA_KIND_MOVIE else 0


def _is_tv_show(track: TrackInfo) -> int:
    return 1 if _media_kind(track) == MEDIA_KIND_TV_SHOW else 0


def _is_podcast(track: TrackInfo) -> int:
    return 1 if _media_kind(track) == MEDIA_KIND_PODCAST else 0


def _is_ringtone(track: TrackInfo) -> int:
    return 1 if _media_kind(track) == MEDIA_KIND_RINGTONE else 0


def _strip_article(name: str) -> str:
    """Strip leading articles (A, An, The) for sort field generation.

    iTunes auto-generates sort_title/sort_album/etc. by stripping common
    English leading articles.  We replicate this behaviour so that iPod
    browsing order matches what iTunes would produce.
    """
    if not name:
        return name
    lower = name.lower()
    for article in ('the ', 'a ', 'an '):
        if lower.startswith(article):
            return name[len(article):]
    return name


def _s64(val: int) -> int:
    """Convert unsigned 64-bit int to signed for SQLite INTEGER storage.

    SQLite INTEGER is signed 64-bit (max 2^63-1).  iPod db_ids and PIDs
    are unsigned 64-bit values that may exceed this limit.
    """
    if val >= (1 << 63):
        return val - (1 << 64)
    return val


# ── Schema DDL ─────────────────────────────────────────────────────────
# These CREATE TABLE statements match a real Nano 6G Library.itdb exactly.
# We issue them in dependency order.

_LIBRARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS version_info (
    id INTEGER PRIMARY KEY,
    major INTEGER,
    minor INTEGER,
    compatibility INTEGER DEFAULT 0,
    update_level INTEGER DEFAULT 0,
    device_update_level INTEGER DEFAULT 0,
    platform INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS db_info (
    pid INTEGER NOT NULL,
    primary_container_pid INTEGER,
    media_folder_url TEXT,
    audio_language INTEGER,
    subtitle_language INTEGER,
    genius_cuid TEXT,
    bib BLOB,
    rib BLOB,
    PRIMARY KEY (pid)
);

CREATE TABLE IF NOT EXISTS genre_map (
    id INTEGER NOT NULL,
    genre TEXT NOT NULL,
    genre_order INTEGER DEFAULT 0,
    is_unknown INTEGER DEFAULT 0,
    has_music INTEGER DEFAULT 0,
    artist_count_calc INTEGER DEFAULT 0 NOT NULL,
    album_count_calc INTEGER DEFAULT 0 NOT NULL,
    compilation_count_calc INTEGER DEFAULT 0 NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (genre)
);

CREATE TABLE IF NOT EXISTS location_kind_map (
    id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (kind)
);

CREATE TABLE IF NOT EXISTS category_map (
    id INTEGER NOT NULL,
    category TEXT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (category)
);

CREATE TABLE IF NOT EXISTS item (
    pid INTEGER NOT NULL,
    revision_level INTEGER,
    media_kind INTEGER DEFAULT 0,
    is_song INTEGER DEFAULT 0,
    is_audio_book INTEGER DEFAULT 0,
    is_music_video INTEGER DEFAULT 0,
    is_movie INTEGER DEFAULT 0,
    is_tv_show INTEGER DEFAULT 0,
    is_home_video INTEGER DEFAULT 0,
    is_ringtone INTEGER DEFAULT 0,
    is_tone INTEGER DEFAULT 0,
    is_voice_memo INTEGER DEFAULT 0,
    is_book INTEGER DEFAULT 0,
    is_rental INTEGER DEFAULT 0,
    is_itunes_u INTEGER DEFAULT 0,
    is_digital_booklet INTEGER DEFAULT 0,
    is_podcast INTEGER DEFAULT 0,
    date_modified INTEGER DEFAULT 0,
    year INTEGER DEFAULT 0,
    content_rating INTEGER DEFAULT 0,
    content_rating_level INTEGER DEFAULT 0,
    is_compilation INTEGER,
    is_user_disabled INTEGER DEFAULT 0,
    remember_bookmark INTEGER DEFAULT 0,
    exclude_from_shuffle INTEGER DEFAULT 0,
    part_of_gapless_album INTEGER DEFAULT 0,
    chosen_by_auto_fill INTEGER DEFAULT 0,
    artwork_status INTEGER,
    artwork_cache_id INTEGER DEFAULT 0,
    start_time_ms REAL DEFAULT 0,
    stop_time_ms REAL DEFAULT 0,
    total_time_ms REAL DEFAULT 0,
    total_burn_time_ms REAL,
    track_number INTEGER DEFAULT 0,
    track_count INTEGER DEFAULT 0,
    disc_number INTEGER DEFAULT 0,
    disc_count INTEGER DEFAULT 0,
    bpm INTEGER DEFAULT 0,
    relative_volume INTEGER,
    eq_preset TEXT,
    radio_stream_status TEXT,
    genius_id INTEGER DEFAULT 0,
    genre_id INTEGER DEFAULT 0,
    category_id INTEGER DEFAULT 0,
    album_pid INTEGER DEFAULT 0,
    artist_pid INTEGER DEFAULT 0,
    composer_pid INTEGER DEFAULT 0,
    title TEXT,
    artist TEXT,
    album TEXT,
    album_artist TEXT,
    composer TEXT,
    sort_title TEXT,
    sort_artist TEXT,
    sort_album TEXT,
    sort_album_artist TEXT,
    sort_composer TEXT,
    title_order INTEGER,
    artist_order INTEGER,
    album_order INTEGER,
    genre_order INTEGER,
    composer_order INTEGER,
    album_artist_order INTEGER,
    album_by_artist_order INTEGER,
    series_name_order INTEGER,
    comment TEXT,
    grouping TEXT,
    description TEXT,
    description_long TEXT,
    collection_description TEXT,
    copyright TEXT,
    track_artist_pid INTEGER DEFAULT 0,
    physical_order INTEGER,
    has_lyrics INTEGER DEFAULT 0,
    date_released INTEGER DEFAULT 0,
    PRIMARY KEY (pid)
);

CREATE TABLE IF NOT EXISTS album (
    pid INTEGER NOT NULL,
    kind INTEGER,
    artwork_status INTEGER,
    artwork_item_pid INTEGER,
    artist_pid INTEGER,
    user_rating INTEGER,
    name TEXT,
    name_order INTEGER,
    all_compilations INTEGER,
    feed_url TEXT,
    season_number INTEGER,
    is_unknown INTEGER DEFAULT 0,
    has_songs INTEGER DEFAULT 0,
    has_music_videos INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    artist_order INTEGER DEFAULT 0,
    has_any_compilations INTEGER DEFAULT 0,
    sort_name TEXT,
    artist_count_calc INTEGER DEFAULT 0 NOT NULL,
    has_movies INTEGER DEFAULT 0,
    item_count INTEGER DEFAULT 0,
    PRIMARY KEY (pid)
);

CREATE TABLE IF NOT EXISTS artist (
    pid INTEGER NOT NULL,
    kind INTEGER,
    artwork_status INTEGER,
    artwork_album_pid INTEGER,
    name TEXT,
    name_order INTEGER,
    sort_name TEXT,
    is_unknown INTEGER DEFAULT 0,
    has_songs INTEGER DEFAULT 0,
    has_music_videos INTEGER DEFAULT 0,
    PRIMARY KEY (pid)
);

CREATE TABLE IF NOT EXISTS track_artist (
    pid INTEGER NOT NULL,
    name TEXT,
    name_order INTEGER,
    sort_name TEXT,
    has_songs INTEGER DEFAULT 0,
    has_music_videos INTEGER DEFAULT 0,
    has_non_compilation_tracks INTEGER DEFAULT 0,
    is_unknown INTEGER DEFAULT 0,
    album_count INTEGER DEFAULT 0,
    PRIMARY KEY (pid)
);

CREATE TABLE IF NOT EXISTS composer (
    pid INTEGER NOT NULL,
    name TEXT,
    name_order INTEGER,
    sort_name TEXT,
    is_unknown INTEGER DEFAULT 0,
    has_music INTEGER DEFAULT 0,
    PRIMARY KEY (pid)
);

CREATE TABLE IF NOT EXISTS avformat_info (
    item_pid INTEGER NOT NULL,
    sub_id INTEGER NOT NULL DEFAULT 0,
    audio_format INTEGER,
    bit_rate INTEGER DEFAULT 0,
    channels INTEGER DEFAULT 0,
    sample_rate REAL DEFAULT 0,
    duration INTEGER,
    gapless_heuristic_info INTEGER,
    gapless_encoding_delay INTEGER,
    gapless_encoding_drain INTEGER,
    gapless_last_frame_resynch INTEGER,
    analysis_inhibit_flags INTEGER,
    audio_fingerprint INTEGER,
    volume_normalization_energy INTEGER,
    PRIMARY KEY (item_pid, sub_id)
);

CREATE TABLE IF NOT EXISTS container (
    pid INTEGER NOT NULL,
    distinguished_kind INTEGER,
    date_created INTEGER,
    date_modified INTEGER,
    name TEXT,
    name_order INTEGER,
    parent_pid INTEGER,
    media_kinds INTEGER,
    workout_template_id INTEGER,
    is_hidden INTEGER,
    smart_is_folder INTEGER,
    smart_is_dynamic INTEGER,
    smart_is_filtered INTEGER,
    smart_is_genius INTEGER,
    smart_enabled_only INTEGER,
    smart_is_limited INTEGER,
    smart_limit_kind INTEGER,
    smart_limit_order INTEGER,
    smart_evaluation_order INTEGER,
    smart_limit_value INTEGER,
    smart_reverse_limit_order INTEGER,
    smart_criteria BLOB,
    description TEXT,
    PRIMARY KEY (pid)
);

CREATE TABLE IF NOT EXISTS item_to_container (
    item_pid INTEGER,
    container_pid INTEGER,
    physical_order INTEGER,
    shuffle_order INTEGER
);

CREATE TABLE IF NOT EXISTS container_seed (
    container_pid INTEGER NOT NULL,
    item_pid INTEGER NOT NULL,
    seed_order INTEGER DEFAULT 0,
    UNIQUE (container_pid, item_pid)
);

CREATE TABLE IF NOT EXISTS video_info (
    item_pid INTEGER NOT NULL,
    has_alternate_audio INTEGER,
    has_subtitles INTEGER,
    characteristics_valid INTEGER,
    has_closed_captions INTEGER,
    is_self_contained INTEGER,
    is_compressed INTEGER,
    is_anamorphic INTEGER,
    is_hd INTEGER,
    season_number INTEGER,
    audio_language INTEGER,
    audio_track_index INTEGER,
    audio_track_id INTEGER,
    subtitle_language INTEGER,
    subtitle_track_index INTEGER,
    subtitle_track_id INTEGER,
    series_name TEXT,
    sort_series_name TEXT,
    episode_id TEXT,
    episode_sort_id INTEGER,
    network_name TEXT,
    extended_content_rating TEXT,
    movie_info TEXT,
    PRIMARY KEY (item_pid)
);

CREATE TABLE IF NOT EXISTS video_characteristics (
    item_pid INTEGER,
    sub_id INTEGER DEFAULT 0,
    track_id INTEGER,
    height INTEGER,
    width INTEGER,
    depth INTEGER,
    codec INTEGER,
    frame_rate REAL,
    percentage_encrypted REAL,
    bit_rate INTEGER,
    peak_bit_rate INTEGER,
    buffer_size INTEGER,
    profile INTEGER,
    level INTEGER,
    complexity_level INTEGER,
    UNIQUE (item_pid, sub_id, track_id)
);

CREATE TABLE IF NOT EXISTS podcast_info (
    item_pid INTEGER NOT NULL,
    date_released INTEGER DEFAULT 0,
    external_guid TEXT,
    feed_url TEXT,
    feed_keywords TEXT,
    PRIMARY KEY (item_pid)
);

CREATE TABLE IF NOT EXISTS store_info (
    item_pid INTEGER NOT NULL,
    store_kind INTEGER,
    date_purchased INTEGER DEFAULT 0,
    date_released INTEGER DEFAULT 0,
    account_id INTEGER,
    key_versions INTEGER,
    key_platform_id INTEGER,
    key_id INTEGER,
    key_id2 INTEGER,
    store_item_id INTEGER,
    artist_id INTEGER,
    composer_id INTEGER,
    genre_id INTEGER,
    playlist_id INTEGER,
    storefront_id INTEGER,
    store_link_id INTEGER,
    relevance REAL,
    popularity REAL,
    xid TEXT,
    flavor TEXT,
    PRIMARY KEY (item_pid)
);

CREATE TABLE IF NOT EXISTS store_link (
    id INTEGER NOT NULL,
    url TEXT,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS track_size_calc (
    pid INTEGER NOT NULL,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    PRIMARY KEY (pid),
    UNIQUE (kind)
);
"""

# Indexes match those found on a real Nano 6G Library.itdb
_LIBRARY_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_item_album_pid ON item (album_pid);
CREATE INDEX IF NOT EXISTS idx_item_track_artist_pid ON item (track_artist_pid);
CREATE INDEX IF NOT EXISTS item_album_order_idx ON item (album_order, disc_number, track_number, artist_order, sort_title, physical_order);
CREATE INDEX IF NOT EXISTS item_artist_sort_order_idx ON item (artist_order, album_order, disc_number, track_number, sort_title, physical_order);
CREATE INDEX IF NOT EXISTS item_composer_order_idx ON item (composer_pid, composer_order, media_kind);
CREATE INDEX IF NOT EXISTS item_genre_id_idx ON item (genre_id);
CREATE INDEX IF NOT EXISTS item_title_order_idx ON item (title_order, media_kind);
CREATE INDEX IF NOT EXISTS item_to_container_container_pid_idx ON item_to_container (container_pid, physical_order, item_pid);
CREATE INDEX IF NOT EXISTS item_to_container_physical_order_idx ON item_to_container (physical_order);
"""


def _sort_key(name: Optional[str]) -> str:
    """Generate a collation key for sorting.

    Uses the article-stripped form, lowercased for case-insensitive sort.
    Returns empty string for None/empty so they sort first (matching libgpod
    which returns 100 for NULL fields).
    """
    if not name:
        return ""
    return _strip_article(name).lower()


def _compute_sort_orders(tracks: list[TrackInfo]) -> dict:
    """Compute sort orders for all items, replicating libgpod compute_key_orders.

    For each order type (title, artist, album, genre, composer, album_artist),
    collect unique sort keys, sort alphabetically, and assign rank = (pos+1)*100.
    A NULL/empty key gets rank 100 (matching libgpod's default).

    Returns dict mapping order type → {sort_key → rank}.
    """
    ORDER_FIELDS = {
        'title': lambda t: t.sort_name or t.title,
        'artist': lambda t: t.sort_artist or t.artist,
        'album': lambda t: t.sort_album or t.album,
        'genre': lambda t: t.genre,
        'composer': lambda t: t.sort_composer or t.composer,
        # libgpod ORDER_ALBUM_ARTIST: sort_artist → artist (simple)
        'album_artist': lambda t: t.sort_artist or t.artist,
        # libgpod ORDER_ALBUM_BY_ARTIST: sort_albumartist → albumartist → sort_artist → artist
        'album_by_artist': lambda t: (t.sort_album_artist or t.album_artist
                                      or t.sort_artist or t.artist),
    }

    orders: dict[str, dict[str, int]] = {}
    for name, field_fn in ORDER_FIELDS.items():
        keys: set[str] = set()
        for track in tracks:
            val = field_fn(track)
            if val:
                keys.add(_sort_key(val))
        sorted_keys = sorted(keys)
        rank_map = {k: (i + 1) * 100 for i, k in enumerate(sorted_keys)}
        orders[name] = rank_map

    return orders


def _lookup_order(orders: dict, order_type: str, value: Optional[str]) -> int:
    """Look up the sort order rank for a value.  Returns 100 if not found."""
    if not value:
        return 100
    key = _sort_key(value)
    return orders.get(order_type, {}).get(key, 100)


def write_library_itdb(
    path: str,
    tracks: list[TrackInfo],
    playlists: Optional[list[PlaylistInfo]] = None,
    smart_playlists: Optional[list[PlaylistInfo]] = None,
    master_playlist_name: str = "iPod",
    db_pid: int = 0,
    tz_offset: int = 0,
) -> None:
    """Write Library.itdb SQLite database.

    Args:
        path: Output file path.
        tracks: List of TrackInfo objects (with db_id already assigned).
        playlists: User playlists (master is auto-generated).
        smart_playlists: Smart playlists for dataset 5.
        master_playlist_name: Name for the master playlist.
        db_pid: Database persistent ID (from mhbd db_id).
        tz_offset: Timezone offset in seconds (positive = east of UTC).
    """
    import os
    if os.path.exists(path):
        os.remove(path)

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA encoding='UTF-8'")
    cur = conn.cursor()

    # Create schema
    cur.executescript(_LIBRARY_SCHEMA)

    # ── version_info ───────────────────────────────────────────────────
    # Values from a real iTunes-synced Nano 6G database:
    #   major=1, minor=111, device_update_level=1104, platform=2
    cur.execute(
        "INSERT INTO version_info (id, major, minor, compatibility, "
        "update_level, device_update_level, platform) "
        "VALUES (1, 1, 111, 0, 0, 1104, 2)"
    )

    # ── db_info ────────────────────────────────────────────────────────
    # primary_container_pid will be the master playlist pid
    # media_folder_url=NULL, audio/subtitle_language=-1: matches iTunes ref
    master_pid = db_pid if db_pid else 1
    cur.execute(
        "INSERT INTO db_info (pid, primary_container_pid, media_folder_url, "
        "audio_language, subtitle_language, genius_cuid, bib, rib) "
        "VALUES (?, ?, NULL, -1, -1, NULL, NULL, NULL)",
        (_s64(db_pid), _s64(master_pid))
    )

    # ── location_kind_map ──────────────────────────────────────────────
    # IDs and names must match what iTunes writes (from real Nano 6G backup)
    cur.execute("INSERT INTO location_kind_map (id, kind) VALUES (1, 'MPEG audio file')")
    cur.execute("INSERT INTO location_kind_map (id, kind) VALUES (2, 'Purchased AAC audio file')")
    cur.execute("INSERT INTO location_kind_map (id, kind) VALUES (3, 'AAC audio file')")

    # ── Compute sort orders ────────────────────────────────────────────
    # Replicates libgpod's compute_key_orders: for each field type, collect
    # all unique sort keys, sort alphabetically, assign rank = (pos+1)*100.
    orders = _compute_sort_orders(tracks)

    # ── Collect genres ─────────────────────────────────────────────────
    genre_map: dict[str, int] = {}    # genre_name → genre_id
    genre_id_counter = 1
    for track in tracks:
        g = track.genre or ""
        if g and g not in genre_map:
            genre_map[g] = genre_id_counter
            genre_id_counter += 1

    # Compute genre_order (alphabetical rank), calc fields
    genre_sorted = sorted(genre_map.keys(), key=str.lower)
    genre_order_map: dict[str, int] = {
        g: i + 1 for i, g in enumerate(genre_sorted)
    }

    # Compute genre calc fields: artist_count, album_count, compilation_count
    genre_artists: dict[str, set] = {}    # genre → set of artist names
    genre_albums: dict[str, set] = {}     # genre → set of album keys
    genre_comp_albums: dict[str, set] = {}  # genre → set of compilation album keys
    for track in tracks:
        g = track.genre or ""
        if not g:
            continue
        aa = track.album_artist or track.artist or ""
        album_key = (track.album or "", aa)
        genre_artists.setdefault(g, set()).add(aa)
        genre_albums.setdefault(g, set()).add(album_key)
        if track.compilation:
            genre_comp_albums.setdefault(g, set()).add(album_key)

    for genre_name, gid in genre_map.items():
        g_order = genre_order_map.get(genre_name, 0)
        a_count = len(genre_artists.get(genre_name, set()))
        al_count = len(genre_albums.get(genre_name, set()))
        c_count = len(genre_comp_albums.get(genre_name, set()))
        cur.execute(
            "INSERT INTO genre_map (id, genre, genre_order, is_unknown, "
            "has_music, artist_count_calc, album_count_calc, compilation_count_calc) "
            "VALUES (?, ?, ?, 0, 1, ?, ?, ?)",
            (gid, genre_name, g_order, a_count, al_count, c_count)
        )

    # ── Collect albums, artists, composers ─────────────────────────────
    # We use stable PIDs based on name hashing.
    # Album key: (album_name, album_artist or artist)
    album_map: dict[tuple[str, str], int] = {}   # (album, artist) → pid
    artist_map: dict[str, int] = {}               # artist_name → pid
    track_artist_map: dict[str, int] = {}         # track_artist_name → pid
    composer_map: dict[str, int] = {}             # composer_name → pid
    pid_counter = 100  # Start above small IDs used for other things

    # db_id → track_id map for playlist references
    db_id_to_track_idx: dict[int, int] = {}

    for idx, track in enumerate(tracks):
        db_id_to_track_idx[track.db_id] = idx

        # Album
        album_name = track.album or ""
        album_artist_name = track.album_artist or track.artist or ""
        album_key = (album_name, album_artist_name)
        if album_key not in album_map:
            pid_counter += 1
            album_map[album_key] = pid_counter

        # Artist (album artist)
        aa = track.album_artist or track.artist or ""
        if aa and aa not in artist_map:
            pid_counter += 1
            artist_map[aa] = pid_counter

        # Track artist
        ta = track.artist or ""
        if ta and ta not in track_artist_map:
            pid_counter += 1
            track_artist_map[ta] = pid_counter

        # Composer
        comp = track.composer or ""
        if comp and comp not in composer_map:
            pid_counter += 1
            composer_map[comp] = pid_counter

    # ── Write albums ───────────────────────────────────────────────────
    # Count items per album for item_count, determine if compilation
    album_item_counts: dict[tuple[str, str], int] = {}
    album_has_compilation: dict[tuple[str, str], bool] = {}
    album_artist_pids: dict[tuple[str, str], int] = {}
    album_artwork_pids: dict[tuple[str, str], int] = {}

    for track in tracks:
        album_name = track.album or ""
        album_artist_name = track.album_artist or track.artist or ""
        key = (album_name, album_artist_name)
        album_item_counts[key] = album_item_counts.get(key, 0) + 1
        if track.compilation:
            album_has_compilation[key] = True
        # Store album artist pid
        aa = track.album_artist or track.artist or ""
        if aa and aa in artist_map:
            album_artist_pids[key] = artist_map[aa]
        # Store artwork item pid (first track in album with artwork)
        if track.mhii_link and key not in album_artwork_pids:
            album_artwork_pids[key] = track.db_id

    # Compute album sort orders: name_order = rank by sort_name, sort_order = same
    album_sort_names: dict[tuple[str, str], str] = {}
    for key in album_map:
        album_sort_names[key] = _strip_article(key[0]) if key[0] else key[0]
    album_sorted = sorted(album_map.keys(),
                          key=lambda k: _sort_key(k[0]))
    album_name_orders: dict[tuple[str, str], int] = {
        k: (i + 1) * 100 for i, k in enumerate(album_sorted)
    }

    for (album_name, album_artist_name), album_pid in album_map.items():
        key = (album_name, album_artist_name)
        is_compilation = 1 if album_has_compilation.get(key, False) else 0
        artwork_pid = album_artwork_pids.get(key, 0)
        a_pid = album_artist_pids.get(key, 0)
        item_count = album_item_counts.get(key, 0)
        is_unknown = 1 if not album_name else 0
        a_name_order = album_name_orders.get(key, 0)
        a_sort_name = album_sort_names.get(key) or None
        # artist_order for album = the album_artist order rank
        a_artist_order = _lookup_order(orders, 'album_artist', album_artist_name)

        cur.execute(
            "INSERT INTO album (pid, kind, artwork_status, artwork_item_pid, "
            "artist_pid, user_rating, name, name_order, all_compilations, "
            "feed_url, season_number, is_unknown, has_songs, has_music_videos, "
            "sort_order, artist_order, has_any_compilations, sort_name, "
            "artist_count_calc, has_movies, item_count) "
            "VALUES (?, 2, 0, ?, ?, 0, ?, ?, ?, NULL, 0, ?, 1, 0, ?, ?, ?, ?, 0, 0, ?)",
            (album_pid, _s64(artwork_pid), a_pid,
             album_name or None, a_name_order, is_compilation, is_unknown,
             a_name_order, a_artist_order, is_compilation, a_sort_name,
             item_count)
        )

    # ── Write artists ──────────────────────────────────────────────────
    artist_sorted = sorted(artist_map.keys(), key=_sort_key)
    artist_name_orders: dict[str, int] = {
        k: (i + 1) * 100 for i, k in enumerate(artist_sorted)
    }
    for artist_name, a_pid in artist_map.items():
        is_unknown = 1 if not artist_name else 0
        a_name_order = artist_name_orders.get(artist_name, 0)
        a_sort_name = _strip_article(artist_name) if artist_name else None
        cur.execute(
            "INSERT INTO artist (pid, kind, artwork_status, artwork_album_pid, "
            "name, name_order, sort_name, is_unknown, has_songs, has_music_videos) "
            "VALUES (?, 2, 0, 0, ?, ?, ?, ?, 1, 0)",
            (a_pid, artist_name or None, a_name_order, a_sort_name,
             is_unknown)
        )

    # ── Write track artists ────────────────────────────────────────────
    ta_sorted = sorted(track_artist_map.keys(), key=_sort_key)
    ta_name_orders: dict[str, int] = {
        k: (i + 1) * 100 for i, k in enumerate(ta_sorted)
    }
    for ta_name, ta_pid in track_artist_map.items():
        is_unknown = 1 if not ta_name else 0
        ta_name_order = ta_name_orders.get(ta_name, 0)
        ta_sort_name = _strip_article(ta_name) if ta_name else None
        cur.execute(
            "INSERT INTO track_artist (pid, name, name_order, sort_name, "
            "has_songs, has_music_videos, has_non_compilation_tracks, "
            "is_unknown, album_count) "
            "VALUES (?, ?, ?, ?, 1, 0, 1, ?, 0)",
            (ta_pid, ta_name or None, ta_name_order, ta_sort_name,
             is_unknown)
        )

    # ── Write composers ────────────────────────────────────────────────
    comp_sorted = sorted(composer_map.keys(), key=_sort_key)
    comp_name_orders: dict[str, int] = {
        k: (i + 1) * 100 for i, k in enumerate(comp_sorted)
    }
    for comp_name, comp_pid in composer_map.items():
        is_unknown = 1 if not comp_name else 0
        c_name_order = comp_name_orders.get(comp_name, 0)
        c_sort_name = _strip_article(comp_name) if comp_name else None
        cur.execute(
            "INSERT INTO composer (pid, name, name_order, sort_name, "
            "is_unknown, has_music) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            (comp_pid, comp_name or None, c_name_order, c_sort_name,
             is_unknown)
        )

    # ── Write items (tracks) ──────────────────────────────────────────
    now_cd = _unix_to_coredata(int(time.time()), tz_offset)

    total_audio_size = 0
    total_video_size = 0
    total_mv_size = 0

    for idx, track in enumerate(tracks):
        # Resolve foreign keys
        album_name = track.album or ""
        album_artist_name = track.album_artist or track.artist or ""
        album_key = (album_name, album_artist_name)
        album_pid = album_map.get(album_key, 0)

        aa = track.album_artist or track.artist or ""
        artist_pid = artist_map.get(aa, 0)

        ta = track.artist or ""
        ta_pid = track_artist_map.get(ta, 0)

        comp = track.composer or ""
        composer_pid = composer_map.get(comp, 0)

        genre_id = genre_map.get(track.genre or "", 0)

        media_kind = _media_kind(track)

        # Accumulate track_size_calc
        if media_kind == MEDIA_KIND_MUSIC_VIDEO:
            total_mv_size += track.size
        elif media_kind in (MEDIA_KIND_MOVIE, MEDIA_KIND_TV_SHOW):
            total_video_size += track.size
        else:
            total_audio_size += track.size

        # Timestamps
        date_mod = _unix_to_coredata(track.last_modified or track.date_added, tz_offset) if (track.last_modified or track.date_added) else now_cd
        date_released = _unix_to_coredata(track.date_released, tz_offset) if track.date_released else 0

        # Artwork: iTunes uses artwork_status=1 when art is present
        art_status = 1 if track.mhii_link else 0
        art_cache_id = track.mhii_link or 0

        has_lyrics = 1 if (track.has_lyrics or track.lyrics) else 0

        # Sort fields: fall back to article-stripped name (matches iTunes/libgpod)
        sort_title = track.sort_name or _strip_article(track.title) if track.title else None
        sort_artist = track.sort_artist or _strip_article(track.artist) if track.artist else None
        sort_album = track.sort_album or _strip_article(track.album) if track.album else None
        sort_aa = (track.sort_album_artist or _strip_article(track.album_artist)
                   if track.album_artist else
                   (track.sort_artist or _strip_article(track.artist) if track.artist else None))
        sort_composer = track.sort_composer or _strip_article(track.composer) if track.composer else None

        # Order ranks from pre-computed sort orders
        title_order = _lookup_order(orders, 'title', track.sort_name or track.title)
        artist_order = _lookup_order(orders, 'artist', track.sort_artist or track.artist)
        album_order = _lookup_order(orders, 'album', track.sort_album or track.album)
        genre_order = _lookup_order(orders, 'genre', track.genre)
        composer_order = _lookup_order(orders, 'composer', track.sort_composer or track.composer)
        aa_order = _lookup_order(orders, 'album_artist',
                                 track.sort_artist or track.artist)
        aba_order = _lookup_order(orders, 'album_by_artist',
                                  track.sort_album_artist or track.album_artist
                                  or track.sort_artist or track.artist)

        cur.execute(
            """INSERT INTO item (
                pid, revision_level, media_kind,
                is_song, is_audio_book, is_music_video, is_movie,
                is_tv_show, is_home_video, is_ringtone, is_tone,
                is_voice_memo, is_book, is_rental, is_itunes_u,
                is_digital_booklet, is_podcast,
                date_modified, year,
                content_rating, content_rating_level,
                is_compilation, is_user_disabled,
                remember_bookmark, exclude_from_shuffle,
                part_of_gapless_album, chosen_by_auto_fill,
                artwork_status, artwork_cache_id,
                start_time_ms, stop_time_ms, total_time_ms, total_burn_time_ms,
                track_number, track_count, disc_number, disc_count,
                bpm, relative_volume, eq_preset, radio_stream_status,
                genius_id, genre_id, category_id,
                album_pid, artist_pid, composer_pid,
                title, artist, album, album_artist, composer,
                sort_title, sort_artist, sort_album,
                sort_album_artist, sort_composer,
                title_order, artist_order, album_order,
                genre_order, composer_order,
                album_artist_order, album_by_artist_order,
                series_name_order,
                comment, grouping,
                description, description_long,
                collection_description, copyright,
                track_artist_pid, physical_order,
                has_lyrics, date_released
            ) VALUES (
                ?, NULL, ?,
                ?, ?, ?, ?,
                ?, 0, ?, 0,
                0, 0, 0, 0,
                0, ?,
                ?, ?,
                ?, 0,
                ?, ?,
                ?, ?,
                ?, 0,
                ?, ?,
                ?, ?, ?, NULL,
                ?, ?, ?, ?,
                ?, ?, ?, NULL,
                0, ?, 0,
                ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?,
                ?, ?,
                ?, NULL,
                NULL, NULL,
                ?, ?,
                ?, ?
            )""",
            (
                _s64(track.db_id), media_kind,
                _is_song(track), _is_audio_book(track), _is_music_video(track), _is_movie(track),
                _is_tv_show(track), _is_ringtone(track),
                _is_podcast(track),
                date_mod, track.year,
                track.explicit_flag,
                1 if track.compilation else 0, 1 if track.checked else 0,
                1 if track.remember_position else 0, 1 if track.skip_when_shuffling else 0,
                1 if track.gapless_album_flag else 0,
                art_status, art_cache_id,
                float(track.start_time), float(track.stop_time),
                float(track.length),
                track.track_number, track.total_tracks, track.disc_number, track.total_discs,
                track.bpm, track.volume, track.eq_setting,
                genre_id,
                album_pid, artist_pid, composer_pid,
                track.title, track.artist, track.album,
                track.album_artist, track.composer,
                sort_title, sort_artist, sort_album,
                sort_aa, sort_composer,
                title_order, artist_order, album_order,
                genre_order, composer_order,
                aa_order, aba_order,
                100,
                track.comment, track.grouping,
                track.description,
                ta_pid, idx,
                has_lyrics, date_released,
            )
        )

        # ── avformat_info ──────────────────────────────────────────────
        ft = track.filetype.lower()
        audio_format = _FILETYPE_TO_AUDIO_FORMAT.get(ft, AUDIO_FORMAT_MP3)
        # Detect ALAC: M4A container + high bitrate (ALAC >= ~500 kbps,
        # AAC caps at ~330 kbps)
        if ft in ('m4a', 'm4b') and track.bitrate > 500:
            audio_format = AUDIO_FORMAT_ALAC
        # Duration in avformat_info is in SAMPLES, not milliseconds.
        # libgpod writes 0 ("iTunes sometimes set it to 0"); we compute
        # when sample_rate is available, else 0.
        duration_samples = int(track.length * track.sample_rate / 1000) if track.sample_rate else 0

        cur.execute(
            """INSERT INTO avformat_info (
                item_pid, sub_id, audio_format, bit_rate, channels,
                sample_rate, duration,
                gapless_heuristic_info, gapless_encoding_delay,
                gapless_encoding_drain, gapless_last_frame_resynch,
                analysis_inhibit_flags, audio_fingerprint,
                volume_normalization_energy
            ) VALUES (?, 0, ?, ?, 0, ?, ?, ?, ?, ?, ?, 0, 0, ?)""",
            (
                _s64(track.db_id), audio_format, track.bitrate,
                float(track.sample_rate), duration_samples,
                track.gapless_track_flag, track.pregap, track.postgap,
                track.gapless_data,
                track.sound_check,
            )
        )

    # ── track_size_calc ────────────────────────────────────────────────
    # Three rows: audio, video, music_video with total file sizes
    cur.execute("INSERT INTO track_size_calc (pid, kind, size) VALUES (1, 'audio', ?)",
                (total_audio_size,))
    cur.execute("INSERT INTO track_size_calc (pid, kind, size) VALUES (2, 'video', ?)",
                (total_video_size,))
    cur.execute("INSERT INTO track_size_calc (pid, kind, size) VALUES (3, 'music_video', ?)",
                (total_mv_size,))

    # ── Write containers (playlists) ───────────────────────────────────
    # Master playlist: distinguished_kind=0, is_hidden=1 (SQLite schema), smart fields=NULL
    # (matches iTunes reference — NOT distinguished_kind=2)
    container_pos = 0
    cur.execute(
        """INSERT INTO container (
            pid, distinguished_kind, date_created, date_modified,
            name, name_order, parent_pid, media_kinds,
            workout_template_id, is_hidden,
            smart_is_folder, smart_is_dynamic, smart_is_filtered,
            smart_is_genius, smart_enabled_only, smart_is_limited,
            smart_limit_kind, smart_limit_order, smart_evaluation_order,
            smart_limit_value, smart_reverse_limit_order,
            smart_criteria, description
        ) VALUES (?, 0, ?, ?, ?, ?, 0, 1, 0, 1,
                  0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                  NULL, NULL, NULL, NULL)""",
        (_s64(master_pid), now_cd, now_cd, master_playlist_name,
         (container_pos + 1) * 100)
    )
    container_pos += 1

    # Master playlist contains all tracks
    for idx, track in enumerate(tracks):
        cur.execute(
            "INSERT INTO item_to_container (item_pid, container_pid, physical_order, shuffle_order) "
            "VALUES (?, ?, ?, NULL)",
            (_s64(track.db_id), _s64(master_pid), idx)
        )

    # User playlists
    playlist_pid_counter = master_pid + 1
    for pl in (playlists or []):
        pl_pid = playlist_pid_counter
        playlist_pid_counter += 1

        cur.execute(
            """INSERT INTO container (
                pid, distinguished_kind, date_created, date_modified,
                name, name_order, parent_pid, media_kinds,
                workout_template_id, is_hidden,
                smart_is_folder, smart_is_dynamic, smart_is_filtered,
                smart_is_genius, smart_enabled_only, smart_is_limited,
                smart_limit_kind, smart_limit_order, smart_evaluation_order,
                smart_limit_value, smart_reverse_limit_order,
                smart_criteria, description
            ) VALUES (?, 0, ?, ?, ?, ?, 0, 1, 0, 0,
                      0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                      NULL, NULL, NULL, NULL)""",
            (_s64(pl_pid), now_cd, now_cd, pl.name,
             (container_pos + 1) * 100)
        )
        container_pos += 1

        for order, db_id in enumerate(pl.track_ids):
            if db_id in db_id_to_track_idx:
                cur.execute(
                    "INSERT INTO item_to_container (item_pid, container_pid, physical_order, shuffle_order) "
                    "VALUES (?, ?, ?, NULL)",
                    (_s64(db_id), _s64(pl_pid), order)
                )

    # Smart playlists
    for spl in (smart_playlists or []):
        spl_pid = playlist_pid_counter
        playlist_pid_counter += 1

        # Determine smart playlist SQLite fields from SmartPlaylistPrefs
        spl_is_limited = 0
        spl_limit_kind = 2   # default: MB
        spl_limit_order = 2  # default: random
        spl_limit_value = 25
        spl_eval_order = 1   # default: 1 (from ref)
        spl_reverse = 0
        spl_criteria = None

        if spl.smart_prefs is not None:
            spl_is_limited = 1 if spl.smart_prefs.check_limits else 0
            spl_limit_kind = spl.smart_prefs.limit_type
            spl_limit_order = spl.smart_prefs.limit_sort
            spl_limit_value = spl.smart_prefs.limit_value

        # Build smart_criteria blob from rules (SLst format)
        if spl.smart_rules is not None:
            from iTunesDB_Writer.mhod_spl_writer import write_mhod51
            # write_mhod51 returns a full MHOD (24-byte header + SLst body).
            # smart_criteria in SQLite stores the raw SLst blob (starts with
            # b'SLst'), so we strip the 24-byte MHOD header.
            mhod51_data = write_mhod51(spl.smart_rules)
            if len(mhod51_data) > 24:
                spl_criteria = mhod51_data[24:]

        # Distinguished kind for smart playlists (from ref):
        #   4 = Music, 5 = Audiobooks
        dk = 0
        if spl.mhsd5_type == 1:   # music
            dk = 4
        elif spl.mhsd5_type == 5:  # audiobooks
            dk = 5

        # media_kinds: 1=music, 0=audiobooks (from ref)
        spl_media_kinds = 1 if dk == 4 else (0 if dk == 5 else 1)

        # is_hidden maps from PlaylistInfo.master:
        #   - For ds5 built-in categories (Music, Audiobooks, ...),
        #     master=True → is_hidden=1.  This matches Apple's reference
        #     SQLite databases where system categories are hidden.
        #   - For regular user smart playlists, master=False → is_hidden=0.
        cur.execute(
            """INSERT INTO container (
                pid, distinguished_kind, date_created, date_modified,
                name, name_order, parent_pid, media_kinds,
                workout_template_id, is_hidden,
                smart_is_folder, smart_is_dynamic, smart_is_filtered,
                smart_is_genius, smart_enabled_only, smart_is_limited,
                smart_limit_kind, smart_limit_order, smart_evaluation_order,
                smart_limit_value, smart_reverse_limit_order,
                smart_criteria, description
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, 0, ?,
                      0, 1, 1, 0, 0, ?, ?, ?, ?, ?, ?,
                      ?, NULL)""",
            (_s64(spl_pid), dk, now_cd, now_cd, spl.name,
             (container_pos + 1) * 100, spl_media_kinds,
             1 if spl.master else 0,
             spl_is_limited, spl_limit_kind, spl_limit_order,
             spl_eval_order, spl_limit_value, spl_reverse,
             spl_criteria)
        )
        container_pos += 1

        # Add evaluated track list for smart playlists
        for order, db_id in enumerate(spl.track_ids):
            if db_id in db_id_to_track_idx:
                cur.execute(
                    "INSERT INTO item_to_container (item_pid, container_pid, physical_order, shuffle_order) "
                    "VALUES (?, ?, ?, NULL)",
                    (_s64(db_id), _s64(spl_pid), order)
                )

    # ── Create indexes ─────────────────────────────────────────────────
    cur.executescript(_LIBRARY_INDEXES)

    conn.commit()
    conn.close()

    logger.info("Wrote Library.itdb: %d tracks, %d albums, %d artists, "
                "%d composers, %d genres, %d containers",
                len(tracks), len(album_map), len(artist_map),
                len(composer_map), len(genre_map),
                1 + len(playlists or []) + len(smart_playlists or []))
