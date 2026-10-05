"""Application-only album artwork policy for every supported iPod."""

from __future__ import annotations

from device_registry import (
    ArtworkFormat,
    ArtworkPixelFormat,
    ArtworkUsage,
    DeviceProfile,
)
from iPodDB.library import CoverFormat, CoverPixelFormat

APPLICATION_ARTWORK_ROOT_VALUE = 2

_APPLICATION_COVER_FORMAT = ArtworkFormat(
    format_id=1060,
    width=320,
    height=320,
    row_bytes=640,
    pixel_format=ArtworkPixelFormat.RGB565_LE,
    usage=ArtworkUsage.COVER,
)


def application_artwork_formats(
    profile: DeviceProfile,
) -> tuple[ArtworkFormat, ...]:
    """Return native layouts or the iOpenPod-only display layout."""

    native = profile.capabilities.artwork.cover_formats
    return native or (_APPLICATION_COVER_FORMAT,)


def application_cover_formats(profile: DeviceProfile) -> tuple[CoverFormat, ...]:
    """Translate application artwork layouts into iPodDB write layouts."""

    return tuple(
        CoverFormat(
            artwork_format.format_id,
            artwork_format.width,
            artwork_format.height,
            artwork_format.row_bytes,
            CoverPixelFormat(artwork_format.pixel_format.value),
        )
        for artwork_format in application_artwork_formats(profile)
    )


def application_artwork_root_value(profile: DeviceProfile) -> int:
    """Return the retained-or-created ArtworkDB root policy for the app."""

    native = profile.capabilities.artwork
    return native.artwork_root_value or APPLICATION_ARTWORK_ROOT_VALUE


__all__ = [
    "APPLICATION_ARTWORK_ROOT_VALUE",
    "application_artwork_formats",
    "application_artwork_root_value",
    "application_cover_formats",
]
