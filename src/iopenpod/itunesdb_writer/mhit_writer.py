"""
MHIT Writer — Write track item chunks for iTunesDB.

MHIT chunks contain all metadata for a single track, plus child MHOD
chunks for strings (title, artist, path, etc.).

The binary layout of the header is defined declaratively in
``iopenpod.itunesdb_shared.field_defs.MHIT_FIELDS``.  This writer builds a
values dict and delegates serialization to ``write_fields()``,
guaranteeing that field offsets / sizes / transforms stay in sync
with the parser.

Cross-referenced against:
  - src/iopenpod/itunesdb_shared/field_defs.py (single source of truth for offsets)
  - src/iopenpod/itunesdb_parser/mhit_parser.py parse_trackItem()
  - libgpod itdb_itunesdb.c: mk_mhit()
  - iPodLinux wiki MHIT documentation
"""

import math
import random
import time
from dataclasses import dataclass
from typing import Any

from iopenpod.itunesdb_shared.constants import (
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
from iopenpod.itunesdb_shared.field_base import write_fields, write_generic_header
from iopenpod.itunesdb_shared.mhit_defs import MHIT_HEADER_SIZE, mhit_header_size_for_version

from .mhod_writer import write_track_mhods


def generate_db_track_id() -> int:
    """Generate a random 64-bit persistent ID for a track."""
    return random.getrandbits(64)


generate_db_id = generate_db_track_id

_U8_MAX = 0xFF
_U16_MAX = 0xFFFF
_U32_MAX = 0xFFFFFFFF
_U64_MAX = 0xFFFFFFFFFFFFFFFF
_DEFAULT_SAMPLE_RATE = 44100
_MAX_IPOD_SAMPLE_RATE = 48000
_MIN_AUDIO_SAMPLE_RATE = 8000


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
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    genre: str | None = None
    composer: str | None = None
    comment: str | None = None
    year: int = 0
    track_number: int = 0
    total_tracks: int = 0
    disc_number: int = 1
    total_discs: int = 1
    bpm: int = 0
    compilation_flag: bool = False

    # Playback
    rating: int = 0  # 0-100 (stars × 20)
    play_count: int = 0
    play_count_2: int = 0
    skip_count: int = 0
    volume: int = 0  # -255 to +255
    start_time: int = 0  # ms
    stop_time: int = 0  # ms
    sound_check: int = 0  # Volume normalization value (from ReplayGain)
    bookmark_time: int = 0  # Resume position in ms (audiobooks/podcasts)
    checked_flag: int = 0  # 0 = checked/enabled, 1 = unchecked/disabled

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
    lyrics: str | None = None  # Full lyrics text (MHOD type 10)
    eq_setting: str | None = None  # EQ preset name (MHOD type 7), e.g. "Bass Booster"

    # Timestamps (Unix)
    date_added: int = 0  # Will be set to now if 0
    date_released: int = 0
    last_modified: int = 0  # 0x20: file modification time (0 = use date_added)
    last_played: int = 0
    last_skipped: int = 0

    # iPod-specific
    track_id: int = 0  # Will be assigned during write
    db_track_id: int = 0  # Will be generated if 0
    media_type: int = MEDIA_TYPE_AUDIO
    season_number: int = 0  # 0xD4: TV show season number
    episode_number: int = 0  # 0xD8: TV show episode number
    artwork_count: int = 0
    artwork_size: int = 0
    mhii_link: int = 0  # Link to ArtworkDB
    album_id: int = 0  # Links to MHIA album entry
    source_path: str | None = None  # PC source path; internal write-time helper context
    source_relative_path: str | None = None  # PC path relative to library root, if known

    # Sorting
    sort_artist: str | None = None
    sort_name: str | None = None
    sort_album: str | None = None
    sort_album_artist: str | None = None
    sort_composer: str | None = None

    # Extra string metadata
    grouping: str | None = None
    keywords: str | None = None  # MHOD type 24 (track keywords)

    # Podcast string metadata (written as MHODs)
    podcast_enclosure_url: str | None = None  # MHOD type 15
    podcast_rss_url: str | None = None        # MHOD type 16
    category: str | None = None               # MHOD type 9

    # Video string metadata (written as MHODs)
    description: str | None = None       # MHOD type 14
    subtitle: str | None = None          # MHOD type 18
    show_name: str | None = None         # MHOD type 19 (TV show name)
    episode_id: str | None = None        # MHOD type 20 (e.g. "S01E05")
    network_name: str | None = None      # MHOD type 21 (TV network)
    sort_show: str | None = None         # MHOD type 31
    show_locale: str | None = None       # MHOD type 25 (show locale, e.g. "en_US")

    # Filetype description
    filetype_desc: str | None = None  # e.g., "MPEG audio file"

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

    # Chapter data (MHOD type 17) lives in iTunesDB, independent of filetype.
    chapter_data: dict | None = None

    # Internal sync hint (transient, not written to database)
    # Used by ArtworkDB writer to determine preservation strategy:
    # "preserve_existing" = use existing art without re-encoding
    # "clear_art" = remove art for this track
    # "" (empty) = normal processing
    _iop_artwork_sync_hint: str = ""

    @property
    def db_id(self) -> int:
        """Backward-compatible alias for the track persistent ID."""
        return self.db_track_id

    @db_id.setter
    def db_id(self, value: int) -> None:
        self.db_track_id = value


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


def _int_or_default(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, float) and not math.isfinite(value):
            return default
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _clamp_int(value: Any, lower: int, upper: int, default: int = 0) -> int:
    number = _int_or_default(value, default)
    return max(lower, min(upper, number))


def _u8(value: Any, default: int = 0) -> int:
    return _clamp_int(value, 0, _U8_MAX, default)


def _u16(value: Any, default: int = 0) -> int:
    return _clamp_int(value, 0, _U16_MAX, default)


def _u32(value: Any, default: int = 0) -> int:
    return _clamp_int(value, 0, _U32_MAX, default)


def _u64(value: Any, default: int = 0) -> int:
    return _clamp_int(value, 0, _U64_MAX, default)


def _bool_flag(value: Any) -> bool:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"", "0", "false", "no", "off"}:
            return False
        if normalized in {"1", "true", "yes", "on"}:
            return True
    return bool(value)


