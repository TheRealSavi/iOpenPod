"""Path-free Photo decoding with Pillow's limits and bounded working rasters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image, ImageOps

if TYPE_CHECKING:
    from typing import BinaryIO


def photo_source_size(source: BinaryIO) -> tuple[int, int]:
    """Inspect encoded dimensions without changing Pillow's pixel limits."""
    with Image.open(source) as image:
        return image.size


def photo_viewing_image(source: BinaryIO, target_size: tuple[int, int]) -> Image.Image:
    """Return owned RGB pixels, reducing before orientation and color copies.

    JPEG can shrink during decoding through ``thumbnail``'s draft path. Other
    decoders may still allocate one source raster, governed by Pillow's unchanged
    decompression-bomb limits. Only the reduced raster is transposed and converted.
    """
    if min(target_size) <= 0:
        raise ValueError("Photo viewing dimensions must be positive.")
    with Image.open(source) as opened:
        opened.seek(0)
        orientation = opened.getexif().get(274)
        bounds = (
            (target_size[1], target_size[0])
            if orientation in (5, 6, 7, 8)
            else target_size
        )
        opened.thumbnail(bounds, Image.Resampling.LANCZOS, reducing_gap=3.0)
        with ImageOps.exif_transpose(opened) as oriented:
            return oriented.convert("RGB")
