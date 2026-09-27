"""Declarative optional-column projection for the Track table."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, auto
from typing import cast

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication

from iPodDB.library import ContentAdvisory, MediaKind, MediaType, Track

type TrackSortValue = str | int | float | None

_MISSING = "—"


def _marked(source: object) -> str:
    return cast("str", source)


_COLUMN_TRANSLATION_SOURCES = frozenset(
    {
        QT_TRANSLATE_NOOP("TrackTableModel", "#"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Title"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Artist"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Album"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Genre"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Time"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Year"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Size"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Bitrate"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Plays"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Rating"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Album Artist"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Composer"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Comment"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Grouping"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Track Total"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Disc #"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Disc Total"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Compilation"),
        QT_TRANSLATE_NOOP("TrackTableModel", "BPM"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Unscrobbled Plays"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Skip Count"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Last Played"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Last Skipped"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Start Time"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Stop Time"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Bookmark Time"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Checked"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Played"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Sound Check"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Volume Adjustment"),
        QT_TRANSLATE_NOOP("TrackTableModel", "File Format"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Sample Rate"),
        QT_TRANSLATE_NOOP("TrackTableModel", "VBR"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Media Type"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Content Advisory"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Encoder"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Date Added"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Date Modified"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Release Date"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Sort Title"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Sort Artist"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Sort Album"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Sort Album Artist"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Sort Composer"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Sort Show"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Show"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Season"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Episode #"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Episode ID"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Network"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Description"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Subtitle"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Category"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Enclosure URL"),
        QT_TRANSLATE_NOOP("TrackTableModel", "RSS URL"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Podcast"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Chapters"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Chapter Titles"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Gapless"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Gapless Album"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Pre-gap"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Post-gap"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Sample Count"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Gapless Payload"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Skip Shuffle"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Remember Position"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Has Lyrics"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Artwork Count"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Artwork Reference"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Track ID"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Database Track ID"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Album ID"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Artist Reference"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Composer ID"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Equalizer"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Location"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Lyrics"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Keywords"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Locale"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Artwork"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Playlist Position"),
        QT_TRANSLATE_NOOP("TrackTableModel", "Sync"),
    }
)
_YES_SOURCE = _marked(QT_TRANSLATE_NOOP("TrackTableModel", "Yes"))
_NO_SOURCE = _marked(QT_TRANSLATE_NOOP("TrackTableModel", "No"))
_UNTITLED_TRACK_SOURCE = _marked(QT_TRANSLATE_NOOP("LibraryLabels", "Untitled Track"))
_UNTITLED_CHAPTER_SOURCE = _marked(
    QT_TRANSLATE_NOOP("TrackTableModel", "Untitled Chapter")
)
_MORE_CHAPTERS_SOURCE = _marked(
    QT_TRANSLATE_NOOP("TrackTableModel", "{summary}, +{count} more")
)
_EXPLICIT_SOURCE = _marked(QT_TRANSLATE_NOOP("TrackTableModel", "Explicit"))
_CLEAN_SOURCE = _marked(QT_TRANSLATE_NOOP("TrackTableModel", "Clean"))
_MEDIA_TYPE_LABELS = {
    MediaType.AUDIO_VIDEO: _marked(QT_TRANSLATE_NOOP("TrackTableModel", "Audio/Video")),
    MediaType.AUDIO: _marked(QT_TRANSLATE_NOOP("TrackTableModel", "Audio")),
    MediaType.VIDEO: _marked(QT_TRANSLATE_NOOP("TrackTableModel", "Video")),
    MediaType.PODCAST: _marked(QT_TRANSLATE_NOOP("TrackTableModel", "Podcast")),
    MediaType.VIDEO_PODCAST: _marked(
        QT_TRANSLATE_NOOP("TrackTableModel", "Video Podcast")
    ),
    MediaType.AUDIOBOOK: _marked(QT_TRANSLATE_NOOP("TrackTableModel", "Audiobook")),
    MediaType.MUSIC_VIDEO: _marked(QT_TRANSLATE_NOOP("TrackTableModel", "Music Video")),
    MediaType.TV_SHOW: _marked(QT_TRANSLATE_NOOP("TrackTableModel", "TV Show")),
    MediaType.RINGTONE: _marked(QT_TRANSLATE_NOOP("TrackTableModel", "Ringtone")),
    MediaType.RENTAL: _marked(QT_TRANSLATE_NOOP("TrackTableModel", "Rental")),
    MediaType.ITUNES_EXTRA: _marked(
        QT_TRANSLATE_NOOP("TrackTableModel", "iTunes Extra")
    ),
    MediaType.MEMO: _marked(QT_TRANSLATE_NOOP("TrackTableModel", "Memo")),
    MediaType.ITUNES_U: _marked(QT_TRANSLATE_NOOP("TrackTableModel", "iTunes U")),
    MediaType.EPUB_BOOK: _marked(QT_TRANSLATE_NOOP("TrackTableModel", "EPUB Book")),
    MediaType.PDF_BOOK: _marked(QT_TRANSLATE_NOOP("TrackTableModel", "PDF Book")),
}


class TrackColumn(IntEnum):
    """Stable logical columns exposed by the shared Track model."""

    NUMBER = 0
    TITLE = 1
    ARTIST = 2
    ALBUM = 3
    GENRE = 4
    TIME = 5
    YEAR = 6
    SIZE = 7
    BITRATE = 8
    PLAYS = 9
    RATING = 10
    ALBUM_ARTIST = auto()
    COMPOSER = auto()
    COMMENT = auto()
    GROUPING = auto()
    TOTAL_TRACKS = auto()
    DISC_NUMBER = auto()
    TOTAL_DISCS = auto()
    COMPILATION = auto()
    BPM = auto()
    UNSCROBBLED_PLAYS = auto()
    SKIP_COUNT = auto()
    LAST_PLAYED = auto()
    LAST_SKIPPED = auto()
    START_TIME = auto()
    STOP_TIME = auto()
    BOOKMARK_TIME = auto()
    CHECKED = auto()
    PLAYED = auto()
    SOUND_CHECK = auto()
    VOLUME_ADJUSTMENT = auto()
    FILE_FORMAT = auto()
    SAMPLE_RATE = auto()
    VBR = auto()
    MEDIA_TYPE = auto()
    CONTENT_ADVISORY = auto()
    ENCODER = auto()
    DATE_ADDED = auto()
    DATE_MODIFIED = auto()
    RELEASE_DATE = auto()
    SORT_TITLE = auto()
    SORT_ARTIST = auto()
    SORT_ALBUM = auto()
    SORT_ALBUM_ARTIST = auto()
    SORT_COMPOSER = auto()
    SORT_SHOW = auto()
    SHOW = auto()
    SEASON = auto()
    EPISODE_NUMBER = auto()
    EPISODE_ID = auto()
    NETWORK = auto()
    DESCRIPTION = auto()
    SUBTITLE = auto()
    CATEGORY = auto()
    ENCLOSURE_URL = auto()
    RSS_URL = auto()
    PODCAST = auto()
    CHAPTERS = auto()
    CHAPTER_TITLES = auto()
    GAPLESS = auto()
    GAPLESS_ALBUM = auto()
    PREGAP = auto()
    POSTGAP = auto()
    SAMPLE_COUNT = auto()
    GAPLESS_PAYLOAD = auto()
    SKIP_SHUFFLE = auto()
    REMEMBER_POSITION = auto()
    HAS_LYRICS = auto()
    ARTWORK_COUNT = auto()
    ARTWORK_REFERENCE = auto()
    TRACK_ID = auto()
    DB_TRACK_ID = auto()
    ALBUM_ID = auto()
    ARTIST_REFERENCE = auto()
    COMPOSER_ID = auto()
    EQUALIZER = auto()
    LOCATION = auto()
    LYRICS = auto()
    KEYWORDS = auto()
    LOCALE = auto()
    # Keep new columns at the end so retained QHeaderView state preserves the
    # logical identity of every pre-existing column.
    ARTWORK = auto()
    PLAYLIST_POSITION = auto()
    SYNC_SELECTION = auto()


_COLUMN_GROUPS = (
    (
        _marked(QT_TRANSLATE_NOOP("TrackTable", "Core Metadata")),
        (
            TrackColumn.NUMBER,
            TrackColumn.TITLE,
            TrackColumn.ARTIST,
            TrackColumn.ALBUM,
            TrackColumn.ALBUM_ARTIST,
            TrackColumn.GENRE,
            TrackColumn.COMPOSER,
            TrackColumn.COMMENT,
            TrackColumn.GROUPING,
            TrackColumn.YEAR,
            TrackColumn.TOTAL_TRACKS,
            TrackColumn.DISC_NUMBER,
            TrackColumn.TOTAL_DISCS,
            TrackColumn.COMPILATION,
            TrackColumn.BPM,
        ),
    ),
    (
        _marked(QT_TRANSLATE_NOOP("TrackTable", "Playback and Stats")),
        (
            TrackColumn.TIME,
            TrackColumn.RATING,
            TrackColumn.PLAYS,
            TrackColumn.UNSCROBBLED_PLAYS,
            TrackColumn.SKIP_COUNT,
            TrackColumn.LAST_PLAYED,
            TrackColumn.LAST_SKIPPED,
            TrackColumn.CHECKED,
            TrackColumn.PLAYED,
            TrackColumn.START_TIME,
            TrackColumn.STOP_TIME,
            TrackColumn.BOOKMARK_TIME,
        ),
    ),
    (
        _marked(QT_TRANSLATE_NOOP("TrackTable", "Audio Quality")),
        (
            TrackColumn.FILE_FORMAT,
            TrackColumn.BITRATE,
            TrackColumn.SAMPLE_RATE,
            TrackColumn.SIZE,
            TrackColumn.VBR,
            TrackColumn.ENCODER,
            TrackColumn.SOUND_CHECK,
            TrackColumn.VOLUME_ADJUSTMENT,
        ),
    ),
    (
        _marked(QT_TRANSLATE_NOOP("TrackTable", "Dates")),
        (
            TrackColumn.DATE_ADDED,
            TrackColumn.DATE_MODIFIED,
            TrackColumn.RELEASE_DATE,
        ),
    ),
    (
        _marked(QT_TRANSLATE_NOOP("TrackTable", "Sort Overrides")),
        (
            TrackColumn.SORT_TITLE,
            TrackColumn.SORT_ARTIST,
            TrackColumn.SORT_ALBUM,
            TrackColumn.SORT_ALBUM_ARTIST,
            TrackColumn.SORT_COMPOSER,
            TrackColumn.SORT_SHOW,
        ),
    ),
    (
        _marked(QT_TRANSLATE_NOOP("TrackTable", "Video and TV")),
        (
            TrackColumn.MEDIA_TYPE,
            TrackColumn.SHOW,
            TrackColumn.SEASON,
            TrackColumn.EPISODE_NUMBER,
            TrackColumn.EPISODE_ID,
            TrackColumn.NETWORK,
            TrackColumn.DESCRIPTION,
            TrackColumn.SUBTITLE,
        ),
    ),
    (
        _marked(QT_TRANSLATE_NOOP("TrackTable", "Podcast")),
        (
            TrackColumn.CATEGORY,
            TrackColumn.PODCAST,
            TrackColumn.ENCLOSURE_URL,
            TrackColumn.RSS_URL,
        ),
    ),
    (
        _marked(QT_TRANSLATE_NOOP("TrackTable", "Chapters")),
        (
            TrackColumn.CHAPTERS,
            TrackColumn.CHAPTER_TITLES,
        ),
    ),
    (
        _marked(QT_TRANSLATE_NOOP("TrackTable", "Gapless")),
        (
            TrackColumn.GAPLESS,
            TrackColumn.GAPLESS_ALBUM,
            TrackColumn.PREGAP,
            TrackColumn.POSTGAP,
            TrackColumn.SAMPLE_COUNT,
            TrackColumn.GAPLESS_PAYLOAD,
        ),
    ),
    (
        _marked(QT_TRANSLATE_NOOP("TrackTable", "Flags")),
        (
            TrackColumn.SKIP_SHUFFLE,
            TrackColumn.REMEMBER_POSITION,
            TrackColumn.HAS_LYRICS,
            TrackColumn.CONTENT_ADVISORY,
        ),
    ),
    (
        _marked(QT_TRANSLATE_NOOP("TrackTable", "Artwork")),
        (
            TrackColumn.ARTWORK,
            TrackColumn.ARTWORK_COUNT,
            TrackColumn.ARTWORK_REFERENCE,
        ),
    ),
    (
        _marked(QT_TRANSLATE_NOOP("TrackTable", "Identifiers")),
        (
            TrackColumn.TRACK_ID,
            TrackColumn.DB_TRACK_ID,
            TrackColumn.ALBUM_ID,
            TrackColumn.ARTIST_REFERENCE,
            TrackColumn.COMPOSER_ID,
        ),
    ),
    (
        _marked(QT_TRANSLATE_NOOP("TrackTable", "Other")),
        (
            TrackColumn.EQUALIZER,
            TrackColumn.LOCATION,
            TrackColumn.LYRICS,
            TrackColumn.KEYWORDS,
            TrackColumn.LOCALE,
        ),
    ),
    (
        _marked(QT_TRANSLATE_NOOP("TrackTable", "Playlist")),
        (TrackColumn.PLAYLIST_POSITION,),
    ),
    (
        _marked(QT_TRANSLATE_NOOP("TrackTable", "Sync")),
        (TrackColumn.SYNC_SELECTION,),
    ),
)
_DEFAULT_VISIBLE_COLUMNS = frozenset(
    {
        TrackColumn.NUMBER,
        TrackColumn.TITLE,
        TrackColumn.ARTIST,
        TrackColumn.ALBUM,
        TrackColumn.GENRE,
        TrackColumn.TIME,
        TrackColumn.YEAR,
        TrackColumn.RATING,
        TrackColumn.ARTWORK,
    }
)
_DEFAULT_COLUMN_WIDTHS = {
    TrackColumn.NUMBER: 52,
    TrackColumn.TITLE: 260,
    TrackColumn.ARTIST: 172,
    TrackColumn.ALBUM: 190,
    TrackColumn.GENRE: 128,
    TrackColumn.TIME: 76,
    TrackColumn.YEAR: 68,
    TrackColumn.SIZE: 92,
    TrackColumn.BITRATE: 88,
    TrackColumn.PLAYS: 72,
    TrackColumn.RATING: 112,
    TrackColumn.ARTWORK: 52,
    TrackColumn.PLAYLIST_POSITION: 88,
    TrackColumn.SYNC_SELECTION: 64,
}
_LONG_TEXT_COLUMNS = frozenset(
    {
        TrackColumn.COMMENT,
        TrackColumn.DESCRIPTION,
        TrackColumn.ENCLOSURE_URL,
        TrackColumn.RSS_URL,
        TrackColumn.CHAPTER_TITLES,
        TrackColumn.LOCATION,
        TrackColumn.LYRICS,
        TrackColumn.KEYWORDS,
    }
)
_DATE_COLUMNS = frozenset(
    {
        TrackColumn.LAST_PLAYED,
        TrackColumn.LAST_SKIPPED,
        TrackColumn.DATE_ADDED,
        TrackColumn.DATE_MODIFIED,
        TrackColumn.RELEASE_DATE,
    }
)
_NARROW_COLUMNS = frozenset(
    {
        TrackColumn.TOTAL_TRACKS,
        TrackColumn.DISC_NUMBER,
        TrackColumn.TOTAL_DISCS,
        TrackColumn.BPM,
        TrackColumn.SKIP_COUNT,
        TrackColumn.CHAPTERS,
        TrackColumn.ARTWORK_COUNT,
        TrackColumn.PLAYLIST_POSITION,
    }
)


@dataclass(frozen=True, slots=True)
class TrackColumnDefinition:
    """One translated table heading and its typed Track value projection."""

    source_text: str
    display_value: Callable[[Track], str]
    sort_value: Callable[[Track], TrackSortValue]
    right_aligned: bool = False


def _column[T: TrackSortValue](
    source_text: str,
    value: Callable[[Track], T],
    formatter: Callable[[T], str] | None = None,
    *,
    right_aligned: bool = False,
) -> TrackColumnDefinition:
    """Bind a value to its formatter before storing heterogeneous columns."""

    format_value: Callable[[T], str] = (
        formatter if formatter is not None else _format_text
    )
    return TrackColumnDefinition(
        source_text=source_text,
        display_value=lambda track: format_value(value(track)),
        sort_value=lambda track: _sort_value(value(track)),
        right_aligned=right_aligned,
    )


def _build_column_definitions() -> tuple[TrackColumnDefinition, ...]:
    return (
        _column(
            "#",
            lambda track: track.track_number,
            _format_positive_integer,
            right_aligned=True,
        ),
        _column(
            "Title",
            lambda track: (
                track.title
                or QCoreApplication.translate("LibraryLabels", _UNTITLED_TRACK_SOURCE)
            ),
        ),
        _column("Artist", lambda track: track.artist),
        _column("Album", lambda track: track.album),
        _column("Genre", lambda track: track.genre),
        _column(
            "Time", lambda track: track.length_ms, _format_duration, right_aligned=True
        ),
        _column(
            "Year",
            lambda track: track.year,
            _format_positive_integer,
            right_aligned=True,
        ),
        _column(
            "Size", lambda track: track.size_bytes, _format_size, right_aligned=True
        ),
        _column(
            "Bitrate",
            lambda track: track.bitrate_kbps,
            _format_bitrate,
            right_aligned=True,
        ),
        _column(
            "Plays", lambda track: track.play_count, _format_count, right_aligned=True
        ),
        _column(
            "Rating", lambda track: track.rating, _format_rating, right_aligned=True
        ),
        _column("Album Artist", lambda track: track.album_artist),
        _column("Composer", lambda track: track.metadata.composer),
        _column("Comment", lambda track: track.metadata.comment),
        _column("Grouping", lambda track: track.metadata.grouping),
        _column(
            "Track Total",
            lambda track: track.metadata.total_tracks,
            _format_positive_integer,
            right_aligned=True,
        ),
        _column(
            "Disc #",
            lambda track: track.metadata.disc_number,
            _format_positive_integer,
            right_aligned=True,
        ),
        _column(
            "Disc Total",
            lambda track: track.metadata.total_discs,
            _format_positive_integer,
            right_aligned=True,
        ),
        _column(
            "Compilation",
            lambda track: track.metadata.compilation,
            _format_boolean,
        ),
        _column(
            "BPM",
            lambda track: track.metadata.bpm,
            _format_positive_integer,
            right_aligned=True,
        ),
        _column(
            "Unscrobbled Plays",
            lambda track: track.metadata.unscrobbled_play_count,
            _format_count,
            right_aligned=True,
        ),
        _column(
            "Skip Count",
            lambda track: track.metadata.skip_count,
            _format_count,
            right_aligned=True,
        ),
        _column("Last Played", lambda track: track.metadata.last_played, _format_date),
        _column(
            "Last Skipped", lambda track: track.metadata.last_skipped, _format_date
        ),
        _column(
            "Start Time",
            lambda track: track.metadata.start_time_ms,
            _format_optional_duration,
            right_aligned=True,
        ),
        _column(
            "Stop Time",
            lambda track: track.metadata.stop_time_ms,
            _format_optional_duration,
            right_aligned=True,
        ),
        _column(
            "Bookmark Time",
            lambda track: track.metadata.bookmark_time_ms,
            _format_optional_duration,
            right_aligned=True,
        ),
        _column("Checked", lambda track: track.metadata.checked, _format_boolean),
        _column(
            "Played",
            lambda track: track.play_count > 0 or track.metadata.played,
            _format_boolean,
        ),
        _column(
            "Sound Check",
            lambda track: track.metadata.normalization_gain_db,
            _format_sound_check,
            right_aligned=True,
        ),
        _column(
            "Volume Adjustment",
            lambda track: track.metadata.volume_adjustment_percent,
            _format_volume,
            right_aligned=True,
        ),
        _column(
            "File Format",
            lambda track: track.metadata.file_format,
        ),
        _column(
            "Sample Rate",
            lambda track: track.metadata.sample_rate_hz,
            _format_sample_rate,
            right_aligned=True,
        ),
        _column("VBR", lambda track: track.metadata.variable_bitrate, _format_boolean),
        _column("Media Type", _media_type_value),
        _column(
            "Content Advisory",
            lambda track: track.metadata.content_advisory,
            _format_content_advisory,
        ),
        _column(
            "Encoder",
            lambda track: track.ipod.encoder if track.ipod is not None else 0,
            _format_positive_integer,
        ),
        _column("Date Added", lambda track: track.metadata.date_added, _format_date),
        _column(
            "Date Modified", lambda track: track.metadata.last_modified, _format_date
        ),
        _column(
            "Release Date", lambda track: track.metadata.release_date, _format_date
        ),
        _column("Sort Title", lambda track: track.metadata.sort_title),
        _column("Sort Artist", lambda track: track.metadata.sort_artist),
        _column("Sort Album", lambda track: track.metadata.sort_album),
        _column("Sort Album Artist", lambda track: track.metadata.sort_album_artist),
        _column("Sort Composer", lambda track: track.metadata.sort_composer),
        _column("Sort Show", lambda track: track.metadata.sort_show),
        _column("Show", lambda track: track.show),
        _column(
            "Season",
            lambda track: track.season_number,
            _format_positive_integer,
            right_aligned=True,
        ),
        _column(
            "Episode #",
            lambda track: track.episode_number,
            _format_positive_integer,
            right_aligned=True,
        ),
        _column("Episode ID", lambda track: track.episode),
        _column("Network", lambda track: track.metadata.tv_network),
        _column("Description", lambda track: track.metadata.description),
        _column("Subtitle", lambda track: track.metadata.subtitle),
        _column("Category", lambda track: track.metadata.category),
        _column("Enclosure URL", lambda track: track.metadata.podcast_enclosure_url),
        _column("RSS URL", lambda track: track.metadata.podcast_rss_url),
        _column(
            "Podcast",
            lambda track: (
                track.metadata.podcast or track.media_kind is MediaKind.PODCAST
            ),
            _format_boolean,
        ),
        _column(
            "Chapters",
            lambda track: len(track.metadata.chapters),
            _format_positive_integer,
            right_aligned=True,
        ),
        _column("Chapter Titles", lambda track: _chapter_summary(track)),
        _column(
            "Gapless",
            lambda track: track.metadata.gapless,
            _format_boolean,
        ),
        _column(
            "Gapless Album",
            lambda track: track.metadata.gapless_album,
            _format_boolean,
        ),
        _column(
            "Pre-gap",
            lambda track: track.metadata.pregap,
            _format_samples,
            right_aligned=True,
        ),
        _column(
            "Post-gap",
            lambda track: track.metadata.postgap,
            _format_samples,
            right_aligned=True,
        ),
        _column(
            "Sample Count",
            lambda track: track.metadata.sample_count,
            _format_samples,
            right_aligned=True,
        ),
        _column(
            "Gapless Payload",
            lambda track: (
                track.ipod.gapless_audio_payload_size if track.ipod is not None else 0
            ),
            _format_samples,
            right_aligned=True,
        ),
        _column(
            "Skip Shuffle",
            lambda track: track.metadata.skip_shuffle,
            _format_boolean,
        ),
        _column(
            "Remember Position",
            lambda track: track.metadata.remember_position,
            _format_boolean,
        ),
        _column(
            "Has Lyrics",
            lambda track: track.metadata.has_lyrics,
            _format_boolean,
        ),
        _column(
            "Artwork Count",
            lambda track: track.metadata.artwork_count,
            _format_count,
            right_aligned=True,
        ),
        _column(
            "Artwork Reference",
            lambda track: track.ipod.artwork_id_ref if track.ipod is not None else 0,
            _format_positive_integer,
            right_aligned=True,
        ),
        _column(
            "Track ID",
            lambda track: track.track_id,
            _format_positive_integer,
            right_aligned=True,
        ),
        _column(
            "Database Track ID",
            lambda track: track.ipod.db_track_id if track.ipod is not None else 0,
            _format_db_track_id,
            right_aligned=True,
        ),
        _column(
            "Album ID",
            lambda track: track.ipod.album_id if track.ipod is not None else 0,
            _format_positive_integer,
            right_aligned=True,
        ),
        _column(
            "Artist Reference",
            lambda track: track.ipod.artist_id_ref if track.ipod is not None else 0,
            _format_positive_integer,
            right_aligned=True,
        ),
        _column(
            "Composer ID",
            lambda track: track.ipod.composer_id if track.ipod is not None else 0,
            _format_positive_integer,
            right_aligned=True,
        ),
        _column("Equalizer", lambda track: track.metadata.equalizer),
        _column("Location", lambda track: track.metadata.location),
        _column("Lyrics", lambda track: track.metadata.lyrics),
        _column("Keywords", lambda track: track.metadata.track_keywords),
        _column("Locale", lambda track: track.metadata.show_locale),
        _column("Artwork", lambda track: track.artwork_id, _format_artwork),
        # Playlist position belongs to an occurrence rather than a Track. The
        # table model supplies its contextual value for this logical column.
        _column("Playlist Position", lambda _track: None, right_aligned=True),
        # Sync Selection belongs to the current workflow, not Track metadata.
        _column("Sync", lambda _track: None, lambda _value: ""),
    )


def track_column_count() -> int:
    return len(_COLUMN_DEFINITIONS)


def track_column_groups() -> tuple[tuple[str, tuple[TrackColumn, ...]], ...]:
    """Return extraction-marked group labels and their ordered columns."""

    return _COLUMN_GROUPS


def track_column_default_visible(column: TrackColumn) -> bool:
    return column in _DEFAULT_VISIBLE_COLUMNS


def track_column_default_width(column: TrackColumn) -> int:
    retained_width = _DEFAULT_COLUMN_WIDTHS.get(column)
    if retained_width is not None:
        return retained_width
    if column in _LONG_TEXT_COLUMNS:
        return 260
    if column in _DATE_COLUMNS:
        return 112
    if column in _NARROW_COLUMNS:
        return 88
    return 148


def track_column_header(column: int) -> str | None:
    definition = _definition(column)
    return None if definition is None else _translate(definition.source_text)


def track_column_display_value(track: Track, column: int) -> str:
    definition = _definition(column)
    if definition is None:
        return ""
    return definition.display_value(track)


def track_column_sort_value(track: Track, column: int) -> TrackSortValue:
    definition = _definition(column)
    if definition is None:
        return ""
    return definition.sort_value(track)


def _sort_value(value: TrackSortValue) -> TrackSortValue:
    return value.casefold() if isinstance(value, str) else value


def track_column_is_right_aligned(column: int) -> bool:
    definition = _definition(column)
    return definition is not None and definition.right_aligned


def _definition(column: int) -> TrackColumnDefinition | None:
    if not 0 <= column < len(_COLUMN_DEFINITIONS):
        return None
    return _COLUMN_DEFINITIONS[column]


def _format_text(value: TrackSortValue) -> str:
    if value is None or value == "" or value == 0:
        return _MISSING
    return str(value)


def _format_count(value: int) -> str:
    return str(max(0, value))


def _format_positive_integer(value: int) -> str:
    return str(value) if value > 0 else _MISSING


def _format_boolean(value: bool) -> str:
    return _translate(_YES_SOURCE) if value else _translate(_NO_SOURCE)


def _format_artwork(value: int) -> str:
    return _translate("Artwork") if value > 0 else _MISSING


def _format_duration(value: int) -> str:
    return _duration_text(value)


def _format_optional_duration(value: int) -> str:
    return _duration_text(value) if value > 0 else _MISSING


def _duration_text(milliseconds: int) -> str:
    total_seconds = max(0, milliseconds) // 1000
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _format_size(value: int) -> str:
    if value <= 0:
        return _MISSING
    return f"{value / (1024 * 1024):.1f} MB"


def _format_bitrate(value: int) -> str:
    return f"{value} kbps" if value > 0 else _MISSING


def _format_rating(value: int) -> str:
    stars = min(5, max(0, round(value / 20)))
    return ("★" * stars) + ("☆" * (5 - stars))


def _format_sample_rate(value: int) -> str:
    return f"{value / 1000:g} kHz" if value > 0 else _MISSING


def _format_volume(value: float) -> str:
    if value == 0:
        return _MISSING
    return f"{round(value):+d}%"


def _format_sound_check(value: float | None) -> str:
    return f"{value:+.1f} dB" if value is not None else _MISSING


def _format_date(value: int) -> str:
    if value <= 0:
        return _MISSING
    try:
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return _MISSING


def _format_content_advisory(value: ContentAdvisory) -> str:
    if value is ContentAdvisory.EXPLICIT:
        return _translate(_EXPLICIT_SOURCE)
    if value is ContentAdvisory.CLEAN:
        return _translate(_CLEAN_SOURCE)
    return _MISSING


def _media_type_value(track: Track) -> str:
    labels = tuple(_MEDIA_TYPE_LABELS[kind] for kind in track.media_types)
    if track.ipod is not None and track.ipod.unknown_media_type_bits:
        labels += (f"0x{track.ipod.unknown_media_type_bits:X}",)
    return " | ".join(_translate(label) for label in labels)


def _format_db_track_id(value: int) -> str:
    return f"0x{value:016X}" if value > 0 else _MISSING


def _format_samples(value: int) -> str:
    return f"{value:,}" if value > 0 else _MISSING


def _chapter_summary(track: Track, maximum_titles: int = 3) -> str:
    titles = tuple(
        chapter.title.strip() or _translate(_UNTITLED_CHAPTER_SOURCE)
        for chapter in track.metadata.chapters
    )
    if not titles:
        return ""
    shown = ", ".join(titles[:maximum_titles])
    remaining = len(titles) - maximum_titles
    if remaining > 0:
        return _translate(_MORE_CHAPTERS_SOURCE).format(
            summary=shown,
            count=remaining,
        )
    return shown


def _translate(source_text: str) -> str:
    return QCoreApplication.translate("TrackTableModel", source_text)


_COLUMN_DEFINITIONS = _build_column_definitions()
if len(_COLUMN_DEFINITIONS) != len(TrackColumn):
    raise RuntimeError("every TrackColumn must have exactly one definition")
if {definition.source_text for definition in _COLUMN_DEFINITIONS} != set(
    _COLUMN_TRANSLATION_SOURCES
):
    raise RuntimeError("every TrackColumn heading must be marked for translation")

_GROUPED_COLUMNS = tuple(
    column for _group_label, columns in _COLUMN_GROUPS for column in columns
)
if len(_GROUPED_COLUMNS) != len(TrackColumn) or set(_GROUPED_COLUMNS) != set(
    TrackColumn
):
    raise RuntimeError("every TrackColumn must appear in exactly one menu group")
