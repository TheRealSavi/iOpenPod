from __future__ import annotations

import numpy as np
from PIL import Image

from iopenpod.artworkdb_writer.ithmb_codecs import decode_pixels_for_format, encode_image_for_format
from iopenpod.device.artwork import resolve_cover_art_format_definitions


def test_nano_7g_small_alt_writes_padded_stride() -> None:
    width = 57
    height = 57
    stride = 58
    fmt_override = resolve_cover_art_format_definitions("iPod Nano", "7th Gen")[1016]

    # A structured gradient makes row-boundary shear obvious in round-trips.
    x = np.tile(np.arange(width, dtype=np.uint8), (height, 1))
    y = np.tile(np.arange(height, dtype=np.uint8).reshape(height, 1), (1, width))
    rgb = np.stack((x * 4, y * 4, (x + y) * 2), axis=2)
    img = Image.fromarray(rgb)

    encoded = encode_image_for_format(img, 1016, width, height, fmt_override=fmt_override)

    assert encoded.stride_pixels == stride
    assert encoded.size == stride * height * 2
    assert len(encoded.data) == stride * height * 2

    decoded = decode_pixels_for_format(
        1016,
        encoded.data,
        width,
        height,
        fmt_override=fmt_override,
    )

    assert decoded is not None
    assert decoded.size == (width, height)


def test_nano_7g_override_decode_uses_override_pixel_format() -> None:
    fmt_override = resolve_cover_art_format_definitions("iPod Nano", "7th Gen")[1013]
    img = Image.new("RGB", (fmt_override.width, fmt_override.height), (240, 16, 32))

    encoded = encode_image_for_format(
        img,
        fmt_override.format_id,
        fmt_override.width,
        fmt_override.height,
        fmt_override=fmt_override,
    )
    decoded = decode_pixels_for_format(
        fmt_override.format_id,
        encoded.data,
        fmt_override.width,
        fmt_override.height,
        fmt_override=fmt_override,
    )

    assert decoded is not None
    assert decoded.size == (fmt_override.width, fmt_override.height)
    decoded_rgb = np.asarray(decoded.convert("RGB"), dtype=np.uint8)
    assert int(decoded_rgb[0, 0, 0]) > 200
