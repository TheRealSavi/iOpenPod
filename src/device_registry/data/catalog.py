"""Built-in iPod catalog translated from Original iOpenPod research.

The release catalog contains filesystem-accessible full-size iPod generations 1
through 5.5, iPod Classic, iPod Mini, and iPod Nano families. iPod touch and iPod
shuffle remain out of scope.
"""

from __future__ import annotations

from dataclasses import replace

from device_registry.models import (
    ArtworkCapabilities,
    ArtworkFormat,
    ArtworkPixelFormat,
    ArtworkUsage,
    AudioCapabilities,
    ConnectionMode,
    DatabaseCapabilities,
    DatabaseChecksum,
    DeviceCapabilities,
    DeviceProfile,
    DisplayCapabilities,
    ModelIdentity,
    RegistryCatalog,
    SerialSuffixDefinition,
    StorageTechnology,
    UsbIdentifier,
    UsbProductDefinition,
    VideoCapabilities,
)

_MIB = 1024 * 1024
_STANDARD_DATABASE_LIMIT = 32 * _MIB
_LARGE_DATABASE_LIMIT = 64 * _MIB


def _artwork_format(
    format_id: int,
    width: int,
    height: int,
    row_bytes: int,
    pixel_format: ArtworkPixelFormat = ArtworkPixelFormat.RGB565_LE,
    usage: ArtworkUsage = ArtworkUsage.COVER,
) -> ArtworkFormat:
    return ArtworkFormat(
        format_id=format_id,
        width=width,
        height=height,
        row_bytes=row_bytes,
        pixel_format=pixel_format,
        usage=usage,
    )


_ARTWORK_FORMATS_BY_ID: dict[int, ArtworkFormat] = {
    1005: _artwork_format(1005, 80, 80, 160, usage=ArtworkUsage.PHOTO),
    1007: _artwork_format(1007, 480, 864, 960, usage=ArtworkUsage.PHOTO),
    1009: _artwork_format(1009, 42, 30, 84, usage=ArtworkUsage.PHOTO),
    1013: _artwork_format(
        1013,
        220,
        176,
        440,
        ArtworkPixelFormat.RGB565_BE_90,
        ArtworkUsage.PHOTO,
    ),
    1015: _artwork_format(1015, 130, 88, 260, usage=ArtworkUsage.PHOTO),
    1016: _artwork_format(1016, 140, 140, 280),
    1017: _artwork_format(1017, 56, 56, 112),
    1019: _artwork_format(
        1019,
        720,
        480,
        1440,
        ArtworkPixelFormat.UYVY_FIELDS,
        ArtworkUsage.TV_OUTPUT,
    ),
    1023: _artwork_format(
        1023,
        176,
        132,
        352,
        ArtworkPixelFormat.RGB565_BE,
        ArtworkUsage.PHOTO,
    ),
    1024: _artwork_format(1024, 320, 240, 640, usage=ArtworkUsage.PHOTO),
    1027: _artwork_format(1027, 100, 100, 200),
    1028: _artwork_format(1028, 100, 100, 200),
    1029: _artwork_format(1029, 200, 200, 400),
    1031: _artwork_format(1031, 42, 42, 84),
    1032: _artwork_format(1032, 42, 37, 84, usage=ArtworkUsage.PHOTO),
    1036: _artwork_format(1036, 50, 41, 100, usage=ArtworkUsage.PHOTO),
    1055: _artwork_format(1055, 128, 128, 256),
    1056: _artwork_format(1056, 128, 128, 256),
    1060: _artwork_format(1060, 320, 320, 640),
    # Original iOpenPod creates 56-row F1061 images; retained 55-row images
    # are selected from ArtworkDB evidence during preparation.
    1061: _artwork_format(1061, 56, 56, 112),
    1066: _artwork_format(1066, 64, 64, 128, usage=ArtworkUsage.PHOTO),
    1067: _artwork_format(
        1067,
        720,
        480,
        1080,
        ArtworkPixelFormat.I420_LE,
        ArtworkUsage.TV_OUTPUT,
    ),
    1068: _artwork_format(1068, 128, 128, 256),
    1071: _artwork_format(1071, 240, 240, 480),
    1073: _artwork_format(1073, 240, 240, 480),
    1074: _artwork_format(1074, 50, 50, 100),
    1078: _artwork_format(1078, 80, 80, 160),
    1079: _artwork_format(1079, 80, 80, 160, usage=ArtworkUsage.PHOTO),
    1083: _artwork_format(1083, 240, 320, 480, usage=ArtworkUsage.PHOTO),
    1084: _artwork_format(1084, 240, 240, 480),
    1085: _artwork_format(1085, 88, 88, 176),
    1087: _artwork_format(1087, 384, 384, 768, usage=ArtworkUsage.PHOTO),
    1089: _artwork_format(1089, 58, 58, 116),
    1092: _artwork_format(1092, 80, 80, 160, usage=ArtworkUsage.PHOTO),
    1093: _artwork_format(1093, 512, 512, 1024, usage=ArtworkUsage.PHOTO),
}


def _artwork_formats(*format_ids: int) -> tuple[ArtworkFormat, ...]:
    return tuple(_ARTWORK_FORMATS_BY_ID[format_id] for format_id in format_ids)


_NANO_7G_COVER_FORMATS = (
    _artwork_format(1010, 240, 240, 480),
    _artwork_format(1013, 50, 50, 100),
    _artwork_format(1015, 58, 58, 116),
    _artwork_format(1016, 57, 57, 116),
)


