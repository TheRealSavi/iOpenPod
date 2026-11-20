"""Read and recolor native BMaps without changing layout, indices or alpha.

The formats are documented by pinned osos-lab's themes/compiler.py. Grayscale
formats are coverage masks: deliberately never recolor those as visible pixels.
"""

import struct
from collections.abc import Callable, Iterable
from dataclasses import dataclass

RGB = tuple[int, int, int]


def unpack565(value: int) -> RGB:
    return (
        (value >> 11) * 255 // 31,
        ((value >> 5) & 63) * 255 // 63,
        (value & 31) * 255 // 31,
    )


def pack565(color: RGB) -> int:
    red, green, blue = color
    return ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)


@dataclass(frozen=True)
class Bitmap:
    data: bytes
    format: int
    stride: int
    width: int
    height: int
    start: int
    pixels: int
    colors: int

    @classmethod
    def parse(cls, data: bytes) -> "Bitmap":
        if len(data) < 28:
            raise ValueError("Truncated native bitmap")
        fmt, _, stride, depth = struct.unpack_from("<4H", data)
        height, width = struct.unpack_from("<2I", data, 16)
        formats = {4: 4, 8: 8, 0x64: 8, 0x65: 16, 0x565: 16, 0x1888: 32}
        if formats.get(fmt) != depth or not width or not height:
            raise ValueError("Unsupported native bitmap format or dimensions")
        start = 28 if struct.unpack_from("<I", data, 24)[0] == len(data) - 28 else 32
        if (
            len(data) < start
            or struct.unpack_from("<I", data, start - 4)[0] != len(data) - start
        ):
            raise ValueError("Native bitmap length changed")
        colors = struct.unpack_from("<I", data, start)[0] if fmt in (0x64, 0x65) else 0
        pixels = start + (4 + colors * 4 if fmt in (0x64, 0x65) else 0)
        if stride < (width * depth + 7) // 8 or pixels + stride * height != len(data):
            raise ValueError("Native bitmap stride/palette exceeds payload")
        return cls(data, fmt, stride, width, height, start, pixels, colors)

    def recolor(self, transform: Callable[[RGB], RGB]) -> bytes:
        """Leave alpha, padding, geometry and palette index planes byte-identical."""
        result = bytearray(self.data)
        if self.format in (4, 8):
            raise ValueError("Grayscale coverage masks must not be recolored")
        offsets: Iterable[int]
        if self.colors:
            offsets = range(self.start + 4, self.pixels, 4)
        else:
            step = 2 if self.format == 0x565 else 4
            offsets = (
                self.pixels + y * self.stride + x * step
                for y in range(self.height)
                for x in range(self.width)
            )
        for offset in offsets:
            if self.format == 0x565:
                color = unpack565(struct.unpack_from("<H", result, offset)[0])
                struct.pack_into("<H", result, offset, pack565(transform(color)))
            elif result[offset + 3]:
                blue, green, red = result[offset : offset + 3]
                r, g, b = transform((red, green, blue))
                result[offset : offset + 3] = bytes((b, g, r))
        return bytes(result)

    def rgba(self) -> bytes:
        """Decode for inspection; mask previews show coverage as grayscale."""
        output = bytearray()
        for y in range(self.height):
            row = self.pixels + y * self.stride
            for x in range(self.width):
                if self.format == 4:
                    shade = (
                        (self.data[row + x // 2] >> (4 if x % 2 == 0 else 0)) & 15
                    ) * 17
                    output.extend((shade, shade, shade, 255))
                elif self.format == 8:
                    shade = self.data[row + x]
                    output.extend((shade, shade, shade, 255))
                elif self.format == 0x565:
                    output.extend(
                        (
                            *unpack565(
                                struct.unpack_from("<H", self.data, row + x * 2)[0]
                            ),
                            255,
                        )
                    )
                else:
                    if self.colors:
                        index = (
                            self.data[row + x]
                            if self.format == 0x64
                            else struct.unpack_from("<H", self.data, row + x * 2)[0]
                        )
                        if index >= self.colors:
                            raise ValueError("Bitmap palette index out of range")
                        offset = self.start + 4 + index * 4
                    else:
                        offset = row + x * 4
                    blue, green, red, alpha = self.data[offset : offset + 4]
                    output.extend((red, green, blue, alpha))
        return bytes(output)

    def replace_rgba(self, pixels: bytes) -> bytes:
        """Fit an authored/status counterpart into the existing indexed allocation."""
        if (
            self.format not in (0x64, 0x65)
            or len(pixels) != self.width * self.height * 4
        ):
            raise ValueError("Replacement needs an indexed bitmap of equal dimensions")
        colors = list(
            dict.fromkeys(pixels[i : i + 4] for i in range(0, len(pixels), 4))
        )
        if len(colors) > self.colors:
            raise ValueError("Replacement exceeds native palette capacity")
        result = bytearray(self.data)
        for index, color in enumerate(colors):
            red, green, blue, alpha = color
            offset = self.start + 4 + index * 4
            result[offset : offset + 4] = bytes((blue, green, red, alpha))
        indices = {color: i for i, color in enumerate(colors)}
        for y in range(self.height):
            for x in range(self.width):
                pixel = (y * self.width + x) * 4
                index = indices[pixels[pixel : pixel + 4]]
                offset = self.pixels + y * self.stride
                if self.format == 0x64:
                    result[offset + x] = index
                else:
                    struct.pack_into("<H", result, offset + x * 2, index)
        return bytes(result)
