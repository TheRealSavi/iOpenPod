"""Generic image-color extraction and theme-owned tint recipes."""

from PIL import Image
from PySide6.QtGui import QColor

from iOpenPod.app.core.settings.definitions import DarkTheme, LightTheme
from iOpenPod.GUI.presentation.image_color import dominant_image_color
from iOpenPod.GUI.presentation.theme.dynamic import (
    colorful_card_fill,
    colorful_header_colors,
)
from iOpenPod.GUI.presentation.theme.tokens import (
    DARK_TOKENS,
    tokens_for,
)


def test_dominant_image_color_matches_original_iopenpod_algorithm() -> None:
    image = Image.new("RGB", (20, 20), (30, 102, 245))
    for x in range(4):
        for y in range(image.height):
            image.putpixel((x, y), (208, 15, 57))

    assert dominant_image_color(image) == (0, 72, 216)
    assert image.getpixel((0, 0)) == (208, 15, 57)


def test_dominant_image_color_skips_a_uniform_frame() -> None:
    image = Image.new("RGB", (40, 40), (255, 255, 255))
    for x in range(5, 35):
        for y in range(5, 35):
            image.putpixel((x, y), (30, 102, 245))

    assert dominant_image_color(image) == (0, 72, 216)


def test_dominant_image_color_accepts_wide_and_tall_uniform_images() -> None:
    assert dominant_image_color(Image.new("RGB", (80, 6), "white")) == (
        216,
        195,
        195,
    )
    assert dominant_image_color(Image.new("RGB", (6, 80), "white")) == (
        216,
        195,
        195,
    )


def test_dynamic_tints_preserve_selection_and_text_contrast() -> None:
    sources = (
        (0, 0, 0),
        (255, 255, 255),
        (255, 255, 0),
        (0, 0, 255),
        (216, 24, 80),
    )
    for theme in (*LightTheme, *DarkTheme):
        tokens = tokens_for(theme)
        for source in sources:
            fill = colorful_card_fill(source, tokens)
            selected_fill = colorful_card_fill(source, tokens, emphasized=True)
            header = colorful_header_colors(source, tokens)

            for card_fill in (fill, selected_fill):
                assert _contrast(card_fill, QColor(tokens.text)) >= 4.5
                assert _contrast(card_fill, QColor(tokens.text_secondary)) >= 4.5
            assert _contrast(header.fill, QColor(tokens.text)) >= 4.5
            assert _contrast(header.separator, header.fill) >= 1.5


def test_colorful_card_fill_uses_a_stronger_interaction_tint_when_safe() -> None:
    source = (216, 24, 80)

    fill = colorful_card_fill(source, DARK_TOKENS)
    selected_fill = colorful_card_fill(source, DARK_TOKENS, emphasized=True)

    assert fill != QColor(DARK_TOKENS.surface)
    assert selected_fill != fill


def _contrast(first: QColor, second: QColor) -> float:
    lighter = max(_luminance(first), _luminance(second))
    darker = min(_luminance(first), _luminance(second))
    return (lighter + 0.05) / (darker + 0.05)


def _luminance(color: QColor) -> float:
    channels = tuple(
        _linearize(channel) for channel in (color.redF(), color.greenF(), color.blueF())
    )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _linearize(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return float(((channel + 0.055) / 1.055) ** 2.4)
