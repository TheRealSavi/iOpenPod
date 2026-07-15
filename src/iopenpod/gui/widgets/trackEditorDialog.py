"""Multi-track metadata editor for parsed iPod MHIT records."""

from __future__ import annotations

import ast
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dateutil import parser as dateutil_parser
from dateutil.parser import ParserError
from PIL import Image, ImageOps, UnidentifiedImageError
from PyQt6.QtCore import QAbstractItemModel, QModelIndex, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
    QShowEvent,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from iopenpod.itunesdb_shared.constants import MEDIA_TYPE_MAP
from iopenpod.itunesdb_shared.mhit_defs import MHIT_FIELDS
from iopenpod.search import matches_search

from ..imgMaker import TrackArtworkPreview, get_track_artwork_previews
from ..styles import (
    FONT_FAMILY,
    Colors,
    Design,
    Metrics,
    accent_btn_css,
    btn_css,
    chip_btn_css,
    input_css,
    make_scroll_area,
    panel_css,
    sidebar_item_view_css,
)
from .artworkUnifier import (
    ArtworkUnifyContext,
    UnifyArtworkDialog,
    artwork_compare_hash,
    build_track_artwork_unify_context,
    representative_artwork_variant,
    save_unified_artwork_temp,
    track_artwork_id,
)
from .flowLayout import FlowLayout
from .formatters import format_duration_mmss, format_size
from .photoViewer import pil_to_pixmap

logger = logging.getLogger(__name__)


class _MixedValue:
    pass


MIXED = _MixedValue()
_MIXED_ARTWORK_METADATA_VALUE = "mixed value"
_MISSING_ARTWORK_METADATA = object()


@dataclass(frozen=True)
class TrackFieldSpec:
    key: str
    label: str
    group: str
    kind: str = "text"
    editable: bool = True
    help_text: str = ""
    read_only_reason: str = ""


_STRING_FIELDS: tuple[tuple[str, str], ...] = (
    ("Title", "Metadata"),
    ("Artist", "Metadata"),
    ("Album", "Metadata"),
    ("Album Artist", "Metadata"),
    ("Genre", "Metadata"),
    ("Composer", "Metadata"),
    ("Grouping", "Metadata"),
    ("Comment", "Metadata"),
    ("Lyrics", "Metadata"),
    ("eq_setting", "Playback"),
    ("Sort Title", "Sorting"),
    ("Sort Artist", "Sorting"),
    ("Sort Album", "Sorting"),
    ("Sort Album Artist", "Sorting"),
    ("Sort Composer", "Sorting"),
    ("Sort Show", "Sorting"),
    ("Show", "Video"),
    ("Episode", "Video"),
    ("Subtitle", "Video"),
    ("TV Network", "Video"),
    ("Description Text", "Video"),
    ("Track Keywords", "Video"),
    ("Show Locale", "Video"),
    ("Category", "Podcast"),
    ("Podcast Enclosure URL", "Podcast"),
    ("Podcast RSS URL", "Podcast"),
    ("Location", "File"),
    ("filetype", "File"),
)

_LONG_TEXT_FIELDS = frozenset(
    {
        "Comment",
        "Description Text",
        "Lyrics",
        "Podcast Enclosure URL",
        "Podcast RSS URL",
        "Location",
    }
)

_BOOL_FIELDS = frozenset(
    {
        "compilation_flag",
        "skip_when_shuffling",
        "remember_position",
        "movie_flag",
        "gapless_track_flag",
        "gapless_album_flag",
        "visible",
        "vbr_flag",
        "mp3_flag",
        "lyrics_flag",
        "purchased_aac_flag",
        "podcast_flag",
    }
)

_DATE_FIELD_KEYS = frozenset(
    {
        "date_added",
        "last_modified",
        "date_released",
        "last_played",
        "last_skipped",
        "date_added_to_itunes",
    }
)

_READ_ONLY_FIELDS = frozenset(
    {
        "Location",
        "filetype",
        "child_count",
        "track_id",
        "db_track_id",
        "db_track_id_2",
        "db_id_2_ref",
        "album_id",
        "artist_id_ref",
        "composer_id",
        "user_id",
        "visible",
        "vbr_flag",
        "mp3_flag",
        "lyrics_flag",
        "purchased_aac_flag",
        "length",
        "size",
        "size_2",
        "bitrate",
        "sample_rate_1",
        "sample_rate_2",
        "audio_format_flag",
        "mpeg_audio_type",
        "pregap",
        "postgap",
        "sample_count",
        "encoder",
        "gapless_audio_payload_size",
        "play_count_2",
        "app_rating",
        "artwork_count",
        "artwork_size",
        "artwork_id_ref",
        "has_artwork",
        "store_track_id",
        "store_encoder_version",
        "store_artist_id",
        "store_album_id",
        "store_content_flag",
        "source_path",
        "source_relative_path",
        "Source Path",
        "Source Relative Path",
        "podcast_flag",
    }
)

_SAFE_EDITABLE_FIELDS = frozenset(
    {
        "Title",
        "Artist",
        "Album",
        "Album Artist",
        "Genre",
        "Composer",
        "Grouping",
        "Comment",
        "eq_setting",
        "Sort Title",
        "Sort Artist",
        "Sort Album",
        "Sort Album Artist",
        "Sort Composer",
        "Sort Show",
        "Show",
        "Episode",
        "Subtitle",
        "TV Network",
        "Description Text",
        "Category",
        "Podcast Enclosure URL",
        "Podcast RSS URL",
        "Track Keywords",
        "Show Locale",
        "Lyrics",
        "year",
        "track_number",
        "total_tracks",
        "disc_number",
        "total_discs",
        "bpm",
        "rating",
        "play_count_1",
        "skip_count",
        "volume",
        "sound_check",
        "start_time",
        "stop_time",
        "bookmark_time",
        "last_played",
        "last_skipped",
        "date_added",
        "last_modified",
        "date_released",
        "date_added_to_itunes",
        "checked_flag",
        "explicit_flag",
        "not_played_flag",
        "compilation_flag",
        "skip_when_shuffling",
        "remember_position",
        "gapless_track_flag",
        "gapless_album_flag",
        "movie_flag",
        "use_podcast_now_playing_flag",
        "media_type",
        "season_number",
        "episode_number",
        "chapter_data",
    }
)

_GROUP_OVERRIDES = {
    "child_count": "Advanced",
    "source_path": "File",
    "source_relative_path": "File",
    "Source Path": "File",
    "Source Relative Path": "File",
    "track_id": "Identifiers",
    "db_track_id": "Identifiers",
    "db_track_id_2": "Identifiers",
    "db_id_2_ref": "Identifiers",
    "album_id": "Identifiers",
    "artist_id_ref": "Identifiers",
    "composer_id": "Identifiers",
    "user_id": "Identifiers",
    "filetype": "File",
    "visible": "Options",
    "compilation_flag": "Options",
    "checked_flag": "Options",
    "explicit_flag": "Options",
    "skip_when_shuffling": "Options",
    "remember_position": "Options",
    "lyrics_flag": "Options",
    "gapless_track_flag": "Options",
    "gapless_album_flag": "Options",
    "podcast_flag": "Podcast",
    "use_podcast_now_playing_flag": "Podcast",
    "not_played_flag": "Podcast",
    "chapter_data": "Chapters",
    "movie_flag": "Video",
    "rating": "Playback",
    "length": "Playback",
    "start_time": "Playback",
    "stop_time": "Playback",
    "sound_check": "Playback",
    "play_count_1": "Playback",
    "play_count_2": "Playback",
    "bookmark_time": "Playback",
    "skip_count": "Playback",
    "volume": "Playback",
    "vbr_flag": "File",
    "mp3_flag": "File",
    "purchased_aac_flag": "File",
    "size": "File",
    "bitrate": "File",
    "sample_rate_1": "File",
    "sample_rate_2": "File",
    "audio_format_flag": "File",
    "mpeg_audio_type": "File",
    "size_2": "File",
    "pregap": "File",
    "postgap": "File",
    "sample_count": "File",
    "encoder": "File",
    "media_type": "File",
    "gapless_audio_payload_size": "File",
    "artwork_count": "Artwork",
    "artwork_size": "Artwork",
    "artwork_id_ref": "Artwork",
    "has_artwork": "Artwork",
    "date_added": "Dates",
    "last_modified": "Dates",
    "date_released": "Dates",
    "last_played": "Dates",
    "last_skipped": "Dates",
    "date_added_to_itunes": "Dates",
    "app_rating": "Playback",
    "year": "Metadata",
    "track_number": "Metadata",
    "total_tracks": "Metadata",
    "disc_number": "Metadata",
    "total_discs": "Metadata",
    "bpm": "Metadata",
    "season_number": "Video",
    "episode_number": "Video",
    "store_track_id": "Store",
    "store_encoder_version": "Store",
    "store_artist_id": "Store",
    "store_album_id": "Store",
    "store_content_flag": "Store",
}

_GROUP_ORDER = (
    "Metadata",
    "Sorting",
    "Playback",
    "Options",
    "Video",
    "Podcast",
    "Chapters",
    "File",
    "Artwork",
    "Dates",
    "Store",
    "Identifiers",
    "Advanced",
    "Other",
)

_GROUP_TITLES = {
    "Metadata": "Metadata",
    "Sorting": "Sorting",
    "Playback": "Playback",
    "Options": "Playback Options",
    "Video": "Video",
    "Podcast": "Podcast",
    "Chapters": "Chapters",
    "File": "File",
    "Artwork": "Artwork",
    "Dates": "Dates",
    "Store": "Store",
    "Identifiers": "IDs",
    "Advanced": "Advanced",
    "Other": "Other",
}

_GROUP_DESCRIPTIONS = {
    "Metadata": "Titles, artists, albums, genres, and tags",
    "Sorting": "Sort overrides used by the iPod library",
    "Playback": "Rating, counts, timing, and playback position",
    "Options": "Advisory, shuffle, resume, and gapless flags",
    "Video": "Show, episode, and TV metadata",
    "Podcast": "Podcast feeds, categories, and playback markers",
    "Chapters": "Chapter markers stored in the iPod database",
    "File": "Location, format, media kind, and audio technical fields",
    "Artwork": "Artwork counts and ArtworkDB references",
    "Dates": "Added, modified, released, played, and skipped timestamps",
    "Store": "iTunes Store metadata preserved from the database",
    "Identifiers": "Track, album, artist, composer, and database IDs",
    "Advanced": "Less common MHIT header fields",
    "Other": "Additional parsed fields present on this selection",
}

_SUBGROUP_TITLES = {
    "core": "Core Metadata",
    "numbering": "Track & Disc",
    "tags": "Tags",
    "notes": "Notes & Lyrics",
    "sort_overrides": "Sort Overrides",
    "counts": "Rating & Counts",
    "timing": "Timing",
    "position": "Resume Position",
    "levels": "Volume & Sound Check",
    "equalizer": "Equalizer",
    "advisory": "Advisory & Visibility",
    "playback_flags": "Playback Flags",
    "gapless_flags": "Gapless Flags",
    "content_flags": "Content Flags",
    "video_show": "Show Details",
    "video_desc": "Descriptions",
    "video_flags": "Video Flags",
    "podcast_feed": "Feed",
    "podcast_meta": "Category & Locale",
    "podcast_flags": "Podcast Flags",
    "chapters": "Chapter Timeline",
    "location": "Location & Kind",
    "sizes": "Sizes",
    "encoding": "Encoding",
    "format_flags": "Format Flags",
    "samples": "Gapless Samples",
    "artwork": "Artwork",
    "dates": "Dates",
    "store": "Store",
    "ids": "Identifiers",
    "advanced": "Advanced",
    "other": "Other",
}

