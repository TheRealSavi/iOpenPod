"""Bounded encoders for the declared iTHMB raster layouts, with no file I/O."""

from io import BytesIO
from typing import Literal

from PIL import Image

from iPodDB.ArtworkDB.ithmb import (
    DecodedImage,
    IthmbLayout,
    IthmbPaddingMode,
    IthmbPixelFormat,
)


def encode_ithmb(pixels: DecodedImage, layout: IthmbLayout) -> bytes:
    """Fit without cropping, center on black, then encode the complete raster."""
    if (
        pixels.width > 8192
        or pixels.height > 8192
        or pixels.width * pixels.height > 32 * 1024 * 1024
    ):
        raise ValueError("Artwork source exceeds the supported pixel bounds")
    symmetric = layout.padding_mode is IthmbPaddingMode.SYMMETRIC
    if not symmetric and (layout.horizontal_padding or layout.vertical_padding):
        raise ValueError("Nonzero iTHMB padding requires symmetric padding mode")
    stored_width = layout.width + (layout.horizontal_padding if symmetric else 0)
    stored_height = layout.height + (layout.vertical_padding if symmetric else 0)
    visible_width = (
        layout.width - layout.horizontal_padding if symmetric else layout.width
    )
    visible_height = (
        layout.height - layout.vertical_padding if symmetric else layout.height
    )
    if visible_width <= 0 or visible_height <= 0:
        raise ValueError("Symmetrically padded iTHMB layout has no visible raster")
    if (
        stored_width > 8192
        or stored_height > 8192
        or stored_width * stored_height > 32 * 1024 * 1024
    ):
        raise ValueError("The padded artwork raster exceeds the supported pixel bounds")
    if layout.row_bytes * max(stored_width, stored_height) > 128 * 1024 * 1024:
        raise ValueError("The padded artwork raster exceeds the supported byte limit")
    image = Image.frombytes("RGB", (pixels.width, pixels.height), pixels.pixels)
    scale = min(visible_width / pixels.width, visible_height / pixels.height)
    size = (max(1, round(pixels.width * scale)), max(1, round(pixels.height * scale)))
    # Pillow's optional NumPy size annotation is unresolved without NumPy.
    image = image.resize(size, Image.Resampling.LANCZOS)  # pyright: ignore[reportUnknownMemberType]
    canvas = Image.new("RGB", (stored_width, stored_height))
    left = layout.horizontal_padding if symmetric else 0
    top = layout.vertical_padding if symmetric else 0
    canvas.paste(
        image,
        (
            left + (visible_width - size[0]) // 2,
            top + (visible_height - size[1]) // 2,
        ),
    )
    kind = layout.pixel_format
    if kind is IthmbPixelFormat.JPEG:
        stream = BytesIO()
        canvas.save(
            stream, format="JPEG", quality=92, optimize=False, progressive=False
        )
        return stream.getvalue()
    if kind is IthmbPixelFormat.RGB565_BE_90:
        canvas = canvas.transpose(Image.Transpose.ROTATE_270)
    width, height = canvas.size
    if kind in (
        IthmbPixelFormat.UYVY,
        IthmbPixelFormat.UYVY_FIELDS,
        IthmbPixelFormat.I420_LE,
    ):
        if width % 2 or (
            kind in (IthmbPixelFormat.UYVY_FIELDS, IthmbPixelFormat.I420_LE)
            and height % 2
        ):
            raise ValueError("Subsampled YUV requires even raster dimensions")
        ycbcr = canvas.convert("YCbCr").tobytes()
        y = bytes(round(16 + v * 219 / 255) for v in ycbcr[0::3])
        cb = bytes(round(128 + (v - 128) * 224 / 255) for v in ycbcr[1::3])
        cr = bytes(round(128 + (v - 128) * 224 / 255) for v in ycbcr[2::3])
        if kind is IthmbPixelFormat.I420_LE:
            # Catalog RowBytes includes both chroma planes amortized over the
            # image height. The three individual planes remain tightly packed;
            # F1067 still reserves a two-byte-per-pixel record for that image.
            if layout.row_bytes not in (0, width, width * 3 // 2):
                raise ValueError("I420 requires tightly packed planar rows")
            planes = [
                bytes(
                    round(
                        sum(
                            plane[(r + dy) * width + c + dx]
                            for dy in (0, 1)
                            for dx in (0, 1)
                        )
                        / 4
                    )
                    for r in range(0, height, 2)
                    for c in range(0, width, 2)
                )
                for plane in (cb, cr)
            ]
            payload = y + planes[0] + planes[1]
            return payload + bytes(width * height * 2 - len(payload))
        stride = layout.row_bytes or width * 2
        if stride < width * 2:
            raise ValueError("UYVY row stride is too short")
        output = bytearray(stride * height)
        separated_fields = kind is IthmbPixelFormat.UYVY_FIELDS
        even_field_rows = (height + 1) // 2
        for r in range(height):
            stored_row = r
            if separated_fields:
                stored_row = r // 2
                if r % 2:
                    stored_row += even_field_rows
            for c in range(0, width, 2):
                i, offset = r * width + c, stored_row * stride + c * 2
                output[offset : offset + 4] = bytes(
                    (
                        round((cb[i] + cb[i + 1]) / 2),
                        y[i],
                        round((cr[i] + cr[i + 1]) / 2),
                        y[i + 1],
                    )
                )
        return bytes(output)
    if kind not in (
        IthmbPixelFormat.RGB565_LE,
        IthmbPixelFormat.RGB565_BE,
        IthmbPixelFormat.RGB565_BE_90,
        IthmbPixelFormat.RGB555_LE,
        IthmbPixelFormat.RGB555_BE,
        IthmbPixelFormat.REC_RGB555_LE,
    ):
        raise ValueError(f"Unsupported iTHMB encoding: {kind}")
    stride = layout.row_bytes or width * 2
    if stride < width * 2 or stride % 2:
        raise ValueError("Packed RGB row stride must contain complete 16-bit pixels")
    rgb = canvas.tobytes()
    output = bytearray(stride * height)
    bits565 = kind in (
        IthmbPixelFormat.RGB565_LE,
        IthmbPixelFormat.RGB565_BE,
        IthmbPixelFormat.RGB565_BE_90,
    )
    endian: Literal["big", "little"] = (
        "big"
        if kind
        in (
            IthmbPixelFormat.RGB565_BE,
            IthmbPixelFormat.RGB565_BE_90,
            IthmbPixelFormat.RGB555_BE,
        )
        else "little"
    )
    for row in range(height):
        for column in range(width):
            i = (row * width + column) * 3
            red, green, blue = rgb[i : i + 3]
            value = (
                ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
                if bits565
                else ((red >> 3) << 10) | ((green >> 3) << 5) | (blue >> 3)
            )
            offset = row * stride + column * 2
            output[offset : offset + 2] = value.to_bytes(2, endian)
    return bytes(output)
