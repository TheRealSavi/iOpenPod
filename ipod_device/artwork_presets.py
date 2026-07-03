"""Canonical ithmb artwork format definitions.

Sources:
  - libgpod ``src/itdb_device.c`` fallback artwork tables
  - Keith's photo database reader README (model/prefix cross-checks)
  - cyianor/ithmbrdr README (1067 photo payload confirmation)
  - local iTunes-authored Nano 7G artwork dump (F1010/F1013/F1015/F1016)

The global registry below is the default source of truth for artwork IDs.
Only a very small number of device families are known to reinterpret IDs,
so those conflicts are modeled as explicit overrides rather than treating
the whole ID space as device-specific.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ArtworkFormat:
    """One ithmb artwork format definition."""

    format_id: int
    width: int
    height: int
    row_bytes: int
    pixel_format: str = "RGB565_LE"
    role: str = "cover"
    description: str = ""


ARTWORK_FORMATS_BY_ID: dict[int, ArtworkFormat] = {
    # iPod 4G photo/color and 5G era
    1005: ArtworkFormat(1005, 80, 80, 160, "RGB565_LE", "photo_thumb", "Nano 7G photo thumbnail"),
    1007: ArtworkFormat(1007, 480, 864, 960, "RGB565_LE", "photo_full", "Nano 7G photo full screen"),
    1009: ArtworkFormat(1009, 42, 30, 84, "RGB565_LE", "photo_list", "Photo list thumbnail"),
    1010: ArtworkFormat(1010, 240, 240, 480, "RGB565_LE", "cover_large", "Nano 7G album art large"),
    1013: ArtworkFormat(1013, 220, 176, 440, "RGB565_BE_90", "photo_full", "Photo full screen (rotated)"),
    1015: ArtworkFormat(1015, 130, 88, 260, "RGB565_LE", "photo_preview", "iPod 4G/5G preview"),
    1016: ArtworkFormat(1016, 140, 140, 280, "RGB565_LE", "cover_large", "iPod 4G photo/color album art large"),
    1017: ArtworkFormat(1017, 56, 56, 112, "RGB565_LE", "cover_small", "iPod 4G photo/color album art small"),
    1019: ArtworkFormat(1019, 720, 480, 1440, "UYVY", "tv_out", "iPod 4G/5G NTSC TV output"),
    # Compatibility alias preserved from existing Apple databases.
    1020: ArtworkFormat(1020, 220, 176, 440, "RGB565_BE_90", "photo_full", "Photo full screen (alt rotated)"),
    1023: ArtworkFormat(1023, 176, 132, 352, "RGB565_BE", "photo_full", "Nano full screen"),
    1024: ArtworkFormat(1024, 320, 240, 640, "RGB565_LE", "photo_full", "320x240 photo full screen"),
    1027: ArtworkFormat(1027, 100, 100, 200, "RGB565_LE", "cover_large", "Nano album art large"),
    1028: ArtworkFormat(1028, 100, 100, 200, "RGB565_LE", "cover_small", "iPod 5G album art small"),
    1029: ArtworkFormat(1029, 200, 200, 400, "RGB565_LE", "cover_large", "iPod 5G album art large"),
    1031: ArtworkFormat(1031, 42, 42, 84, "RGB565_LE", "cover_small", "Nano album art small"),
    1032: ArtworkFormat(1032, 42, 37, 84, "RGB565_LE", "photo_list", "Nano list thumbnail"),
    1036: ArtworkFormat(1036, 50, 41, 100, "RGB565_LE", "photo_list", "Video list thumbnail"),
    # Classic / later click-wheel iPods
    # Compatibility alias preserved from existing Apple databases.
    1044: ArtworkFormat(1044, 128, 128, 256, "RGB565_LE", "cover_medium", "Classic album art medium"),
    1055: ArtworkFormat(1055, 128, 128, 256, "RGB565_LE", "cover_medium", "Classic album art medium"),
    1056: ArtworkFormat(1056, 128, 128, 256, "RGB565_LE", "cover_medium_alt", "128x128 cover art (alternate)"),
    1060: ArtworkFormat(1060, 320, 320, 640, "RGB565_LE", "cover_large", "Classic album art large"),
    1061: ArtworkFormat(1061, 56, 56, 112, "RGB565_LE", "cover_small", "Classic album art small"),
    1066: ArtworkFormat(1066, 64, 64, 128, "RGB565_LE", "photo_thumb", "Classic photo thumbnail"),
    1067: ArtworkFormat(1067, 720, 480, 1080, "I420_LE", "tv_out", "Classic TV output (YUV)"),
    1068: ArtworkFormat(1068, 128, 128, 256, "RGB565_LE", "cover_medium_alt", "Classic album art medium (alt 2)"),
    1071: ArtworkFormat(1071, 240, 240, 480, "RGB565_LE", "cover_large", "Nano 4G album art large"),
    1073: ArtworkFormat(1073, 240, 240, 480, "RGB565_LE", "cover_large", "Nano 5G/6G album art large"),
    1074: ArtworkFormat(1074, 50, 50, 100, "RGB565_LE", "cover_xsmall", "Nano album art tiny"),
    1078: ArtworkFormat(1078, 80, 80, 160, "RGB565_LE", "cover_small", "Nano 4G/5G album art small"),
    1079: ArtworkFormat(1079, 80, 80, 160, "RGB565_LE", "photo_thumb", "Nano 4G/5G photo thumbnail"),
    1081: ArtworkFormat(1081, 640, 480, 0, "JPEG", "photo_full", "JPEG photo format (experimental/legacy)"),
    1083: ArtworkFormat(1083, 240, 320, 480, "RGB565_LE", "photo_full", "Nano 4G photo full screen (portrait)"),
    1084: ArtworkFormat(1084, 240, 240, 480, "RGB565_LE", "cover_large_alt", "Nano 4G album art (alt)"),
    # Newer iPod-only formats beyond libgpod's older hardcoded tables.
    1085: ArtworkFormat(1085, 88, 88, 176, "RGB565_LE", "cover_medium", "Nano 6G album art medium"),
    1087: ArtworkFormat(1087, 384, 384, 768, "RGB565_LE", "photo_large", "Nano 5G photo large"),
    1089: ArtworkFormat(1089, 58, 58, 116, "RGB565_LE", "cover_small", "Nano 6G album art small"),
    1092: ArtworkFormat(1092, 80, 80, 160, "RGB565_LE", "photo_thumb", "Nano 6G photo thumbnail"),
    1093: ArtworkFormat(1093, 512, 512, 1024, "RGB565_LE", "photo_full", "Nano 6G photo full screen"),
    # Mobile / touch-era formats
    2002: ArtworkFormat(2002, 50, 50, 100, "RGB565_BE", "cover_small", "iPod Mobile cover art small"),
    2003: ArtworkFormat(2003, 150, 150, 300, "RGB565_BE", "cover_large", "iPod Mobile cover art large"),
    3001: ArtworkFormat(3001, 256, 256, 512, "REC_RGB555_LE", "cover_large", "iPod touch cover art large"),
    3002: ArtworkFormat(3002, 128, 128, 256, "REC_RGB555_LE", "cover_medium", "iPod touch cover art medium"),
    3003: ArtworkFormat(3003, 64, 64, 128, "REC_RGB555_LE", "cover_small", "iPod touch cover art small"),
    3005: ArtworkFormat(3005, 320, 320, 640, "RGB555_LE", "cover_xlarge", "iPod touch cover art xlarge"),
}


CLASSIC_COVER_ART_FORMATS = (
    ARTWORK_FORMATS_BY_ID[1055],
    ARTWORK_FORMATS_BY_ID[1060],
    ARTWORK_FORMATS_BY_ID[1061],
    ARTWORK_FORMATS_BY_ID[1068],
)
"""Cover-art formats used by click-wheel iPod Classic generations."""


NANO_7G_COVER_ART_OVERRIDES = (
    ARTWORK_FORMATS_BY_ID[1010],
    ArtworkFormat(1013, 50, 50, 100, "RGB565_LE", "cover_xsmall", "Nano 7G album art tiny"),
    ArtworkFormat(1015, 58, 58, 116, "RGB565_LE", "cover_small", "Nano 7G album art small"),
    ArtworkFormat(1016, 57, 57, 116, "RGB565_LE", "cover_small_alt", "Nano 7G album art small (aligned)"),
)
"""Known Nano 7G overrides for a few globally-defined artwork IDs."""


# Backward-compatible alias used by capability tables and existing imports.
NANO_7G_COVER_ART_FORMATS = NANO_7G_COVER_ART_OVERRIDES


def artwork_format_candidates() -> tuple[ArtworkFormat, ...]:
    """Return the global registry plus the small set of known override variants."""
    candidates = [
        *ARTWORK_FORMATS_BY_ID.values(),
        *CLASSIC_COVER_ART_FORMATS,
        *NANO_7G_COVER_ART_OVERRIDES,
    ]
    unique: dict[tuple[int, int, int, str], ArtworkFormat] = {}
    for fmt in candidates:
        key = (fmt.format_id, fmt.width, fmt.height, fmt.pixel_format)
        unique.setdefault(key, fmt)
    return tuple(unique.values())