def _text_or_default(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _normalize_ipod_location(value: Any) -> str:
    location = _text_or_default(value, "")
    if not location:
        raise ValueError("track iPod location is empty")
    if not location.startswith(":iPod_Control:"):
        raise ValueError(f"track iPod location must be an iPod path, got {location!r}")
    return location


def _normalize_filetype(value: Any) -> str:
    filetype = str(value or "mp3").strip().lower().lstrip(".")
    return filetype or "mp3"


def _normalize_sample_rate(value: Any) -> int:
    sample_rate = _int_or_default(value, _DEFAULT_SAMPLE_RATE)
    if sample_rate < _MIN_AUDIO_SAMPLE_RATE:
        return _DEFAULT_SAMPLE_RATE
    return min(sample_rate, _MAX_IPOD_SAMPLE_RATE)


def _normalize_trim_times(
    length: int,
    start_time: Any,
    stop_time: Any,
    bookmark_time: Any,
) -> tuple[int, int, int]:
    start = _u32(start_time)
    stop = _u32(stop_time)
    bookmark = _u32(bookmark_time)

    if length:
        start_invalid = start >= length
        if start >= length:
            start = 0
        if stop > length:
            stop = length
        if stop and (stop <= start or start_invalid):
            stop = 0
        if bookmark > length:
            bookmark = length

    return start, stop, bookmark


def _resolve_media_type(track: TrackInfo, capabilities) -> int:
    """Downgrade media type when the device lacks required capability."""
    media_type = _u32(track.media_type, MEDIA_TYPE_AUDIO)
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
    movie_file_flag = _u8(track.movie_file_flag)
    if movie_file_flag != 0:
        return movie_file_flag
    if media_type in (MEDIA_TYPE_VIDEO, MEDIA_TYPE_MUSIC_VIDEO,
                      MEDIA_TYPE_TV_SHOW, MEDIA_TYPE_VIDEO_PODCAST):
        return 1
    return 0


def _resolve_not_played(track: TrackInfo) -> int:
    """Resolve the not_played_flag: auto-derive from play_count when -1."""
    played_mark = _int_or_default(track.played_mark, -1)
    if played_mark >= 0:
        return _u8(played_mark)
    return 0x01 if _u32(track.play_count) > 0 else 0x02


def _gapless_or_zero(value: int, capabilities) -> int:
    """Return *value* when the device supports gapless, else 0."""
    if capabilities is not None and not capabilities.supports_gapless:
        return 0
    return value


def write_mhit(track: TrackInfo, track_id: int, db_id_2: int = 0,
               capabilities=None, db_version: int = 0) -> bytes:
    """Write a complete MHIT chunk with all child MHODs.

    Args:
        track: TrackInfo dataclass with all track metadata.
        track_id: Unique track ID within this database.
        db_id_2: Database-wide ID from MHBD offset 0x24 (written into every track).
        capabilities: Optional DeviceCapabilities for gapless/video filtering.
        db_version: Database version — controls the MHIT header size.
                    Older iPods require smaller headers (e.g. 0x148 for db_version ≤ 0x19).

    Returns:
        Complete MHIT chunk bytes (header + MHODs).
    """
    track.db_track_id = _u64(track.db_track_id)
    if track.db_track_id == 0:
        track.db_track_id = generate_db_track_id()
    track.date_added = _u32(track.date_added)
    if track.date_added == 0:
        track.date_added = int(time.time())

    ft = _normalize_filetype(track.filetype)
    filetype_code = FILETYPE_CODES.get(ft, FILETYPE_CODES['mp3'])
    media_type = _resolve_media_type(track, capabilities)
    has_lyrics = track.has_lyrics or bool(track.lyrics)
    title = _text_or_default(track.title, "Unknown Title")
    location = _normalize_ipod_location(track.location)
    length = _u32(track.length)
    sample_rate = _normalize_sample_rate(track.sample_rate)
    start_time, stop_time, bookmark_time = _normalize_trim_times(
        length,
        track.start_time,
        track.stop_time,
        track.bookmark_time,
    )

    # Build child MHODs first to know count + size.
    mhod_data, mhod_count = write_track_mhods(
        title=title, location=location,
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

    # Use device-appropriate header size.  Older iPod firmware expects smaller
    # MHIT headers; fields beyond the header boundary are automatically skipped
    # by write_fields() via each field's min_header_length attribute.
    header_size = mhit_header_size_for_version(db_version) if db_version else MHIT_HEADER_SIZE
    total_length = header_size + len(mhod_data)

    # Assemble the values dict — write_fields handles transforms & packing.
    values: dict = {
        'child_count': mhod_count,
        'track_id': _u32(track_id),
        'visible': 1,
        'filetype': filetype_code,
        'vbr_flag': 1 if _bool_flag(track.vbr) else 0,
        'mp3_flag': 1 if ft == 'mp3' else 0,
        'compilation_flag': 1 if _bool_flag(track.compilation_flag) else 0,
        'rating': _clamp_int(track.rating, 0, 100),
        'last_modified': _u32(track.last_modified or track.date_added),
        'size': _u32(track.size),
        'length': length,
        'track_number': _u32(track.track_number),
        'total_tracks': _u32(track.total_tracks),
        'year': _u32(track.year),
        'bitrate': _u32(track.bitrate),
        'sample_rate_1': sample_rate,
        'volume': _clamp_int(track.volume, -255, 255),
        'start_time': start_time,
        'stop_time': stop_time,
        'sound_check': _u32(track.sound_check),
        'play_count_1': _u32(track.play_count),
        'play_count_2': _u32(track.play_count_2),
        'last_played': _u32(track.last_played),
        'disc_number': _u32(track.disc_number),
        'total_discs': _u32(track.total_discs),
        'user_id': _u32(track.user_id),
        'date_added': track.date_added,
        'bookmark_time': bookmark_time,
        'db_track_id': track.db_track_id,
        'checked_flag': _u8(track.checked_flag),
        'app_rating': _u8(track.app_rating),
        'bpm': _u16(track.bpm),
        'artwork_count': _u16(track.artwork_count),
        'audio_format_flag': AUDIO_FORMAT_FLAG_MAP.get(ft, AUDIO_FORMAT_FLAG_DEFAULT),
        'artwork_size': _u32(track.artwork_size),
        'sample_rate_2': float(sample_rate),
        'date_released': _u32(track.date_released),
        'mpeg_audio_type': _u16(track.mpeg_audio_type),
        'explicit_flag': _u8(track.explicit_flag),
        'purchased_aac_flag': _u8(track.purchased_aac_flag),
        # Extended fields
        'skip_count': _u32(track.skip_count),
        'last_skipped': _u32(track.last_skipped),
        'has_artwork': 1 if _u16(track.artwork_count) > 0 else 2,
        'skip_when_shuffling': 1 if _bool_flag(track.skip_when_shuffling) else 0,
        'remember_position': 1 if _bool_flag(track.remember_position) else 0,
        'use_podcast_now_playing_flag': _u8(track.podcast_flag),
        'db_track_id_2': track.db_track_id,
        'lyrics_flag': 1 if has_lyrics else 0,
        'movie_flag': _u8(_resolve_movie_flag(track, media_type)),
        'not_played_flag': _u8(_resolve_not_played(track)),
        'pregap': _u32(_gapless_or_zero(track.pregap, capabilities)),
        'sample_count': _u64(_gapless_or_zero(track.sample_count, capabilities)),
        'postgap': _u32(_gapless_or_zero(track.postgap, capabilities)),
        'encoder': _u32(track.encoder_flag),
        'media_type': _u32(media_type),
        'season_number': _u32(track.season_number),
        'episode_number': _u32(track.episode_number),
        'date_added_to_itunes': _u32(track.date_added_to_itunes),
        'store_track_id': _u32(track.store_track_id),
        'store_encoder_version': _u32(track.store_encoder_version),
        'store_artist_id': _u32(track.store_artist_id),
        'store_album_id': _u32(track.store_album_id),
        'store_content_flag': _u32(track.store_content_flag),
        'gapless_audio_payload_size': _u32(_gapless_or_zero(track.gapless_data, capabilities)),
        'gapless_track_flag': _u16(_gapless_or_zero(track.gapless_track_flag, capabilities)),
        'gapless_album_flag': _u16(_gapless_or_zero(track.gapless_album_flag, capabilities)),
        'album_id': _u32(track.album_id),
        'db_id_2_ref': _u64(db_id_2),
        'size_2': _u32(track.size),
        'sort_mhod_indicators': _compute_sort_indicators(track),
        'artwork_id_ref': _u32(track.mhii_link),
        'artist_id_ref': _u32(track.artist_id),
        'composer_id': _u32(track.composer_id),
    }

    header = bytearray(header_size)
    write_generic_header(header, 0, b'mhit', header_size, total_length)
    write_fields(header, 0, 'mhit', values, header_size)

    return bytes(header) + mhod_data
