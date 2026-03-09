"""
MHIT Writer — Write track item chunks for iTunesDB.

MHIT chunks contain all metadata for a single track, plus child MHOD
chunks for strings (title, artist, path, etc.).

The binary layout of the header is defined declaratively in
``iTunesDB_Shared.field_defs.MHIT_FIELDS``.  This writer builds a
values dict and delegates serialization to ``write_fields()``,
guaranteeing that field offsets / sizes / transforms stay in sync
with the parser.

Cross-referenced against:
  - iTunesDB_Shared/field_defs.py (single source of truth for offsets)
  - iTunesDB_Parser/mhit_parser.py parse_trackItem()
  - libgpod itdb_itunesdb.c: mk_mhit()
  - iPodLinux wiki MHIT documentation
"""

import time
import random
from dataclasses import dataclass
from typing import Optional

from iTunesDB_Shared.constants import (
    AUDIO_FORMAT_FLAG_DEFAULT,
    AUDIO_FORMAT_FLAG_MAP,
    FILETYPE_CODES,
    MEDIA_TYPE_AUDIO,
    MEDIA_TYPE_MUSIC_VIDEO,
    MEDIA_TYPE_PODCAST,
    MEDIA_TYPE_TV_SHOW,
    MEDIA_TYPE_VIDEO,
    MEDIA_TYPE_VIDEO_PODCAST,
)
from iTunesDB_Shared.field_base import write_fields, write_generic_header
from iTunesDB_Shared.mhit_defs import MHIT_HEADER_SIZE
from .mhod_writer import write_track_mhods


def generate_dbid() -> int:
    """Generate a random 64-bit database ID for a track."""
    return random.getrandbits(64)


