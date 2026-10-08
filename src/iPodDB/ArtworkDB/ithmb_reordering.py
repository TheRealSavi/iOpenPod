"""The recursive quadrant ordering used by REC_RGB555 iTHMB rasters."""


def reorder_recursive_rgb555(
    payload: bytes,
    width: int,
    height: int,
    row_bytes: int,
    *,
    encode: bool,
) -> bytes:
    """Convert between row-major words and TL, BL, TR, BR quadrant words.

    Each recursive level interleaves the Y bit before the X bit. This follows
    libgpod's paired rearrange_pixels/derange_pixels, including its square-raster
    restriction. A power-of-two side prevents silently dropping odd quadrants.
    """

    if width != height or width <= 0 or width & (width - 1):
        raise ValueError("Recursive RGB555 requires a square power-of-two raster")
    if row_bytes not in (0, width * 2):
        raise ValueError("Recursive RGB555 requires tightly packed 16-bit rows")
    required = width * height * 2
    if len(payload) < required:
        raise ValueError(f"Recursive RGB555 payload is shorter than {required} bytes")
    # One small table per axis avoids both per-pixel recursive calls and a
    # raster-sized table. Width is already bounded by the public codec layout.
    spread = tuple(
        sum(((value >> bit) & 1) << (2 * bit) for bit in range(width.bit_length() - 1))
        for value in range(width)
    )
    output = bytearray(required)
    for row, row_bits in enumerate(spread):
        for column, column_bits in enumerate(spread):
            linear_offset = (row * width + column) * 2
            recursive_offset = (row_bits | (column_bits << 1)) * 2
            source, destination = (
                (linear_offset, recursive_offset)
                if encode
                else (recursive_offset, linear_offset)
            )
            output[destination : destination + 2] = payload[source : source + 2]
    return bytes(output)