_SUBGROUP_ORDER = tuple(_SUBGROUP_TITLES)

_SUBGROUP_BY_KEY = {
    "Title": "core",
    "Artist": "core",
    "Album": "core",
    "Album Artist": "core",
    "Genre": "core",
    "Composer": "core",
    "Grouping": "tags",
    "eq_setting": "equalizer",
    "year": "tags",
    "track_number": "numbering",
    "total_tracks": "numbering",
    "disc_number": "numbering",
    "total_discs": "numbering",
    "bpm": "tags",
    "Comment": "notes",
    "Lyrics": "notes",
    "Sort Title": "sort_overrides",
    "Sort Artist": "sort_overrides",
    "Sort Album": "sort_overrides",
    "Sort Album Artist": "sort_overrides",
    "Sort Composer": "sort_overrides",
    "Sort Show": "sort_overrides",
    "rating": "counts",
    "app_rating": "counts",
    "play_count_1": "counts",
    "play_count_2": "counts",
    "skip_count": "counts",
    "length": "timing",
    "start_time": "timing",
    "stop_time": "timing",
    "bookmark_time": "position",
    "volume": "levels",
    "sound_check": "levels",
    "checked_flag": "advisory",
    "explicit_flag": "advisory",
    "visible": "advisory",
    "compilation_flag": "advisory",
    "skip_when_shuffling": "playback_flags",
    "remember_position": "playback_flags",
    "gapless_track_flag": "gapless_flags",
    "gapless_album_flag": "gapless_flags",
    "lyrics_flag": "content_flags",
    "vbr_flag": "format_flags",
    "mp3_flag": "format_flags",
    "purchased_aac_flag": "format_flags",
    "movie_flag": "video_flags",
    "Show": "video_show",
    "season_number": "video_show",
    "episode_number": "video_show",
    "Episode": "video_show",
    "TV Network": "video_show",
    "Subtitle": "video_desc",
    "Description Text": "video_desc",
    "Category": "podcast_meta",
    "Podcast Enclosure URL": "podcast_feed",
    "Podcast RSS URL": "podcast_feed",
    "Track Keywords": "video_show",
    "Show Locale": "video_show",
    "podcast_flag": "podcast_flags",
    "use_podcast_now_playing_flag": "podcast_flags",
    "not_played_flag": "podcast_flags",
    "chapter_data": "chapters",
    "Location": "location",
    "filetype": "format_flags",
    "media_type": "location",
    "size": "sizes",
    "size_2": "sizes",
    "source_path": "location",
    "source_relative_path": "location",
    "Source Path": "location",
    "Source Relative Path": "location",
    "bitrate": "encoding",
    "sample_rate_1": "encoding",
    "sample_rate_2": "encoding",
    "audio_format_flag": "encoding",
    "mpeg_audio_type": "encoding",
    "encoder": "encoding",
    "pregap": "samples",
    "postgap": "samples",
    "sample_count": "samples",
    "gapless_audio_payload_size": "samples",
    "artwork_count": "artwork",
    "artwork_size": "artwork",
    "artwork_id_ref": "artwork",
    "has_artwork": "artwork",
    "date_added": "dates",
    "last_modified": "dates",
    "date_released": "dates",
    "last_played": "dates",
    "last_skipped": "dates",
    "date_added_to_itunes": "dates",
    "store_track_id": "store",
    "store_encoder_version": "store",
    "store_artist_id": "store",
    "store_album_id": "store",
    "store_content_flag": "store",
}

_LABEL_OVERRIDES = {
    "db_track_id": "Database Track ID",
    "db_track_id_2": "Database Track ID 2",
    "db_id_2_ref": "Database ID 2 Ref",
    "checked_flag": "Checked",
    "explicit_flag": "Content Advisory",
    "not_played_flag": "Played Status",
    "use_podcast_now_playing_flag": "Podcast Display",
    "sample_rate_1": "Sample Rate",
    "sample_rate_2": "Sample Rate Float",
    "gapless_audio_payload_size": "Gapless Payload",
    "artwork_id_ref": "Artwork Ref",
    "has_artwork": "Artwork Presence",
    "media_type": "Media Kind",
    "filetype": "File Format",
    "vbr_flag": "VBR",
    "mp3_flag": "MP3 Marker",
    "purchased_aac_flag": "Purchased AAC",
    "audio_format_flag": "Audio Format",
    "mpeg_audio_type": "MPEG Audio Type",
    "app_rating": "Application Rating",
    "play_count_1": "Play Count",
    "play_count_2": "Play Count Delta",
    "skip_count": "Skip Count",
    "eq_setting": "Equalizer",
    "date_added_to_itunes": "iTunes Date Added",
    "chapter_data": "Chapter Timeline",
}

_RATING_OPTIONS = (
    ("No Rating", 0),
    ("1 star (20)", 20),
    ("2 stars (40)", 40),
    ("3 stars (60)", 60),
    ("4 stars (80)", 80),
    ("5 stars (100)", 100),
)
_EXPLICIT_OPTIONS = (("None", 0), ("Explicit", 1), ("Clean", 2))
_CHECKED_OPTIONS = (("Checked (0)", 0), ("Unchecked (1)", 1))
_BOOL_OPTIONS = (("No", 0), ("Yes", 1))
_PLAYED_MARK_OPTIONS = (
    ("Normal / unset (0)", 0),
    ("Played (1)", 1),
    ("Unplayed (2)", 2),
)
_PODCAST_DISPLAY_OPTIONS = (
    ("Normal (0)", 0),
    ("Podcast (1)", 1),
    ("Podcast alternate (2)", 2),
)
_ARTWORK_PRESENCE_OPTIONS = (
    ("Unset (0)", 0),
    ("Has artwork (1)", 1),
    ("No artwork (2)", 2),
)
_MEDIA_TYPE_OPTIONS = tuple(
    (f"{label} ({value})", value) for value, label in sorted(MEDIA_TYPE_MAP.items())
)

_FIELD_HELP = {
    "Title": "MHOD type 1. The display name shown by the iPod.",
    "Artist": "MHOD type 4. Primary track artist.",
    "Album": "MHOD type 3. Album title used for grouping.",
    "Album Artist": "MHOD type 22. Album-level artist used by newer iTunes databases.",
    "Genre": "MHOD type 5. Genre string used by the iPod browser.",
    "Composer": "MHOD type 12. Composer metadata.",
    "Grouping": "MHOD type 13. Grouping/work text.",
    "eq_setting": "MHOD type 7. iTunes equalizer preset name.",
    "Sort Title": "Sort override for title/name (MHOD type 27). Accepts legacy Sort Name on import.",
    "Sort Artist": "Sort override for artist.",
    "Sort Album": "Sort override for album.",
    "Sort Album Artist": "Sort override for album artist.",
    "Sort Composer": "Sort override for composer.",
    "Sort Show": "Sort override for TV show.",
    "Location": "iPod-internal file path. Changing it would require moving the media file too.",
    "filetype": "File format/description used when the database is written.",
    "rating": "iPod star rating stored as 0-100 in 20-point steps.",
    "checked_flag": "Inverted iPod value: 0 means checked and 1 means unchecked. This is the iTunes checkbox state and does not control normal playback.",
    "explicit_flag": "Content advisory: 0 none, 1 explicit, 2 clean.",
    "not_played_flag": "Podcast-style played marker. 2 marks an item unplayed.",
    "volume": "Signed per-track volume adjustment. Valid range is -255 to +255.",
    "start_time": "Playback start offset in milliseconds.",
    "stop_time": "Playback stop offset in milliseconds.",
    "bookmark_time": "Resume/bookmark position in milliseconds.",
    "sound_check": "ReplayGain/iTunes sound check normalization value.",
    "media_type": "iPod media-kind bitfield that controls music/video/podcast/audiobook placement.",
    "use_podcast_now_playing_flag": "Podcast display flag. libgpod treats 1 and 2 as podcast-style values.",
    "has_artwork": "Not a plain boolean: libgpod writes 1 for artwork present and 2 for none.",
    "artwork_id_ref": "Reference into ArtworkDB. It must match generated artwork entries.",
    "gapless_track_flag": "Marks the track as having gapless playback data.",
    "gapless_album_flag": "Marks the album as gapless.",
    "gapless_audio_payload_size": "Raw gapless encoder-delay payload size.",
    "pregap": "Raw encoder pregap sample count.",
    "postgap": "Raw encoder padding/postgap sample count.",
    "sample_count": "Total decoded sample count.",
    "date_added": "When the item was added to the iPod library. Stored as a Unix timestamp and shown here as local date/time.",
    "last_modified": "Source file modification date. Stored as a Unix timestamp and shown here as local date/time.",
    "date_released": "Release date. Stored as a Unix timestamp and shown here as local date/time.",
    "last_played": "Last play time. Stored as a Unix timestamp and shown here as local date/time.",
    "last_skipped": "Last skip time. Stored as a Unix timestamp and shown here as local date/time.",
    "date_added_to_itunes": "Original iTunes add date. Stored as a Unix timestamp and shown here as local date/time.",
    "play_count_1": "Main play count stored in iTunesDB after Play Counts deltas are merged.",
    "play_count_2": "Transient iPod play delta slot used for scrobbling; cleared after sync.",
    "app_rating": "Application-computed/backup rating slot used by libgpod conventions.",
    "store_track_id": "iTunes Store content identifier preserved from the database.",
    "store_encoder_version": "iTunes Store encoder/version metadata preserved from the database.",
    "store_artist_id": "iTunes Store artist identifier preserved from the database.",
    "store_album_id": "iTunes Store album identifier preserved from the database.",
    "store_content_flag": "iTunes Store content flag preserved from the database.",
    "chapter_data": "MHOD type 17 chapter timeline. Edit chapter titles and start times; existing raw preamble fields are preserved.",
}

_READ_ONLY_REASON_BY_KEY = {
    "Location": "the database path must match the actual file on the iPod",
    "filetype": "changing the codec marker without changing the file can make the track unplayable",
    "visible": "the writer currently always emits visible tracks",
    "play_count_2": "this slot is transient and cleared after play-count sync",
    "has_artwork": "it is derived from ArtworkDB entries",
}

_MHIT_FIELD_MAP = {field.name: field for field in MHIT_FIELDS}
_STRING_FIELD_KEYS = {key for key, _ in _STRING_FIELDS}


def _normalize_sort_title_aliases(tracks: list[dict]) -> None:
    for track in tracks:
        if "Sort Name" not in track:
            continue
        sort_name = track.get("Sort Name")
        if not track.get("Sort Title") and sort_name:
            track["Sort Title"] = sort_name
        track.pop("Sort Name", None)


def _humanize_key(key: str) -> str:
    if key in _LABEL_OVERRIDES:
        return _LABEL_OVERRIDES[key]
    text = key.replace("_", " ")
    return " ".join(part.upper() if part in {"id", "db", "eq", "bpm"} else part.capitalize() for part in text.split())


