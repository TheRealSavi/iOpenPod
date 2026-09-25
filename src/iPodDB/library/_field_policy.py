"""Semantic ownership and inverse-field bindings for Library edits."""

from dataclasses import dataclass, fields
from enum import StrEnum

from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library.models import LibrarySnapshot, Track, TrackMetadata
from iPodDB.library.photos import (
    IPodPhotoAlbumDetails,
    Photo,
    PhotoAlbum,
    PhotoFileFormat,
    PhotoLibrary,
    PhotoRepresentation,
)
from iPodDB.library.playlists import Playlist, PlaylistEntry

TRACK_TEXT = {
    name: MhodType[name.upper()]
    for name in (
        "title",
        "artist",
        "album",
        "genre",
        "show",
        "episode",
        "album_artist",
    )
}
METADATA_TEXT = {
    name: MhodType[name.upper()]
    for name in (
        "location",
        "comment",
        "category",
        "lyrics",
        "composer",
        "grouping",
        "description",
        "podcast_enclosure_url",
        "podcast_rss_url",
        "subtitle",
        "tv_network",
        "sort_artist",
        "track_keywords",
        "show_locale",
        "sort_title",
        "sort_album",
        "sort_album_artist",
        "sort_composer",
        "sort_show",
        "content_provider",
        "copyright",
        "purchase_account",
        "purchaser_name",
    )
} | {
    "equalizer": MhodType.EQ_SETTING,
    "file_format": MhodType.FILETYPE,
    "encoding_quality": MhodType.ENCODING_QUALITY_DESCRIPTOR,
}
TRACK_FIELDS = {
    "length_ms": "length",
    "year": "year",
    "track_number": "track_number",
    "size_bytes": "size",
    "bitrate_kbps": "bitrate",
    "play_count": "play_count_1",
    "rating": "rating",
    "season_number": "season_number",
    "episode_number": "episode_number",
}
METADATA_FIELDS = {
    "variable_bitrate": "vbr_flag",
    "compilation": "compilation_flag",
    "total_tracks": "total_tracks",
    "start_time_ms": "start_time",
    "stop_time_ms": "stop_time",
    "unscrobbled_play_count": "play_count_2",
    "disc_number": "disc_number",
    "total_discs": "total_discs",
    "bookmark_time_ms": "bookmark_time",
    "bpm": "bpm",
    "skip_count": "skip_count",
    "skip_shuffle": "skip_when_shuffling",
    "remember_position": "remember_position",
    "podcast": "podcast_now_playing_flag",
    "has_lyrics": "lyrics_flag",
    "pregap": "pregap",
    "sample_count": "sample_count",
    "postgap": "postgap",
    "gapless": "gapless_track_flag",
    "gapless_album": "gapless_album_flag",
}
DATE_FIELDS = {
    "last_modified": "last_modified",
    "last_played": "last_played",
    "date_added": "date_added",
    "release_date": "date_released",
    "last_skipped": "last_skipped",
}


class FieldOwnership(StrEnum):
    EDITABLE = "editable"
    CLASSIFICATION = "classification"
    MEDIA = "prepared_media"
    ARTWORK = "artwork_selection"
    DERIVED = "derived"
    RETAINED = "retained"
    IDENTITY = "identity"
    MEMBERSHIP = "membership"
    RECORDS = "records"


@dataclass(frozen=True, slots=True)
class FieldPolicy:
    path: str
    ownership: FieldOwnership
    dependencies: tuple[str, ...] = ()