def _capabilities(
    *,
    display: tuple[int, int, bool],
    podcasts: bool = True,
    gapless: bool = False,
    alac: bool = True,
    cover_formats: tuple[ArtworkFormat, ...] = (),
    photo_formats: tuple[ArtworkFormat, ...] = (),
    photo_album_creation_type: int = 2,
    chapter_images: bool = False,
    sparse_artwork: bool = False,
    video: tuple[int, int, int, str] | None = None,
    subtitles: bool = False,
    captions: bool = False,
    checksum: DatabaseChecksum = DatabaseChecksum.NONE,
    database_version: int = 0x13,
    music_directories: int,
    database_limit: int = _STANDARD_DATABASE_LIMIT,
    compressed_database: bool = False,
    sqlite_database: bool = False,
    sqlite_checksum: DatabaseChecksum = DatabaseChecksum.NONE,
) -> DeviceCapabilities:
    width, height, color = display
    video_capabilities = (
        VideoCapabilities(supported=False)
        if video is None
        else VideoCapabilities(
            supported=True,
            max_width=video[0],
            max_height=video[1],
            max_bitrate_kbps=video[2],
            h264_level=video[3],
            supports_tx3g_subtitles=subtitles,
            supports_cea608_captions=captions,
        )
    )
    return DeviceCapabilities(
        display=DisplayCapabilities(width=width, height=height, color=color),
        audio=AudioCapabilities(
            supports_podcasts=podcasts,
            supports_gapless_playback=gapless,
            supports_alac=alac,
        ),
        artwork=ArtworkCapabilities(
            supports_cover_art=bool(cover_formats),
            supports_photos=bool(photo_formats),
            supports_chapter_images=chapter_images,
            supports_sparse_artwork=sparse_artwork,
            cover_formats=cover_formats,
            photo_formats=photo_formats,
            # Original iOpenPod's album-art writer uses this seed without a
            # reference database. It is a compatibility policy, not a version.
            artwork_root_value=6 if cover_formats else None,
            photo_album_creation_type=(
                photo_album_creation_type if photo_formats else None
            ),
            # Original's iTunes-written Nano 2/6/7 samples retain this root value.
            photos_root_value=6 if photo_formats else None,
        ),
        video=video_capabilities,
        database=DatabaseCapabilities(
            checksum=checksum,
            binary_version=database_version,
            music_directory_count=music_directories,
            max_database_bytes=database_limit,
            supports_compressed_database=compressed_database,
            uses_sqlite_database=sqlite_database,
            sqlite_checksum=sqlite_checksum,
        ),
    )


_CLASSIC_CAPABILITIES = _capabilities(
    display=(320, 240, True),
    gapless=True,
    cover_formats=_artwork_formats(1055, 1060, 1061, 1068),
    photo_formats=_artwork_formats(1067, 1024, 1066),
    chapter_images=True,
    sparse_artwork=True,
    video=(640, 480, 2500, "3.0"),
    subtitles=True,
    captions=True,
    checksum=DatabaseChecksum.HASH58,
    database_version=0x30,
    music_directories=50,
    database_limit=_LARGE_DATABASE_LIMIT,
)
_MINI_CAPABILITIES = _capabilities(
    display=(138, 110, False),
    music_directories=6,
)

_EARLY_IPOD_CAPABILITIES = _capabilities(
    display=(160, 128, False),
    podcasts=False,
    music_directories=20,
)
_IPOD_4G_MONO_CAPABILITIES = _capabilities(
    display=(160, 128, False),
    music_directories=20,
)
_IPOD_4G_COLOR_CAPABILITIES = _capabilities(
    display=(220, 176, True),
    cover_formats=_artwork_formats(1017, 1016),
    photo_formats=_artwork_formats(1009, 1013, 1015, 1019),
    music_directories=20,
)
_IPOD_5G_CAPABILITIES = _capabilities(
    display=(320, 240, True),
    cover_formats=_artwork_formats(1028, 1029),
    photo_formats=_artwork_formats(1036, 1024, 1015, 1019),
    # Firmware-independent Baseline output; the 640x480 mode additionally needs
    # Apple's low-complexity restrictions and firmware evidence (see media policy).
    video=(320, 240, 768, "1.3"),
    database_version=0x19,
    music_directories=20,
)
_IPOD_5_5G_CAPABILITIES = replace(
    _IPOD_5G_CAPABILITIES,
    audio=replace(
        _IPOD_5G_CAPABILITIES.audio,
        supports_gapless_playback=True,
    ),
)

