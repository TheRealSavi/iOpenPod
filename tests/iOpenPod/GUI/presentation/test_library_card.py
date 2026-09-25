"""Shared Library-card geometry and semantic interaction painting."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.GUI.presentation.image_color import RGBColor
from iOpenPod.GUI.presentation.library_card import (
    library_card_size,
    paint_library_card,
)
from iOpenPod.GUI.presentation.theme.tokens import (
    DARK_TOKENS,
    LAYOUT,
    LIGHT_TOKENS,
    ORIGINAL_DARK_TOKENS,
    ThemeTokens,
    resolve_typography,
)


def test_library_card_height_grows_with_host_relative_typography() -> None:
    typography = replace(
        resolve_typography(),
        album_card_title_pt=28.0,
        album_card_detail_pt=22.0,
    )

    size = library_card_size(APPLICATION.font(), typography)

    assert size.width() == LAYOUT.album_card_width
    assert size.height() > LAYOUT.album_card_minimum_height


@pytest.mark.parametrize("tokens", [LIGHT_TOKENS, DARK_TOKENS, ORIGINAL_DARK_TOKENS])
@pytest.mark.parametrize("tint", [None, (216, 24, 80), (24, 100, 216), (240, 220, 40)])
@pytest.mark.parametrize("dpr", [1.0, 1.5, 2.0])
def test_selection_stays_distinct_from_hover_without_focus(
    tokens: ThemeTokens,
    tint: RGBColor | None,
    dpr: float,
) -> None:
    selected = _render_card(tokens, tint, QStyle.StateFlag.State_Selected, dpr)
    hovered = _render_card(tokens, tint, QStyle.StateFlag.State_MouseOver, dpr)
    normal = _render_card(tokens, tint, QStyle.StateFlag.State_None, dpr)
    selected_hovered = _render_card(
        tokens,
        tint,
        QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver,
        dpr,
    )

    # The outline survives on both sides even when a card is not active/focused.
    for x in (1.5, LAYOUT.album_card_width - 1.5):
        point = (int(x * dpr), selected.height() // 2)
        assert selected.pixelColor(*point) == QColor(tokens.accent)
        assert selected_hovered.pixelColor(*point) == QColor(tokens.accent)
        assert hovered.pixelColor(*point) != QColor(tokens.accent)
        assert normal.pixelColor(*point) != QColor(tokens.accent)
    # Selection preserves the artwork, and Colorful Mode retains its card tint.
    assert selected.pixelColor(int(40 * dpr), int(40 * dpr)) == normal.pixelColor(
        int(40 * dpr), int(40 * dpr)
    )
    if tint is not None:
        assert selected.pixelColor(int(90 * dpr), int(4 * dpr)) == hovered.pixelColor(
            int(90 * dpr), int(4 * dpr)
        )


@pytest.mark.parametrize("tokens", [LIGHT_TOKENS, DARK_TOKENS, ORIGINAL_DARK_TOKENS])
@pytest.mark.parametrize("tint", [None, (216, 24, 80)])
def test_keyboard_focus_is_separate_from_the_persistent_selection_outline(
    tokens: ThemeTokens,
    tint: RGBColor | None,
) -> None:
    selected = _render_card(tokens, tint, QStyle.StateFlag.State_Selected)
    focused = _render_card(tokens, tint, QStyle.StateFlag.State_HasFocus)
    both = _render_card(
        tokens,
        tint,
        QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_HasFocus,
    )

    middle = selected.height() // 2
    assert both.pixelColor(1, middle) == selected.pixelColor(1, middle)
    assert focused.pixelColor(1, middle) != QColor(tokens.accent)
    # The inner dashed ring adds a geometric cue, not just a different border hue.
    focus_pixels = [both.pixelColor(4, y) for y in range(30, 70)]
    assert QColor(tokens.focus) in focus_pixels
    assert len({color.name() for color in focus_pixels}) > 1
    assert any(
        both.pixelColor(4, y) != selected.pixelColor(4, y) for y in range(30, 70)
    )


def _render_card(
    tokens: ThemeTokens,
    tint: RGBColor | None,
    state: QStyle.StateFlag,
    dpr: float = 1.0,
) -> QImage:
    typography = resolve_typography()
    option = QStyleOptionViewItem()
    option.font = QFont(APPLICATION.font())
    size = library_card_size(option.font, typography)
    option.rect = QRect(0, 0, size.width(), size.height())
    option.state = QStyle.StateFlag.State_Enabled | state
    image = QImage(
        round(size.width() * dpr),
        round(size.height() * dpr),
        QImage.Format.Format_RGB32,
    )
    image.setDevicePixelRatio(dpr)
    image.fill(QColor(tokens.window))
    painter = QPainter(image)

    paint_library_card(
        painter,
        option,
        title="Album",
        detail="Artist",
        tint=tint,
        tokens=tokens,
        typography=typography,
        paint_artwork=lambda rect: painter.fillRect(
            rect,
            QColor(tokens.artwork_coral),
        ),
    )
    painter.end()

    return image