TRACK_POLICY = (
    *(
        FieldPolicy(p, FieldOwnership.EDITABLE)
        for p in (
            *TRACK_TEXT,
            "year",
            "track_number",
            "play_count",
            "rating",
            "season_number",
            "episode_number",
        )
    ),
    *(
        FieldPolicy(p, FieldOwnership.MEDIA)
        for p in ("length_ms", "size_bytes", "bitrate_kbps")
    ),
    # Reclassifying retained media changes firmware presentation, not its bytes.
    # The generic metadata editor still accepts only EDITABLE fields; dedicated
    # Application workflows own classification changes such as Podcast conversion.
    FieldPolicy("media_types", FieldOwnership.CLASSIFICATION),
    FieldPolicy("track_id", FieldOwnership.IDENTITY),
    FieldPolicy("artwork_id", FieldOwnership.ARTWORK),
    FieldPolicy("ipod", FieldOwnership.RETAINED),
    *(
        FieldPolicy("metadata." + p, FieldOwnership.EDITABLE)
        for p in (
            "compilation",
            "last_modified",
            "total_tracks",
            "volume_adjustment_percent",
            "start_time_ms",
            "stop_time_ms",
            "normalization_gain_db",
            "unscrobbled_play_count",
            "last_played",
            "disc_number",
            "total_discs",
            "date_added",
            "bookmark_time_ms",
            "checked",
            "bpm",
            "release_date",
            "content_advisory",
            "skip_count",
            "last_skipped",
            "skip_shuffle",
            "remember_position",
            "podcast",
            "played",
            "gapless_album",
            "equalizer",
            "comment",
            "category",
            "lyrics",
            "composer",
            "grouping",
            "description",
            "podcast_enclosure_url",
            "podcast_rss_url",
            "subtitle",
            "tv_network",
            "sort_artist",
            "track_keywords",
            "show_locale",
            "sort_title",
            "sort_album",
            "sort_album_artist",
            "sort_composer",
            "sort_show",
            "content_provider",
            "copyright",
            "encoding_quality",
            "purchase_account",
            "purchaser_name",
            "chapters",
        )
    ),
    *(
        FieldPolicy("metadata." + p, FieldOwnership.MEDIA)
        for p in (
            "file_format",
            "variable_bitrate",
            "sample_rate_hz",
            "pregap",
            "sample_count",
            "postgap",
            "gapless",
            "location",
        )
    ),
    FieldPolicy("metadata.artwork_count", FieldOwnership.DERIVED, ("artwork_id",)),
    FieldPolicy("metadata.has_lyrics", FieldOwnership.DERIVED, ("metadata.lyrics",)),
)
PLAYLIST_POLICY = (
    FieldPolicy("playlist_id", FieldOwnership.IDENTITY),
    FieldPolicy("system_managed", FieldOwnership.RETAINED),
    *(
        FieldPolicy(p, FieldOwnership.EDITABLE)
        for p in (
            "name",
            "kind",
            "parent_id",
            "smart",
            "description",
            "sort_order",
        )
    ),
    # Regular membership is caller-owned; Smart matches are applied by iOpenPod;
    # folder membership is derived. Analysis enforces the kind-specific rule.
    FieldPolicy("entries", FieldOwnership.MEMBERSHIP, ("kind", "smart")),
)
ENTRY_POLICY = (
    FieldPolicy("entry_id", FieldOwnership.IDENTITY),
    FieldPolicy("track_id", FieldOwnership.IDENTITY),
    FieldPolicy("position", FieldOwnership.MEMBERSHIP),
)
SNAPSHOT_POLICY = (
    FieldPolicy("tracks", FieldOwnership.RECORDS),
    FieldPolicy("playlists", FieldOwnership.RECORDS),
    FieldPolicy("device_name", FieldOwnership.EDITABLE),
    FieldPolicy("photos", FieldOwnership.RECORDS),
)
PHOTO_POLICY = (
    FieldPolicy("photo_id", FieldOwnership.IDENTITY),
    FieldPolicy("rating", FieldOwnership.EDITABLE),
    FieldPolicy("original_date", FieldOwnership.EDITABLE),
    FieldPolicy("taken_date", FieldOwnership.EDITABLE),
    FieldPolicy("source_size_bytes", FieldOwnership.RETAINED),
    FieldPolicy("representations", FieldOwnership.RETAINED),
)
PHOTO_ALBUM_POLICY = (
    FieldPolicy("album_id", FieldOwnership.IDENTITY),
    FieldPolicy("name", FieldOwnership.EDITABLE),
    FieldPolicy("photo_ids", FieldOwnership.MEMBERSHIP),
    FieldPolicy("kind", FieldOwnership.RETAINED),
    FieldPolicy("play_music", FieldOwnership.EDITABLE),
    FieldPolicy("repeat", FieldOwnership.EDITABLE),
    FieldPolicy("random", FieldOwnership.EDITABLE),
    FieldPolicy("show_titles", FieldOwnership.EDITABLE),
    FieldPolicy("slide_duration_ms", FieldOwnership.EDITABLE),
    FieldPolicy("transition_duration_ms", FieldOwnership.EDITABLE),
    FieldPolicy("music_track_id", FieldOwnership.EDITABLE),
    FieldPolicy("ipod", FieldOwnership.RETAINED),
)
PHOTO_REPRESENTATION_POLICY = tuple(
    FieldPolicy(field.name, FieldOwnership.RETAINED)
    for field in fields(PhotoRepresentation)
)
PHOTO_FILE_FORMAT_POLICY = (
    FieldPolicy("format_id", FieldOwnership.IDENTITY),
    FieldPolicy("image_size_bytes", FieldOwnership.RETAINED),
    FieldPolicy("relative_path", FieldOwnership.RETAINED),
)
PHOTO_LIBRARY_POLICY = (
    FieldPolicy("photos", FieldOwnership.RECORDS),
    FieldPolicy("albums", FieldOwnership.RECORDS),
    FieldPolicy("formats", FieldOwnership.RECORDS),
)
IPOD_PHOTO_ALBUM_DETAILS_POLICY = tuple(
    FieldPolicy(field.name, FieldOwnership.RETAINED)
    for field in fields(IPodPhotoAlbumDetails)
)

