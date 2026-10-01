"""Private database-format translation into semantic Library records."""

from dataclasses import dataclass, replace

from iPodDB.ArtworkDB.shared.artwork_index import ArtworkIndex
from iPodDB.device_time import DeviceTimeContext, TimeConversion, project_mac
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    MhodChapterDataPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.url_mhod import MhodUrlPayload
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.constants import (
    MEDIA_TYPE_AUDIO,
    MEDIA_TYPE_AUDIO_VIDEO,
    MEDIA_TYPE_AUDIOBOOK,
    MEDIA_TYPE_EPUB_BOOK,
    MEDIA_TYPE_ITUNES_EXTRA,
    MEDIA_TYPE_ITUNES_U,
    MEDIA_TYPE_MEMO,
    MEDIA_TYPE_MUSIC_VIDEO,
    MEDIA_TYPE_PDF_BOOK,
    MEDIA_TYPE_PODCAST,
    MEDIA_TYPE_RENTAL,
    MEDIA_TYPE_RINGTONE,
    MEDIA_TYPE_TV_SHOW,
    MEDIA_TYPE_TV_SHOW_ALT,
    MEDIA_TYPE_VIDEO,
    MEDIA_TYPE_VIDEO_PODCAST,
    MhodType,
)
from iPodDB.iTunesDB.shared.field_converters import fixed_to_sample_rate
from iPodDB.library._native_values import normalization_gain_from_native
from iPodDB.library.models import (
    ContentAdvisory,
    IPodTrackDetails,
    MediaType,
    Track,
    TrackChapter,
    TrackMetadata,
)
from iPodDB.shared.chunk import ChunkSelection, DatabaseDocument


@dataclass(frozen=True, slots=True)
class _TrackTextMetadata:
    """Stable, typed projection of user-facing text MHOD payloads."""

    title: str = ""
    location: str = ""
    album: str = ""
    artist: str = ""
    genre: str = ""
    filetype: str = ""
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
    show: str = ""
    episode: str = ""
    tv_network: str = ""
    album_artist: str = ""
    sort_artist: str = ""
    track_keywords: str = ""
    show_locale: str = ""
    itunes_store_asset_info: str = ""
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


def _project_track(
    selection: ChunkSelection[MhbdHeader, MhitHeader],
    device_timezone: TimeConversion,
) -> Track:
    text, chapters = _project_track_children(selection)
    header = selection.chunk.header
    return Track(
        track_id=header.track_id,
        title=text.title,
        artist=text.artist,
        album=text.album,
        length_ms=header.length,
        genre=text.genre,
        year=header.year,
        track_number=header.track_number,
        size_bytes=header.size,
        bitrate_kbps=header.bitrate,
        play_count=header.play_count_1,
        rating=header.rating,
        artwork_id=header.artwork_id_ref,
        media_types=_media_types(header.media_type),
        show=text.show,
        episode=text.episode,
        album_artist=text.album_artist,
        season_number=header.season_number,
        episode_number=header.episode_number,
        metadata=_project_metadata(header, text, chapters, device_timezone),
        ipod=_project_ipod_details(header, text, device_timezone),
    )