_CAPABILITIES_BY_IDENTITY: dict[tuple[str, str], DeviceCapabilities] = {
    ("iPod", "1st Gen"): _EARLY_IPOD_CAPABILITIES,
    ("iPod", "2nd Gen"): _EARLY_IPOD_CAPABILITIES,
    ("iPod", "3rd Gen"): _EARLY_IPOD_CAPABILITIES,
    ("iPod", "4th Gen (mono)"): _IPOD_4G_MONO_CAPABILITIES,
    ("iPod", "4th Gen (photo)"): _IPOD_4G_COLOR_CAPABILITIES,
    ("iPod", "4th Gen (color)"): _IPOD_4G_COLOR_CAPABILITIES,
    ("iPod", "5th Gen"): _IPOD_5G_CAPABILITIES,
    ("iPod", "5.5th Gen"): _IPOD_5_5G_CAPABILITIES,
    ("iPod Classic", "6th Gen"): _CLASSIC_CAPABILITIES,
    ("iPod Classic", "6.5th Gen"): _CLASSIC_CAPABILITIES,
    ("iPod Classic", "7th Gen"): _CLASSIC_CAPABILITIES,
    ("iPod Mini", "1st Gen"): _MINI_CAPABILITIES,
    ("iPod Mini", "2nd Gen"): _MINI_CAPABILITIES,
    ("iPod Nano", "1st Gen"): _capabilities(
        display=(176, 132, True),
        cover_formats=_artwork_formats(1031, 1027),
        photo_formats=_artwork_formats(1032, 1023),
        music_directories=14,
    ),
    ("iPod Nano", "2nd Gen"): _capabilities(
        display=(176, 132, True),
        cover_formats=_artwork_formats(1031, 1027),
        photo_formats=_artwork_formats(1032, 1023),
        music_directories=14,
    ),
    ("iPod Nano", "3rd Gen"): _capabilities(
        display=(320, 240, True),
        gapless=True,
        cover_formats=_artwork_formats(1061, 1055, 1068, 1060),
        photo_formats=_artwork_formats(1067, 1024, 1066),
        sparse_artwork=True,
        video=(320, 240, 768, "1.3"),
        subtitles=True,
        captions=True,
        checksum=DatabaseChecksum.HASH58,
        database_version=0x30,
        music_directories=20,
    ),
    ("iPod Nano", "4th Gen"): _capabilities(
        display=(240, 320, True),
        gapless=True,
        cover_formats=_artwork_formats(1055, 1068, 1071, 1074, 1078, 1084),
        photo_formats=_artwork_formats(1024, 1066, 1079, 1083),
        chapter_images=True,
        sparse_artwork=True,
        video=(480, 320, 768, "1.3"),
        subtitles=True,
        captions=True,
        checksum=DatabaseChecksum.HASH58,
        database_version=0x30,
        music_directories=20,
    ),
    ("iPod Nano", "5th Gen"): _capabilities(
        display=(240, 376, True),
        gapless=True,
        cover_formats=_artwork_formats(1056, 1078, 1073, 1074),
        photo_formats=_artwork_formats(1087, 1079, 1066),
        sparse_artwork=True,
        video=(640, 480, 2500, "3.0"),
        subtitles=True,
        captions=True,
        checksum=DatabaseChecksum.HASH72,
        database_version=0x30,
        music_directories=14,
        database_limit=_LARGE_DATABASE_LIMIT,
        compressed_database=True,
        sqlite_database=True,
        sqlite_checksum=DatabaseChecksum.HASH72,
    ),
    ("iPod Nano", "6th Gen"): _capabilities(
        display=(240, 240, True),
        gapless=True,
        cover_formats=_artwork_formats(1073, 1085, 1089, 1074),
        photo_formats=_artwork_formats(1092, 1093),
        photo_album_creation_type=6,
        sparse_artwork=True,
        checksum=DatabaseChecksum.HASHAB,
        database_version=0x30,
        music_directories=20,
        database_limit=_LARGE_DATABASE_LIMIT,
        compressed_database=True,
        sqlite_database=True,
        sqlite_checksum=DatabaseChecksum.HASHAB,
    ),
    ("iPod Nano", "7th Gen"): _capabilities(
        display=(240, 432, True),
        gapless=True,
        cover_formats=_NANO_7G_COVER_FORMATS,
        photo_formats=_artwork_formats(1007, 1005),
        photo_album_creation_type=6,
        sparse_artwork=True,
        # Conservative encoder ceiling, not a claimed maximum decoder bitrate.
        video=(720, 576, 2500, "3.0"),
        subtitles=True,
        captions=True,
        checksum=DatabaseChecksum.HASHAB,
        database_version=0x30,
        music_directories=20,
        database_limit=_LARGE_DATABASE_LIMIT,
        compressed_database=True,
        sqlite_database=True,
        sqlite_checksum=DatabaseChecksum.HASHAB,
    ),
}