# Semantic dependencies of native browse and podcast structures. Dataset impact
# and effect attribution consume the same field ownership vocabulary.
BROWSE_FIELDS = frozenset(
    (
        "title",
        "album",
        "artist",
        "album_artist",
        "genre",
        "track_number",
        "show",
        "season_number",
        "episode_number",
        "metadata.disc_number",
        "metadata.composer",
        "metadata.sort_title",
        "metadata.sort_album",
        "metadata.sort_artist",
        "metadata.sort_album_artist",
        "metadata.sort_composer",
        "metadata.sort_show",
    )
)
PODCAST_FIELDS = frozenset(("media_types", "metadata.podcast", "album"))


def value_at(record: object, path: str) -> object:
    for part in path.split("."):
        record = getattr(record, part)
    return record


def changed_fields(
    old: Track | Playlist | Photo | PhotoAlbum | None,
    new: Track | Playlist | Photo | PhotoAlbum,
) -> tuple[str, ...]:
    if isinstance(new, Track):
        policies = TRACK_POLICY
    elif isinstance(new, Playlist):
        policies = PLAYLIST_POLICY
    elif isinstance(new, Photo):
        policies = PHOTO_POLICY
    else:
        policies = PHOTO_ALBUM_POLICY
    return tuple(
        p.path
        for p in policies
        if old is None or value_at(old, p.path) != value_at(new, p.path)
    )


def needs_media(old: Track | None, new: Track) -> bool:
    return old is None or any(
        p.ownership is FieldOwnership.MEDIA
        and value_at(old, p.path) != value_at(new, p.path)
        for p in TRACK_POLICY
    )


def unclassified_fields() -> tuple[str, ...]:
    """Fail closed when a model grows without an explicit editing decision."""
    expected_tracks = {f.name for f in fields(Track) if f.name != "metadata"} | {
        "metadata." + f.name for f in fields(TrackMetadata)
    }
    problems: list[str] = []
    for name, expected, policy in (
        ("track", expected_tracks, TRACK_POLICY),
        ("playlist", {f.name for f in fields(Playlist)}, PLAYLIST_POLICY),
        ("entry", {f.name for f in fields(PlaylistEntry)}, ENTRY_POLICY),
        ("library", {f.name for f in fields(LibrarySnapshot)}, SNAPSHOT_POLICY),
        ("photo", {f.name for f in fields(Photo)}, PHOTO_POLICY),
        ("photo_album", {f.name for f in fields(PhotoAlbum)}, PHOTO_ALBUM_POLICY),
        (
            "photo_representation",
            {f.name for f in fields(PhotoRepresentation)},
            PHOTO_REPRESENTATION_POLICY,
        ),
        (
            "photo_format",
            {f.name for f in fields(PhotoFileFormat)},
            PHOTO_FILE_FORMAT_POLICY,
        ),
        (
            "photo_library",
            {f.name for f in fields(PhotoLibrary)},
            PHOTO_LIBRARY_POLICY,
        ),
        (
            "ipod_photo_album_details",
            {f.name for f in fields(IPodPhotoAlbumDetails)},
            IPOD_PHOTO_ALBUM_DETAILS_POLICY,
        ),
    ):
        paths = [p.path for p in policy]
        problems.extend(
            name + "." + p for p in sorted(expected.symmetric_difference(paths))
        )
        problems.extend(
            name + "." + p for p in sorted(set(paths)) if paths.count(p) != 1
        )
    return tuple(problems)
