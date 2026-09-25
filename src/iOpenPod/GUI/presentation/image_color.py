"""Extract a reusable display color from arbitrary raster images."""

from __future__ import annotations

import colorsys
from typing import cast

from PIL import Image

type RGBColor = tuple[int, int, int]

_ANALYSIS_SIZE = (80, 80)
_PALETTE_COLORS = 8
_BORDER_THRESHOLD = 8


def dominant_image_color(image: Image.Image) -> RGBColor:
    """Return the Original iOpenPod dominant-color result for any image.

    The iTunes-11-inspired algorithm favors saturated colors on the image's
    left edge, ignores a uniform frame, and falls back to the full image when
    that edge is neutral. The input is never mutated.
    """

    small = image.copy()
    small.thumbnail(_ANALYSIS_SIZE)
    analyzed = _without_uniform_border(small.convert("RGB"))

    width, height = analyzed.size
    left_strip = analyzed.crop((0, 0, max(2, width // 5), height))
    best_color, best_score = _best_palette_color(left_strip)

    if best_color is None:
        simple = image.convert("P", palette=Image.Palette.ADAPTIVE, colors=1)
        palette = simple.getpalette() or [0, 0, 0]
        best_color = palette[0], palette[1], palette[2]

    red, green, blue = best_color
    _hue, saturation, _value = colorsys.rgb_to_hsv(
        red / 255,
        green / 255,
        blue / 255,
    )
    if saturation < 0.12 and best_score < 0.8:
        full_color, full_score = _best_palette_color(analyzed)
        if full_color is not None and full_score > best_score:
            red, green, blue = full_color

    hue, saturation, value = colorsys.rgb_to_hsv(
        red / 255,
        green / 255,
        blue / 255,
    )
    saturation = min(1.0, saturation * 1.4 + 0.1)
    value = max(0.35, min(0.85, value * 1.2 + 0.05))
    boosted = colorsys.hsv_to_rgb(hue, saturation, value)
    return (
        int(boosted[0] * 255),
        int(boosted[1] * 255),
        int(boosted[2] * 255),
    )


def _best_palette_color(image: Image.Image) -> tuple[RGBColor | None, float]:
    quantized = image.quantize(
        colors=_PALETTE_COLORS,
        method=Image.Quantize.MEDIANCUT,
    )
    palette = (quantized.getpalette() or [])[: _PALETTE_COLORS * 3]
    best_color: RGBColor | None = None
    best_score = -1.0

    for offset in range(0, len(palette), 3):
        if offset + 2 >= len(palette):
            break
        color = palette[offset], palette[offset + 1], palette[offset + 2]
        _hue, saturation, value = colorsys.rgb_to_hsv(
            color[0] / 255,
            color[1] / 255,
            color[2] / 255,
        )
        score = saturation * 2.5 + value
        if value < 0.15:
            score *= 0.2
        if saturation < 0.08:
            score *= 0.2
        if score > best_score:
            best_score = score
            best_color = color

    return best_color, best_score


def _without_uniform_border(
    image: Image.Image,
    threshold: int = _BORDER_THRESHOLD,
) -> Image.Image:
    width, height = image.size
    if width < 6 or height < 6:
        return image

    pixels = image.load()
    if pixels is None:
        return image
    corner = cast("RGBColor", pixels[0, 0])
    step = max(1, height // 10)
    same_count = 0
    for y in range(0, height, step):
        pixel = cast("RGBColor", pixels[0, y])
        if _colors_are_close(pixel, corner, threshold):
            same_count += 1
    if same_count < (height // step) * 0.8:
        return image

    border = 0
    maximum_border = min(width // 4, height // 4, 20)
    for x in range(maximum_border):
        pixel = cast("RGBColor", pixels[x, height // 2])
        if _colors_are_close(pixel, corner, threshold):
            border = x + 1
        else:
            break

    if 1 < border < min(width, height) / 2:
        return image.crop((border, border, width - border, height - border))
    return image


def _colors_are_close(first: RGBColor, second: RGBColor, threshold: int) -> bool:
    return all(
        abs(channel - other_channel) < threshold
        for channel, other_channel in zip(first, second, strict=True)
    )


__all__ = ["RGBColor", "dominant_image_color"]