def _project_ipod_details(
    header: MhitHeader,
    text: _TrackTextMetadata,
    device_timezone: TimeConversion,
) -> IPodTrackDetails:
    """Retain source diagnostics separately from common metadata."""

    return IPodTrackDetails(
        db_track_id=header.db_track_id,
        media_type_code=header.media_type,
        unknown_media_type_bits=unknown_media_bits(header.media_type),
        filetype_code=header.filetype,
        mp3_flag=header.mp3_flag,
        user_id=header.user_id,
        app_rating=header.app_rating,
        audio_format_flag=header.av_flag,
        artwork_size=header.artwork_size,
        sample_rate_2=header.sample_rate_2,
        mpeg_audio_type=header.mpeg_audio_type,
        purchased_aac_flag=header.purchased_aac_flag,
        genius_category_id=header.genius_category_id,
        has_artwork=header.has_artwork,
        secondary_db_track_id=header.db_track_id_2,
        movie_flag=header.video_flag,
        encoder=header.encoder,
        date_added_to_itunes=_project_timestamp(
            header.date_added_to_itunes, device_timezone, utc=True
        ),
        store_track_id=header.store_track_id,
        store_encoder_version=header.store_encoder_version,
        store_artist_id=header.store_artist_id,
        store_album_id=header.store_album_id,
        gapless_audio_payload_size=header.gapless_audio_payload_size,
        album_id=header.album_id,
        db_id_2_ref=header.db_id_2_ref,
        secondary_size=header.size_2,
        artwork_id_ref=header.artwork_id_ref,
        secondary_store_track_id=header.store_track_id_2,
        secondary_store_encoder_version=header.store_encoder_version_2,
        secondary_store_artist_id=header.store_artist_id_2,
        secondary_store_album_id=header.store_album_id_2,
        artist_id_ref=header.artist_id_ref,
        composer_id=header.composer_id,
        tv_show_media_type_flag=header.tv_show_media_type_flag,
        itunes_store_asset_info=text.itunes_store_asset_info,
    )


def _project_metadata(
    header: MhitHeader,
    text: _TrackTextMetadata,
    chapters: tuple[TrackChapter, ...],
    device_timezone: TimeConversion,
) -> TrackMetadata:
    """Translate source fields into semantic values with the contract's units."""

    return TrackMetadata(
        file_format=_file_format(text.filetype, header.filetype),
        variable_bitrate=bool(header.vbr_flag),
        compilation=bool(header.compilation_flag),
        last_modified=_project_timestamp(header.last_modified, device_timezone),
        total_tracks=header.total_tracks,
        sample_rate_hz=fixed_to_sample_rate(header.sample_rate_1),
        volume_adjustment_percent=header.volume / 255 * 100,
        start_time_ms=header.start_time,
        stop_time_ms=header.stop_time,
        normalization_gain_db=normalization_gain_from_native(header.sound_check),
        unscrobbled_play_count=header.play_count_2,
        last_played=_project_timestamp(header.last_played, device_timezone),
        disc_number=header.disc_number,
        total_discs=header.total_discs,
        date_added=_project_timestamp(header.date_added, device_timezone),
        bookmark_time_ms=header.bookmark_time,
        checked=header.checked_flag == 0,
        bpm=header.bpm,
        artwork_count=header.artwork_count,
        release_date=project_mac(header.date_released, device_timezone, utc=True),
        content_advisory=_content_advisory(header.explicit_flag),
        skip_count=header.skip_count,
        last_skipped=_project_timestamp(header.last_skipped, device_timezone),
        skip_shuffle=bool(header.skip_when_shuffling),
        remember_position=bool(header.remember_position),
        podcast=bool(header.podcast_now_playing_flag),
        has_lyrics=bool(header.lyrics_flag),
        played=header.play_count_1 > 0 or header.not_played_flag == 1,
        pregap=header.pregap,
        sample_count=header.sample_count,
        postgap=header.postgap,
        gapless=bool(header.gapless_track_flag),
        gapless_album=bool(header.gapless_album_flag),
        location=_media_location(text.location),
        equalizer=text.equalizer,
        comment=text.comment,
        category=text.category,
        lyrics=text.lyrics,
        composer=text.composer,
        grouping=text.grouping,
        description=text.description,
        podcast_enclosure_url=text.podcast_enclosure_url,
        podcast_rss_url=text.podcast_rss_url,
        subtitle=text.subtitle,
        tv_network=text.tv_network,
        sort_artist=text.sort_artist,
        track_keywords=text.track_keywords,
        show_locale=text.show_locale,
        sort_title=text.sort_title,
        sort_album=text.sort_album,
        sort_album_artist=text.sort_album_artist,
        sort_composer=text.sort_composer,
        sort_show=text.sort_show,
        content_provider=text.content_provider,
        copyright=text.copyright,
        encoding_quality=text.encoding_quality,
        purchase_account=text.purchase_account,
        purchaser_name=text.purchaser_name,
        chapters=chapters,
    )


