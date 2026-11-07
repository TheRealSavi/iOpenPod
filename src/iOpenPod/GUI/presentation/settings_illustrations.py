"""Select packaged images for settings with a useful visual example."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QPainter, QPainterPath, QPalette, QPixmap

from iOpenPod.app.core.settings.definitions import DarkTheme, LightTheme
from iOpenPod.GUI.presentation.icons import glyph_icon

_CAPTURES = Path(__file__).parents[2] / "assets" / "settings"
_LANGUAGE_IMAGE = "../glyphs/language.svg"


@dataclass(frozen=True, slots=True)
class SettingExample:
    """Presentation-only identity and copy; never include editable field contents."""

    key: str
    category: str
    title: str
    description: str
    choice: str = ""
    value: str = ""
    light_theme: LightTheme = LightTheme.PORCELAIN
    dark_theme: DarkTheme = DarkTheme.SLATE


def has_setting_image(example: SettingExample) -> bool:
    """An explicit allowlist, including the dynamically composed Auto preview."""
    return (
        example.key == "appearanceModeCombo" and example.value == "system"
    ) or _example_filename(example) is not None


def _example_filename(example: SettingExample) -> str | None:
    value = example.value
    match example.key:
        case "lightThemeCombo" if value in LightTheme:
            return f"theme-{value}.png"
        case "darkThemeCombo" if value in DarkTheme:
            return f"theme-{value}.png"
        case "appearanceModeCombo" if value == "light":
            return f"theme-{example.light_theme.value}.png"
        case "appearanceModeCombo" if value == "dark":
            return f"theme-{example.dark_theme.value}.png"
        case "navigationStyleCombo":
            return {
                "sidebar": "navigation-sidebar.png",
                "compact-top-bar": "navigation-compact.png",
            }.get(value)
        case "ipodLibraryViewModeCombo":
            return {
                "split-table": "library-split.png",
                "whole-page-table": "library-whole.png",
                "itunes-11": "library-inline.png",
            }.get(value)
        case "itunes107ArtworkCombo":
            return {"True": "device-classic.png", "False": "device-standard.png"}.get(
                value
            )
        case "colorfulModeCombo":
            return {"True": "colorful-on.png", "False": "colorful-off.png"}.get(value)
        case "trackTitleBarStyleCombo":
            return {"round": "titlebar-round.png", "flat": "titlebar-flat.png"}.get(
                value
            )
        case "playerPositionCombo":
            return {"top": "player-top.png", "bottom": "player-bottom.png"}.get(value)
        case "playerAutoMinimizeCombo":
            return {"True": "idle-hidden.png", "False": "idle-visible.png"}.get(value)
        case "languageCombo":
            return _LANGUAGE_IMAGE
        case _:
            return None


def setting_image(
    example: SettingExample, palette: QPalette, device_pixel_ratio: float = 1.0
) -> QPixmap:
    """Load screenshots, compose Auto's diagonal, or render the Language glyph."""
    if example.key == "appearanceModeCombo" and example.value == "system":
        return _auto_mode_image(example)
    filename = _example_filename(example)
    if filename == _LANGUAGE_IMAGE:
        size = 512
        return glyph_icon(
            "language", size, palette.color(QPalette.ColorRole.Text), device_pixel_ratio
        ).pixmap(QSize(size, size), device_pixel_ratio)
    if filename is None:
        return QPixmap()
    if (
        not filename.startswith("theme-")
        and palette.color(QPalette.ColorRole.Window).lightness() < 128
    ):
        filename = f"slate/{filename}"
    return QPixmap(str(_CAPTURES / filename))


def _auto_mode_image(example: SettingExample) -> QPixmap:
    """Keep Light above/left of the bottom-left to top-right diagonal."""
    light = QPixmap(str(_CAPTURES / f"theme-{example.light_theme.value}.png"))
    dark = QPixmap(str(_CAPTURES / f"theme-{example.dark_theme.value}.png"))
    if light.isNull() or dark.isNull():
        return QPixmap()
    combined = light.copy()
    size = combined.deviceIndependentSize()
    triangle = QPainterPath()
    triangle.moveTo(0, size.height())
    triangle.lineTo(size.width(), 0)
    triangle.lineTo(size.width(), size.height())
    triangle.closeSubpath()
    painter = QPainter(combined)
    painter.setClipPath(triangle)
    painter.drawPixmap(
        QRectF(0, 0, size.width(), size.height()), dark, QRectF(dark.rect())
    )
    painter.end()
    return combined
