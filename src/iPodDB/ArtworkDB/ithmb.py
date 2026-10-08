"""Fast, Qt-independent decoders for known iTHMB pixel layouts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from typing import TYPE_CHECKING, Protocol, cast

from PIL import Image

from iPodDB.ArtworkDB.ithmb_reordering import reorder_recursive_rgb555

if TYPE_CHECKING:
    from collections.abc import Sequence

_MAX_DECODE_DIMENSION = 8192
_MAX_DECODE_PIXELS = 32 * 1024 * 1024


class IthmbDecodeError(ValueError):
    """An iTHMB byte range cannot satisfy its declared pixel layout."""


class IthmbPixelFormat(StrEnum):
    """Pixel layouts evidenced in iPod iTHMB files."""

    RGB565_LE = "RGB565_LE"
    RGB565_BE = "RGB565_BE"
    RGB565_BE_90 = "RGB565_BE_90"
    RGB555_LE = "RGB555_LE"
    RGB555_BE = "RGB555_BE"
    REC_RGB555_LE = "REC_RGB555_LE"
    UYVY = "UYVY"
    UYVY_FIELDS = "UYVY_FIELDS"
    I420_LE = "I420_LE"
    JPEG = "JPEG"


class IthmbPaddingMode(StrEnum):
    """Whether MHNI padding trails the image or surrounds PhotosDB pixels."""

    TRAILING = "trailing"
    SYMMETRIC = "symmetric"


@dataclass(frozen=True, slots=True)
class IthmbLayout:
    """Everything the decoder needs for one already-bounded iTHMB image."""

    width: int
    height: int
    row_bytes: int
    pixel_format: IthmbPixelFormat
    horizontal_padding: int = 0
    vertical_padding: int = 0
    padding_mode: IthmbPaddingMode = IthmbPaddingMode.TRAILING

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("iTHMB dimensions must be positive")
        if self.width > _MAX_DECODE_DIMENSION or self.height > _MAX_DECODE_DIMENSION:
            raise ValueError("iTHMB dimensions exceed the supported safety limit")
        if self.width * self.height > _MAX_DECODE_PIXELS:
            raise ValueError("iTHMB pixel count exceeds the supported safety limit")
        if self.row_bytes < 0:
            raise ValueError("iTHMB row size must not be negative")
        if self.horizontal_padding < 0 or self.vertical_padding < 0:
            raise ValueError("iTHMB padding must not be negative")


@dataclass(frozen=True, slots=True)
class DecodedImage:
    """Owned, tightly packed RGB888 pixels suitable for any presentation adapter."""

    width: int
    height: int
    pixels: bytes

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Decoded image dimensions must be positive")
        expected = self.width * self.height * 3
        if len(self.pixels) != expected:
            raise ValueError(
                f"Decoded RGB payload has {len(self.pixels)} bytes; expected {expected}"
            )

    @property
    def byte_count(self) -> int:
        return len(self.pixels)


_PACKED_RGB565 = frozenset(
    {
        IthmbPixelFormat.RGB565_LE,
        IthmbPixelFormat.RGB565_BE,
        IthmbPixelFormat.RGB565_BE_90,
    }
)
_PACKED_RGB555 = frozenset(
    {
        IthmbPixelFormat.RGB555_LE,
        IthmbPixelFormat.RGB555_BE,
    }
)
_Y_LIMITED_TO_FULL = tuple(
    max(0, min(255, round((value - 16) * 255 / 219))) for value in range(256)
)
_CHROMA_LIMITED_TO_FULL = tuple(
    max(0, min(255, round((value - 128) * 255 / 224 + 128))) for value in range(256)
)


class _PointImage(Protocol):
    def point(
        self,
        lut: Sequence[float],
        mode: str | None = None,
    ) -> Image.Image: ...


class _ResizeImage(Protocol):
    def resize(
        self,
        size: tuple[int, int],
        resample: int | None = None,
    ) -> Image.Image: ...


def _apply_lut(image: Image.Image, lut: Sequence[float]) -> Image.Image:
    """Call Pillow through the narrow operation this decoder actually uses."""

    # Pillow's public annotations also accept an optional NumPy type whose name
    # may be unresolved when NumPy is absent. Strict Pylance then marks the whole
    # bound method partially unknown, despite this explicitly typed LUT path.
    return cast("_PointImage", image).point(lut)


def _resize_nearest(
    image: Image.Image,
    size: tuple[int, int],
) -> Image.Image:
    """Resize through a typed boundary around Pillow's optional NumPy input."""

    return cast("_ResizeImage", image).resize(size, Image.Resampling.NEAREST)


