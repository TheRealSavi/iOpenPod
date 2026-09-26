"""Immutable Library data shared by database and future external-source adapters."""

from dataclasses import dataclass
from enum import StrEnum

from iPodDB.library.photos import PhotoLibrary
from iPodDB.library.playlists import Playlist


class MediaKind(StrEnum):
    """Stable browsing categories shared by all Library sources."""

    MUSIC = "music"
    PODCAST = "podcast"
    AUDIOBOOK = "audiobook"
    MOVIE = "movie"
    TV_SHOW = "tv_show"
    MUSIC_VIDEO = "music_video"


class MediaType(StrEnum):
    """Semantic media classifications; values are not database bit masks."""

    AUDIO = "audio"
    VIDEO = "video"
    AUDIO_VIDEO = "audio_video"
    PODCAST = "podcast"
    VIDEO_PODCAST = "video_podcast"
    AUDIOBOOK = "audiobook"
    MUSIC_VIDEO = "music_video"
    TV_SHOW = "tv_show"
    RINGTONE = "ringtone"
    RENTAL = "rental"
    ITUNES_EXTRA = "itunes_extra"
    MEMO = "memo"
    ITUNES_U = "itunes_u"
    EPUB_BOOK = "epub_book"
    PDF_BOOK = "pdf_book"


class ContentAdvisory(StrEnum):
    UNSPECIFIED = "unspecified"
    EXPLICIT = "explicit"
    CLEAN = "clean"


@dataclass(frozen=True, slots=True)
class TrackChapter:
    """A named position in a playable Track, measured in milliseconds."""

    title: str
    start_ms: int


@dataclass(frozen=True, slots=True)
class IPodTrackDetails:
    """Optional iPod diagnostics; never required to construct a source-neutral Track."""

    db_track_id: int = 0
    media_type_code: int = 0
    unknown_media_type_bits: int = 0
    filetype_code: int = 0
    mp3_flag: int = 0
    user_id: int = 0
    app_rating: int = 0
    audio_format_flag: int = 0
    artwork_size: int = 0
    sample_rate_2: float = 0.0
    mpeg_audio_type: int = 0
    purchased_aac_flag: int = 0
    genius_category_id: int = 0
    has_artwork: int = 0
    secondary_db_track_id: int = 0
    movie_flag: int = 0
    encoder: int = 0
    date_added_to_itunes: int = 0
    store_track_id: int = 0
    store_encoder_version: int = 0
    store_artist_id: int = 0
    store_album_id: int = 0
    gapless_audio_payload_size: int = 0
    album_id: int = 0
    db_id_2_ref: int = 0
    secondary_size: int = 0
    artwork_id_ref: int = 0
    secondary_store_track_id: int = 0
    secondary_store_encoder_version: int = 0
    secondary_store_artist_id: int = 0
    secondary_store_album_id: int = 0
    artist_id_ref: int = 0
    composer_id: int = 0
    tv_show_media_type_flag: int = 0
    itunes_store_asset_info: str = ""