_MODEL_ROWS: tuple[tuple[str, str, str, str, str], ...] = (
    # Full-size iPod 1st generation
    ("M8513", "iPod", "1st Gen", "5GB", "White"),
    ("M8541", "iPod", "1st Gen", "5GB", "White"),
    ("M8697", "iPod", "1st Gen", "5GB", "White"),
    ("M8709", "iPod", "1st Gen", "10GB", "White"),
    # Full-size iPod 2nd generation
    ("M8737", "iPod", "2nd Gen", "10GB", "White"),
    ("M8740", "iPod", "2nd Gen", "10GB", "White"),
    ("M8738", "iPod", "2nd Gen", "20GB", "White"),
    ("M8741", "iPod", "2nd Gen", "20GB", "White"),
    # Full-size iPod 3rd generation
    ("M8976", "iPod", "3rd Gen", "10GB", "White"),
    ("M8946", "iPod", "3rd Gen", "15GB", "White"),
    ("M8948", "iPod", "3rd Gen", "30GB", "White"),
    ("M9244", "iPod", "3rd Gen", "20GB", "White"),
    ("M9245", "iPod", "3rd Gen", "40GB", "White"),
    ("M9460", "iPod", "3rd Gen", "15GB", "White"),
    # Full-size iPod 4th generation, monochrome
    ("M9268", "iPod", "4th Gen (mono)", "40GB", "White"),
    ("M9282", "iPod", "4th Gen (mono)", "20GB", "White"),
    ("ME436", "iPod", "4th Gen (mono)", "40GB", "White"),
    ("M9787", "iPod", "4th Gen (mono)", "20GB", "U2"),
    # Full-size iPod 4th generation, photo and color-display revisions
    ("M9585", "iPod", "4th Gen (photo)", "40GB", "White"),
    ("M9586", "iPod", "4th Gen (photo)", "60GB", "White"),
    ("M9829", "iPod", "4th Gen (photo)", "30GB", "White"),
    ("M9830", "iPod", "4th Gen (photo)", "60GB", "White"),
    ("MA079", "iPod", "4th Gen (color)", "20GB", "White"),
    ("MA127", "iPod", "4th Gen (color)", "20GB", "U2"),
    ("MS492", "iPod", "4th Gen (photo)", "30GB", "White"),
    ("MA215", "iPod", "4th Gen (color)", "20GB", "White"),
    # Full-size iPod 5th generation
    ("MA002", "iPod", "5th Gen", "30GB", "White"),
    ("MA003", "iPod", "5th Gen", "60GB", "White"),
    ("MA146", "iPod", "5th Gen", "30GB", "Black"),
    ("MA147", "iPod", "5th Gen", "60GB", "Black"),
    ("MA452", "iPod", "5th Gen", "30GB", "U2"),
    # Full-size iPod 5.5th generation
    ("MA444", "iPod", "5.5th Gen", "30GB", "White"),
    ("MA446", "iPod", "5.5th Gen", "30GB", "Black"),
    ("MA448", "iPod", "5.5th Gen", "80GB", "White"),
    ("MA450", "iPod", "5.5th Gen", "80GB", "Black"),
    ("MA664", "iPod", "5.5th Gen", "30GB", "U2"),
    # iPod Classic
    ("MB029", "iPod Classic", "6th Gen", "80GB", "Silver"),
    ("MB147", "iPod Classic", "6th Gen", "80GB", "Black"),
    ("MB145", "iPod Classic", "6th Gen", "160GB", "Silver"),
    ("MB150", "iPod Classic", "6th Gen", "160GB", "Black"),
    ("MB562", "iPod Classic", "6.5th Gen", "120GB", "Silver"),
    ("MB565", "iPod Classic", "6.5th Gen", "120GB", "Black"),
    ("MC293", "iPod Classic", "7th Gen", "160GB", "Silver"),
    ("MC297", "iPod Classic", "7th Gen", "160GB", "Black"),
    # iPod Mini
    ("M9160", "iPod Mini", "1st Gen", "4GB", "Silver"),
    ("M9434", "iPod Mini", "1st Gen", "4GB", "Green"),
    ("M9435", "iPod Mini", "1st Gen", "4GB", "Pink"),
    ("M9436", "iPod Mini", "1st Gen", "4GB", "Blue"),
    ("M9437", "iPod Mini", "1st Gen", "4GB", "Gold"),
    ("M9800", "iPod Mini", "2nd Gen", "4GB", "Silver"),
    ("M9801", "iPod Mini", "2nd Gen", "6GB", "Silver"),
    ("M9802", "iPod Mini", "2nd Gen", "4GB", "Blue"),
    ("M9803", "iPod Mini", "2nd Gen", "6GB", "Blue"),
    ("M9804", "iPod Mini", "2nd Gen", "4GB", "Pink"),
    ("M9805", "iPod Mini", "2nd Gen", "6GB", "Pink"),
    ("M9806", "iPod Mini", "2nd Gen", "4GB", "Green"),
    ("M9807", "iPod Mini", "2nd Gen", "6GB", "Green"),
    # iPod Nano 1st generation
    ("MA004", "iPod Nano", "1st Gen", "2GB", "White"),
    ("MA005", "iPod Nano", "1st Gen", "4GB", "White"),
    ("MA099", "iPod Nano", "1st Gen", "2GB", "Black"),
    ("MA107", "iPod Nano", "1st Gen", "4GB", "Black"),
    ("MA350", "iPod Nano", "1st Gen", "1GB", "White"),
    ("MA352", "iPod Nano", "1st Gen", "1GB", "Black"),
    # iPod Nano 2nd generation
    ("MA426", "iPod Nano", "2nd Gen", "4GB", "Silver"),
    ("MA428", "iPod Nano", "2nd Gen", "4GB", "Blue"),
    ("MA477", "iPod Nano", "2nd Gen", "2GB", "Silver"),
    ("MA487", "iPod Nano", "2nd Gen", "4GB", "Green"),
    ("MA489", "iPod Nano", "2nd Gen", "4GB", "Pink"),
    ("MA497", "iPod Nano", "2nd Gen", "8GB", "Black"),
    ("MA725", "iPod Nano", "2nd Gen", "4GB", "Red"),
    ("MA726", "iPod Nano", "2nd Gen", "8GB", "Red"),
    ("MA899", "iPod Nano", "2nd Gen", "8GB", "Red"),
    # iPod Nano 3rd generation
    ("MA978", "iPod Nano", "3rd Gen", "4GB", "Silver"),
    ("MA980", "iPod Nano", "3rd Gen", "8GB", "Silver"),
    ("MB249", "iPod Nano", "3rd Gen", "8GB", "Blue"),
    ("MB253", "iPod Nano", "3rd Gen", "8GB", "Green"),
    ("MB257", "iPod Nano", "3rd Gen", "8GB", "Red"),
    ("MB261", "iPod Nano", "3rd Gen", "8GB", "Black"),
    ("MB453", "iPod Nano", "3rd Gen", "8GB", "Pink"),
    # iPod Nano 4th generation
    ("MB480", "iPod Nano", "4th Gen", "4GB", "Silver"),
    ("MB651", "iPod Nano", "4th Gen", "4GB", "Blue"),
    ("MB654", "iPod Nano", "4th Gen", "4GB", "Pink"),
    ("MB657", "iPod Nano", "4th Gen", "4GB", "Purple"),
    ("MB660", "iPod Nano", "4th Gen", "4GB", "Orange"),
    ("MB663", "iPod Nano", "4th Gen", "4GB", "Green"),
    ("MB666", "iPod Nano", "4th Gen", "4GB", "Yellow"),
    ("MB598", "iPod Nano", "4th Gen", "8GB", "Silver"),
    ("MB732", "iPod Nano", "4th Gen", "8GB", "Blue"),
    ("MB735", "iPod Nano", "4th Gen", "8GB", "Pink"),
    ("MB739", "iPod Nano", "4th Gen", "8GB", "Purple"),
    ("MB742", "iPod Nano", "4th Gen", "8GB", "Orange"),
    ("MB745", "iPod Nano", "4th Gen", "8GB", "Green"),
    ("MB748", "iPod Nano", "4th Gen", "8GB", "Yellow"),
    ("MB751", "iPod Nano", "4th Gen", "8GB", "Red"),
    ("MB754", "iPod Nano", "4th Gen", "8GB", "Black"),
    ("MB903", "iPod Nano", "4th Gen", "16GB", "Silver"),
    ("MB905", "iPod Nano", "4th Gen", "16GB", "Blue"),
    ("MB907", "iPod Nano", "4th Gen", "16GB", "Pink"),
    ("MB909", "iPod Nano", "4th Gen", "16GB", "Purple"),
    ("MB911", "iPod Nano", "4th Gen", "16GB", "Orange"),
    ("MB913", "iPod Nano", "4th Gen", "16GB", "Green"),
    ("MB915", "iPod Nano", "4th Gen", "16GB", "Yellow"),
    ("MB917", "iPod Nano", "4th Gen", "16GB", "Red"),
    ("MB918", "iPod Nano", "4th Gen", "16GB", "Black"),
    # iPod Nano 5th generation
    ("MC027", "iPod Nano", "5th Gen", "8GB", "Silver"),
    ("MC031", "iPod Nano", "5th Gen", "8GB", "Black"),
    ("MC034", "iPod Nano", "5th Gen", "8GB", "Purple"),
    ("MC037", "iPod Nano", "5th Gen", "8GB", "Blue"),
    ("MC040", "iPod Nano", "5th Gen", "8GB", "Green"),
    ("MC043", "iPod Nano", "5th Gen", "8GB", "Yellow"),
    ("MC046", "iPod Nano", "5th Gen", "8GB", "Orange"),
    ("MC049", "iPod Nano", "5th Gen", "8GB", "Red"),
    ("MC050", "iPod Nano", "5th Gen", "8GB", "Pink"),
    ("MC060", "iPod Nano", "5th Gen", "16GB", "Silver"),
    ("MC062", "iPod Nano", "5th Gen", "16GB", "Black"),
    ("MC064", "iPod Nano", "5th Gen", "16GB", "Purple"),
    ("MC066", "iPod Nano", "5th Gen", "16GB", "Blue"),
    ("MC068", "iPod Nano", "5th Gen", "16GB", "Green"),
    ("MC070", "iPod Nano", "5th Gen", "16GB", "Yellow"),
    ("MC072", "iPod Nano", "5th Gen", "16GB", "Orange"),
    ("MC074", "iPod Nano", "5th Gen", "16GB", "Red"),
    ("MC075", "iPod Nano", "5th Gen", "16GB", "Pink"),
    # iPod Nano 6th generation
    ("MC525", "iPod Nano", "6th Gen", "8GB", "Silver"),
    ("MC688", "iPod Nano", "6th Gen", "8GB", "Graphite"),
    ("MC689", "iPod Nano", "6th Gen", "8GB", "Blue"),
    ("MC690", "iPod Nano", "6th Gen", "8GB", "Green"),
    ("MC691", "iPod Nano", "6th Gen", "8GB", "Orange"),
    ("MC692", "iPod Nano", "6th Gen", "8GB", "Pink"),
    ("MC693", "iPod Nano", "6th Gen", "8GB", "Red"),
    ("MC526", "iPod Nano", "6th Gen", "16GB", "Silver"),
    ("MC694", "iPod Nano", "6th Gen", "16GB", "Graphite"),
    ("MC695", "iPod Nano", "6th Gen", "16GB", "Blue"),
    ("MC696", "iPod Nano", "6th Gen", "16GB", "Green"),
    ("MC697", "iPod Nano", "6th Gen", "16GB", "Orange"),
    ("MC698", "iPod Nano", "6th Gen", "16GB", "Pink"),
    ("MC699", "iPod Nano", "6th Gen", "16GB", "Red"),
    # iPod Nano 7th generation
    ("MD475", "iPod Nano", "7th Gen", "16GB", "Pink"),
    ("MD476", "iPod Nano", "7th Gen", "16GB", "Yellow"),
    ("MD477", "iPod Nano", "7th Gen", "16GB", "Blue"),
    ("MD478", "iPod Nano", "7th Gen", "16GB", "Green"),
    ("MD479", "iPod Nano", "7th Gen", "16GB", "Purple"),
    ("MD480", "iPod Nano", "7th Gen", "16GB", "Silver"),
    ("MD481", "iPod Nano", "7th Gen", "16GB", "Slate"),
    ("MD744", "iPod Nano", "7th Gen", "16GB", "Red"),
    ("ME971", "iPod Nano", "7th Gen", "16GB", "Space Gray"),
    ("MKMV2", "iPod Nano", "7th Gen", "16GB", "Pink"),
    ("MKMX2", "iPod Nano", "7th Gen", "16GB", "Gold"),
    ("MKN02", "iPod Nano", "7th Gen", "16GB", "Blue"),
    ("MKN22", "iPod Nano", "7th Gen", "16GB", "Silver"),
    ("MKN52", "iPod Nano", "7th Gen", "16GB", "Space Gray"),
    ("MKN72", "iPod Nano", "7th Gen", "16GB", "Red"),
)


