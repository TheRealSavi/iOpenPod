"""Decode publisher-sized PNGs without keeping multiple full-size rasters."""

from __future__ import annotations

from contextlib import closing, contextmanager
from io import BytesIO
from struct import unpack_from
from threading import Lock
from typing import TYPE_CHECKING

from PIL import Image, PngImagePlugin

from iOpenPod.app.podcasts.errors import PodcastFeedError

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

_PNG_IHDR = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
SYNC_COVER_PIXEL_LIMIT = 32 * 1024 * 1024
_LARGE_PNG_EDGE_LIMIT = 16_384
# Allow the 12,500px publisher originals with at most one ~610 MiB source raster.
_LARGE_PNG_PIXEL_LIMIT = 160_000_000
_large_png_lock = Lock()


def open_embedded_podcast_image(stream: BytesIO) -> Image.Image:
    """Open the image header for verification without allocating a raster."""
    header = stream.read(24)
    stream.seek(0)
    size = _large_png_size(header, SYNC_COVER_PIXEL_LIMIT)
    return Image.open(stream) if size is None else _open_large_png(stream, size)


@contextmanager
def open_podcast_image(
    payload: bytes,
    target_px: int,
    *,
    pixel_limit: int,
    checkpoint: Callable[[], None] | None,
) -> Generator[Image.Image, None, None]:
    with BytesIO(payload) as stream:
        size = _large_png_size(payload, pixel_limit)
        if size is not None:
            with closing(
                _reduce_large_png(stream, size, target_px, checkpoint)
            ) as image:
                yield image
            return
        try:
            with Image.open(stream) as image:
                yield image
        except Image.DecompressionBombError as error:
            raise PodcastFeedError(
                "The Podcast artwork dimensions are unsafe"
            ) from error


def _large_png_size(payload: bytes, pixel_limit: int) -> tuple[int, int] | None:
    if len(payload) < 24 or not payload.startswith(_PNG_IHDR):
        return None
    width, height = unpack_from(">II", payload, 16)
    pixels = width * height
    if pixels <= pixel_limit:
        return None
    if max(width, height) > _LARGE_PNG_EDGE_LIMIT or pixels > _LARGE_PNG_PIXEL_LIMIT:
        raise PodcastFeedError("The Podcast artwork dimensions are unsafe")
    return width, height


def _open_large_png(stream: BytesIO, size: tuple[int, int]) -> Image.Image:
    # Choose the PNG decoder after checking IHDR, without altering Pillow's
    # process-wide decompression-bomb settings. Reject APNG's extra rasters.
    image = PngImagePlugin.PngImageFile(stream)
    if image.size != size or image.get_format_mimetype() != "image/png":
        image.close()
        raise PodcastFeedError("The Podcast artwork could not be decoded")
    return image


def _reduce_large_png(
    stream: BytesIO,
    size: tuple[int, int],
    target_px: int,
    checkpoint: Callable[[], None] | None,
) -> Image.Image:
    # Browser workers and Sync share a single slot for the large source raster.
    while not _large_png_lock.acquire(timeout=0.1):
        if checkpoint is not None:
            checkpoint()
    try:
        if checkpoint is not None:
            checkpoint()
        with closing(_open_large_png(stream, size)) as image:
            edge = max(1, min(target_px * 3, 3600))
            # Avoid a second full-size raster for alpha conversion or EXIF
            # orientation. Callers apply their usual Lanczos resize afterwards.
            image.thumbnail((edge, edge), Image.Resampling.NEAREST)
            if checkpoint is not None:
                checkpoint()
            return image.copy()
    except (SyntaxError, OSError) as error:
        raise PodcastFeedError("The Podcast artwork could not be decoded") from error
    finally:
        _large_png_lock.release()
