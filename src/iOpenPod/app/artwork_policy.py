"""Application-only album artwork policy for every supported iPod."""

from __future__ import annotations

from PIL import Image, ImageOps

from device_registry import (
    ArtworkFormat,
    ArtworkPixelFormat,
    ArtworkUsage,
    DeviceProfile,
)
from iPodDB.library import ArtworkPixels, CoverFormat, CoverPixelFormat

APPLICATION_ARTWORK_ROOT_VALUE = 2
ROCKBOX_NON_NATIVE_ARTWORK_PX = 120

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


def rockbox_artwork(profile: DeviceProfile, pixels: ArtworkPixels) -> ArtworkPixels:
    """Prepare a compact Rockbox cover for profiles without native artwork."""

    if profile.capabilities.artwork.supports_cover_art:
        return pixels
    with Image.frombytes("RGB", (pixels.width, pixels.height), pixels.rgb888) as image:
        image.thumbnail(
            (ROCKBOX_NON_NATIVE_ARTWORK_PX, ROCKBOX_NON_NATIVE_ARTWORK_PX),
            Image.Resampling.LANCZOS,
        )
        grayscale = ImageOps.grayscale(image).convert("RGB")
        try:
            return ArtworkPixels(grayscale.width, grayscale.height, grayscale.tobytes())
        finally:
            grayscale.close()


__all__ = [
    "APPLICATION_ARTWORK_ROOT_VALUE",
    "ROCKBOX_NON_NATIVE_ARTWORK_PX",
    "application_artwork_formats",
    "application_artwork_root_value",
    "application_cover_formats",
    "rockbox_artwork",
]
