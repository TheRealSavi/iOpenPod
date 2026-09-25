"""Shared semantic-to-native conversions for iTunesDB projections."""

import math

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
    MEDIA_TYPE_VIDEO,
    MEDIA_TYPE_VIDEO_PODCAST,
)
from iPodDB.library.models import MediaType

_MEDIA_TYPE_CODES = {
    MediaType.AUDIO_VIDEO: MEDIA_TYPE_AUDIO_VIDEO,
    MediaType.AUDIO: MEDIA_TYPE_AUDIO,
    MediaType.VIDEO: MEDIA_TYPE_VIDEO,
    MediaType.PODCAST: MEDIA_TYPE_PODCAST,
    MediaType.VIDEO_PODCAST: MEDIA_TYPE_VIDEO_PODCAST,
    MediaType.AUDIOBOOK: MEDIA_TYPE_AUDIOBOOK,
    MediaType.MUSIC_VIDEO: MEDIA_TYPE_MUSIC_VIDEO,
    MediaType.TV_SHOW: MEDIA_TYPE_TV_SHOW,
    MediaType.RINGTONE: MEDIA_TYPE_RINGTONE,
    MediaType.RENTAL: MEDIA_TYPE_RENTAL,
    MediaType.ITUNES_EXTRA: MEDIA_TYPE_ITUNES_EXTRA,
    MediaType.MEMO: MEDIA_TYPE_MEMO,
    MediaType.ITUNES_U: MEDIA_TYPE_ITUNES_U,
    MediaType.EPUB_BOOK: MEDIA_TYPE_EPUB_BOOK,
    MediaType.PDF_BOOK: MEDIA_TYPE_PDF_BOOK,
}


def encode_media_types(
    media_types: tuple[MediaType, ...], *, retained_unknown_bits: int = 0
) -> int:
    """Encode semantic media classifications as the native MHIT bitmask."""

    result = retained_unknown_bits
    for media_type in media_types:
        result |= _MEDIA_TYPE_CODES[media_type]
    return result


def volume_adjustment_to_native(value: float) -> int:
    """Convert percentage points to the signed 255-based MHIT value."""

    return round(value * 255 / 100)


def normalization_gain_to_native(value: float | None) -> int:
    """Convert decibels to the inverse logarithmic Sound Check energy value."""

    encoded = 0 if value is None else round(1000 * 10 ** (-value / 10))
    if value is not None and not 0 < encoded <= 0xFFFFFFFF:
        raise ValueError("Normalization gain is outside the representable range.")
    return encoded


def normalization_gain_from_native(value: int) -> float | None:
    """Convert native Sound Check energy to semantic decibels."""

    return 10 * math.log10(1000.0 / value) if value > 0 else None