_NANO_7G_PRODUCT_IMAGES: dict[str, str] = {
    "MD475": "iPod18-Pink.png",
    "MD476": "iPod18-Yellow.png",
    "MD477": "iPod18-Blue.png",
    "MD478": "iPod18-Green.png",
    "MD479": "iPod18-Purple.png",
    "MD480": "iPod18-Silver.png",
    "MD481": "iPod18-DarkGray.png",
    "MD744": "iPod18-Red.png",
    "ME971": "iPod18-SpaceGray.png",
    "MKMV2": "iPod18A-Pink.png",
    "MKMX2": "iPod18A-Gold.png",
    "MKN02": "iPod18A-Blue.png",
    "MKN22": "iPod18A-Silver.png",
    "MKN52": "iPod18A-SpaceGray.png",
    "MKN72": "iPod18A-Red.png",
}

_FULL_SIZE_PRODUCT_IMAGES: dict[tuple[str, str], str] = {
    ("1st Gen", "White"): "iPod1.png",
    ("2nd Gen", "White"): "iPod1.png",
    ("3rd Gen", "White"): "iPod2.png",
    ("4th Gen (mono)", "White"): "iPod4-White.png",
    ("4th Gen (mono)", "U2"): "iPod4-BlackRed.png",
    ("4th Gen (photo)", "White"): "iPod5-White.png",
    ("4th Gen (color)", "White"): "iPod5-White.png",
    ("4th Gen (color)", "U2"): "iPod5-BlackRed.png",
    ("5th Gen", "White"): "iPod6-White.png",
    ("5th Gen", "Black"): "iPod6-Black.png",
    ("5th Gen", "U2"): "iPod6-BlackRed.png",
    ("5.5th Gen", "White"): "iPod6-White.png",
    ("5.5th Gen", "Black"): "iPod6-Black.png",
    ("5.5th Gen", "U2"): "iPod6-BlackRed.png",
}