@dataclass
class TrackInfo:
    """Track metadata for writing to iTunesDB."""

    # Required
    title: str
    location: str  # iPod path like ":iPod_Control:Music:F00:ABCD.mp3"

    # File info
    size: int = 0  # File size in bytes
    length: int = 0  # Duration in milliseconds
    filetype: str = 'mp3'  # mp3, m4a, m4p, etc.
    bitrate: int = 0  # kbps
    sample_rate: int = 44100  # Hz
    vbr: bool = False

    # Metadata
    artist: Optional[str] = None
    album: Optional[str] = None
    album_artist: Optional[str] = None
    genre: Optional[str] = None
    composer: Optional[str] = None
    comment: Optional[str] = None
    year: int = 0
    track_number: int = 0
    total_tracks: int = 0
    disc_number: int = 1
    total_discs: int = 1
    bpm: int = 0
    compilation: bool = False

    # Playback
    rating: int = 0  # 0-100 (stars × 20)
    play_count: int = 0
    skip_count: int = 0
    volume: int = 0  # -255 to +255
    start_time: int = 0  # ms
    stop_time: int = 0  # ms
    sound_check: int = 0  # Volume normalization value (from ReplayGain)
    bookmark_time: int = 0  # Resume position in ms (audiobooks/podcasts)
    checked: int = 0  # 0 = checked/enabled, 1 = unchecked/disabled

    # Gapless playback
    gapless_data: int = 0  # Gapless playback encoder delay data
    gapless_track_flag: int = 0  # 1 = track has gapless info
    gapless_album_flag: int = 0  # 1 = album is gapless
    pregap: int = 0  # Encoder pregap samples
    postgap: int = 0  # Encoder postgap/padding samples (0xC8)
    sample_count: int = 0  # Total decoded sample count (64-bit)
    encoder_flag: int = 0  # 0xCC: 0x01=MP3 encoder, 0x00=other

    # Track flags
    skip_when_shuffling: bool = False  # 1 = skip in shuffle mode
    remember_position: bool = False    # 1 = resume from bookmark (audiobooks)
    podcast_flag: int = 0  # 0xA7: 0x00=normal, 0x01/0x02=podcast
    movie_file_flag: int = 0  # 0xB1: 0x01=video/movie file, 0x00=audio
    played_mark: int = -1  # 0xB2: -1=auto (derive from play_count), 0x01=played, 0x02=unplayed
    explicit_flag: int = 0  # 0=none, 1=explicit, 2=clean
    purchased_aac_flag: int = 0  # 0x93: 1 for M4A/iTunes purchases, 0 for most MP3s
    has_lyrics: bool = False  # True if track has embedded lyrics
    lyrics: Optional[str] = None  # Full lyrics text (MHOD type 10)
    eq_setting: Optional[str] = None  # EQ preset name (MHOD type 7), e.g. "Bass Booster"

    # Timestamps (Unix)
    date_added: int = 0  # Will be set to now if 0
    date_released: int = 0
    last_modified: int = 0  # 0x20: file modification time (0 = use date_added)
    last_played: int = 0
    last_skipped: int = 0

    # iPod-specific
    track_id: int = 0  # Will be assigned during write
    dbid: int = 0  # Will be generated if 0
    media_type: int = MEDIA_TYPE_AUDIO
    season_number: int = 0  # 0xD4: TV show season number
    episode_number: int = 0  # 0xD8: TV show episode number
    artwork_count: int = 0
    artwork_size: int = 0
    mhii_link: int = 0  # Link to ArtworkDB
    album_id: int = 0  # Links to MHIA album entry

    # Sorting
    sort_artist: Optional[str] = None
    sort_name: Optional[str] = None
    sort_album: Optional[str] = None
    sort_album_artist: Optional[str] = None
    sort_composer: Optional[str] = None

    # Extra string metadata
    grouping: Optional[str] = None
    keywords: Optional[str] = None  # MHOD type 24 (track keywords)

    # Podcast string metadata (written as MHODs)
    podcast_enclosure_url: Optional[str] = None  # MHOD type 15
    podcast_rss_url: Optional[str] = None        # MHOD type 16
    category: Optional[str] = None               # MHOD type 9

    # Video string metadata (written as MHODs)
    description: Optional[str] = None       # MHOD type 14
    subtitle: Optional[str] = None          # MHOD type 18
    show_name: Optional[str] = None         # MHOD type 19 (TV show name)
    episode_id: Optional[str] = None        # MHOD type 20 (e.g. "S01E05")
    network_name: Optional[str] = None      # MHOD type 21 (TV network)
    sort_show: Optional[str] = None         # MHOD type 31
    show_locale: Optional[str] = None       # MHOD type 25 (show locale, e.g. "en_US")

    # Filetype description
    filetype_desc: Optional[str] = None  # e.g., "MPEG audio file"

    # Round-trip fields (preserved from existing iPod database)
    user_id: int = 0      # 0x64: DRM user ID (preserved for round-trip)
    app_rating: int = 0   # 0x79: Application-computed rating (preserved for round-trip)
    mpeg_audio_type: int = 0  # 0x90: MPEG Audio Object Type (12=MP3, 51=AAC, 41=Audible)

    # iTunes Store metadata (round-trip, only for Store purchases)
    date_added_to_itunes: int = 0    # 0xDC: Unix ts, original iTunes library add date
    store_track_id: int = 0          # 0xE0: iTunes Store per-track content ID
    store_encoder_version: int = 0   # 0xE4: iTunes version that encoded the file
    store_artist_id: int = 0         # 0xE8: iTunes Store artist/collection ID
    store_album_id: int = 0          # 0xF0: iTunes Store album ID
    store_content_flag: int = 0      # 0xF4: iTunes Store content type flag

    # Internal IDs (assigned during database write, NOT user-provided)
    artist_id: int = 0   # Links to artist entry (assigned by writer)
    composer_id: int = 0  # Links to composer entry (assigned by writer)

    # Chapter data (MHOD type 17) — list of {"startpos": ms, "title": str}
    chapter_data: Optional[dict] = None