def _project_track_children(
    selection: ChunkSelection[MhbdHeader, MhitHeader],
) -> tuple[_TrackTextMetadata, tuple[TrackChapter, ...]]:
    values: dict[MhodType, str] = {}
    chapters: tuple[TrackChapter, ...] = ()
    for metadata in selection.find_chunks(MhodHeader):
        try:
            mhod_type = MhodType(metadata.chunk.header.mhod_type)
        except ValueError:
            continue
        payload = metadata.chunk.payload
        if isinstance(payload, MhodStringPayload | MhodUrlPayload):
            values[mhod_type] = payload.value
        elif mhod_type is MhodType.CHAPTER_DATA and isinstance(
            payload, MhodChapterDataPayload
        ):
            chapters = tuple(
                TrackChapter(chapter.name, chapter.start_pos_ms)
                for chapter in payload.chapters
            )
    return (
        _TrackTextMetadata(
            title=values.get(MhodType.TITLE, ""),
            location=values.get(MhodType.LOCATION, ""),
            album=values.get(MhodType.ALBUM, ""),
            artist=values.get(MhodType.ARTIST, ""),
            genre=values.get(MhodType.GENRE, ""),
            filetype=values.get(MhodType.FILETYPE, ""),
            equalizer=values.get(MhodType.EQ_SETTING, ""),
            comment=values.get(MhodType.COMMENT, ""),
            category=values.get(MhodType.CATEGORY, ""),
            lyrics=values.get(MhodType.LYRICS, ""),
            composer=values.get(MhodType.COMPOSER, ""),
            grouping=values.get(MhodType.GROUPING, ""),
            description=values.get(MhodType.DESCRIPTION, ""),
            podcast_enclosure_url=values.get(MhodType.PODCAST_ENCLOSURE_URL, ""),
            podcast_rss_url=values.get(MhodType.PODCAST_RSS_URL, ""),
            subtitle=values.get(MhodType.SUBTITLE, ""),
            show=values.get(MhodType.SHOW, ""),
            episode=values.get(MhodType.EPISODE, ""),
            tv_network=values.get(MhodType.TV_NETWORK, ""),
            album_artist=values.get(MhodType.ALBUM_ARTIST, ""),
            sort_artist=values.get(MhodType.SORT_ARTIST, ""),
            track_keywords=values.get(MhodType.TRACK_KEYWORDS, ""),
            show_locale=values.get(MhodType.SHOW_LOCALE, ""),
            itunes_store_asset_info=values.get(MhodType.ITUNES_STORE_ASSET_INFO, ""),
            sort_title=values.get(MhodType.SORT_TITLE, ""),
            sort_album=values.get(MhodType.SORT_ALBUM, ""),
            sort_album_artist=values.get(MhodType.SORT_ALBUM_ARTIST, ""),
            sort_composer=values.get(MhodType.SORT_COMPOSER, ""),
            sort_show=values.get(MhodType.SORT_SHOW, ""),
            content_provider=values.get(MhodType.CONTENT_PROVIDER, ""),
            copyright=values.get(MhodType.COPYRIGHT, ""),
            encoding_quality=values.get(MhodType.ENCODING_QUALITY_DESCRIPTOR, ""),
            purchase_account=values.get(MhodType.PURCHASE_ACCOUNT, ""),
            purchaser_name=values.get(MhodType.PURCHASER_NAME, ""),
        ),
        chapters,
    )


def _project_timestamp(
    value: int, device_timezone: TimeConversion, *, utc: bool = False
) -> int:
    return project_mac(value, device_timezone, utc=utc)


def _resolved_artwork_id(track: Track, artwork_index: ArtworkIndex) -> int:
    item = artwork_index.item_for_db_track_id(
        track.ipod.db_track_id if track.ipod is not None else 0
    )
    if item is not None:
        return item.image_id
    # A replacement ArtworkDB must use the source reference, not an image ID
    # resolved from a previous ArtworkDB.
    direct_id = track.ipod.artwork_id_ref if track.ipod is not None else 0
    if artwork_index.item_for_image_id(direct_id) is not None:
        return direct_id
    return 0