def _product_image(
    model_number: str,
    family: str,
    generation: str,
    finish: str,
) -> str:
    if family == "iPod":
        return _FULL_SIZE_PRODUCT_IMAGES[(generation, finish)]
    if family == "iPod Classic":
        if finish == "Silver":
            return "iPod11-Silver.png"
        return "iPod11-Black.png" if generation == "6th Gen" else "iPod11B-Black.png"
    if family == "iPod Mini":
        if generation == "1st Gen" or finish == "Silver":
            return f"iPod3-{finish}.png"
        return f"iPod3B-{finish}.png"
    if family == "iPod Nano":
        if generation == "7th Gen":
            return _NANO_7G_PRODUCT_IMAGES[model_number]
        prefix = {
            "1st Gen": "iPod7",
            "2nd Gen": "iPod9",
            "3rd Gen": "iPod12",
            "4th Gen": "iPod15",
            "5th Gen": "iPod16",
            "6th Gen": "iPod17",
        }[generation]
        image_finish = "DarkGray" if finish == "Graphite" else finish
        return f"{prefix}-{image_finish}.png"
    raise ValueError(f"No product image mapping for {family} {generation}")


def _profiles() -> tuple[DeviceProfile, ...]:
    result: list[DeviceProfile] = []
    for model_number, family, generation, capacity, finish in _MODEL_ROWS:
        result.append(
            DeviceProfile(
                model_number=model_number,
                family=family,
                generation=generation,
                advertised_capacity=capacity,
                finish=finish,
                product_image=_product_image(
                    model_number,
                    family,
                    generation,
                    finish,
                ),
                storage_technology=(
                    StorageTechnology.FLASH
                    if family == "iPod Nano"
                    else StorageTechnology.HARD_DISK
                ),
                capabilities=_profile_capabilities(
                    model_number,
                    family,
                    generation,
                    capacity,
                ),
            )
        )
    return tuple(result)


def _profile_capabilities(
    model_number: str,
    family: str,
    generation: str,
    capacity: str,
) -> DeviceCapabilities:
    capabilities = _CAPABILITIES_BY_IDENTITY[(family, generation)]
    if family != "iPod" or generation not in {"5th Gen", "5.5th Gen"}:
        return capabilities
    high_memory = capacity in {"60GB", "80GB"} or model_number in {
        "MA003",
        "MA147",
        "MA448",
        "MA450",
    }
    if not high_memory:
        return capabilities
    return replace(
        capabilities,
        database=replace(
            capabilities.database,
            max_database_bytes=_LARGE_DATABASE_LIMIT,
        ),
    )


def _suffixes(mapping: dict[str, str]) -> tuple[SerialSuffixDefinition, ...]:
    return tuple(
        SerialSuffixDefinition(suffix=suffix, model_number=model_number)
        for suffix, model_number in mapping.items()
    )