def _is_structural_key(key: str) -> bool:
    return (
        key.startswith("unk")
        or key.startswith("hash_")
        or key in {"sort_mhod_indicators"}
    )


def _is_field_editable(key: str) -> bool:
    if key in _READ_ONLY_FIELDS or _is_structural_key(key):
        return False
    return key in _SAFE_EDITABLE_FIELDS


def _read_only_reason_for_key(key: str) -> str:
    if key in _READ_ONLY_REASON_BY_KEY:
        return _READ_ONLY_REASON_BY_KEY[key]
    if _is_structural_key(key):
        return "this is an unknown or raw structural MHIT field"
    if key in _GROUP_OVERRIDES and _GROUP_OVERRIDES[key] in {"Identifiers", "Store", "Artwork"}:
        return "it is generated or preserved by the database writer"
    if key in _READ_ONLY_FIELDS:
        return "it is computed from the media file or another database"
    return "this field is visible for inspection but is not safely editable yet"


def _help_for_key(key: str, editable: bool) -> str:
    help_text = _FIELD_HELP.get(key, "")
    if editable:
        return help_text
    reason = _read_only_reason_for_key(key)
    if help_text:
        return f"{help_text}\nRead-only: {reason}."
    return f"Read-only: {reason}."


def _subgroup_for_key(key: str, group: str) -> str:
    if key in _SUBGROUP_BY_KEY:
        return _SUBGROUP_BY_KEY[key]
    if group in {"Identifiers", "Advanced", "Other"}:
        return group.lower()
    return group.lower().replace(" & ", "_").replace(" ", "_")