def decode_ithmb(payload: bytes, layout: IthmbLayout) -> DecodedImage:
    """Decode one bounded iTHMB image into owned RGB888 bytes.

    Packed and planar conversion runs in Pillow's native implementation. The
    caller remains responsible for selecting and reading exactly one ArtworkDB
    location; this module has no filesystem or Device Profile dependency.
    """

    try:
        if layout.pixel_format in _PACKED_RGB565:
            image = _decode_packed(payload, layout, raw_mode="BGR;16")
        elif layout.pixel_format is IthmbPixelFormat.REC_RGB555_LE:
            width, height = _stored_raster_size(layout)
            _validate_stored_raster(width, height)
            reordered = reorder_recursive_rgb555(
                payload, width, height, layout.row_bytes, encode=False
            )
            image = _decode_packed(reordered, layout, raw_mode="BGR;15")
        elif layout.pixel_format in _PACKED_RGB555:
            image = _decode_packed(payload, layout, raw_mode="BGR;15")
        elif layout.pixel_format in {
            IthmbPixelFormat.UYVY,
            IthmbPixelFormat.UYVY_FIELDS,
        }:
            image = _decode_uyvy(payload, layout)
        elif layout.pixel_format is IthmbPixelFormat.I420_LE:
            image = _decode_i420(payload, layout)
        elif layout.pixel_format is IthmbPixelFormat.JPEG:
            image = _decode_jpeg(payload, layout)
        else:  # pragma: no cover - exhaustive enum guard
            raise IthmbDecodeError(
                f"Unsupported iTHMB pixel format: {layout.pixel_format}"
            )
    except IthmbDecodeError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise IthmbDecodeError(f"Could not decode iTHMB pixels: {error}") from error

    rgb = image.convert("RGB")
    return DecodedImage(rgb.width, rgb.height, rgb.tobytes())