_SERIAL_SUFFIXES = _suffixes(
    {
        # iPod Classic
        "Y5N": "MB029",
        "YMV": "MB147",
        "YMU": "MB145",
        "YMX": "MB150",
        "2C5": "MB562",
        "2C7": "MB565",
        "9ZS": "MC293",
        "9ZU": "MC297",
        # Full-size iPod 1st generation
        "LG6": "M8541",
        "NAM": "M8541",
        "MJ2": "M8541",
        "ML1": "M8709",
        "MME": "M8709",
        # Full-size iPod 2nd generation
        "MMB": "M8737",
        "MMC": "M8738",
        "NGE": "M8740",
        "NGH": "M8740",
        "MMF": "M8741",
        # Full-size iPod 3rd generation
        "NLW": "M8946",
        "NRH": "M8976",
        "QQF": "M9460",
        "PQ5": "M9244",
        "PNT": "M9244",
        "NLY": "M8948",
        "NM7": "M8948",
        "PNU": "M9245",
        # Full-size iPod 4th generation
        "PS9": "M9282",
        "Q8U": "M9282",
        "PQ7": "M9268",
        "S2X": "M9787",
        "TDU": "MA079",
        "TDS": "MA079",
        "TM2": "MA127",
        "U5H": "MA215",
        "SAZ": "M9830",
        "SB1": "M9830",
        "SAY": "M9829",
        "R5Q": "M9585",
        "R5R": "M9586",
        "R5T": "M9586",
        # Full-size iPod 5th generation
        "SZ9": "MA002",
        "WEC": "MA002",
        "WED": "MA002",
        "WEG": "MA002",
        "WEH": "MA002",
        "WEL": "MA002",
        "TXK": "MA146",
        "TXM": "MA146",
        "WEF": "MA146",
        "WEJ": "MA146",
        "WEK": "MA146",
        "SZA": "MA003",
        "SZU": "MA003",
        "TXL": "MA147",
        "TXN": "MA147",
        "V9V": "MA452",
        # Full-size iPod 5.5th generation
        "V9K": "MA444",
        "V9L": "MA444",
        "WU9": "MA444",
        "VQM": "MA446",
        "V9M": "MA446",
        "V9N": "MA446",
        "WEE": "MA446",
        "V9P": "MA448",
        "V9Q": "MA448",
        "V9R": "MA450",
        "V9S": "MA450",
        "V95": "MA450",
        "V96": "MA450",
        "WUC": "MA450",
        "W9G": "MA664",
        "WEM": "MA664",
        # iPod Mini 1st generation
        "PFW": "M9160",
        "PRC": "M9160",
        "QKL": "M9436",
        "QKQ": "M9436",
        "QKK": "M9435",
        "QKP": "M9435",
        "QKJ": "M9434",
        "QKN": "M9434",
        "QKM": "M9437",
        "QKR": "M9437",
        # iPod Mini 2nd generation
        "S41": "M9800",
        "S4C": "M9800",
        "S43": "M9802",
        "S45": "M9804",
        "S4G": "M9805",
        "S4H": "M9805",
        "S47": "M9806",
        "S4J": "M9806",
        "S42": "M9801",
        "S44": "M9803",
        "S48": "M9807",
        # iPod Nano 1st generation
        "TUZ": "MA004",
        "TV0": "MA005",
        "TUY": "MA099",
        "TV1": "MA107",
        "UYN": "MA350",
        "UYP": "MA352",
        "UNA": "MA350",
        "UNB": "MA350",
        "UPR": "MA352",
        "UPS": "MA352",
        "SZB": "MA004",
        "SZV": "MA004",
        "SZW": "MA004",
        "SZC": "MA005",
        "SZT": "MA005",
        "TJT": "MA099",
        "TJU": "MA099",
        "TK2": "MA107",
        "TK3": "MA107",
        # iPod Nano 2nd generation
        "VQ5": "MA477",
        "VQ6": "MA477",
        "V8T": "MA426",
        "V8U": "MA426",
        "V8W": "MA428",
        "V8X": "MA428",
        "VQH": "MA487",
        "VQJ": "MA487",
        "VQK": "MA489",
        "VQL": "MA489",
        "VKL": "MA489",
        "WL2": "MA725",
        "WL3": "MA725",
        "X9A": "MA726",
        "X9B": "MA726",
        "VQT": "MA497",
        "VQU": "MA497",
        "YER": "MA899",
        "YES": "MA899",
        # iPod Nano 3rd generation
        "Y0P": "MA978",
        "Y0R": "MA980",
        "YXR": "MB249",
        "YXV": "MB257",
        "YXT": "MB253",
        "YXX": "MB261",
        "13F": "MB453",
        # iPod Nano 4th generation
        "37P": "MB663",
        "37Q": "MB666",
        "37G": "MB651",
        "37H": "MB654",
        "1P1": "MB480",
        "37K": "MB657",
        "37L": "MB660",
        "2ME": "MB598",
        "3QS": "MB732",
        "3QT": "MB735",
        "3QU": "MB739",
        "3QW": "MB742",
        "3QX": "MB745",
        "3QY": "MB748",
        "3R0": "MB754",
        "3QZ": "MB751",
        "5B7": "MB903",
        "5B8": "MB905",
        "5B9": "MB907",
        "5BA": "MB909",
        "5BB": "MB911",
        "5BC": "MB913",
        "5BD": "MB915",
        "5BE": "MB917",
        "5BF": "MB918",
        # iPod Nano 5th generation
        "71V": "MC027",
        "71Y": "MC031",
        "721": "MC034",
        "726": "MC037",
        "72A": "MC040",
        "72D": "MC043",
        "72F": "MC046",
        "72K": "MC049",
        "72L": "MC050",
        "72Q": "MC060",
        "72R": "MC062",
        "72S": "MC064",
        "72X": "MC066",
        "734": "MC068",
        "738": "MC070",
        "739": "MC072",
        "73A": "MC074",
        "73B": "MC075",
        # iPod Nano 6th generation
        "DCMN": "MC525",
        "DCMP": "MC526",
        "DDVX": "MC688",
        "DDVY": "MC689",
        "DDW0": "MC690",
        "DDW1": "MC691",
        "DDW2": "MC692",
        "DDW3": "MC693",
        "DDW4": "MC694",
        "DDW5": "MC695",
        "DDW6": "MC696",
        "DDW7": "MC697",
        "DDW8": "MC698",
        "DDW9": "MC699",
        # iPod Nano 7th generation; longest suffix is matched first.
        "F0GD": "MD475",
        "F0GM": "MD475",
        "F0GF": "MD476",
        "F0GN": "MD476",
        "F0GG": "MD477",
        "F0GP": "MD477",
        "F0GH": "MD478",
        "F0GQ": "MD478",
        "F0GJ": "MD479",
        "F0GR": "MD479",
        "F0GK": "MD480",
        "F0GT": "MD480",
        "F0GL": "MD481",
        "F0GV": "MD481",
        "F4LN": "MD744",
        "F4LP": "MD744",
        "FJQ1": "ME971",
        "GK60": "MKMV2",
        "GK61": "MKMX2",
        "GK62": "MKN02",
        "GK63": "MKN22",
        "GK64": "MKN52",
        "GK65": "MKN72",
    }
)


def _identity(family: str, generation: str) -> ModelIdentity:
    return ModelIdentity(family=family, generation=generation)


_CLASSIC_IDENTITIES = tuple(
    _identity("iPod Classic", generation)
    for generation in ("6th Gen", "6.5th Gen", "7th Gen")
)
_IPOD_1G_2G_IDENTITIES = tuple(
    _identity("iPod", generation) for generation in ("1st Gen", "2nd Gen")
)
_IPOD_4G_COLOR_IDENTITIES = tuple(
    _identity("iPod", generation)
    for generation in ("4th Gen (photo)", "4th Gen (color)")
)
_IPOD_5G_IDENTITIES = tuple(
    _identity("iPod", generation) for generation in ("5th Gen", "5.5th Gen")
)
_FULL_SIZE_IPOD_IDENTITIES = tuple(
    _identity("iPod", generation)
    for generation in (
        "1st Gen",
        "2nd Gen",
        "3rd Gen",
        "4th Gen (mono)",
        "4th Gen (photo)",
        "4th Gen (color)",
        "5th Gen",
        "5.5th Gen",
    )
)
_MINI_IDENTITIES = tuple(
    _identity("iPod Mini", generation) for generation in ("1st Gen", "2nd Gen")
)