def _compute_sort_indicators(track: TrackInfo) -> bytes:
    """Build the 8-byte sort_mhod_indicators field from sort field presence.

    Byte layout (verified via exhaustive bit-correlation across 9 databases):
      [0] = sort_title (MHOD 27)
      [1] = sort_album (MHOD 28)
      [2] = sort_artist (MHOD 23)
      [3] = sort_album_artist (MHOD 29)
      [4] = sort_composer (MHOD 30)
      [5] = sort_show (MHOD 31)
      [6..7] = unused (always 0)

    bit 0 = has corresponding sort MHOD override
    bit 7 = collation flag (0x80), always set for compatibility
    """
    ind = bytearray(8)
    ind[0] = 0x81 if track.sort_name else 0x80
    ind[1] = 0x81 if track.sort_album else 0x80
    ind[2] = 0x81 if track.sort_artist else 0x80
    ind[3] = 0x81 if track.sort_album_artist else 0x80
    ind[4] = 0x81 if track.sort_composer else 0x80
    ind[5] = 0x81 if track.sort_show else 0x80
    return bytes(ind)


def _resolve_media_type(track: TrackInfo, capabilities) -> int:
    """Downgrade media type when the device lacks required capability."""
    media_type = track.media_type
    if capabilities is None:
        return media_type
    if not capabilities.supports_video:
        if media_type in (MEDIA_TYPE_VIDEO, MEDIA_TYPE_MUSIC_VIDEO, MEDIA_TYPE_TV_SHOW):
            return MEDIA_TYPE_AUDIO
        if media_type == MEDIA_TYPE_VIDEO_PODCAST:
            return MEDIA_TYPE_PODCAST
    if not capabilities.supports_podcast:
        if media_type in (MEDIA_TYPE_PODCAST, MEDIA_TYPE_VIDEO_PODCAST):
            return MEDIA_TYPE_AUDIO
    return media_type


def _resolve_movie_flag(track: TrackInfo, media_type: int) -> int:
    """Derive movie_flag from media_type when not explicitly set."""
    if track.movie_file_flag != 0:
        return track.movie_file_flag
    if media_type in (MEDIA_TYPE_VIDEO, MEDIA_TYPE_MUSIC_VIDEO,
                      MEDIA_TYPE_TV_SHOW, MEDIA_TYPE_VIDEO_PODCAST):
        return 1
    return 0


def _resolve_not_played(track: TrackInfo) -> int:
    """Resolve the not_played_flag: auto-derive from play_count when -1."""
    if track.played_mark >= 0:
        return track.played_mark
    return 0x01 if track.play_count > 0 else 0x02


def _gapless_or_zero(value: int, capabilities) -> int:
    """Return *value* when the device supports gapless, else 0."""
    if capabilities is not None and not capabilities.supports_gapless:
        return 0
    return value