def _decode_packed(
    payload: bytes,
    layout: IthmbLayout,
    *,
    raw_mode: str,
) -> Image.Image:
    rotated = layout.pixel_format is IthmbPixelFormat.RGB565_BE_90
    symmetric = layout.padding_mode is IthmbPaddingMode.SYMMETRIC
    stored_width = layout.width + (layout.horizontal_padding if symmetric else 0)
    stored_height = layout.height + layout.vertical_padding
    _validate_stored_raster(stored_width, stored_height)
    row_pixels = stored_width
    if rotated:
        row_pixels = stored_height if symmetric else layout.height
    minimum_row_bytes = row_pixels * 2
    row_bytes = layout.row_bytes or minimum_row_bytes
    if row_bytes < minimum_row_bytes or row_bytes % 2:
        raise IthmbDecodeError(
            f"Packed iTHMB row has {row_bytes} bytes; expected at least "
            f"{minimum_row_bytes} even bytes"
        )

    source_height = stored_height
    if rotated:
        source_height = stored_width if symmetric else len(payload) // row_bytes
    required = row_bytes * source_height
    if rotated and source_height < stored_width:
        raise IthmbDecodeError(
            "Rotated iTHMB payload is shorter than its visible raster"
        )
    if rotated and (
        source_height > _MAX_DECODE_DIMENSION
        or row_bytes // 2 > _MAX_DECODE_DIMENSION
        or source_height * (row_bytes // 2) > _MAX_DECODE_PIXELS
    ):
        raise IthmbDecodeError(
            "Rotated iTHMB storage exceeds the supported safety limit"
        )
    if not symmetric and len(payload) < required:
        required = row_bytes * layout.height
        source_height = layout.height
    if len(payload) < required:
        raise IthmbDecodeError(f"Packed iTHMB payload is shorter than {required} bytes")

    source = payload[:required]
    if layout.pixel_format in {
        IthmbPixelFormat.RGB565_BE,
        IthmbPixelFormat.RGB565_BE_90,
        IthmbPixelFormat.RGB555_BE,
    }:
        source = _swap_u16_bytes(source)

    decode_width = row_bytes // 2 if rotated else stored_width
    image = Image.frombytes(
        "RGB",
        (decode_width, source_height),
        source,
        "raw",
        raw_mode,
        row_bytes,
        1,
    )
    if rotated:
        image = image.transpose(Image.Transpose.ROTATE_90)
        return _visible_rotated_region(image, layout)
    return _visible_region(image, layout)


def _decode_uyvy(payload: bytes, layout: IthmbLayout) -> Image.Image:
    width, height = _stored_raster_size(layout)
    _validate_stored_raster(width, height)
    if width % 2:
        raise IthmbDecodeError("UYVY images require an even width")
    if layout.pixel_format is IthmbPixelFormat.UYVY_FIELDS and height % 2:
        raise IthmbDecodeError("Field-separated UYVY images require an even height")
    row_bytes = layout.row_bytes or (width * 2)
    if row_bytes < width * 2:
        raise IthmbDecodeError("UYVY row size is smaller than the visible row")
    required = row_bytes * height
    if len(payload) < required:
        raise IthmbDecodeError(f"UYVY payload is shorter than {required} bytes")

    y_bytes = bytearray()
    cb_bytes = bytearray()
    cr_bytes = bytearray()
    separated_fields = layout.pixel_format is IthmbPixelFormat.UYVY_FIELDS
    even_field_rows = (height + 1) // 2
    for row_index in range(height):
        source_row = row_index
        if separated_fields:
            source_row = row_index // 2
            if row_index % 2:
                source_row += even_field_rows
        start = source_row * row_bytes
        row = payload[start : start + (width * 2)]
        cb_bytes.extend(row[0::4])
        y_bytes.extend(row[1::2])
        cr_bytes.extend(row[2::4])

    y = _apply_lut(
        Image.frombytes("L", (width, height), bytes(y_bytes)),
        _Y_LIMITED_TO_FULL,
    )
    chroma_size = (width // 2, height)
    cb = _resize_nearest(
        Image.frombytes("L", chroma_size, bytes(cb_bytes)),
        (width, height),
    )
    cr = _resize_nearest(
        Image.frombytes("L", chroma_size, bytes(cr_bytes)),
        (width, height),
    )
    image = Image.merge(
        "YCbCr",
        (
            y,
            _apply_lut(cb, _CHROMA_LIMITED_TO_FULL),
            _apply_lut(cr, _CHROMA_LIMITED_TO_FULL),
        ),
    ).convert("RGB")
    return _visible_region(image, layout)


def _decode_i420(payload: bytes, layout: IthmbLayout) -> Image.Image:
    width, height = _stored_raster_size(layout)
    _validate_stored_raster(width, height)
    if width % 2 or height % 2:
        raise IthmbDecodeError("I420 images require even dimensions")
    y_size = width * height
    chroma_size = (width // 2) * (height // 2)
    required = y_size + (2 * chroma_size)
    if len(payload) < required:
        raise IthmbDecodeError(f"I420 payload is shorter than {required} bytes")

    y = _apply_lut(
        Image.frombytes("L", (width, height), payload[:y_size]),
        _Y_LIMITED_TO_FULL,
    )
    cb_start = y_size
    cr_start = cb_start + chroma_size
    plane_size = (width // 2, height // 2)
    cb = _resize_nearest(
        Image.frombytes(
            "L",
            plane_size,
            payload[cb_start:cr_start],
        ),
        (width, height),
    )
    cr = _resize_nearest(
        Image.frombytes(
            "L",
            plane_size,
            payload[cr_start : cr_start + chroma_size],
        ),
        (width, height),
    )
    image = Image.merge(
        "YCbCr",
        (
            y,
            _apply_lut(cb, _CHROMA_LIMITED_TO_FULL),
            _apply_lut(cr, _CHROMA_LIMITED_TO_FULL),
        ),
    ).convert("RGB")
    return _visible_region(image, layout)


def _decode_jpeg(payload: bytes, layout: IthmbLayout) -> Image.Image:
    if not payload:
        raise IthmbDecodeError("JPEG iTHMB payload is empty")
    expected_size = _stored_raster_size(layout)
    _validate_stored_raster(*expected_size)
    with Image.open(BytesIO(payload)) as source:
        if source.size != expected_size:
            raise IthmbDecodeError(
                "JPEG dimensions do not match the declared iTHMB layout"
            )
        source.load()
        return _visible_region(source.convert("RGB"), layout)


def _stored_raster_size(layout: IthmbLayout) -> tuple[int, int]:
    if layout.padding_mode is IthmbPaddingMode.SYMMETRIC:
        return (
            layout.width + layout.horizontal_padding,
            layout.height + layout.vertical_padding,
        )
    return layout.width, layout.height


def _validate_stored_raster(width: int, height: int) -> None:
    if (
        width > _MAX_DECODE_DIMENSION
        or height > _MAX_DECODE_DIMENSION
        or width * height > _MAX_DECODE_PIXELS
    ):
        raise IthmbDecodeError("Padded iTHMB raster exceeds the supported safety limit")


def _swap_u16_bytes(source: bytes) -> bytes:
    swapped = bytearray(len(source))
    swapped[0::2] = source[1::2]
    swapped[1::2] = source[0::2]
    return bytes(swapped)


def _visible_region(image: Image.Image, layout: IthmbLayout) -> Image.Image:
    if layout.padding_mode is IthmbPaddingMode.SYMMETRIC:
        left = layout.horizontal_padding
        top = layout.vertical_padding
        width = layout.width - left
        height = layout.height - top
        if (
            width <= 0
            or height <= 0
            or left + width > image.width
            or top + height > image.height
        ):
            raise IthmbDecodeError(
                "Symmetrically padded iTHMB layout has no valid visible region"
            )
        return image.crop((left, top, left + width, top + height))

    width = min(layout.width, image.width)
    height = min(layout.height, image.height)
    if width <= 0 or height <= 0:
        raise IthmbDecodeError("Decoded iTHMB image has no visible pixels")
    if (width, height) == image.size:
        return image
    return image.crop((0, 0, width, height))


def _visible_rotated_region(
    image: Image.Image,
    layout: IthmbLayout,
) -> Image.Image:
    """Remove row-stride padding that becomes a top band after rotation."""

    if layout.padding_mode is IthmbPaddingMode.SYMMETRIC:
        left = layout.horizontal_padding
        width = layout.width - left
        height = layout.height - layout.vertical_padding
        top = max(0, image.height - layout.height)
        if (
            width <= 0
            or height <= 0
            or left + width > image.width
            or top + height > image.height
        ):
            raise IthmbDecodeError(
                "Symmetrically padded rotated iTHMB layout has no valid visible region"
            )
        return image.crop((left, top, left + width, top + height))

    width = min(layout.width, image.width)
    height = min(layout.height, image.height)
    top = max(0, image.height - height)
    if width <= 0 or height <= 0:
        raise IthmbDecodeError("Decoded rotated iTHMB image has no visible pixels")
    return image.crop((0, top, width, top + height))


__all__ = [
    "DecodedImage",
    "IthmbDecodeError",
    "IthmbLayout",
    "IthmbPaddingMode",
    "IthmbPixelFormat",
    "decode_ithmb",
]