@dataclass(frozen=True, slots=True)
class TrackMetadata:
    """Optional semantic metadata, with Unix-second dates and explicit units."""

    file_format: str = ""
    variable_bitrate: bool = False
    compilation: bool = False
    last_modified: int = 0
    total_tracks: int = 0
    sample_rate_hz: int = 0
    volume_adjustment_percent: float = 0.0
    start_time_ms: int = 0
    stop_time_ms: int = 0
    normalization_gain_db: float | None = None
    unscrobbled_play_count: int = 0
    last_played: int = 0
    disc_number: int = 0
    total_discs: int = 0
    date_added: int = 0
    bookmark_time_ms: int = 0
    checked: bool = True
    bpm: int = 0
    artwork_count: int = 0
    release_date: int = 0
    content_advisory: ContentAdvisory = ContentAdvisory.UNSPECIFIED
    skip_count: int = 0
    last_skipped: int = 0
    skip_shuffle: bool = False
    remember_position: bool = False
    podcast: bool = False
    has_lyrics: bool = False
    played: bool = False
    pregap: int = 0
    sample_count: int = 0
    postgap: int = 0
    gapless: bool = False
    gapless_album: bool = False
    location: str = ""
    equalizer: str = ""
    comment: str = ""
    category: str = ""
    lyrics: str = ""
    composer: str = ""
    grouping: str = ""
    description: str = ""
    podcast_enclosure_url: str = ""
    podcast_rss_url: str = ""
    subtitle: str = ""
    tv_network: str = ""
    sort_artist: str = ""
    track_keywords: str = ""
    show_locale: str = ""
    sort_title: str = ""
    sort_album: str = ""
    sort_album_artist: str = ""
    sort_composer: str = ""
    sort_show: str = ""
    content_provider: str = ""
    copyright: str = ""
    encoding_quality: str = ""
    purchase_account: str = ""
    purchaser_name: str = ""
    chapters: tuple[TrackChapter, ...] = ()


@dataclass(frozen=True, slots=True)
class Track:
    """Source-neutral Track; numeric IDs are opaque within one Library Snapshot."""

    track_id: int
    title: str
    artist: str
    album: str
    length_ms: int
    genre: str = ""
    year: int = 0
    track_number: int = 0
    size_bytes: int = 0
    bitrate_kbps: int = 0
    play_count: int = 0
    rating: int = 0
    artwork_id: int = 0
    media_types: tuple[MediaType, ...] = (MediaType.AUDIO,)
    show: str = ""
    episode: str = ""
    album_artist: str = ""
    season_number: int = 0
    episode_number: int = 0
    metadata: TrackMetadata = TrackMetadata()
    ipod: IPodTrackDetails | None = None

    @property
    def effective_album_artist(self) -> str:
        """Return the album artist used to group this Track."""

        return self.album_artist or self.artist

    @property
    def album_key(self) -> str:
        """Return the stable presentation key used to group this Track."""

        return "\x1f".join(
            (self.effective_album_artist.casefold(), self.album.casefold())
        )

    @property
    def artist_key(self) -> str:
        return self.artist.casefold()

    @property
    def genre_key(self) -> str:
        return self.genre.casefold()

    @property
    def show_key(self) -> str:
        return self.show.casefold()

    @property
    def media_kind(self) -> MediaKind:
        """Resolve the browsing category from semantic media types."""

        kinds = self.media_types
        if MediaType.PODCAST in kinds or MediaType.VIDEO_PODCAST in kinds:
            return MediaKind.PODCAST
        if MediaType.AUDIOBOOK in kinds:
            return MediaKind.AUDIOBOOK
        if MediaType.TV_SHOW in kinds:
            return MediaKind.TV_SHOW
        if MediaType.MUSIC_VIDEO in kinds:
            return MediaKind.MUSIC_VIDEO
        if MediaType.VIDEO in kinds:
            return MediaKind.MOVIE
        return MediaKind.MUSIC


@dataclass(frozen=True, slots=True)
class LibrarySnapshot:
    """Ordered immutable Library records, independent of database or transport."""

    tracks: tuple[Track, ...] = ()
    playlists: tuple[Playlist, ...] = ()
    device_name: str = ""
    photos: PhotoLibrary | None = None

    def __post_init__(self) -> None:
        track_ids: set[int] = set()
        for track in self.tracks:
            if track.track_id in track_ids:
                raise ValueError(
                    f"Duplicate Track ID in Library Snapshot: {track.track_id}"
                )
            track_ids.add(track.track_id)
        playlist_ids: set[int] = set()
        for playlist in self.playlists:
            if playlist.playlist_id in playlist_ids:
                raise ValueError(
                    f"Duplicate Playlist ID in Library Snapshot: {playlist.playlist_id}"
                )
            playlist_ids.add(playlist.playlist_id)