def _usb_product(
    product_id: int,
    mode: ConnectionMode,
    *identities: ModelIdentity,
) -> UsbProductDefinition:
    return UsbProductDefinition(
        identifier=UsbIdentifier(vendor_id=0x05AC, product_id=product_id),
        mode=mode,
        candidate_identities=identities,
    )


_USB_PRODUCTS = (
    _usb_product(
        0x1201,
        ConnectionMode.NORMAL,
        _identity("iPod", "3rd Gen"),
    ),
    _usb_product(0x1202, ConnectionMode.NORMAL, *_IPOD_1G_2G_IDENTITIES),
    _usb_product(
        0x1203,
        ConnectionMode.NORMAL,
        _identity("iPod", "4th Gen (mono)"),
    ),
    _usb_product(0x1204, ConnectionMode.NORMAL, *_IPOD_4G_COLOR_IDENTITIES),
    _usb_product(0x1205, ConnectionMode.NORMAL, *_MINI_IDENTITIES),
    _usb_product(0x1206, ConnectionMode.NORMAL, *_FULL_SIZE_IPOD_IDENTITIES),
    _usb_product(0x1207, ConnectionMode.NORMAL, *_FULL_SIZE_IPOD_IDENTITIES),
    _usb_product(0x1208, ConnectionMode.NORMAL, *_FULL_SIZE_IPOD_IDENTITIES),
    _usb_product(0x1209, ConnectionMode.NORMAL, *_IPOD_5G_IDENTITIES),
    _usb_product(
        0x120A,
        ConnectionMode.NORMAL,
        _identity("iPod Nano", "1st Gen"),
    ),
    _usb_product(
        0x1260,
        ConnectionMode.NORMAL,
        _identity("iPod Nano", "2nd Gen"),
    ),
    _usb_product(0x1261, ConnectionMode.NORMAL, *_CLASSIC_IDENTITIES),
    _usb_product(
        0x1262,
        ConnectionMode.NORMAL,
        _identity("iPod Nano", "3rd Gen"),
    ),
    _usb_product(
        0x1263,
        ConnectionMode.NORMAL,
        _identity("iPod Nano", "4th Gen"),
    ),
    _usb_product(
        0x1265,
        ConnectionMode.NORMAL,
        _identity("iPod Nano", "5th Gen"),
    ),
    _usb_product(
        0x1266,
        ConnectionMode.NORMAL,
        _identity("iPod Nano", "6th Gen"),
    ),
    _usb_product(
        0x1267,
        ConnectionMode.NORMAL,
        _identity("iPod Nano", "7th Gen"),
    ),
    _usb_product(
        0x1220,
        ConnectionMode.RECOVERY,
        _identity("iPod Nano", "2nd Gen"),
    ),
    _usb_product(
        0x1223,
        ConnectionMode.RECOVERY,
        *_CLASSIC_IDENTITIES,
        _identity("iPod Nano", "3rd Gen"),
    ),
    _usb_product(
        0x1224,
        ConnectionMode.RECOVERY,
        _identity("iPod Nano", "3rd Gen"),
    ),
    _usb_product(
        0x1225,
        ConnectionMode.RECOVERY,
        _identity("iPod Nano", "4th Gen"),
    ),
    _usb_product(
        0x1231,
        ConnectionMode.RECOVERY,
        _identity("iPod Nano", "5th Gen"),
    ),
    _usb_product(
        0x1232,
        ConnectionMode.RECOVERY,
        _identity("iPod Nano", "6th Gen"),
    ),
    _usb_product(
        0x1234,
        ConnectionMode.RECOVERY,
        _identity("iPod Nano", "7th Gen"),
    ),
    _usb_product(
        0x1240,
        ConnectionMode.RECOVERY,
        _identity("iPod Nano", "2nd Gen"),
    ),
    _usb_product(
        0x1241,
        ConnectionMode.RECOVERY,
        _identity("iPod Classic", "6th Gen"),
    ),
    _usb_product(
        0x1242,
        ConnectionMode.RECOVERY,
        _identity("iPod Nano", "3rd Gen"),
    ),
    _usb_product(
        0x1243,
        ConnectionMode.RECOVERY,
        _identity("iPod Nano", "4th Gen"),
    ),
    _usb_product(
        0x1245,
        ConnectionMode.RECOVERY,
        _identity("iPod Classic", "6.5th Gen"),
    ),
    _usb_product(
        0x1246,
        ConnectionMode.RECOVERY,
        _identity("iPod Nano", "5th Gen"),
    ),
    _usb_product(
        0x1247,
        ConnectionMode.RECOVERY,
        _identity("iPod Classic", "7th Gen"),
    ),
    _usb_product(
        0x1248,
        ConnectionMode.RECOVERY,
        _identity("iPod Nano", "6th Gen"),
    ),
    _usb_product(
        0x1249,
        ConnectionMode.RECOVERY,
        _identity("iPod Nano", "7th Gen"),
    ),
    _usb_product(
        0x124A,
        ConnectionMode.RECOVERY,
        _identity("iPod Nano", "7th Gen"),
    ),
    _usb_product(
        0x1255,
        ConnectionMode.RECOVERY,
        _identity("iPod Nano", "4th Gen"),
    ),
)

DEFAULT_CATALOG = RegistryCatalog(
    profiles=_profiles(),
    serial_suffixes=_SERIAL_SUFFIXES,
    usb_products=_USB_PRODUCTS,
)
