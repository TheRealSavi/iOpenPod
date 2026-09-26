"""Presentation descriptions and input conversion for the semantic metadata editor."""

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from iPodDB.library import (
    ContentAdvisory,
    MediaType,
    MetadataValue,
    Track,
    editable_track_fields,
)

type MetadataFieldValue = MetadataValue | tuple[MediaType, ...]


class FieldKind(StrEnum):
    TEXT = "text"
    LONG_TEXT = "long_text"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"
    ADVISORY = "advisory"
    MEDIA_TYPE = "media_type"
    CHAPTERS = "chapters"


@dataclass(frozen=True, slots=True)
class MetadataField:
    path: str
    label: str
    group: str
    kind: FieldKind


_GROUPS: dict[str, tuple[str, ...]] = {
    "Metadata": (
        "title",
        "artist",
        "album",
        "album_artist",
        "genre",
        "year",
        "track_number",
        "metadata.total_tracks",
        "metadata.disc_number",
        "metadata.total_discs",
        "metadata.bpm",
        "metadata.composer",
        "metadata.grouping",
        "metadata.comment",
        "metadata.lyrics",
    ),
    "Sorting": tuple(
        "metadata.sort_" + field
        for field in ("title", "artist", "album", "album_artist", "composer", "show")
    ),
    "Playback": (
        "rating",
        "play_count",
        "metadata.skip_count",
        "metadata.unscrobbled_play_count",
        "metadata.volume_adjustment_percent",
        "metadata.normalization_gain_db",
        "metadata.start_time_ms",
        "metadata.stop_time_ms",
        "metadata.bookmark_time_ms",
        "metadata.equalizer",
    ),
    "Options": (
        "media_types",
        "metadata.compilation",
        "metadata.checked",
        "metadata.content_advisory",
        "metadata.skip_shuffle",
        "metadata.remember_position",
        "metadata.gapless_album",
    ),
    "Video": (
        "show",
        "episode",
        "season_number",
        "episode_number",
        "metadata.subtitle",
        "metadata.tv_network",
        "metadata.description",
        "metadata.track_keywords",
        "metadata.show_locale",
    ),
    "Podcast": (
        "metadata.category",
        "metadata.podcast_enclosure_url",
        "metadata.podcast_rss_url",
        "metadata.podcast",
        "metadata.played",
    ),
    "Dates": (
        "metadata.last_modified",
        "metadata.last_played",
        "metadata.date_added",
        "metadata.release_date",
        "metadata.last_skipped",
    ),
    "Chapters": ("metadata.chapters",),
    "Store": (
        "metadata.content_provider",
        "metadata.copyright",
        "metadata.encoding_quality",
        "metadata.purchase_account",
        "metadata.purchaser_name",
    ),
}
_LABELS = {
    "media_types": "Media type",
    "track_number": "Track number",
    "metadata.total_tracks": "Total tracks",
    "metadata.volume_adjustment_percent": "Volume adjustment (%)",
    "metadata.normalization_gain_db": "Normalization gain (dB)",
    "metadata.start_time_ms": "Start time (ms)",
    "metadata.stop_time_ms": "Stop time (ms; 0 = end)",
    "metadata.bookmark_time_ms": "Bookmark time (ms)",
    "metadata.skip_shuffle": "Skip when shuffling",
    "metadata.bpm": "BPM",
    "metadata.podcast": "Use Podcast Now Playing display",
    "rating": "Rating (0-100)",
    "metadata.played": "Played",
}
_LONG = frozenset(("metadata.comment", "metadata.lyrics", "metadata.description"))


def field_value(track: Track, path: str) -> MetadataFieldValue:
    value: MetadataFieldValue = (
        getattr(track.metadata, path[9:])
        if path.startswith("metadata.")
        else getattr(track, path)
    )
    return value


def metadata_fields() -> tuple[MetadataField, ...]:
    defaults = Track(0, "", "", "", 0)
    # Classification goes through the Application Layer's dedicated workflow.
    allowed = frozenset((*editable_track_fields(), "media_types"))
    result: list[MetadataField] = []
    for group, paths in _GROUPS.items():
        for path in paths:
            if path not in allowed:
                continue
            value = field_value(defaults, path)
            kind = FieldKind.TEXT
            if path == "media_types":
                kind = FieldKind.MEDIA_TYPE
            elif path == "metadata.chapters":
                kind = FieldKind.CHAPTERS
            elif path == "metadata.content_advisory":
                kind = FieldKind.ADVISORY
            elif group == "Dates":
                kind = FieldKind.DATE
            elif type(value) is bool:
                kind = FieldKind.BOOLEAN
            elif type(value) is int:
                kind = FieldKind.INTEGER
            elif type(value) is float or value is None:
                kind = FieldKind.FLOAT
            elif path in _LONG:
                kind = FieldKind.LONG_TEXT
            label = _LABELS.get(
                path, path.removeprefix("metadata.").replace("_", " ").capitalize()
            )
            result.append(MetadataField(path, label, group, kind))
    return tuple(result)


def display_value(value: MetadataFieldValue, kind: FieldKind) -> str:
    if kind is FieldKind.DATE and isinstance(value, int) and value:
        try:
            return (
                datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")
            )
        except (ValueError, OSError, OverflowError):
            return str(value)
    if value is None:
        return ""
    if isinstance(value, ContentAdvisory):
        return value.value
    return str(value)


def parse_field(field: MetadataField, text: str) -> MetadataValue:
    if field.kind in (FieldKind.TEXT, FieldKind.LONG_TEXT):
        return text
    text = text.strip()
    if field.kind is FieldKind.INTEGER:
        return int(text)
    if field.kind is FieldKind.FLOAT:
        if not text and field.path == "metadata.normalization_gain_db":
            return None
        number = float(text)
        if not math.isfinite(number):
            raise ValueError("Use a finite number.")
        return number
    if field.kind is FieldKind.DATE:
        if not text:
            return 0
        try:
            return int(text)
        except ValueError:
            return int(datetime.fromisoformat(text).timestamp())
    raise ValueError("Choose a value using this field's control.")
