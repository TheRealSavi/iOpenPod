"""Application-wide theme selection and Qt palette orchestration."""

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from iOpenPod.app.core.settings.definitions import (
    APPEARANCE_DARK_THEME,
    APPEARANCE_LIGHT_THEME,
    APPEARANCE_MODE,
    COLORFUL_MODE,
    TRACK_TITLE_BAR_STYLE,
    AppearanceMode,
    DarkTheme,
    LightTheme,
    TrackTitleBarStyle,
)
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.GUI.presentation.theme.checkbox_style import apply_checkbox_style
from iOpenPod.GUI.presentation.theme.stylesheet import render_stylesheet
from iOpenPod.GUI.presentation.theme.tokens import (
    Theme,
    ThemeTokens,
    TypographyTokens,
    resolve_typography,
    tokens_for,
)


class ThemeManager(QObject):
    """Resolve appearance mode and exact palettes, then apply them globally."""

    modeChanged = Signal(str)
    lightThemeChanged = Signal(str)
    darkThemeChanged = Signal(str)
    effectiveThemeChanged = Signal(str)
    colorfulModeChanged = Signal(bool)
    trackTitleBarStyleChanged = Signal(str)

    def __init__(
        self,
        application: QApplication,
        settings: SettingsService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._application = application
        self._settings = settings
        self._native_is_dark = _palette_is_dark(application.palette())
        self._effective_theme: Theme | None = None
        self._typography = resolve_typography()
        self._closed = False

        application_font = application.font()
        application_font.setFamily(self._typography.body)
        application_font.setPointSizeF(self._typography.body_pt)
        application.setFont(application_font)

        settings.settingChanged.connect(self._setting_changed)
        application.styleHints().colorSchemeChanged.connect(self._system_scheme_changed)
        self.apply()

    def close(self) -> None:
        """Release process-global signal subscriptions during shutdown."""

        if self._closed:
            return
        self._closed = True
        self._settings.settingChanged.disconnect(self._setting_changed)
        self._application.styleHints().colorSchemeChanged.disconnect(
            self._system_scheme_changed
        )

    @property
    def mode(self) -> AppearanceMode:
        return AppearanceMode(self._settings.get(APPEARANCE_MODE))

    @property
    def light_theme(self) -> LightTheme:
        return LightTheme(self._settings.get(APPEARANCE_LIGHT_THEME))

    @property
    def dark_theme(self) -> DarkTheme:
        return DarkTheme(self._settings.get(APPEARANCE_DARK_THEME))

    @property
    def colorful_mode(self) -> bool:
        return self._settings.get(COLORFUL_MODE)

    @property
    def track_title_bar_style(self) -> TrackTitleBarStyle:
        return TrackTitleBarStyle(self._settings.get(TRACK_TITLE_BAR_STYLE))

    @property
    def effective_theme(self) -> Theme:
        if self._effective_theme is None:
            return self._resolve_effective_theme()
        return self._effective_theme

    @property
    def tokens(self) -> ThemeTokens:
        return tokens_for(self.effective_theme)

    @property
    def typography(self) -> TypographyTokens:
        return self._typography

    def set_mode(self, mode: AppearanceMode) -> None:
        self._settings.set_global(APPEARANCE_MODE, mode.value)

    def set_light_theme(self, theme: LightTheme) -> None:
        self._settings.set_global(APPEARANCE_LIGHT_THEME, theme.value)

    def set_dark_theme(self, theme: DarkTheme) -> None:
        self._settings.set_global(APPEARANCE_DARK_THEME, theme.value)

    def set_colorful_mode(self, enabled: bool) -> None:
        self._settings.set_global(COLORFUL_MODE, enabled)

    def set_track_title_bar_style(self, style: TrackTitleBarStyle) -> None:
        self._settings.set_global(TRACK_TITLE_BAR_STYLE, style.value)

    def apply(self) -> None:
        """Apply the effective palette and stylesheet to the application."""

        previous = self._effective_theme
        effective = self._resolve_effective_theme()
        tokens = tokens_for(effective)

        apply_checkbox_style(self._application, tokens)
        self._application.setPalette(_build_palette(tokens))
        self._application.setStyleSheet(render_stylesheet(tokens, self._typography))
        self._effective_theme = effective

        self.modeChanged.emit(self.mode.value)
        self.lightThemeChanged.emit(self.light_theme.value)
        self.darkThemeChanged.emit(self.dark_theme.value)
        if effective is not previous:
            self.effectiveThemeChanged.emit(effective.value)

    def _resolve_effective_theme(self) -> Theme:
        mode = self.mode
        if mode is AppearanceMode.LIGHT:
            return self.light_theme
        if mode is AppearanceMode.DARK:
            return self.dark_theme

        color_scheme = self._application.styleHints().colorScheme()
        if color_scheme is Qt.ColorScheme.Dark:
            return self.dark_theme
        if color_scheme is Qt.ColorScheme.Light:
            return self.light_theme
        return self.dark_theme if self._native_is_dark else self.light_theme

    def _setting_changed(self, key: str, value: object) -> None:
        if key in {
            APPEARANCE_MODE.key,
            APPEARANCE_LIGHT_THEME.key,
            APPEARANCE_DARK_THEME.key,
        }:
            self.apply()
        elif key == COLORFUL_MODE.key and isinstance(value, bool):
            self.colorfulModeChanged.emit(value)
        elif key == TRACK_TITLE_BAR_STYLE.key and isinstance(value, str):
            self.trackTitleBarStyleChanged.emit(value)

    def _system_scheme_changed(self, _scheme: Qt.ColorScheme) -> None:
        if self.mode is AppearanceMode.SYSTEM:
            self.apply()


def _build_palette(tokens: ThemeTokens) -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: tokens.window,
        QPalette.ColorRole.WindowText: tokens.text,
        QPalette.ColorRole.Base: tokens.surface,
        QPalette.ColorRole.AlternateBase: tokens.surface_alt,
        QPalette.ColorRole.ToolTipBase: tokens.surface,
        QPalette.ColorRole.ToolTipText: tokens.text,
        QPalette.ColorRole.Text: tokens.text,
        QPalette.ColorRole.Button: tokens.surface,
        QPalette.ColorRole.ButtonText: tokens.text,
        QPalette.ColorRole.BrightText: tokens.danger,
        QPalette.ColorRole.Light: tokens.surface,
        QPalette.ColorRole.Midlight: tokens.surface_alt,
        QPalette.ColorRole.Mid: tokens.border,
        QPalette.ColorRole.Dark: tokens.surface_pressed,
        QPalette.ColorRole.Shadow: tokens.window,
        QPalette.ColorRole.Highlight: tokens.accent,
        QPalette.ColorRole.HighlightedText: tokens.accent_ink,
        QPalette.ColorRole.Link: tokens.accent,
        QPalette.ColorRole.LinkVisited: tokens.accent_pressed,
        QPalette.ColorRole.PlaceholderText: tokens.text_secondary,
        QPalette.ColorRole.Accent: tokens.accent,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))

    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.PlaceholderText,
    ):
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            role,
            QColor(tokens.text_disabled),
        )
    for role in (
        QPalette.ColorRole.Base,
        QPalette.ColorRole.AlternateBase,
        QPalette.ColorRole.Button,
    ):
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            role,
            QColor(tokens.surface_alt),
        )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Highlight,
        QColor(tokens.surface_pressed),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.HighlightedText,
        QColor(tokens.text_disabled),
    )
    return palette


def _palette_is_dark(palette: QPalette) -> bool:
    return palette.color(QPalette.ColorRole.Window).lightnessF() < 0.5
