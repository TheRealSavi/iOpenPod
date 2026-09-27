"""Rounded Track-header shading stays opaque and readable in every palette."""

from itertools import pairwise

import pytest
from PySide6.QtGui import QColor

from iOpenPod.app.core.settings.definitions import DarkTheme, LightTheme
from iOpenPod.GUI.presentation.theme.dynamic import round_header_colors
from iOpenPod.GUI.presentation.theme.tokens import Theme, tokens_for


@pytest.mark.parametrize("theme", [*LightTheme, *DarkTheme])
@pytest.mark.parametrize(
    "source",
    [
        (0, 0, 0),
        (255, 255, 255),
        (255, 255, 0),
        (0, 0, 255),
        (24, 216, 24),
        (216, 24, 80),
    ],
)
def test_round_shading_is_opaque_and_preserves_text_contrast(
    theme: Theme,
    source: tuple[int, int, int],
) -> None:
    tokens = tokens_for(theme)
    colors = round_header_colors(source, tokens)
    text_luminance = _luminance(QColor(tokens.text))
    stops = (colors.top, colors.highlight, colors.fill, colors.bottom)
    for start, end in pairwise(stops):
        start_rgb = (start.red(), start.green(), start.blue(), start.alpha())
        end_rgb = (end.red(), end.green(), end.blue(), end.alpha())
        # Check the gradient between stops as well as the authored colors.
        for step in range(11):
            shade = QColor(
                *(
                    round(a + (b - a) * step / 10)
                    for a, b in zip(start_rgb, end_rgb, strict=True)
                )
            )
            assert shade.alpha() == 255
            luminance = _luminance(shade)
            assert (max(luminance, text_luminance) + 0.05) / (
                min(luminance, text_luminance) + 0.05
            ) >= 4.5


def _luminance(color: QColor) -> float:
    channels = tuple(
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in (color.redF(), color.greenF(), color.blueF())
    )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