MEDIA_TYPES = {
    MEDIA_TYPE_AUDIO_VIDEO: MediaType.AUDIO_VIDEO,
    MEDIA_TYPE_AUDIO: MediaType.AUDIO,
    MEDIA_TYPE_VIDEO: MediaType.VIDEO,
    MEDIA_TYPE_PODCAST: MediaType.PODCAST,
    MEDIA_TYPE_VIDEO_PODCAST: MediaType.VIDEO_PODCAST,
    MEDIA_TYPE_AUDIOBOOK: MediaType.AUDIOBOOK,
    MEDIA_TYPE_MUSIC_VIDEO: MediaType.MUSIC_VIDEO,
    MEDIA_TYPE_TV_SHOW: MediaType.TV_SHOW,
    MEDIA_TYPE_TV_SHOW_ALT: MediaType.TV_SHOW,
    MEDIA_TYPE_RINGTONE: MediaType.RINGTONE,
    MEDIA_TYPE_RENTAL: MediaType.RENTAL,
    MEDIA_TYPE_ITUNES_EXTRA: MediaType.ITUNES_EXTRA,
    MEDIA_TYPE_MEMO: MediaType.MEMO,
    MEDIA_TYPE_ITUNES_U: MediaType.ITUNES_U,
    MEDIA_TYPE_EPUB_BOOK: MediaType.EPUB_BOOK,
    MEDIA_TYPE_PDF_BOOK: MediaType.PDF_BOOK,
}
_SINGLE_BIT_TYPES = tuple(
    (flag, kind)
    for flag, kind in MEDIA_TYPES.items()
    if flag > 0 and flag & (flag - 1) == 0
)


def _media_types(value: int) -> tuple[MediaType, ...]:
    exact = MEDIA_TYPES.get(value)
    if exact is not None:
        return (exact,)
    return tuple(
        dict.fromkeys(kind for flag, kind in _SINGLE_BIT_TYPES if value & flag)
    )


def unknown_media_bits(value: int) -> int:
    if value in MEDIA_TYPES:
        return 0
    for flag, _kind in _SINGLE_BIT_TYPES:
        value &= ~flag
    return value


def _content_advisory(value: int) -> ContentAdvisory:
    if value == 1:
        return ContentAdvisory.EXPLICIT
    if value == 2:
        return ContentAdvisory.CLEAN
    return ContentAdvisory.UNSPECIFIED


def _media_location(value: str) -> str:
    # iTunesDB stores colon-delimited device locations. The consumer still must
    # validate containment and file identity before accessing any bytes.
    value = value.strip()
    return value[1:].replace(":", "/") if value.startswith(":") else value


def _file_format(label: str, code: int) -> str:
    if label:
        return label
    if code <= 0:
        return ""
    try:
        decoded = code.to_bytes(4, "big").decode("ascii").strip()
    except (OverflowError, UnicodeDecodeError):
        decoded = ""
    return decoded if decoded and decoded.isprintable() else f"0x{code:08X}"


def project_tracks(
    database: DatabaseDocument[MhbdHeader], device_time: DeviceTimeContext | None = None
) -> tuple[Track, ...]:
    """Translate the Track dataset using the shared format definitions."""

    track_dataset = next(
        (
            selection
            for selection in database.find_chunks(MhsdHeader)
            if selection.chunk.header.dataset_type == 1
        ),
        None,
    )
    if track_dataset is None:
        return ()
    device_timezone = device_time or DeviceTimeContext().for_database(
        database.header.timezone_offset
    )
    return tuple(
        _project_track(selection, device_timezone)
        for selection in track_dataset.find_chunks(MhitHeader)
    )


def link_artwork(
    tracks: tuple[Track, ...], artwork_index: ArtworkIndex
) -> tuple[Track, ...]:
    """Prefer ArtworkDB Track relationships, then a valid direct reference."""

    return tuple(
        replace(track, artwork_id=_resolved_artwork_id(track, artwork_index))
        for track in tracks
    )
