"""Independent raster vectors and coverage for every catalog artwork layout."""

import pytest

from device_registry import DEFAULT_DEVICE_REGISTRY
from iPodDB.ArtworkDB.ithmb import (
    DecodedImage,
    IthmbLayout,
    IthmbPaddingMode,
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
        layout.width * layout.height * 2
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
    assert len(payload) == 8
    # Allow one level for the full-range to limited-range integer conversion.
    assert all(
        abs(a - b) <= 1
        for a, b in zip(payload[:6], (81, 81, 81, 81, 90, 240), strict=True)
    )
    assert payload[6:] == b"\x00\x00"


def test_recursive_rgb555_uses_top_left_bottom_left_top_right_bottom_right_order() -> (
    None
):
    # Independent libgpod quadrant-order vector: row-major red levels 0..15
    # become 0,4,1,5 / 8,12,9,13 / 2,6,3,7 / 10,14,11,15 on disk.
    image = DecodedImage(
        4, 4, b"".join(bytes((level * 255 // 31, 0, 0)) for level in range(16))
    )
    layout = IthmbLayout(4, 4, 8, IthmbPixelFormat.REC_RGB555_LE)
    expected = bytes.fromhex(
        "0000 0010 0004 0014 0020 0030 0024 0034 "
        "0008 0018 000c 001c 0028 0038 002c 003c"
    )

    assert encode_ithmb(image, layout) == expected
    assert decode_ithmb(expected, layout) == image


@pytest.mark.parametrize(
    ("width", "height", "row_bytes"),
    ((4, 2, 8), (3, 3, 6), (4, 4, 10)),
)
def test_recursive_rgb555_rejects_unevidenced_raster_geometry(
    width: int, height: int, row_bytes: int
) -> None:
    layout = IthmbLayout(width, height, row_bytes, IthmbPixelFormat.REC_RGB555_LE)
    pixels = DecodedImage(width, height, bytes(width * height * 3))

    with pytest.raises(ValueError, match="Recursive RGB555 requires"):
        encode_ithmb(pixels, layout)
    with pytest.raises(ValueError, match="Recursive RGB555 requires"):
        decode_ithmb(bytes(row_bytes * height), layout)


def test_recursive_rgb555_uses_the_stored_square_before_cropping_padding() -> None:
    image = DecodedImage(2, 2, bytes((255, 0, 0)) * 4)
    layout = IthmbLayout(
        3,
        3,
        8,
        IthmbPixelFormat.REC_RGB555_LE,
        horizontal_padding=1,
        vertical_padding=1,
        padding_mode=IthmbPaddingMode.SYMMETRIC,
    )
    # The 2x2 red center occupies the fourth, seventh, tenth and thirteenth
    # recursive words of the independently established 4x4 ordering.
    expected = bytes.fromhex(
        "0000 0000 0000 007c 0000 0000 007c 0000 "
        "0000 007c 0000 0000 007c 0000 0000 0000"
    )

    assert encode_ithmb(image, layout) == expected
    assert decode_ithmb(expected, layout) == image


def test_recursive_rgb555_rejects_a_truncated_record() -> None:
    with pytest.raises(ValueError, match="shorter than 32 bytes"):
        decode_ithmb(bytes(31), IthmbLayout(4, 4, 8, IthmbPixelFormat.REC_RGB555_LE))


def test_symmetric_padding_encoder_preserves_the_visible_raster() -> None:
    image = DecodedImage(
        2,
        1,
        bytes((255, 0, 0, 0, 255, 0)),
    )
    layout = IthmbLayout(
        3,
        2,
        8,
        IthmbPixelFormat.RGB565_LE,
        horizontal_padding=1,
        vertical_padding=1,
        padding_mode=IthmbPaddingMode.SYMMETRIC,
    )

    decoded = decode_ithmb(encode_ithmb(image, layout), layout)

    assert decoded == image


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
    image = DecodedImage(4, 4, bytes((255, 0, 0)) * 16)
    layout = IthmbLayout(4, 4, 0, kind)
    decoded = decode_ithmb(encode_ithmb(image, layout), layout)
    assert (decoded.width, decoded.height) == (4, 4)
    assert all(
        abs(a - b) < 8 for a, b in zip(decoded.pixels, image.pixels, strict=True)
    )


def test_truncated_rotated_payload_cannot_silently_shrink_the_image() -> None:
    with pytest.raises(ValueError, match="shorter"):
        decode_ithmb(bytes(8), IthmbLayout(3, 2, 4, IthmbPixelFormat.RGB565_BE_90))
