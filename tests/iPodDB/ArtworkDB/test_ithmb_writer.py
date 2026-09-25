"""Independent raster vectors and coverage for every catalog artwork layout."""

import pytest

from device_registry import DEFAULT_DEVICE_REGISTRY
from iPodDB.ArtworkDB.ithmb import (
    DecodedImage,
    IthmbLayout,
    IthmbPixelFormat,
    decode_ithmb,
)
from iPodDB.ArtworkDB.ithmb_writer import encode_ithmb

CATALOG_LAYOUTS = tuple(
    dict.fromkeys(
        IthmbLayout(
            f.width, f.height, f.row_bytes, IthmbPixelFormat(f.pixel_format.value)
        )
        for profile in DEFAULT_DEVICE_REGISTRY.profiles
        for f in (
            *profile.capabilities.artwork.cover_formats,
            *profile.capabilities.artwork.photo_formats,
        )
    )
)


@pytest.mark.parametrize("layout", CATALOG_LAYOUTS)
def test_every_catalog_layout_encodes_a_complete_white_raster(
    layout: IthmbLayout,
) -> None:
    # Exact white survives RGB quantization and limited-range YUV conversion.
    image = DecodedImage(
        layout.width,
        layout.height,
        bytes((255, 255, 255)) * (layout.width * layout.height),
    )
    payload = encode_ithmb(image, layout)
    expected_size = (
        layout.width * layout.height * 3 // 2
        if layout.pixel_format is IthmbPixelFormat.I420_LE
        else layout.row_bytes
        * (
            layout.width
            if layout.pixel_format is IthmbPixelFormat.RGB565_BE_90
            else layout.height
        )
    )
    assert len(payload) == expected_size
    assert decode_ithmb(payload, layout) == image


def test_rotated_rectangular_raster_matches_clockwise_big_endian_vector() -> None:
    # Visible: red green blue / white black yellow. Stored columns run bottom-up.
    image = DecodedImage(
        3,
        2,
        bytes((255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255, 0, 0, 0, 255, 255, 0)),
    )
    layout = IthmbLayout(3, 2, 6, IthmbPixelFormat.RGB565_BE_90)
    payload = encode_ithmb(image, layout)
    assert payload == bytes.fromhex("fffff8000000 000007e00000 ffe0001f0000")
    assert decode_ithmb(payload, layout) == image


def test_i420_planes_accept_catalog_aggregate_row_size() -> None:
    image = DecodedImage(2, 2, bytes((255, 0, 0)) * 4)
    payload = encode_ithmb(image, IthmbLayout(2, 2, 3, IthmbPixelFormat.I420_LE))
    # Allow one level for the full-range to limited-range integer conversion.
    assert all(
        abs(a - b) <= 1 for a, b in zip(payload, (81, 81, 81, 81, 90, 240), strict=True)
    )


def test_field_separated_uyvy_writer_stores_even_rows_before_odd_rows() -> None:
    rows = (0, 77, 170, 255)
    image = DecodedImage(
        2,
        4,
        b"".join(bytes((value, value, value)) * 2 for value in rows),
    )
    layout = IthmbLayout(2, 4, 4, IthmbPixelFormat.UYVY_FIELDS)

    payload = encode_ithmb(image, layout)

    assert tuple(payload[row * 4 + 1] for row in range(4)) == (16, 162, 82, 235)
    assert decode_ithmb(payload, layout) == image


def test_field_separated_uyvy_writer_rejects_an_odd_height() -> None:
    image = DecodedImage(2, 3, bytes((255, 255, 255)) * 6)

    with pytest.raises(ValueError, match="even raster dimensions"):
        encode_ithmb(
            image,
            IthmbLayout(2, 3, 4, IthmbPixelFormat.UYVY_FIELDS),
        )


@pytest.mark.parametrize("kind", tuple(IthmbPixelFormat))
def test_every_pixel_encoding_supports_an_implicit_tight_stride(
    kind: IthmbPixelFormat,
) -> None:
    image = DecodedImage(4, 2, bytes((255, 0, 0)) * 8)
    layout = IthmbLayout(4, 2, 0, kind)
    decoded = decode_ithmb(encode_ithmb(image, layout), layout)
    assert (decoded.width, decoded.height) == (4, 2)
    assert all(
        abs(a - b) < 8 for a, b in zip(decoded.pixels, image.pixels, strict=True)
    )


def test_truncated_rotated_payload_cannot_silently_shrink_the_image() -> None:
    with pytest.raises(ValueError, match="shorter"):
        decode_ithmb(bytes(8), IthmbLayout(3, 2, 4, IthmbPixelFormat.RGB565_BE_90))