def write_mhit(track: TrackInfo, track_id: int, id_0x24: int = 0,
               capabilities=None) -> bytes:
    """Write a complete MHIT chunk with all child MHODs.

    Args:
        track: TrackInfo dataclass with all track metadata.
        track_id: Unique track ID within this database.
        id_0x24: Database-wide ID from MHBD offset 0x24 (written into every track).
        capabilities: Optional DeviceCapabilities for gapless/video filtering.

    Returns:
        Complete MHIT chunk bytes (header + MHODs).
    """
    if track.dbid == 0:
        track.dbid = generate_dbid()
    if track.date_added == 0:
        track.date_added = int(time.time())

    filetype_code = FILETYPE_CODES.get(track.filetype.lower(), FILETYPE_CODES['mp3'])
    ft = track.filetype.lower()
    media_type = _resolve_media_type(track, capabilities)
    has_lyrics = track.has_lyrics or bool(track.lyrics)

    # Build child MHODs first to know count + size.
    mhod_data, mhod_count = write_track_mhods(
        title=track.title, location=track.location,
        artist=track.artist, album=track.album, genre=track.genre,
        album_artist=track.album_artist, composer=track.composer,
        comment=track.comment, filetype_desc=track.filetype_desc,
        sort_artist=track.sort_artist, sort_name=track.sort_name,
        sort_album=track.sort_album, sort_album_artist=track.sort_album_artist,
        sort_composer=track.sort_composer, grouping=track.grouping,
        keywords=track.keywords, description=track.description,
        subtitle=track.subtitle, show_name=track.show_name,
        episode_id=track.episode_id, network_name=track.network_name,
        sort_show=track.sort_show, show_locale=track.show_locale,
        podcast_enclosure_url=track.podcast_enclosure_url,
        podcast_rss_url=track.podcast_rss_url, category=track.category,
        lyrics=track.lyrics, eq_setting=track.eq_setting,
        chapter_data=track.chapter_data,
    )

    total_length = MHIT_HEADER_SIZE + len(mhod_data)

    # Assemble the values dict — write_fields handles transforms & packing.
    values: dict = {
        'child_count': mhod_count,
        'track_id': track_id,
        'visible': 1,
        'filetype': filetype_code,
        'vbr_flag': 1 if track.vbr else 0,
        'mp3_flag': 1 if ft == 'mp3' else 0,
        'compilation_flag': 1 if track.compilation else 0,
        'rating': track.rating,
        'last_modified': track.last_modified or track.date_added,
        'size': track.size,
        'length': track.length,
        'track_number': track.track_number,
        'total_tracks': track.total_tracks,
        'year': track.year,
        'bitrate': track.bitrate,
        'sample_rate_1': track.sample_rate,
        'volume': track.volume,
        'start_time': track.start_time,
        'stop_time': track.stop_time,
        'sound_check': track.sound_check,
        'play_count_1': track.play_count,
        'play_count_2': 0,  # reset after sync
        'last_played': track.last_played,
        'disc_number': track.disc_number,
        'total_discs': track.total_discs,
        'user_id': track.user_id,
        'date_added': track.date_added,
        'bookmark_time': track.bookmark_time,
        'db_id': track.dbid,
        'checked_flag': track.checked,
        'app_rating': track.app_rating,
        'bpm': track.bpm,
        'artwork_count': track.artwork_count,
        'audio_format_flag': AUDIO_FORMAT_FLAG_MAP.get(ft, AUDIO_FORMAT_FLAG_DEFAULT),
        'artwork_size': track.artwork_size,
        'sample_rate_2': float(track.sample_rate),
        'date_released': track.date_released,
        'mpeg_audio_type': track.mpeg_audio_type,
        'explicit_flag': track.explicit_flag,
        'purchased_aac_flag': track.purchased_aac_flag,
        # Extended fields
        'skip_count': track.skip_count,
        'last_skipped': track.last_skipped,
        'has_artwork': 1 if track.artwork_count > 0 else 2,
        'skip_when_shuffling': 1 if track.skip_when_shuffling else 0,
        'remember_position': 1 if track.remember_position else 0,
        'use_podcast_now_playing_flag': track.podcast_flag,
        'db_id_2': track.dbid,
        'lyrics_flag': 1 if has_lyrics else 0,
        'movie_flag': _resolve_movie_flag(track, media_type),
        'not_played_flag': _resolve_not_played(track),
        'pregap': _gapless_or_zero(track.pregap, capabilities),
        'sample_count': _gapless_or_zero(track.sample_count, capabilities),
        'postgap': _gapless_or_zero(track.postgap, capabilities),
        'encoder': track.encoder_flag,
        'media_type': media_type,
        'season_number': track.season_number,
        'episode_number': track.episode_number,
        'date_added_to_itunes': track.date_added_to_itunes,
        'store_track_id': track.store_track_id,
        'store_encoder_version': track.store_encoder_version,
        'store_artist_id': track.store_artist_id,
        'store_album_id': track.store_album_id,
        'store_content_flag': track.store_content_flag,
        'gapless_audio_payload_size': _gapless_or_zero(track.gapless_data, capabilities),
        'gapless_track_flag': _gapless_or_zero(track.gapless_track_flag, capabilities),
        'gapless_album_flag': _gapless_or_zero(track.gapless_album_flag, capabilities),
        'album_id': track.album_id,
        'mhbd_id_ref': id_0x24,
        'size_2': track.size,
        'sort_mhod_indicators': _compute_sort_indicators(track),
        'artwork_id_ref': track.mhii_link,
        'artist_id_ref': track.artist_id,
        'composer_id': track.composer_id,
    }

    header = bytearray(MHIT_HEADER_SIZE)
    write_generic_header(header, 0, b'mhit', MHIT_HEADER_SIZE, total_length)
    write_fields(header, 0, 'mhit', values, MHIT_HEADER_SIZE)

    return bytes(header) + mhod_data
