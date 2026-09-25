"""Tests through the public, Qt-independent Library translation interface."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from iPodDB.ArtworkDB.builder.build_ArtworkDB import (
    new_artwork_chunk,
    new_ArtworkDB,
    new_container_mhod,
)
from iPodDB.ArtworkDB.builder.build_ArtworkDB import (
    new_string_mhod as new_artwork_string,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import DEFINITION as MHII_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import DEFINITION as MHNI_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.ArtworkDB.shared.constants import ArtworkMhodType
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.iTunesDB.builder.build_iTunesDB import (
    new_itunes_chunk,
    new_iTunesDB,
    new_string_mhod,
    new_url_mhod,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import DEFINITION as MHIT_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhlt import DEFINITION as MHLT_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    MhodChapterDataChapter,
    MhodChapterDataPayload,
    MhodChapterDataPreamble,
    MhodChapterDataSeanHeader,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.shared.device_time import unix_to_mac
from iPodDB.iTunesDB.shared.field_converters import sample_rate_to_fixed
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    ContentAdvisory,
    CoverFormat,
    CoverPixelFormat,
    IPodLibrary,
    IPodTrackDetails,
    MediaType,
    Track,
    TrackChapter,
    TrackMetadata,
)
from iPodDB.shared.chunk import EmptyChunkHeader, ParsedChunk


def test_ipod_library_translates_optional_metadata_without_exposing_chunks() -> None:
    timestamp = int(datetime(2024, 5, 6, 12, tzinfo=UTC).timestamp())
    mac_timestamp = unix_to_mac(timestamp, UTC)
    metadata = (
        new_string_mhod(MhodType.TITLE, "Title"),
        new_string_mhod(
            MhodType.LOCATION,
            ":iPod_Control:Music:F00:track.m4a",
        ),
        new_string_mhod(MhodType.ALBUM, "Album"),
        new_string_mhod(MhodType.ARTIST, "Artist"),
        new_string_mhod(MhodType.GENRE, "Genre"),
        new_string_mhod(MhodType.FILETYPE, "AAC audio file"),
        new_string_mhod(MhodType.EQ_SETTING, "Acoustic"),
        new_string_mhod(MhodType.COMMENT, "Comment"),
        new_string_mhod(MhodType.CATEGORY, "Technology"),
        new_string_mhod(MhodType.LYRICS, "Lyrics"),
        new_string_mhod(MhodType.COMPOSER, "Composer"),
        new_string_mhod(MhodType.GROUPING, "Grouping"),
        new_string_mhod(MhodType.DESCRIPTION, "Description"),
        new_url_mhod(
            MhodType.PODCAST_ENCLOSURE_URL,
            "https://example.test/enclosure.m4a",
        ),
        new_url_mhod(
            MhodType.PODCAST_RSS_URL,
            "https://example.test/feed",
        ),
        _chapter_mhod(),
        new_string_mhod(MhodType.SUBTITLE, "Subtitle"),
        new_string_mhod(MhodType.SHOW, "Show"),
        new_string_mhod(MhodType.EPISODE, "S01E02"),
        new_string_mhod(MhodType.TV_NETWORK, "Network"),
        new_string_mhod(MhodType.ALBUM_ARTIST, "Album Artist"),
        new_string_mhod(MhodType.SORT_ARTIST, "Sort Artist"),
        new_string_mhod(MhodType.TRACK_KEYWORDS, "keywords"),
        new_string_mhod(MhodType.SHOW_LOCALE, "en_US"),
        new_string_mhod(MhodType.ITUNES_STORE_ASSET_INFO, "Asset Info"),
        new_string_mhod(MhodType.SORT_TITLE, "Sort Title"),
        new_string_mhod(MhodType.SORT_ALBUM, "Sort Album"),
        new_string_mhod(MhodType.SORT_ALBUM_ARTIST, "Sort Album Artist"),
        new_string_mhod(MhodType.SORT_COMPOSER, "Sort Composer"),
        new_string_mhod(MhodType.SORT_SHOW, "Sort Show"),
        new_string_mhod(MhodType.CONTENT_PROVIDER, "Provider"),
        new_string_mhod(MhodType.COPYRIGHT, "Copyright"),
        new_string_mhod(MhodType.ENCODING_QUALITY_DESCRIPTOR, "High Quality"),
        new_string_mhod(MhodType.PURCHASE_ACCOUNT, "account@example.test"),
        new_string_mhod(MhodType.PURCHASER_NAME, "Purchaser"),
    )
    track = new_itunes_chunk(
        MHIT_DEFINITION,
        MhitHeader(
            track_id=7,
            filetype=2,
            vbr_flag=1,
            mp3_flag=1,
            compilation_flag=1,
            rating=80,
            last_modified=mac_timestamp,
            size=5_000_000,
            length=185_000,
            track_number=2,
            total_tracks=12,
            year=2024,
            bitrate=256,
            sample_rate_1=sample_rate_to_fixed(44_100),
            volume=-32,
            start_time=1_000,
            stop_time=184_000,
            sound_check=1_000,
            play_count_1=9,
            play_count_2=4,
            last_played=mac_timestamp,
            disc_number=2,
            total_discs=3,
            user_id=17,
            date_added=mac_timestamp,
            bookmark_time=12_000,
            db_track_id=0x0102030405060708,
            checked_flag=1,
            app_rating=60,
            bpm=128,
            artwork_count=2,
            av_flag=7,
            artwork_size=123_456,
            sample_rate_2=44_100.0,
            date_released=mac_timestamp,
            mpeg_audio_type=3,
            explicit_flag=2,
            purchased_aac_flag=1,
            genius_category_id=18,
            skip_count=5,
            last_skipped=mac_timestamp,
            has_artwork=1,
            skip_when_shuffling=1,
            remember_position=1,
            podcast_now_playing_flag=1,
            db_track_id_2=0x1112131415161718,
            lyrics_flag=1,
            video_flag=1,
            not_played_flag=2,
            pregap=2112,
            sample_count=8_158_500,
            postgap=512,
            encoder=3,
            media_type=4,
            season_number=1,
            episode_number=2,
            date_added_to_itunes=mac_timestamp,
            store_track_id=19,
            store_encoder_version=20,
            store_artist_id=21,
            store_album_id=22,
            gapless_audio_payload_size=8_000_000,
            gapless_track_flag=1,
            gapless_album_flag=1,
            album_id=44,
            db_id_2_ref=0x2122232425262728,
            size_2=4_999_999,
            artwork_id_ref=91,
            store_track_id_2=29,
            store_encoder_version_2=30,
            store_artist_id_2=31,
            store_album_id_2=32,
            artist_id_ref=45,
            composer_id=46,
            tv_show_media_type_flag=33,
        ),
        children=metadata,
    )
    assert track.header.gapless_album_flag == 1
    track_list = new_itunes_chunk(
        MHLT_DEFINITION,
        EmptyChunkHeader(),
        children=(track,),
    )
    dataset = new_itunes_chunk(
        MHSD_DEFINITION,
        MhsdHeader(dataset_type=1),
        children=(track_list,),
    )
    data = write_iTunesDB(
        new_iTunesDB(MhbdHeader(timezone_offset=0), datasets=(dataset,))
    )

    library = IPodLibrary.parse(data)
    projected = library.snapshot.tracks[0]
    assert library.serialize().itunes == data

    assert projected == Track(
        track_id=7,
        title="Title",
        artist="Artist",
        album="Album",
        length_ms=185_000,
        genre="Genre",
        year=2024,
        track_number=2,
        size_bytes=5_000_000,
        bitrate_kbps=256,
        play_count=9,
        rating=80,
        artwork_id=91,
        media_types=(MediaType.PODCAST,),
        show="Show",
        episode="S01E02",
        album_artist="Album Artist",
        season_number=1,
        episode_number=2,
        ipod=IPodTrackDetails(
            db_track_id=0x0102030405060708,
            media_type_code=4,
            filetype_code=2,
            mp3_flag=1,
            user_id=17,
            app_rating=60,
            audio_format_flag=7,
            artwork_size=123_456,
            sample_rate_2=44_100.0,
            mpeg_audio_type=3,
            purchased_aac_flag=1,
            genius_category_id=18,
            has_artwork=1,
            secondary_db_track_id=0x1112131415161718,
            movie_flag=1,
            encoder=3,
            date_added_to_itunes=timestamp,
            store_track_id=19,
            store_encoder_version=20,
            store_artist_id=21,
            store_album_id=22,
            gapless_audio_payload_size=8_000_000,
            album_id=44,
            db_id_2_ref=0x2122232425262728,
            secondary_size=4_999_999,
            artwork_id_ref=91,
            secondary_store_track_id=29,
            secondary_store_encoder_version=30,
            secondary_store_artist_id=31,
            secondary_store_album_id=32,
            artist_id_ref=45,
            composer_id=46,
            tv_show_media_type_flag=33,
            itunes_store_asset_info="Asset Info",
        ),
        metadata=TrackMetadata(
            file_format="AAC audio file",
            variable_bitrate=True,
            compilation=True,
            last_modified=timestamp,
            total_tracks=12,
            sample_rate_hz=44_100,
            volume_adjustment_percent=-32 / 255 * 100,
            start_time_ms=1_000,
            stop_time_ms=184_000,
            normalization_gain_db=0.0,
            unscrobbled_play_count=4,
            last_played=timestamp,
            disc_number=2,
            total_discs=3,
            date_added=timestamp,
            bookmark_time_ms=12_000,
            checked=False,
            bpm=128,
            artwork_count=2,
            release_date=timestamp,
            content_advisory=ContentAdvisory.CLEAN,
            skip_count=5,
            last_skipped=timestamp,
            skip_shuffle=True,
            remember_position=True,
            podcast=True,
            has_lyrics=True,
            played=True,
            pregap=2112,
            sample_count=8_158_500,
            postgap=512,
            gapless=True,
            gapless_album=True,
            location="iPod_Control/Music/F00/track.m4a",
            equalizer="Acoustic",
            comment="Comment",
            category="Technology",
            lyrics="Lyrics",
            composer="Composer",
            grouping="Grouping",
            description="Description",
            podcast_enclosure_url="https://example.test/enclosure.m4a",
            podcast_rss_url="https://example.test/feed",
            subtitle="Subtitle",
            tv_network="Network",
            sort_artist="Sort Artist",
            track_keywords="keywords",
            show_locale="en_US",
            sort_title="Sort Title",
            sort_album="Sort Album",
            sort_album_artist="Sort Album Artist",
            sort_composer="Sort Composer",
            sort_show="Sort Show",
            content_provider="Provider",
            copyright="Copyright",
            encoding_quality="High Quality",
            purchase_account="account@example.test",
            purchaser_name="Purchaser",
            chapters=(
                TrackChapter("Opening", 0),
                TrackChapter("Finale", 120_000),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("raw_type", "types", "unknown"),
    (
        (0, (MediaType.AUDIO_VIDEO,), 0),
        (1, (MediaType.AUDIO,), 0),
        (6, (MediaType.VIDEO_PODCAST,), 0),
        (8, (MediaType.AUDIOBOOK,), 0),
        (0x60, (MediaType.TV_SHOW,), 0),
        (0x41, (MediaType.AUDIO, MediaType.TV_SHOW), 0),
        (0x4001, (MediaType.AUDIO, MediaType.RINGTONE), 0),
        (0x11, (MediaType.AUDIO,), 0x10),
    ),
)
def test_media_translation_retains_unknown_values_without_exposing_flags(
    raw_type: int, types: tuple[MediaType, ...], unknown: int
) -> None:
    data = _itunes_bytes(MhitHeader(track_id=1, media_type=raw_type))
    source = IPodLibrary.parse(data)
    track = source.snapshot.tracks[0]
    assert track.media_types == types
    assert track.ipod is not None
    assert track.ipod.media_type_code == raw_type
    assert track.ipod.unknown_media_type_bits == unknown
    assert source.serialize().itunes == data


def test_translation_normalizes_file_formats_and_preserves_unknown_source_bytes() -> (
    None
):
    data = _itunes_bytes(MhitHeader(track_id=1, filetype=0x4D344120)) + b"future suffix"
    source = IPodLibrary.parse(data)
    assert source.snapshot.tracks[0].metadata.file_format == "M4A"
    assert source.serialize().itunes == data


@pytest.mark.parametrize(
    ("sound_check", "gain_db"),
    ((0, None), (100, 10.0), (1_000, 0.0), (10_000, -10.0)),
)
def test_sound_check_projects_amplification_and_attenuation_losslessly(
    sound_check: int, gain_db: float | None
) -> None:
    data = _itunes_bytes(MhitHeader(track_id=1, sound_check=sound_check))
    source = IPodLibrary.parse(data)
    projected_gain = source.snapshot.tracks[0].metadata.normalization_gain_db

    if gain_db is None:
        assert projected_gain is None
    else:
        assert projected_gain == pytest.approx(gain_db)
    assert source.serialize().itunes == data


def test_ipod_source_rejects_ambiguous_track_ids() -> None:
    data = _itunes_bytes(
        MhitHeader(track_id=7, db_track_id=1),
        MhitHeader(track_id=7, db_track_id=2),
    )

    with pytest.raises(ValueError, match=r"Duplicate Track ID.*7"):
        IPodLibrary.parse(data)


def test_source_construction_and_snapshot_edits_keep_documents_private() -> None:
    data = _itunes_bytes(MhitHeader(track_id=1)) + b"future suffix"
    source = IPodLibrary(data)
    original = source.snapshot
    edited = replace(
        original,
        tracks=(replace(original.tracks[0], title="Presentation edit"),),
    )

    with pytest.raises(AttributeError):
        source.snapshot = edited  # type: ignore[misc]  # Exercise the runtime guard too.
    assert source.snapshot is original
    assert source.serialize().itunes == data
    assert source.serialize().artwork is None


def test_artwork_relationships_and_replacement_use_source_identifiers() -> None:
    source = IPodLibrary.parse(
        _itunes_bytes(
            MhitHeader(track_id=1, db_track_id=7, artwork_id_ref=91),
            MhitHeader(track_id=2, db_track_id=8, artwork_id_ref=91),
            MhitHeader(track_id=3, db_track_id=9, artwork_id_ref=99),
        )
    )
    artwork = _artwork_bytes((64, 7), (91, 0)) + b"future artwork suffix"
    linked = source.with_artwork(artwork)
    assert tuple(track.artwork_id for track in linked.snapshot.tracks) == (64, 91, 0)
    assert tuple(track.artwork_id for track in source.snapshot.tracks) == (91, 91, 99)
    assert linked.serialize().artwork == artwork
    assert linked.serialize().itunes == source.serialize().itunes

    # Image 64 now belongs to someone else; a previously resolved image ID must
    # never become the next database's fallback reference.
    replaced = linked.with_artwork(_artwork_bytes((64, 100)))
    assert tuple(track.artwork_id for track in replaced.snapshot.tracks) == (0, 0, 0)


def test_lazy_artwork_plan_selects_reduced_ranges_and_decodes_only_supplied_bytes() -> (
    None
):
    source = IPodLibrary.parse(_itunes_bytes(MhitHeader(track_id=1, db_track_id=7)))
    source = source.with_artwork(_artwork_bytes((64, 7)))
    formats = (
        CoverFormat(1002, 2, 2, 4, CoverPixelFormat.RGB565_LE),
        CoverFormat(1008, 8, 8, 16, CoverPixelFormat.RGB565_LE),
    )
    read = source.artwork_read(64, formats, 2)
    assert read is not None
    assert (read.relative_path, read.offset, read.length) == (
        "iPod_Control/Artwork/F1002_1.ithmb",
        16,
        8,
    )
    pixels = read.decode(b"\xe0\x07" * 4)
    assert (pixels.width, pixels.height, pixels.rgb888) == (2, 2, b"\x00\xff\x00" * 4)
    with pytest.raises(ValueError, match="requested range"):
        read.decode(b"short")
    for target in (4, 20):
        larger = source.artwork_read(64, formats, target)
        assert larger is not None
        assert larger.format_id == 1008
    assert source.artwork_read(0, formats, 2) is None
    assert source.artwork_read(999, formats, 2) is None
    assert source.artwork_read(64, (), 2) is None


def _itunes_bytes(*headers: MhitHeader) -> bytes:
    tracks = tuple(new_itunes_chunk(MHIT_DEFINITION, header) for header in headers)
    track_list = new_itunes_chunk(MHLT_DEFINITION, EmptyChunkHeader(), children=tracks)
    dataset = new_itunes_chunk(
        MHSD_DEFINITION,
        MhsdHeader(dataset_type=1),
        children=(track_list,),
    )
    return write_iTunesDB(new_iTunesDB(MhbdHeader(), datasets=(dataset,)))


def _artwork_bytes(*identities: tuple[int, int]) -> bytes:
    images: list[ParsedChunk[MhiiHeader]] = []
    for image_id, database_track_id in identities:
        variants = tuple(
            new_container_mhod(
                ArtworkMhodType.THUMBNAIL_IMAGE,
                new_artwork_chunk(
                    MHNI_DEFINITION,
                    MhniHeader(
                        format_id=1000 + size,
                        ithmb_offset=16,
                        image_size=size * size * 2,
                        image_width=size,
                        image_height=size,
                    ),
                    children=(
                        new_artwork_string(
                            ArtworkMhodType.FILE_NAME,
                            f":F{1000 + size}_1.ithmb",
                        ),
                    ),
                ),
            )
            for size in (2, 8)
        )
        images.append(
            new_artwork_chunk(
                MHII_DEFINITION,
                MhiiHeader(image_id=image_id, db_track_id_ref=database_track_id),
                children=variants,
            )
        )
    return write_ArtworkDB(
        new_ArtworkDB(
            next_mhii_id=1
            + max((image_id for image_id, _track_id in identities), default=0),
            unk_mhfd_0x10=2,
            image_items=tuple(images),
        )
    )


def _chapter_mhod() -> ParsedChunk[MhodHeader]:
    return new_itunes_chunk(
        MHOD_DEFINITION,
        MhodHeader(mhod_type=MhodType.CHAPTER_DATA),
        payload=MhodChapterDataPayload(
            preamble=MhodChapterDataPreamble(0, 0, 0),
            sean=MhodChapterDataSeanHeader(
                total_size=0,
                atom_type=b"sean",
                unk_0x08=0,
                child_count=0,
                unk_0x10=0,
            ),
            hedr=None,
            chapters=(
                MhodChapterDataChapter("Opening", 0, ()),
                MhodChapterDataChapter("Finale", 120_000, ()),
            ),
            other_atoms=(),
        ),
    )
