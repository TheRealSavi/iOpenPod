"""Format-aware, Qt-independent iTHMB decoding."""

from io import BytesIO

import pytest
from PIL import Image

from iPodDB.ArtworkDB.ithmb import (
    DecodedImage,
    IthmbDecodeError,
    IthmbLayout,
    IthmbPaddingMode,
    IthmbPixelFormat,
    decode_ithmb,
)


def test_decodes_rgb565_with_padded_rows_and_crops_to_visible_width() -> None:
    layout = IthmbLayout(
        width=2,
        height=1,
        row_bytes=6,
        pixel_format=IthmbPixelFormat.RGB565_LE,
        horizontal_padding=1,
    )
    decoded = decode_ithmb(
        b"\x00\xf8\xe0\x07\x1f\x00",
        layout,
    )

    assert decoded == DecodedImage(
        width=2,
        height=1,
        pixels=bytes((255, 0, 0, 0, 255, 0)),
    )


def test_decodes_symmetric_rgb565_padding_around_visible_pixels() -> None:
    decoded = decode_ithmb(
        b"\x00\x00" * 4 + b"\x00\x00\x00\xf8\xe0\x07\x00\x00" + b"\x00\x00" * 4,
        IthmbLayout(
            width=3,
            height=2,
            row_bytes=8,
            pixel_format=IthmbPixelFormat.RGB565_LE,
            horizontal_padding=1,
            vertical_padding=1,
            padding_mode=IthmbPaddingMode.SYMMETRIC,
        ),
    )

    assert decoded == DecodedImage(
        width=2,
        height=1,
        pixels=bytes((255, 0, 0, 0, 255, 0)),
    )


@pytest.mark.parametrize(
    ("pixel_format", "payload"),
    (
        (IthmbPixelFormat.RGB565_BE, b"\xf8\x00"),
        (IthmbPixelFormat.RGB555_BE, b"\x7c\x00"),
    ),
)
def test_decodes_big_endian_packed_red_pixels(
    pixel_format: IthmbPixelFormat,
    payload: bytes,
) -> None:
    decoded = decode_ithmb(
        payload,
        IthmbLayout(1, 1, 2, pixel_format),
    )

    red, green, blue = decoded.pixels
    assert red >= 246
    assert green == 0
    assert blue == 0


def test_decodes_rotated_big_endian_rgb565_and_removes_stride_padding() -> None:
    decoded = decode_ithmb(
        b"\xf8\x00\x00\x00\x07\xe0\x00\x00",
        IthmbLayout(
            width=2,
            height=1,
            row_bytes=4,
            pixel_format=IthmbPixelFormat.RGB565_BE_90,
        ),
    )

    assert decoded == DecodedImage(
        width=2,
        height=1,
        pixels=bytes((255, 0, 0, 0, 255, 0)),
    )


def test_decodes_rotated_rgb565_and_removes_declared_horizontal_padding() -> None:
    decoded = decode_ithmb(
        # Matching black storage rows surround the visible red and green
        # pixels; each row also has one stride-padding pixel that rotates into
        # a top band.
        b"\x00\x00\x00\x00\xf8\x00\x00\x00\x07\xe0\x00\x00\x00\x00\x00\x00",
        IthmbLayout(
            width=3,
            height=1,
            row_bytes=4,
            pixel_format=IthmbPixelFormat.RGB565_BE_90,
            horizontal_padding=1,
            padding_mode=IthmbPaddingMode.SYMMETRIC,
        ),
    )

    assert decoded == DecodedImage(
        width=2,
        height=1,
        pixels=bytes((255, 0, 0, 0, 255, 0)),
    )


@pytest.mark.parametrize(
    "pixel_format",
    (IthmbPixelFormat.RGB555_LE, IthmbPixelFormat.REC_RGB555_LE),
)
def test_decodes_little_endian_rgb555_variants(
    pixel_format: IthmbPixelFormat,
) -> None:
    decoded = decode_ithmb(
        b"\x00\x7c",
        IthmbLayout(1, 1, 2, pixel_format),
    )

    assert decoded.pixels[0] >= 246
    assert decoded.pixels[1:] == b"\x00\x00"


def test_decodes_uyvy_and_i420_limited_range_yuv() -> None:
    uyvy = decode_ithmb(
        bytes((90, 82, 240, 82)),
        IthmbLayout(2, 1, 4, IthmbPixelFormat.UYVY),
    )
    i420 = decode_ithmb(
        bytes((82, 82, 82, 82, 90, 240)),
        IthmbLayout(2, 2, 3, IthmbPixelFormat.I420_LE),
    )

    for decoded in (uyvy, i420):
        assert decoded.pixels[0] > 220
        assert decoded.pixels[1] < 45
        assert decoded.pixels[2] < 45


def test_uyvy_uses_distinct_luma_for_each_pixel_in_a_pair() -> None:
    decoded = decode_ithmb(
        bytes((128, 16, 128, 235)),
        IthmbLayout(2, 1, 4, IthmbPixelFormat.UYVY),
    )

    assert decoded.pixels == bytes((0, 0, 0, 255, 255, 255))


