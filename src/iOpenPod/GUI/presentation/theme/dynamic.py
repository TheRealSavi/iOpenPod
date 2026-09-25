"""Theme-owned recipes for colors derived from dynamic visual content."""

from dataclasses import dataclass

from PySide6.QtGui import QColor

from iOpenPod.GUI.presentation.image_color import RGBColor
from iOpenPod.GUI.presentation.theme.tokens import ThemeTokens

_HEADER_SEPARATOR_CONTRAST = 1.5
_TEXT_CONTRAST = 4.5
_DARK_CARD_ALPHA = 30
_DARK_CARD_EMPHASIZED_ALPHA = 55
_LIGHT_CARD_ALPHA = 48
_LIGHT_CARD_EMPHASIZED_ALPHA = 82
_DARK_HEADER_OPACITY = 0.52
_LIGHT_HEADER_OPACITY = 0.30


@dataclass(frozen=True, slots=True)
class ColorfulHeaderColors:
    """Coordinated colors for an artwork-tinted Track-list header."""

    fill: QColor
    separator: QColor


def colorful_card_fill(
    color: RGBColor,
    tokens: ThemeTokens,
    *,
    emphasized: bool = False,
) -> QColor:
    """Return an opaque artwork-tinted card fill for one interaction state."""

    background = _rgb(tokens.surface)
    light_theme = _relative_luminance(background) >= 0.5
    if light_theme:
        alpha = _LIGHT_CARD_EMPHASIZED_ALPHA if emphasized else _LIGHT_CARD_ALPHA
    else:
        alpha = _DARK_CARD_EMPHASIZED_ALPHA if emphasized else _DARK_CARD_ALPHA
    text_colors = (_rgb(tokens.text), _rgb(tokens.text_secondary))
    for candidate_alpha in range(alpha, -1, -1):
        candidate = _blend(color, background, candidate_alpha / 255)
        if all(
            _contrast_ratio(candidate, text_color) >= _TEXT_CONTRAST
            for text_color in text_colors
        ):
            return QColor(*candidate)
    return QColor(*background)


def colorful_header_colors(
    color: RGBColor,
    tokens: ThemeTokens,
) -> ColorfulHeaderColors:
    """Return a readable header fill and a separator contrasted against it."""

    background = _rgb(tokens.surface_alt)
    text = _rgb(tokens.text)
    opacity = (
        _DARK_HEADER_OPACITY
        if _relative_luminance(background) < 0.5
        else _LIGHT_HEADER_OPACITY
    )
    while opacity > 0:
        candidate = _blend(color, background, opacity)
        if _contrast_ratio(candidate, text) >= 4.5:
            return ColorfulHeaderColors(
                fill=QColor(*candidate),
                separator=QColor(
                    *_normalized_for_contrast(
                        color,
                        candidate,
                        _HEADER_SEPARATOR_CONTRAST,
                    )
                ),
            )
        opacity = round(opacity - 0.04, 2)
    return ColorfulHeaderColors(
        fill=QColor(*background),
        separator=QColor(
            *_normalized_for_contrast(
                color,
                background,
                _HEADER_SEPARATOR_CONTRAST,
            )
        ),
    )


def _normalized_for_contrast(
    color: RGBColor,
    background: RGBColor,
    target: float,
) -> RGBColor:
    if _contrast_ratio(color, background) >= target:
        return color

    destination = (
        (255, 255, 255) if _relative_luminance(background) < 0.5 else (0, 0, 0)
    )
    for step in range(1, 101):
        candidate = _blend(destination, color, step / 100)
        if _contrast_ratio(candidate, background) >= target:
            return candidate
    return destination


def _blend(foreground: RGBColor, background: RGBColor, opacity: float) -> RGBColor:
    channels = tuple(
        round((foreground_channel * opacity) + (background_channel * (1 - opacity)))
        for foreground_channel, background_channel in zip(
            foreground,
            background,
            strict=True,
        )
    )
    return channels[0], channels[1], channels[2]


def _rgb(value: str) -> RGBColor:
    color = QColor(value)
    return color.red(), color.green(), color.blue()


def _contrast_ratio(first: RGBColor, second: RGBColor) -> float:
    lighter = max(_relative_luminance(first), _relative_luminance(second))
    darker = min(_relative_luminance(first), _relative_luminance(second))
    return (lighter + 0.05) / (darker + 0.05)


def _relative_luminance(color: RGBColor) -> float:
    channels = tuple(_linearize(channel / 255) for channel in color)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _linearize(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return float(((channel + 0.055) / 1.055) ** 2.4)


__all__ = [
    "ColorfulHeaderColors",
    "colorful_card_fill",
    "colorful_header_colors",
]