def _ordered_subgroups(specs: list[TrackFieldSpec]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for subgroup in _SUBGROUP_ORDER:
        if any(_subgroup_for_key(spec.key, spec.group) == subgroup for spec in specs):
            result.append(subgroup)
            seen.add(subgroup)
    for spec in specs:
        subgroup = _subgroup_for_key(spec.key, spec.group)
        if subgroup not in seen:
            result.append(subgroup)
            seen.add(subgroup)
    return result


def _selection_summary(tracks: list[dict]) -> str:
    count = len(tracks)
    if count != 1:
        return f"{count} selected tracks"
    track = tracks[0]
    title = str(track.get("Title") or "Untitled")
    artist = str(track.get("Artist") or "")
    album = str(track.get("Album") or "")
    pieces = [title]
    if artist:
        pieces.append(artist)
    if album:
        pieces.append(album)
    return " • ".join(pieces)


def _common_value(tracks: list[dict], key: str) -> Any:
    values = [track.get(key) for track in tracks]
    if not values:
        return None
    first = values[0]
    for value in values[1:]:
        if value != first:
            return MIXED
    return first


def _format_chapter_time(value: Any) -> str:
    try:
        milliseconds = int(value or 0)
    except (TypeError, ValueError):
        return ""
    if milliseconds <= 0:
        return "0:00"
    return format_duration_mmss(milliseconds)


def _format_chapter_data(value: Any) -> str:
    if not isinstance(value, dict):
        return ""

    chapters = value.get("chapters") or []
    if not isinstance(chapters, list) or not chapters:
        return ""

    width = max(2, len(str(len(chapters))))
    lines: list[str] = []
    for index, chapter in enumerate(chapters):
        if not isinstance(chapter, dict):
            continue
        title = str(chapter.get("title") or "").strip() or f"Chapter {index + 1}"
        start = _format_chapter_time(chapter.get("startpos", 0))
        lines.append(f"{index + 1:0{width}d}  {start:>7}  {title}")
    return "\n".join(lines)


def _format_chapter_time_for_editor(value: Any) -> str:
    try:
        milliseconds = max(0, int(value or 0))
    except (TypeError, ValueError):
        milliseconds = 0

    seconds_total, ms_remainder = divmod(milliseconds, 1000)
    hours, remainder = divmod(seconds_total, 3600)
    minutes, seconds = divmod(remainder, 60)
    second_text = f"{seconds:02d}"
    if ms_remainder:
        second_text = f"{second_text}.{ms_remainder:03d}".rstrip("0").rstrip(".")
    if hours:
        return f"{hours}:{minutes:02d}:{second_text}"
    return f"{minutes}:{second_text}"


def _parse_chapter_time_text(text: str, label: str = "Chapter time") -> int:
    stripped = text.strip().lower()
    if not stripped:
        raise ValueError(f"{label} needs a start time.")

    try:
        if stripped.endswith("ms"):
            value = int(float(stripped[:-2].strip()))
        elif stripped.endswith("s") and ":" not in stripped:
            value = int(round(float(stripped[:-1].strip()) * 1000))
        elif ":" in stripped:
            parts = stripped.split(":")
            if len(parts) not in (2, 3):
                raise ValueError
            seconds = float(parts[-1])
            minutes = int(parts[-2])
            hours = int(parts[0]) if len(parts) == 3 else 0
            if minutes < 0 or minutes >= 60 or seconds < 0 or seconds >= 60:
                raise ValueError
            value = int(round(((hours * 3600) + (minutes * 60) + seconds) * 1000))
        elif "." in stripped:
            value = int(round(float(stripped) * 1000))
        else:
            value = int(stripped, 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{label} must be a time like 0:00, 1:23, 1:02:03.500, 83s, or raw milliseconds."
        ) from exc

    if value < 0:
        raise ValueError(f"{label} cannot be negative.")
    return value


def _chapter_entries_from_data(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    chapters = value.get("chapters") or []
    if not isinstance(chapters, list):
        return []

    entries: list[dict[str, Any]] = []
    for index, chapter in enumerate(chapters):
        if not isinstance(chapter, dict):
            continue
        try:
            startpos = max(0, int(chapter.get("startpos") or 0))
        except (TypeError, ValueError):
            startpos = 0
        title = str(chapter.get("title") or "").strip() or f"Chapter {index + 1}"
        entries.append({"startpos": startpos, "title": title})
    return entries


def _chapter_data_with_entries(value: Any, chapters: list[dict[str, Any]]) -> dict[str, Any]:
    data = dict(value) if isinstance(value, dict) else {}
    data["chapters"] = chapters
    return data


def _infer_kind(key: str, sample: Any = None) -> str:
    if key == "chapter_data":
        return "chapters"
    if key in _DATE_FIELD_KEYS:
        return "date"
    if key == "checked_flag":
        return "checked_flag"
    if key == "rating":
        return "rating"
    if key == "explicit_flag":
        return "explicit"
    if key == "not_played_flag":
        return "played_mark"
    if key == "use_podcast_now_playing_flag":
        return "podcast_display"
    if key == "has_artwork":
        return "artwork_presence"
    if key == "media_type":
        return "media_type"
    if key in _BOOL_FIELDS:
        return "bool"
    if key in _LONG_TEXT_FIELDS:
        return "long_text"
    if key in _STRING_FIELD_KEYS:
        return "text"

    field = _MHIT_FIELD_MAP.get(key)
    if field is not None:
        fmt = field.struct_format
        if "s" in fmt:
            return "literal"
        if "f" in fmt:
            return "float"
        return "int"

    if isinstance(sample, bool):
        return "bool"
    if isinstance(sample, int):
        return "int"
    if isinstance(sample, float):
        return "float"
    if isinstance(sample, (bytes, bytearray, list, tuple, dict)):
        return "literal"
    return "text"


def build_track_field_specs(tracks: list[dict]) -> list[TrackFieldSpec]:
    """Return ordered editable field specs for a selection of track dicts."""

    specs: list[TrackFieldSpec] = []
    seen: set[str] = set()

    def add(key: str, group: str | None = None) -> None:
        if key in seen:
            return
        seen.add(key)
        sample = next((track.get(key) for track in tracks if key in track), None)
        editable = _is_field_editable(key)
        specs.append(
            TrackFieldSpec(
                key=key,
                label=_humanize_key(key),
                group=group or _GROUP_OVERRIDES.get(key, "Advanced"),
                kind=_infer_kind(key, sample),
                editable=editable,
                help_text=_help_for_key(key, editable),
                read_only_reason="" if editable else _read_only_reason_for_key(key),
            )
        )

    for key, group in _STRING_FIELDS:
        add(key, group)

    add("chapter_data", "Chapters")

    for field in MHIT_FIELDS:
        add(field.name, _GROUP_OVERRIDES.get(field.name))

    ignored = {"children", "mhod_children", "mhip_children"}
    for key in sorted({key for track in tracks for key in track}):
        if key not in seen and key not in ignored:
            add(key, "Advanced")

    return specs


class _ChapterCellDelegate(QStyledItemDelegate):
    """Opaque inline editor for chapter table cells."""

    def createEditor(self, parent: QWidget | None, option: QStyleOptionViewItem, index: QModelIndex) -> QWidget | None:
        editor = QLineEdit(parent)
        editor.setAutoFillBackground(True)
        if index.column() == 0:
            editor.setPlaceholderText(_CHAPTER_TIME_PLACEHOLDER)
            editor.setToolTip(_CHAPTER_TIME_HINT)
            editor.setMinimumWidth(_CHAPTER_TIME_COLUMN_WIDTH)
        else:
            editor.setPlaceholderText("Chapter title")
        editor.setStyleSheet(
            f"""
            QLineEdit {{
                background-color: {Colors.DROPDOWN_BG};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_FOCUS};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                padding: 0 6px;
                font-family: {FONT_FAMILY};
                font-size: {Metrics.FONT_SM}pt;
                selection-background-color: {Colors.ACCENT};
                selection-color: {Colors.TEXT_ON_ACCENT};
            }}
            """
        )
        return editor

    def setEditorData(self, editor: QWidget | None, index: QModelIndex) -> None:
        if isinstance(editor, QLineEdit):
            editor.setText(str(index.data(Qt.ItemDataRole.EditRole) or ""))
            QTimer.singleShot(0, editor.selectAll)
            return
        super().setEditorData(editor, index)

    def setModelData(self, editor: QWidget | None, model: QAbstractItemModel | None, index: QModelIndex) -> None:
        if isinstance(editor, QLineEdit) and model is not None:
            model.setData(index, editor.text(), Qt.ItemDataRole.EditRole)
            return
        super().setModelData(editor, model, index)


class _NoFocusItemDelegate(QStyledItemDelegate):
    """Paint list items without Qt's dotted current-item focus rectangle."""

    def paint(self, painter: QPainter | None, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        clean_option = QStyleOptionViewItem(option)
        clean_option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, clean_option, index)


_CHAPTER_TIME_COLUMN_WIDTH = 156
_CHAPTER_TIME_PLACEHOLDER = "0:00, 1:23.500, 62500ms"
_CHAPTER_TIME_HINT = (
    "Start times are offsets from the beginning of the track. "
    "Use 0:00, 1:23.500, 1:02:03, 83s, or 62500ms."
)


class _ChapterTimelineEditor(QFrame):
    """Editable chapter timeline widget for MHOD type 17 chapter data."""

    modifiedChanged = pyqtSignal()

    def __init__(
        self,
        value: Any,
        *,
        mixed: bool = False,
        editable: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._initial_value = value
        self._mixed = mixed
        self._editable = editable
        self._loading = False
        self.setObjectName("chapterTimelineEditor")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        self._summary = QLabel("")
        self._summary.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._summary.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        toolbar.addWidget(self._summary)
        toolbar.addStretch()

        self._add_btn = QPushButton("Add Chapter")
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setStyleSheet(accent_btn_css())
        self._add_btn.clicked.connect(self.add_chapter)
        toolbar.addWidget(self._add_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_btn.setStyleSheet(btn_css())
        self._delete_btn.clicked.connect(self.delete_selected_chapters)
        toolbar.addWidget(self._delete_btn)

        self._sort_btn = QPushButton("Sort by Time")
        self._sort_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sort_btn.setStyleSheet(btn_css())
        self._sort_btn.clicked.connect(self.sort_by_time)
        toolbar.addWidget(self._sort_btn)
        layout.addLayout(toolbar)

        self._time_hint = QLabel(_CHAPTER_TIME_HINT)
        self._time_hint.setObjectName("chapterTimeHint")
        self._time_hint.setWordWrap(True)
        self._time_hint.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self._time_hint.setStyleSheet(f"color: {Colors.TEXT_TERTIARY};")
        layout.addWidget(self._time_hint)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Start Time", "Title"])
        start_header = self._table.horizontalHeaderItem(0)
        if start_header is not None:
            start_header.setToolTip(_CHAPTER_TIME_HINT)
        title_header = self._table.horizontalHeaderItem(1)
        if title_header is not None:
            title_header.setToolTip("Chapter title shown on the iPod")
        self._table.setItemDelegate(_ChapterCellDelegate(self._table))
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self._table.setAlternatingRowColors(True)
        self._table.setMinimumHeight(190)
        self._table.setShowGrid(False)
        vertical_header = self._table.verticalHeader()
        if vertical_header is not None:
            vertical_header.setVisible(False)
        header = self._table.horizontalHeader()
        if header is not None:
            header.setMinimumSectionSize(96)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, _CHAPTER_TIME_COLUMN_WIDTH)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.itemSelectionChanged.connect(self._sync_actions)
        self._table.setStyleSheet(
            f"""
            QTableWidget {{
                background: {Colors.SURFACE_ALT};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                selection-background-color: {Colors.ACCENT_MUTED};
                selection-color: {Colors.TEXT_PRIMARY};
                font-family: {FONT_FAMILY};
                font-size: {Metrics.FONT_SM}pt;
            }}
            QTableWidget::item {{
                padding: 7px 8px;
            }}
            QTableWidget::item:selected {{
                background: {Colors.ACCENT_MUTED};
                color: {Colors.TEXT_PRIMARY};
            }}
            QHeaderView::section {{
                background: {Colors.SURFACE_RAISED};
                color: {Colors.TEXT_SECONDARY};
                border: none;
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
                padding: 7px 8px;
                font-family: {FONT_FAMILY};
                font-size: {Metrics.FONT_XS}pt;
                font-weight: 700;
            }}
            """
        )
        layout.addWidget(self._table)

        self.set_chapter_data(value, mixed=mixed)
        self._set_editable(editable)

    def set_chapter_data(self, value: Any, *, mixed: bool = False) -> None:
        self._loading = True
        try:
            self._initial_value = value
            self._mixed = mixed
            self._table.setRowCount(0)
            if not mixed:
                for chapter in _chapter_entries_from_data(value):
                    self._append_row(chapter["startpos"], str(chapter["title"]))
        finally:
            self._loading = False
        self._sync_actions()
        self._sync_summary()

    def chapter_data(self) -> dict[str, Any]:
        chapters = self._chapters_from_table(validate_order=True)
        return _chapter_data_with_entries(self._initial_value, chapters)

    def add_chapter(self) -> None:
        if not self._editable:
            return
        selected_rows = self._selected_rows()
        insert_at = (selected_rows[-1] + 1) if selected_rows else self._table.rowCount()
        startpos = self._suggest_start_for_insert(insert_at)
        self._insert_row(insert_at, startpos, f"Chapter {insert_at + 1}")
        self._renumber_default_titles()
        self._mixed = False
        self._table.selectRow(insert_at)
        self._emit_modified()

    def delete_selected_chapters(self) -> None:
        if not self._editable:
            return
        rows = self._selected_rows()
        if not rows:
            return
        self._loading = True
        try:
            for row in reversed(rows):
                self._table.removeRow(row)
        finally:
            self._loading = False
        self._renumber_default_titles()
        self._emit_modified()

    def sort_by_time(self) -> None:
        if not self._editable:
            return
        try:
            chapters = self._chapters_from_table(validate_order=False)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Chapter Time", str(exc))
            return
        chapters.sort(key=lambda chapter: int(chapter["startpos"]))
        self._loading = True
        try:
            self._table.setRowCount(0)
            for chapter in chapters:
                self._append_row(int(chapter["startpos"]), str(chapter["title"]))
        finally:
            self._loading = False
        self._emit_modified()

    def _set_editable(self, editable: bool) -> None:
        self._editable = editable
        self._add_btn.setEnabled(editable)
        self._sort_btn.setEnabled(editable)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            if editable
            else QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._sync_actions()

    def _chapters_from_table(self, *, validate_order: bool) -> list[dict[str, Any]]:
        chapters: list[dict[str, Any]] = []
        previous_start: int | None = None
        for row in range(self._table.rowCount()):
            start_item = self._table.item(row, 0)
            title_item = self._table.item(row, 1)
            start_text = start_item.text() if start_item is not None else ""
            title_text = title_item.text() if title_item is not None else ""
            startpos = _parse_chapter_time_text(start_text, f"Chapter {row + 1} start")
            if validate_order and previous_start is not None and startpos <= previous_start:
                raise ValueError("Chapter start times must be in ascending order with no duplicates.")
            previous_start = startpos
            title = title_text.strip() or f"Chapter {row + 1}"
            chapters.append({"startpos": startpos, "title": title})
        return chapters

    def _append_row(self, startpos: int, title: str) -> None:
        self._insert_row(self._table.rowCount(), startpos, title)

    def _insert_row(self, row: int, startpos: int, title: str) -> None:
        self._loading = True
        try:
            self._table.insertRow(row)
            time_item = QTableWidgetItem(_format_chapter_time_for_editor(startpos))
            title_item = QTableWidgetItem(title)
            flags = (
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
            )
            time_item.setFlags(flags)
            title_item.setFlags(flags)
            time_item.setToolTip(_CHAPTER_TIME_HINT)
            title_item.setToolTip("Chapter title")
            self._table.setItem(row, 0, time_item)
            self._table.setItem(row, 1, title_item)
        finally:
            self._loading = False
        self._sync_actions()
        self._sync_summary()

    def _suggest_start_for_insert(self, row: int) -> int:
        chapters: list[dict[str, Any]]
        try:
            chapters = self._chapters_from_table(validate_order=False)
        except ValueError:
            return max(0, row) * 60_000
        if not chapters:
            return 0

        previous = chapters[row - 1]["startpos"] if row > 0 else 0
        next_start = chapters[row]["startpos"] if row < len(chapters) else None
        previous = int(previous)
        if next_start is not None:
            next_start = int(next_start)
            if next_start > previous + 1000:
                return previous + ((next_start - previous) // 2)
        return previous + 60_000

    def _selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self._table.selectedIndexes()})

    @staticmethod
    def _is_default_title(text: str) -> bool:
        stripped = text.strip()
        return stripped.startswith("Chapter ") and stripped.removeprefix("Chapter ").isdigit()

    def _renumber_default_titles(self) -> None:
        self._loading = True
        try:
            for row in range(self._table.rowCount()):
                item = self._table.item(row, 1)
                if item is not None and (
                    not item.text().strip() or self._is_default_title(item.text())
                ):
                    item.setText(f"Chapter {row + 1}")
        finally:
            self._loading = False

    def _on_item_changed(self, _item: QTableWidgetItem) -> None:
        self._mixed = False
        self._emit_modified()

    def _emit_modified(self) -> None:
        if self._loading:
            return
        self._sync_actions()
        self._sync_summary()
        self.modifiedChanged.emit()

    def _sync_actions(self) -> None:
        rows = self._selected_rows()
        self._delete_btn.setEnabled(self._editable and bool(rows))
        self._sort_btn.setEnabled(self._editable and self._table.rowCount() > 1)

    def _sync_summary(self) -> None:
        if self._mixed and self._table.rowCount() == 0:
            self._summary.setText("Mixed chapter values")
            return
        count = self._table.rowCount()
        if count == 0:
            self._summary.setText("No chapters")
            return
        noun = "chapter" if count == 1 else "chapters"
        self._summary.setText(f"{count} {noun}")


class _TrackFieldRow(QFrame):
    modifiedChanged = pyqtSignal()

    def __init__(self, spec: TrackFieldSpec, value: Any, parent: QWidget | None = None):
        super().__init__(parent)
        self.spec = spec
        self._initializing = True
        self._initial_value = value
        self._mixed = value is MIXED
        self._modified = False
        self.setObjectName("trackFieldRow")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        label = QLabel(spec.label)
        label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        if spec.help_text:
            label.setToolTip(spec.help_text)
        header.addWidget(label)
        header.addStretch()

        if not spec.editable:
            read_only = QLabel("Read-only")
            read_only.setObjectName("readOnlyPill")
            read_only.setToolTip(spec.help_text)
            read_only.setStyleSheet(
                f"""
                QLabel#readOnlyPill {{
                    background: {Colors.SURFACE_ALT};
                    border: 1px solid {Colors.BORDER_SUBTLE};
                    border-radius: {Metrics.BORDER_RADIUS_SM}px;
                    color: {Colors.TEXT_TERTIARY};
                    padding: 2px 7px;
                    font-family: {FONT_FAMILY};
                    font-size: {Metrics.FONT_XS}pt;
                }}
                """
            )
            header.addWidget(read_only)

        self.reset_button = QPushButton("Reset")
        self.reset_button.setObjectName("fieldResetButton")
        self.reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_button.setVisible(False)
        self.reset_button.setFixedHeight(Design.CONTROL_HEIGHT_SM)
        self.reset_button.clicked.connect(self.reset)
        self.reset_button.setStyleSheet(
            f"""
            QPushButton#fieldResetButton {{
                background: transparent;
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_SECONDARY};
                padding: 2px 8px;
                font-family: {FONT_FAMILY};
                font-size: {Metrics.FONT_SM}pt;
            }}
            QPushButton#fieldResetButton:hover {{
                border-color: {Colors.BORDER_FOCUS};
                color: {Colors.TEXT_PRIMARY};
            }}
            """
        )
        header.addWidget(self.reset_button)
        layout.addLayout(header)

        self.editor = self._build_editor(value)
        if spec.help_text:
            self.editor.setToolTip(spec.help_text)
        layout.addWidget(self.editor)

        self._initializing = False

    def matches(self, query: str) -> bool:
        haystack = (
            f"{self.spec.label} {self.spec.key} {self.spec.group} "
            f"{self.spec.help_text}"
        )
        return matches_search(query, haystack)

    def is_modified(self) -> bool:
        return self._modified

    def value(self) -> Any:
        return self._editor_value()

    def reset(self) -> None:
        self._set_editor_to_initial()
        self._set_modified(False)

    def _mark_modified(self) -> None:
        if self._initializing or not self.spec.editable:
            return
        editor = self.editor
        if isinstance(editor, QComboBox) and editor.currentData() is MIXED:
            self._set_modified(False)
            return
        self._set_modified(True)

    def _set_modified(self, modified: bool) -> None:
        if modified and not self.spec.editable:
            return
        if self._modified == modified:
            return
        self._modified = modified
        self.reset_button.setVisible(modified)
        self.setProperty("modified", modified)
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
        self.modifiedChanged.emit()

    def _set_editor_to_initial(self) -> None:
        self._initializing = True
        try:
            editor = self.editor
            value = self._initial_value
            mixed = value is MIXED
            self._mixed = mixed
            if isinstance(editor, QComboBox):
                for index in range(editor.count()):
                    data = editor.itemData(index)
                    if (mixed and data is MIXED) or (not mixed and data == value):
                        editor.setCurrentIndex(index)
                        break
            elif isinstance(editor, QPlainTextEdit):
                editor.setPlaceholderText("Mixed values" if mixed else "")
                editor.setPlainText("" if mixed or value is None else self._format_value(value))
            elif isinstance(editor, QLineEdit):
                editor.setPlaceholderText("Mixed values" if mixed else "")
                editor.setText("" if mixed or value is None else self._format_value(value))
            elif isinstance(editor, _ChapterTimelineEditor):
                editor.set_chapter_data(value, mixed=mixed)
        finally:
            self._initializing = False

    def _field_css(self) -> str:
        return f"""
            QLineEdit, QPlainTextEdit, QComboBox {{
                background: {Colors.SURFACE_ALT};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_PRIMARY};
                padding: 7px 9px;
                font-family: {FONT_FAMILY};
                font-size: {Metrics.FONT_SM}pt;
            }}
            QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
                border-color: {Colors.BORDER_FOCUS};
            }}
            QLineEdit:read-only, QPlainTextEdit[readOnly="true"], QComboBox:disabled {{
                background: {Colors.SURFACE};
                color: {Colors.TEXT_SECONDARY};
                border-color: {Colors.BORDER_SUBTLE};
            }}
            QComboBox QAbstractItemView {{
                background: {Colors.DROPDOWN_BG};
                color: {Colors.TEXT_PRIMARY};
                selection-background-color: {Colors.ACCENT};
                selection-color: {Colors.TEXT_ON_ACCENT};
            }}
        """

    def _build_editor(self, value: Any) -> QWidget:
        if self.spec.kind in {
            "bool",
            "checked_flag",
            "rating",
            "explicit",
            "played_mark",
            "podcast_display",
            "artwork_presence",
            "media_type",
        }:
            return self._build_combo(value)
        if self.spec.kind == "long_text":
            editor = QPlainTextEdit()
            editor.setPlaceholderText("Mixed values" if self._mixed else "")
            editor.setPlainText("" if self._mixed or value is None else str(value))
            editor.setMinimumHeight(92)
            editor.setStyleSheet(self._field_css())
            editor.setReadOnly(not self.spec.editable)
            editor.textChanged.connect(self._mark_modified)
            return editor
        if self.spec.kind == "chapters":
            editor = _ChapterTimelineEditor(
                value,
                mixed=self._mixed,
                editable=self.spec.editable,
            )
            editor.modifiedChanged.connect(self._mark_modified)
            return editor

        editor = QLineEdit()
        editor.setPlaceholderText("Mixed values" if self._mixed else "")
        editor.setText("" if self._mixed or value is None else self._format_value(value))
        editor.setStyleSheet(self._field_css())
        editor.setMinimumHeight(34)
        editor.setReadOnly(not self.spec.editable)
        editor.textChanged.connect(self._mark_modified)
        return editor

    def _build_combo(self, value: Any) -> QComboBox:
        combo = QComboBox()
        combo.setStyleSheet(self._field_css())
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.setMinimumHeight(34)

        options = self._combo_options(value)
        if self._mixed:
            combo.addItem("Mixed values", MIXED)
        for label, data in options:
            combo.addItem(label, data)

        if not self._mixed:
            found = False
            for index in range(combo.count()):
                if combo.itemData(index) == value:
                    combo.setCurrentIndex(index)
                    found = True
                    break
            if not found and value is not None:
                combo.addItem(f"Current ({value})", value)
                combo.setCurrentIndex(combo.count() - 1)

        combo.currentIndexChanged.connect(self._mark_modified)
        combo.setEnabled(self.spec.editable)
        return combo

    def _combo_options(self, value: Any) -> tuple[tuple[str, Any], ...]:
        if self.spec.kind == "checked_flag":
            return _CHECKED_OPTIONS
        if self.spec.kind == "rating":
            return _RATING_OPTIONS
        if self.spec.kind == "explicit":
            return _EXPLICIT_OPTIONS
        if self.spec.kind == "played_mark":
            return _PLAYED_MARK_OPTIONS
        if self.spec.kind == "podcast_display":
            return _PODCAST_DISPLAY_OPTIONS
        if self.spec.kind == "artwork_presence":
            return _ARTWORK_PRESENCE_OPTIONS
        if self.spec.kind == "media_type":
            if value is not MIXED and value is not None and all(data != value for _, data in _MEDIA_TYPE_OPTIONS):
                return _MEDIA_TYPE_OPTIONS + ((f"Custom ({value})", value),)
            return _MEDIA_TYPE_OPTIONS
        return _BOOL_OPTIONS

    def _format_value(self, value: Any) -> str:
        if self.spec.kind == "chapters":
            return _format_chapter_data(value)
        if self.spec.kind == "date":
            return _format_datetime_value(value)
        if isinstance(value, bytes):
            return value.hex()
        return repr(value) if isinstance(value, (list, tuple, dict, bytearray)) else str(value)

    def _editor_value(self) -> Any:
        editor = self.editor
        if isinstance(editor, QComboBox):
            data = editor.currentData()
            if data is MIXED:
                raise ValueError(f"{self.spec.label} is still mixed")
            return data
        if isinstance(editor, _ChapterTimelineEditor):
            return editor.chapter_data()
        if isinstance(editor, QPlainTextEdit):
            text = editor.toPlainText()
        elif isinstance(editor, QLineEdit):
            text = editor.text()
        else:
            return None

        if self.spec.kind == "int":
            return int(text.strip() or "0", 0)
        if self.spec.kind == "float":
            return float(text.strip() or "0")
        if self.spec.kind == "date":
            return _parse_datetime_text(text, self.spec.label)
        if self.spec.kind == "literal":
            return _parse_literal_text(text)
        return text


def _parse_literal_text(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return b""
    try:
        return ast.literal_eval(stripped)
    except (SyntaxError, ValueError):
        try:
            return bytes.fromhex(stripped)
        except ValueError:
            return stripped


def _format_datetime_value(unix_timestamp: Any) -> str:
    if unix_timestamp in (None, ""):
        return ""
    try:
        ts = int(unix_timestamp)
    except (TypeError, ValueError):
        return str(unix_timestamp)
    if ts <= 0:
        return ""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return str(unix_timestamp)


def _parse_datetime_text(text: str, label: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    try:
        return int(stripped, 0)
    except ValueError:
        pass

    normalized = stripped.replace("T", " ")
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            dt = dateutil_parser.parse(
                stripped,
                fuzzy=True,
                default=datetime(1970, 1, 1, 0, 0, 0),
            )
        except (ParserError, OverflowError, TypeError, ValueError) as exc:
            raise ValueError(
                f"{label} must be a Unix timestamp or a recognizable date/time like 2024-03-09 17:00 or Mar 9 2024 5pm"
            ) from exc
    try:
        return int(dt.timestamp())
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError(
            f"{label} could not be converted into a valid Unix timestamp"
        ) from exc


_ARTWORK_CROP_OUTPUT_SIZE = 1200
_ARTWORK_TEMP_PREFIX = "iopenpod-artwork-"


class _SquareCropCanvas(QWidget):
    """Interactive square crop surface for album artwork images."""

    scaleChanged = pyqtSignal(float)

    def __init__(self, image: Image.Image, parent: QWidget | None = None):
        super().__init__(parent)
        self._image = image.convert("RGB")
        self._pixmap = pil_to_pixmap(self._image)
        self._scale = 1.0
        self._min_scale = 1.0
        self._max_scale = 5.0
        self._center = QPointF()
        self._drag_start: QPointF | None = None
        self._drag_center = QPointF()
        self._view_initialized = False
        self.setMinimumSize(420, 420)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def zoom_fraction(self) -> float:
        span = self._max_scale - self._min_scale
        if span <= 0:
            return 0.0
        return (self._scale - self._min_scale) / span

    def set_zoom_fraction(self, fraction: float) -> None:
        fraction = max(0.0, min(1.0, fraction))
        self._update_scale_bounds()
        self._scale = self._min_scale + (self._max_scale - self._min_scale) * fraction
        self._clamp_center()
        self.scaleChanged.emit(self.zoom_fraction())
        self.update()

    def reset_view(self) -> None:
        self._update_scale_bounds()
        self._scale = self._min_scale
        self._center = self._crop_rect().center()
        self._view_initialized = True
        self._clamp_center()
        self.scaleChanged.emit(self.zoom_fraction())
        self.update()

    def cropped_image(self) -> Image.Image:
        self._update_scale_bounds()
        self._clamp_center()
        crop = self._crop_rect()
        image_rect = self._image_rect()
        scale = max(self._scale, 0.0001)
        left = (crop.left() - image_rect.left()) / scale
        top = (crop.top() - image_rect.top()) / scale
        right = (crop.right() - image_rect.left()) / scale
        bottom = (crop.bottom() - image_rect.top()) / scale

        width, height = self._image.size
        left = max(0.0, min(float(width), left))
        top = max(0.0, min(float(height), top))
        right = max(left + 1.0, min(float(width), right))
        bottom = max(top + 1.0, min(float(height), bottom))

        box = (
            int(round(left)),
            int(round(top)),
            int(round(right)),
            int(round(bottom)),
        )
        cropped = self._image.crop(box)
        if cropped.width != cropped.height:
            side = min(cropped.width, cropped.height)
            cropped = cropped.crop((0, 0, side, side))
        if cropped.size != (_ARTWORK_CROP_OUTPUT_SIZE, _ARTWORK_CROP_OUTPUT_SIZE):
            cropped = cropped.resize(
                (_ARTWORK_CROP_OUTPUT_SIZE, _ARTWORK_CROP_OUTPUT_SIZE),
                Image.Resampling.LANCZOS,
            )
        return cropped

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        super().paintEvent(a0)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor(18, 20, 24))

        if not self._view_initialized:
            self.reset_view()

        image_rect = self._image_rect()
        painter.drawPixmap(image_rect, self._pixmap, QRectF(self._pixmap.rect()))

        crop = self._crop_rect()
        overlay = QColor(0, 0, 0, 150)
        painter.fillRect(QRectF(0, 0, self.width(), crop.top()), overlay)
        painter.fillRect(
            QRectF(0, crop.bottom(), self.width(), self.height() - crop.bottom()),
            overlay,
        )
        painter.fillRect(QRectF(0, crop.top(), crop.left(), crop.height()), overlay)
        painter.fillRect(
            QRectF(crop.right(), crop.top(), self.width() - crop.right(), crop.height()),
            overlay,
        )

        grid_pen = QPen(QColor(255, 255, 255, 95))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        third = crop.width() / 3.0
        for index in (1, 2):
            x = int(round(crop.left() + third * index))
            y = int(round(crop.top() + third * index))
            painter.drawLine(x, int(crop.top()), x, int(crop.bottom()))
            painter.drawLine(int(crop.left()), y, int(crop.right()), y)

        border_pen = QPen(QColor(255, 255, 255, 235))
        border_pen.setWidth(2)
        painter.setPen(border_pen)
        painter.drawRect(crop)

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        old_fraction = self.zoom_fraction()
        self._update_scale_bounds()
        if not self._view_initialized:
            self.reset_view()
            return
        self._scale = self._min_scale + (self._max_scale - self._min_scale) * old_fraction
        self._clamp_center()

    def wheelEvent(self, a0: QWheelEvent | None) -> None:
        if a0 is None:
            return
        delta = a0.angleDelta().y()
        if delta == 0:
            return
        self.set_zoom_fraction(self.zoom_fraction() + (delta / 120.0) * 0.06)
        a0.accept()

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None:
            return
        if a0.button() == Qt.MouseButton.LeftButton:
            self._drag_start = a0.position()
            self._drag_center = QPointF(self._center)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            a0.accept()
            return
        super().mousePressEvent(a0)

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None:
            return
        if self._drag_start is None:
            super().mouseMoveEvent(a0)
            return
        delta = a0.position() - self._drag_start
        self._center = self._drag_center + delta
        self._clamp_center()
        self.update()
        a0.accept()

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is None:
            return
        if a0.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
            self._drag_start = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            a0.accept()
            return
        super().mouseReleaseEvent(a0)

    def _crop_rect(self) -> QRectF:
        side = max(160.0, min(float(self.width()), float(self.height())) - 32.0)
        side = min(side, float(self.width()), float(self.height()))
        return QRectF(
            (self.width() - side) / 2.0,
            (self.height() - side) / 2.0,
            side,
            side,
        )

    def _image_rect(self) -> QRectF:
        width, height = self._image.size
        draw_w = width * self._scale
        draw_h = height * self._scale
        return QRectF(
            self._center.x() - draw_w / 2.0,
            self._center.y() - draw_h / 2.0,
            draw_w,
            draw_h,
        )

    def _update_scale_bounds(self) -> None:
        crop = self._crop_rect()
        width, height = self._image.size
        self._min_scale = max(crop.width() / width, crop.height() / height)
        self._max_scale = max(self._min_scale * 5.0, self._min_scale + 0.01)
        self._scale = max(self._min_scale, min(self._max_scale, self._scale))

    def _clamp_center(self) -> None:
        crop = self._crop_rect()
        width, height = self._image.size
        draw_w = width * self._scale
        draw_h = height * self._scale

        min_x = crop.right() - draw_w / 2.0
        max_x = crop.left() + draw_w / 2.0
        min_y = crop.bottom() - draw_h / 2.0
        max_y = crop.top() + draw_h / 2.0

        if min_x > max_x:
            clamped_x = crop.center().x()
        else:
            clamped_x = max(min_x, min(max_x, self._center.x()))
        if min_y > max_y:
            clamped_y = crop.center().y()
        else:
            clamped_y = max(min_y, min(max_y, self._center.y()))
        self._center = QPointF(clamped_x, clamped_y)


class _ArtworkCropDialog(QDialog):
    """Modal cropper that returns a square PIL image."""

    def __init__(self, image_path: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._image_path = image_path
        self._cropped_image: Image.Image | None = None
        with Image.open(image_path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")

        self.setWindowTitle("Crop Artwork")
        self.setMinimumSize(560, 650)
        self.resize(660, 740)
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {Colors.DIALOG_BG};
            }}
            QLabel {{
                color: {Colors.TEXT_SECONDARY};
                font-family: {FONT_FAMILY};
                font-size: {Metrics.FONT_SM}pt;
            }}
            QSlider::groove:horizontal {{
                background: {Colors.SURFACE_ALT};
                border: 1px solid {Colors.BORDER_SUBTLE};
                height: 6px;
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {Colors.ACCENT};
                border: 1px solid {Colors.ACCENT_BORDER};
                width: 16px;
                height: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._canvas = _SquareCropCanvas(image, self)
        layout.addWidget(self._canvas, 1)

        scale_row = QHBoxLayout()
        scale_row.setContentsMargins(0, 0, 0, 0)
        scale_row.setSpacing(10)
        scale_label = QLabel("Scale")
        scale_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        scale_row.addWidget(scale_label)
        self._scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._scale_slider.setRange(0, 100)
        self._scale_slider.setValue(0)
        self._scale_slider.valueChanged.connect(
            lambda value: self._canvas.set_zoom_fraction(value / 100.0)
        )
        self._canvas.scaleChanged.connect(self._sync_scale_slider)
        scale_row.addWidget(self._scale_slider, 1)
        reset_btn = QPushButton("Reset")
        reset_btn.setStyleSheet(btn_css())
        reset_btn.clicked.connect(self._canvas.reset_view)
        scale_row.addWidget(reset_btn)
        layout.addLayout(scale_row)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(btn_css())
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        use = QPushButton("Use Artwork")
        use.setStyleSheet(accent_btn_css())
        use.clicked.connect(self.accept)
        buttons.addWidget(use)
        layout.addLayout(buttons)

    def cropped_image(self) -> Image.Image | None:
        return self._cropped_image

    def accept(self) -> None:
        self._cropped_image = self._canvas.cropped_image()
        super().accept()

    def _sync_scale_slider(self, fraction: float) -> None:
        self._scale_slider.blockSignals(True)
        self._scale_slider.setValue(int(round(max(0.0, min(1.0, fraction)) * 100)))
        self._scale_slider.blockSignals(False)


class _ArtworkPreviewPanel(QFrame):
    """Preview assigned track artwork and its decoded device format variants."""

    changeArtworkRequested = pyqtSignal()
    unifyArtworkRequested = pyqtSignal()

    def __init__(
        self,
        artworks: list[TrackArtworkPreview],
        tracks: list[dict] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._all_previews = list(artworks)
        self._tracks = list(tracks or [])
        self._artworks, self._has_multiple_images = self._aggregate_artworks(artworks)
        self._has_mixed_artwork_presence = self._mixed_artwork_presence(
            self._tracks,
            artworks,
        )
        self._unify_context = self._build_unify_context()
        self._format_index = 0
        self._source_pixmap = QPixmap()
        self._pending_pixmap = QPixmap()
        self._pending_metadata: tuple[tuple[str, str], ...] = ()
        self._scale_queued = False
        self.setObjectName("sectionPanel")

        self.setStyleSheet(
            panel_css(
                "artworkPreviewRail",
                bg=Colors.SURFACE_ALT,
                radius=Metrics.BORDER_RADIUS_SM,
            )
            + panel_css(
                "artworkMetadataPanel",
                bg=Colors.SURFACE_ALT,
                radius=Metrics.BORDER_RADIUS_SM,
            )
            + f"""
            QLabel#artworkInspectorLabel {{
                color: {Colors.TEXT_TERTIARY};
                background: transparent;
                text-transform: uppercase;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self._title_label = QLabel("Assigned Artwork")
        self._title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.Bold))
        self._title_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        header.addWidget(self._title_label)
        header.addStretch()

        self._change_btn = QPushButton("Change Artwork")
        self._change_btn.setStyleSheet(btn_css())
        self._change_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._change_btn.setToolTip("Choose a new artwork image")
        self._change_btn.clicked.connect(self.changeArtworkRequested.emit)
        header.addWidget(self._change_btn)

        self._unify_btn = QPushButton("Unify Artwork")
        self._unify_btn.setStyleSheet(btn_css())
        self._unify_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._unify_btn.setToolTip("Pick one selected artwork image for all selected tracks")
        self._unify_btn.clicked.connect(self.unifyArtworkRequested.emit)
        header.addWidget(self._unify_btn)

        layout.addLayout(header)

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(10)
        layout.addLayout(content, 1)

        preview_rail = QFrame()
        preview_rail.setObjectName("artworkPreviewRail")
        preview_rail.setMinimumWidth(250)
        preview_rail.setMaximumWidth(320)
        preview_rail.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        preview_layout = QVBoxLayout(preview_rail)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.setSpacing(7)
        content.addWidget(preview_rail, 0)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumHeight(220)
        self._image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._image_label.setStyleSheet(
            f"""
            QLabel {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_TERTIARY};
                padding: 8px;
            }}
            """
        )
        preview_layout.addWidget(self._image_label, 1)

        self._meta_label = QLabel("")
        self._meta_label.setWordWrap(True)
        self._meta_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._meta_label.setStyleSheet(
            f"""
            QLabel {{
                color: {Colors.TEXT_SECONDARY};
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                padding: 6px 7px;
            }}
            """
        )
        preview_layout.addWidget(self._meta_label)

        format_label = QLabel("Formats")
        format_label.setObjectName("artworkInspectorLabel")
        format_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.Bold))
        preview_layout.addWidget(format_label)

        self._format_buttons_host = QWidget()
        self._format_buttons_layout = FlowLayout(self._format_buttons_host, spacing=5)
        self._format_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._format_buttons_host.setMinimumHeight(32)
        preview_layout.addWidget(self._format_buttons_host)

        metadata_panel = QFrame()
        metadata_panel.setObjectName("artworkMetadataPanel")
        metadata_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        metadata_layout = QVBoxLayout(metadata_panel)
        metadata_layout.setContentsMargins(8, 8, 8, 8)
        metadata_layout.setSpacing(6)
        content.addWidget(metadata_panel, 1)

        metadata_label = QLabel("ArtworkDB Fields")
        metadata_label.setObjectName("artworkInspectorLabel")
        metadata_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.Bold))
        metadata_layout.addWidget(metadata_label)

        self._metadata_tree = QTreeWidget()
        self._metadata_tree.setHeaderLabels(["ArtworkDB Field", "Value"])
        self._metadata_tree.setRootIsDecorated(True)
        self._metadata_tree.setAlternatingRowColors(True)
        self._metadata_tree.setUniformRowHeights(False)
        self._metadata_tree.setWordWrap(True)
        self._metadata_tree.setAllColumnsShowFocus(True)
        self._metadata_tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._metadata_tree.setMinimumHeight(290)
        self._metadata_tree.setStyleSheet(
            f"""
            QTreeWidget {{
                background: {Colors.SURFACE};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                padding: 3px;
            }}
            QTreeWidget::item {{
                padding: 2px 2px;
            }}
            QTreeWidget::item:selected {{
                background: {Colors.SURFACE_ACTIVE};
                color: {Colors.TEXT_PRIMARY};
            }}
            QHeaderView::section {{
                background: {Colors.SURFACE_RAISED};
                color: {Colors.TEXT_SECONDARY};
                border: none;
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
                padding: 6px;
                font-weight: 600;
            }}
            """
        )
        header_view = self._metadata_tree.header()
        if header_view is not None:
            header_view.setStretchLastSection(True)
            header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        metadata_layout.addWidget(self._metadata_tree, 1)

        self._render()

    @classmethod
    def _track_has_artwork(
        cls,
        track: dict,
        preview_img_ids: set[int],
        preview_song_ids: set[int],
    ) -> bool:
        if track.get("_iop_pending_artwork_path"):
            return True
        artwork_id = track_artwork_id(track)
        if artwork_id is not None and artwork_id in preview_img_ids:
            return True
        for key in ("db_track_id", "track_id"):
            try:
                track_id = int(track.get(key) or 0)
            except (TypeError, ValueError):
                track_id = 0
            if track_id and track_id in preview_song_ids:
                return True
        return False

    @classmethod
    def _mixed_artwork_presence(
        cls,
        tracks: list[dict],
        artworks: list[TrackArtworkPreview],
    ) -> bool:
        if len(tracks) < 2:
            return False
        preview_img_ids = {
            int(artwork.img_id)
            for artwork in artworks
            if int(artwork.img_id or 0) > 0
        }
        preview_song_ids = {
            int(artwork.song_id)
            for artwork in artworks
            if int(artwork.song_id or 0) > 0
        }
        presence = [
            cls._track_has_artwork(track, preview_img_ids, preview_song_ids)
            for track in tracks
        ]
        return any(presence) and not all(presence)

    @classmethod
    def _aggregate_artworks(
        cls,
        artworks: list[TrackArtworkPreview],
    ) -> tuple[list[TrackArtworkPreview], bool]:
        unique_by_hash: dict[str, TrackArtworkPreview] = {}
        fallback_without_decodable_image: list[TrackArtworkPreview] = []

        for artwork in artworks:
            variant = representative_artwork_variant(artwork)
            if variant is None:
                fallback_without_decodable_image.append(artwork)
                continue
            digest = artwork_compare_hash(variant.image)
            unique_by_hash.setdefault(digest, artwork)

        if len(unique_by_hash) > 1:
            return [], True
        if len(unique_by_hash) == 1:
            return [next(iter(unique_by_hash.values()))], False
        return fallback_without_decodable_image[:1], False

    @staticmethod
    def _metadata_rows_to_map(rows: tuple[tuple[str, str], ...]) -> dict[str, str]:
        mapped: dict[str, str] = {}
        for key, value in rows:
            key_text = str(key).strip()
            if not key_text:
                continue
            value_text = str(value)
            existing = mapped.get(key_text)
            if existing is not None and existing != value_text:
                mapped[key_text] = _MIXED_ARTWORK_METADATA_VALUE
            else:
                mapped[key_text] = value_text
        return mapped

    @classmethod
    def _aggregate_metadata_rows(
        cls,
        observations: list[tuple[tuple[str, str], ...]],
        *,
        include_missing_observation: bool = False,
    ) -> tuple[tuple[str, str], ...]:
        metadata_maps = [cls._metadata_rows_to_map(rows) for rows in observations]
        key_order: list[str] = []
        seen_keys: set[str] = set()
        for metadata in metadata_maps:
            for key in metadata:
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                key_order.append(key)

        aggregated: list[tuple[str, str]] = []
        for key in key_order:
            values: list[str | object] = [
                metadata.get(key, _MISSING_ARTWORK_METADATA)
                for metadata in metadata_maps
            ]
            if include_missing_observation:
                values.append(_MISSING_ARTWORK_METADATA)

            present_values = [value for value in values if isinstance(value, str)]
            if len(present_values) == len(values) and len(set(present_values)) == 1:
                aggregated.append((key, present_values[0]))
            else:
                aggregated.append((key, _MIXED_ARTWORK_METADATA_VALUE))
        return tuple(aggregated)

    def _aggregate_artwork_metadata_sections(
        self,
        *,
        include_missing_observation: bool,
    ) -> list[tuple[str, tuple[tuple[str, str], ...]]]:
        image_rows = self._aggregate_metadata_rows(
            [artwork.metadata for artwork in self._all_previews],
            include_missing_observation=include_missing_observation,
        )

        format_observations: list[tuple[tuple[str, str], ...]] = []
        missing_format_observation = include_missing_observation
        for artwork in self._all_previews:
            variant = representative_artwork_variant(artwork)
            if variant is None:
                missing_format_observation = True
                continue
            format_observations.append(variant.metadata)

        format_rows = self._aggregate_metadata_rows(
            format_observations,
            include_missing_observation=missing_format_observation,
        )

        sections: list[tuple[str, tuple[tuple[str, str], ...]]] = []
        if image_rows:
            sections.append(("ArtworkDB Image Item", image_rows))
        if format_rows:
            sections.append(("Representative Format Container", format_rows))
        return sections

    def _build_unify_context(self) -> ArtworkUnifyContext | None:
        if not (self._has_mixed_artwork_presence or self._has_multiple_images):
            return None
        return build_track_artwork_unify_context(
            "Selected Tracks",
            self._tracks,
            self._all_previews,
        )

    def unify_context(self) -> ArtworkUnifyContext | None:
        return self._unify_context

    def set_pending_artwork(self, image: Image.Image, source_path: str) -> None:
        self._pending_pixmap = pil_to_pixmap(image)
        source_name = os.path.basename(source_path) or source_path
        self._pending_metadata = (
            ("Source", source_name),
            ("Cropped Size", f"{image.width}x{image.height}"),
            ("Final Shape", "Square"),
        )
        self._render()

    def clear_pending_artwork(self) -> None:
        self._pending_pixmap = QPixmap()
        self._pending_metadata = ()
        self._render()

    def _select_format(self, index: int) -> None:
        self._format_index = index
        self._render()

    def _render(self) -> None:
        self._unify_btn.setVisible(
            self._pending_pixmap.isNull() and self._unify_context is not None
        )
        if not self._pending_pixmap.isNull():
            self._title_label.setText("New Artwork")
            self._source_pixmap = self._pending_pixmap
            self._image_label.clear()
            size_text = next(
                (value for key, value in self._pending_metadata if key == "Cropped Size"),
                "",
            )
            self._meta_label.setText(
                "New artwork: pending apply"
                if not size_text
                else f"New artwork: {size_text}, pending apply"
            )
            self._set_format_buttons([])
            self._set_metadata_sections([("Pending Image", self._pending_metadata)])
            self._queue_scaled_pixmap()
            return

        self._title_label.setText("Assigned Artwork")
        if self._has_mixed_artwork_presence:
            self._source_pixmap = QPixmap()
            self._image_label.clear()
            self._image_label.setText("Multiple values")
            self._meta_label.setText("Some selected tracks have artwork and some do not.")
            self._set_format_buttons([])
            self._set_metadata_sections(
                self._aggregate_artwork_metadata_sections(
                    include_missing_observation=True,
                )
            )
            return

        if self._has_multiple_images:
            self._source_pixmap = QPixmap()
            self._image_label.clear()
            self._image_label.setText("Multiple images")
            self._meta_label.setText("Selected tracks have different assigned artwork.")
            self._set_format_buttons([])
            self._set_metadata_sections(
                self._aggregate_artwork_metadata_sections(
                    include_missing_observation=False,
                )
            )
            return

        if not self._artworks:
            self._source_pixmap = QPixmap()
            self._image_label.clear()
            self._image_label.setText("No assigned artwork found")
            self._meta_label.setText("ArtworkDB data is not available for this track, or this track has no assigned artwork.")
            self._set_format_buttons([])
            self._set_metadata_sections([])
            return

        artwork = self._artworks[0]
        variants = list(artwork.variants)
        if not variants:
            self._source_pixmap = QPixmap()
            self._image_label.clear()
            self._image_label.setText("No decodable artwork formats")
            self._meta_label.setText(f"Artwork ID {artwork.img_id}")
            self._set_format_buttons([])
            self._set_metadata_sections([
                ("ArtworkDB Image Item", artwork.metadata),
            ])
            return

        self._format_index = max(0, min(self._format_index, len(variants) - 1))
        variant = variants[self._format_index]
        self._source_pixmap = pil_to_pixmap(variant.image)

        detail_parts = [
            f"Artwork ID {artwork.img_id}",
            f"Format {variant.format_id}",
        ]
        if variant.width and variant.height:
            detail_parts.append(f"{variant.width}x{variant.height}")
        if variant.pixel_format:
            detail_parts.append(variant.pixel_format)
        if variant.size:
            detail_parts.append(format_size(variant.size))
        if variant.filename:
            detail_parts.append(variant.filename)
        self._meta_label.setText(" - ".join(detail_parts))
        self._set_format_buttons(variants)
        self._set_metadata_sections([
            ("ArtworkDB Image Item", artwork.metadata),
            ("Selected Format Container", variant.metadata),
        ])
        self._queue_scaled_pixmap()

    def _set_metadata_sections(self, sections: list[tuple[str, tuple[tuple[str, str], ...]]]) -> None:
        self._metadata_tree.clear()
        has_rows = False
        for section_title, rows in sections:
            clean_rows = [(key, value) for key, value in rows if key]
            if not clean_rows:
                continue

            has_rows = True
            section_item = QTreeWidgetItem([section_title, ""])
            section_font = section_item.font(0)
            section_font.setBold(True)
            section_item.setFont(0, section_font)
            section_item.setFont(1, section_font)
            section_item.setFlags(section_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)

            for key, value in clean_rows:
                row_item = QTreeWidgetItem([key, value])
                row_item.setToolTip(0, key)
                row_item.setToolTip(1, value)
                section_item.addChild(row_item)

            self._metadata_tree.addTopLevelItem(section_item)
            section_item.setExpanded(True)

        if not has_rows:
            placeholder = QTreeWidgetItem(["No ArtworkDB metadata available", ""])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._metadata_tree.addTopLevelItem(placeholder)

    def _set_format_buttons(self, variants: list[Any]) -> None:
        while self._format_buttons_layout.count():
            item = self._format_buttons_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

        if not variants:
            return

        chip_css = chip_btn_css("sm")
        for index, variant in enumerate(variants):
            btn = QPushButton(variant.label)
            btn.setCheckable(True)
            btn.setChecked(index == self._format_index)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(Design.CONTROL_HEIGHT_SM)
            btn.setStyleSheet(chip_css)
            btn.clicked.connect(lambda _checked=False, index=index: self._select_format(index))
            self._format_buttons_layout.addWidget(btn)

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        self._queue_scaled_pixmap()

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        self._queue_scaled_pixmap()

    def _queue_scaled_pixmap(self) -> None:
        if self._source_pixmap.isNull() or self._scale_queued:
            return
        self._scale_queued = True
        QTimer.singleShot(0, self._apply_scaled_pixmap)

    def _apply_scaled_pixmap(self) -> None:
        self._scale_queued = False
        if self._source_pixmap.isNull():
            return
        self._image_label.setText("")
        target_size = self._image_label.contentsRect().size()
        if target_size.width() <= 0 or target_size.height() <= 0:
            target_size = self._image_label.size()
        if target_size.width() <= 32 or target_size.height() <= 32:
            target_size = QSize(
                max(220, self._image_label.minimumWidth()),
                max(220, self._image_label.minimumHeight()),
            )
        self._image_label.setPixmap(
            self._source_pixmap.scaled(
                target_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class TrackEditorDialog(QDialog):
    """iTunes-style metadata editor that applies fields edited by the user."""

    def __init__(self, tracks: list[dict], parent: QWidget | None = None):
        super().__init__(parent)
        _normalize_sort_title_aliases(tracks)
        self._tracks = tracks
        self._rows: list[_TrackFieldRow] = []
        self._changes: dict[str, Any] = {}
        self._page_rows: dict[str, list[_TrackFieldRow]] = {}
        self._page_items: dict[str, QListWidgetItem] = {}
        self._page_indices: dict[str, int] = {}
        self._section_rows: list[tuple[QFrame, list[_TrackFieldRow]]] = []
        self._artwork_panel: _ArtworkPreviewPanel | None = None
        self._pending_artwork_path: str | None = None
        self._accepted = False

        count = len(tracks)
        self.setWindowTitle(f"Edit {count} Track{'s' if count != 1 else ''}")
        self.setMinimumSize(860, 660)
        self.resize(980, 740)
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {Colors.DIALOG_BG};
            }}
            QFrame#trackFieldRow {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
            }}
            QFrame#trackFieldRow[modified="true"] {{
                background: {Colors.ACCENT_MUTED};
                border: 1px solid {Colors.ACCENT_BORDER};
            }}
            """
            + sidebar_item_view_css("QListWidget#sectionNav", background="transparent")
            + panel_css("editorHeader", radius=Metrics.BORDER_RADIUS_SM)
            + panel_css("sectionPanel", radius=Metrics.BORDER_RADIUS_SM)
        )

        self._build_ui()

    def changes(self) -> dict[str, Any]:
        if self._changes:
            return dict(self._changes)
        return dict(self._collect_changes())

    def artwork_path(self) -> str | None:
        return self._pending_artwork_path if self._accepted else None

    def accept(self) -> None:
        try:
            self._changes = self._collect_changes()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Track Edit", str(exc))
            return
        self._accepted = True
        super().accept()

    def reject(self) -> None:
        self._discard_pending_artwork()
        super().reject()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        header = QFrame()
        header.setObjectName("editorHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(12)

        title_wrap = QVBoxLayout()
        title_wrap.setContentsMargins(0, 0, 0, 0)
        title_wrap.setSpacing(3)

        title = QLabel(self.windowTitle())
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        title_wrap.addWidget(title)

        subtitle = QLabel(_selection_summary(self._tracks))
        subtitle.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        subtitle.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        title_wrap.addWidget(subtitle)

        header_layout.addLayout(title_wrap, 1)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter fields")
        self._search.setStyleSheet(
            input_css(padding="8px 10px", font_size=Metrics.FONT_SM)
        )
        self._search.textChanged.connect(self._apply_filter)
        self._search.setFixedWidth(260)
        header_layout.addWidget(self._search, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addWidget(header)

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(12)

        self._nav = QListWidget()
        self._nav.setObjectName("sectionNav")
        self._nav.setFixedWidth(178)
        self._nav.setFont(QFont(FONT_FAMILY, Metrics.FONT_SIDEBAR))
        self._nav.setSpacing(0)
        self._nav.setItemDelegate(_NoFocusItemDelegate(self._nav))
        self._nav.currentRowChanged.connect(self._on_nav_changed)
        content.addWidget(self._nav)

        self._stack = QStackedWidget()
        content.addWidget(self._stack, 1)
        outer.addLayout(content, 1)

        grouped: dict[str, list[TrackFieldSpec]] = {}
        for spec in build_track_field_specs(self._tracks):
            grouped.setdefault(spec.group, []).append(spec)

        for group in _GROUP_ORDER:
            specs = grouped.get(group)
            if specs:
                self._add_group_page(group, specs)
        if self._nav.count() > 0:
            self._nav.setCurrentRow(0)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self._change_label = QLabel("No changes")
        self._change_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._change_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        button_row.addWidget(self._change_label)

        self._reset_all_btn = QPushButton("Reset Changes")
        self._reset_all_btn.setStyleSheet(btn_css())
        self._reset_all_btn.setEnabled(False)
        self._reset_all_btn.clicked.connect(self._reset_all_changes)
        button_row.addWidget(self._reset_all_btn)

        button_row.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(btn_css())
        cancel.clicked.connect(self.reject)
        button_row.addWidget(cancel)

        apply = QPushButton("Apply")
        apply.setStyleSheet(accent_btn_css())
        apply.clicked.connect(self.accept)
        button_row.addWidget(apply)

        outer.addLayout(button_row)

    def _add_group_page(self, group: str, specs: list[TrackFieldSpec]) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)

        page_header = QFrame()
        page_header.setObjectName("sectionPanel")
        page_header_layout = QVBoxLayout(page_header)
        page_header_layout.setContentsMargins(14, 12, 14, 12)
        page_header_layout.setSpacing(3)
        heading = QLabel(_GROUP_TITLES.get(group, group))
        heading.setFont(QFont(FONT_FAMILY, Metrics.FONT_XL, QFont.Weight.Bold))
        heading.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        page_header_layout.addWidget(heading)
        description = QLabel(_GROUP_DESCRIPTIONS.get(group, ""))
        description.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        description.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        page_header_layout.addWidget(description)
        body_layout.addWidget(page_header)

        if group == "Artwork":
            try:
                artworks = get_track_artwork_previews(self._tracks)
            except Exception as exc:
                logger.warning("Failed to load track artwork previews: %s", exc)
                artworks = []
            self._artwork_panel = _ArtworkPreviewPanel(artworks, self._tracks, body)
            self._artwork_panel.changeArtworkRequested.connect(self._choose_artwork)
            self._artwork_panel.unifyArtworkRequested.connect(self._unify_artwork)
            body_layout.addWidget(self._artwork_panel)

        page_rows: list[_TrackFieldRow] = []
        for subgroup in _ordered_subgroups(specs):
            subgroup_specs = [
                spec for spec in specs
                if _subgroup_for_key(spec.key, spec.group) == subgroup
            ]
            if not subgroup_specs:
                continue

            panel = QFrame()
            panel.setObjectName("sectionPanel")
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(12, 10, 12, 12)
            panel_layout.setSpacing(10)

            section_title = QLabel(_SUBGROUP_TITLES.get(subgroup, _humanize_key(subgroup)))
            section_title.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.Bold))
            section_title.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
            panel_layout.addWidget(section_title)

            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(10)
            row_index = 0
            col_index = 0
            subsection_rows: list[_TrackFieldRow] = []
            for spec in subgroup_specs:
                field = _TrackFieldRow(spec, _common_value(self._tracks, spec.key), panel)
                field.modifiedChanged.connect(self._update_change_summary)
                self._rows.append(field)
                page_rows.append(field)
                subsection_rows.append(field)

                is_wide = spec.kind in {"long_text", "chapters"} or spec.key in {"Location", "Podcast Enclosure URL", "Podcast RSS URL"}
                if is_wide and col_index == 1:
                    row_index += 1
                    col_index = 0
                if is_wide:
                    grid.addWidget(field, row_index, 0, 1, 2)
                    row_index += 1
                    col_index = 0
                else:
                    grid.addWidget(field, row_index, col_index)
                    col_index += 1
                    if col_index >= 2:
                        row_index += 1
                        col_index = 0
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            panel_layout.addLayout(grid)
            self._section_rows.append((panel, subsection_rows))
            body_layout.addWidget(panel)

        body_layout.addStretch()

        scroll = make_scroll_area()
        scroll.setWidget(body)
        page_layout.addWidget(scroll)
        index = self._stack.addWidget(page)
        self._page_indices[group] = index
        self._page_rows[group] = page_rows

        item = QListWidgetItem(_GROUP_TITLES.get(group, group))
        item.setData(Qt.ItemDataRole.UserRole, group)
        self._nav.addItem(item)
        self._page_items[group] = item

    def _on_nav_changed(self, row: int) -> None:
        item = self._nav.item(row)
        if item is None:
            return
        group = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(group, str):
            return
        index = self._page_indices.get(group)
        if index is not None:
            self._stack.setCurrentIndex(index)

    def _reset_all_changes(self) -> None:
        for row in self._rows:
            if row.is_modified():
                row.reset()
        if self._pending_artwork_path:
            self._discard_pending_artwork()
            if self._artwork_panel is not None:
                self._artwork_panel.clear_pending_artwork()
        self._update_change_summary()

    def _update_change_summary(self) -> None:
        field_count = sum(1 for row in self._rows if row.is_modified())
        artwork_changed = self._pending_artwork_path is not None
        count = field_count + (1 if artwork_changed else 0)
        if count == 0:
            self._change_label.setText("No changes")
            self._reset_all_btn.setEnabled(False)
        else:
            if artwork_changed and field_count:
                self._change_label.setText(
                    f"{field_count} changed field{'s' if field_count != 1 else ''} + artwork"
                )
            elif artwork_changed:
                self._change_label.setText("Artwork changed")
            else:
                self._change_label.setText(
                    f"{field_count} changed field{'s' if field_count != 1 else ''}"
                )
            self._reset_all_btn.setEnabled(True)

    def _apply_filter(self, text: str) -> None:
        query = text.strip()
        visible_groups: list[str] = []
        for group, rows in self._page_rows.items():
            group_has_visible_rows = False
            for row in rows:
                visible = not query or row.matches(query)
                row.setVisible(visible)
                group_has_visible_rows = group_has_visible_rows or visible

            item = self._page_items.get(group)
            if item is not None:
                item.setHidden(bool(query) and not group_has_visible_rows)
            if group_has_visible_rows:
                visible_groups.append(group)

        for panel, rows in self._section_rows:
            # Use each row's explicit hidden state here instead of effective
            # visibility. Once a parent panel is hidden, child rows report
            # not visible even after being matched again by a new filter.
            panel.setVisible(any(not row.isHidden() for row in rows))

        current = self._nav.currentItem()
        if visible_groups and (current is None or current.isHidden()):
            first_visible = self._page_items.get(visible_groups[0])
            if first_visible is not None:
                self._nav.setCurrentItem(first_visible)

    def _collect_changes(self) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        for row in self._rows:
            if not row.spec.editable or not row.is_modified():
                continue
            changes[row.spec.key] = row.value()
        return changes

    def _choose_artwork(self) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Choose Artwork",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff);;All Files (*)",
        )
        if not file_path:
            return

        try:
            crop_dialog = _ArtworkCropDialog(file_path, self)
        except (OSError, UnidentifiedImageError) as exc:
            QMessageBox.warning(
                self,
                "Artwork Image",
                f"Could not open that image:\n\n{exc}",
            )
            return

        if crop_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        cropped = crop_dialog.cropped_image()
        if cropped is None:
            return

        try:
            temp_path = self._save_cropped_artwork(cropped)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Artwork Image",
                f"Could not prepare cropped artwork:\n\n{exc}",
            )
            return

        self._discard_pending_artwork()
        self._pending_artwork_path = temp_path
        if self._artwork_panel is not None:
            self._artwork_panel.set_pending_artwork(cropped, file_path)
        self._update_change_summary()

    def _unify_artwork(self) -> None:
        if self._artwork_panel is None:
            return
        context = self._artwork_panel.unify_context()
        if context is None:
            return

        dialog = UnifyArtworkDialog(context, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        choice = dialog.selected_choice()
        if choice is None:
            return

        try:
            temp_path = save_unified_artwork_temp(choice.image)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Unify Artwork",
                f"Could not prepare artwork:\n\n{exc}",
            )
            return

        self._discard_pending_artwork()
        self._pending_artwork_path = temp_path
        self._artwork_panel.set_pending_artwork(choice.image, choice.source_label)
        self._update_change_summary()

    def _save_cropped_artwork(self, image: Image.Image) -> str:
        fd, path = tempfile.mkstemp(prefix=_ARTWORK_TEMP_PREFIX, suffix=".png")
        os.close(fd)
        try:
            image.save(path, "PNG")
        except Exception:
            try:
                os.remove(path)
            except OSError:
                pass
            raise
        return path

    def _discard_pending_artwork(self) -> None:
        if not self._pending_artwork_path:
            return
        try:
            os.remove(self._pending_artwork_path)
        except OSError:
            pass
        self._pending_artwork_path = None