def test_row_major_uyvy_does_not_apply_field_weaving() -> None:
    stored_luma = (16, 82, 162, 235)
    decoded = decode_ithmb(
        b"".join(bytes((128, value, 128, value)) for value in stored_luma),
        IthmbLayout(2, 4, 4, IthmbPixelFormat.UYVY),
    )

    first_pixel_by_row = tuple(
        decoded.pixels[row * decoded.width * 3] for row in range(decoded.height)
    )
    assert first_pixel_by_row == (0, 77, 170, 255)


def test_decodes_field_separated_uyvy_rows_in_display_order() -> None:
    # Stored fields contain display rows 0, 2 followed by display rows 1, 3.
    stored_luma = (16, 162, 82, 235)
    decoded = decode_ithmb(
        b"".join(bytes((128, value, 128, value)) for value in stored_luma),
        IthmbLayout(2, 4, 4, IthmbPixelFormat.UYVY_FIELDS),
    )

    assert (decoded.width, decoded.height) == (2, 4)
    first_pixel_by_row = tuple(
        decoded.pixels[row * decoded.width * 3] for row in range(decoded.height)
    )
    assert first_pixel_by_row == (0, 77, 170, 255)


def test_rejects_an_odd_height_for_field_separated_uyvy() -> None:
    with pytest.raises(IthmbDecodeError, match="even height"):
        decode_ithmb(
            bytes(12),
            IthmbLayout(2, 3, 4, IthmbPixelFormat.UYVY_FIELDS),
        )


def test_decodes_symmetric_padding_for_subsampled_photo_formats() -> None:
    uyvy = decode_ithmb(
        bytes((128, 16, 128, 235, 128, 235, 128, 16)),
        IthmbLayout(
            width=3,
            height=1,
            row_bytes=8,
            pixel_format=IthmbPixelFormat.UYVY,
            horizontal_padding=1,
            padding_mode=IthmbPaddingMode.SYMMETRIC,
        ),
    )
    y_plane = bytes(
        (
            16,
            16,
            16,
            16,
            16,
            235,
            235,
            16,
            16,
            235,
            235,
            16,
            16,
            16,
            16,
            16,
        )
    )
    i420 = decode_ithmb(
        y_plane + bytes((128,)) * 8,
        IthmbLayout(
            width=3,
            height=3,
            row_bytes=6,
            pixel_format=IthmbPixelFormat.I420_LE,
            horizontal_padding=1,
            vertical_padding=1,
            padding_mode=IthmbPaddingMode.SYMMETRIC,
        ),
    )

    assert (uyvy.width, uyvy.height) == (2, 1)
    assert (i420.width, i420.height) == (2, 2)
    for decoded in (uyvy, i420):
        assert min(decoded.pixels) >= 250


def test_decodes_embedded_jpeg_to_owned_rgb_bytes() -> None:
    encoded = BytesIO()
    Image.new("RGB", (3, 2), (20, 80, 160)).save(encoded, format="JPEG", quality=100)

    decoded = decode_ithmb(
        encoded.getvalue(),
        IthmbLayout(3, 2, 0, IthmbPixelFormat.JPEG),
    )

    assert (decoded.width, decoded.height) == (3, 2)
    assert len(decoded.pixels) == 3 * 2 * 3


def test_decodes_symmetric_padding_from_an_embedded_photo_jpeg() -> None:
    encoded = BytesIO()
    Image.new("RGB", (4, 4), (20, 80, 160)).save(
        encoded,
        format="JPEG",
        quality=100,
    )

    decoded = decode_ithmb(
        encoded.getvalue(),
        IthmbLayout(
            width=3,
            height=3,
            row_bytes=0,
            pixel_format=IthmbPixelFormat.JPEG,
            horizontal_padding=1,
            vertical_padding=1,
            padding_mode=IthmbPaddingMode.SYMMETRIC,
        ),
    )

    assert (decoded.width, decoded.height) == (2, 2)


def test_rejects_a_truncated_packed_payload() -> None:
    with pytest.raises(IthmbDecodeError, match="shorter"):
        decode_ithmb(
            b"\x00\xf8",
            IthmbLayout(2, 1, 4, IthmbPixelFormat.RGB565_LE),
        )


def test_rejects_unsafe_or_mismatched_declared_dimensions() -> None:
    with pytest.raises(ValueError, match="safety limit"):
        IthmbLayout(100_000, 1, 200_000, IthmbPixelFormat.RGB565_LE)

    encoded = BytesIO()
    Image.new("RGB", (2, 2), (0, 0, 0)).save(encoded, format="JPEG")
    with pytest.raises(IthmbDecodeError, match="do not match"):
        decode_ithmb(
            encoded.getvalue(),
            IthmbLayout(3, 2, 0, IthmbPixelFormat.JPEG),
        )
