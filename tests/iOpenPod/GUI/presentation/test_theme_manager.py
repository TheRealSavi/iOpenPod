"""Tests for semantic palette and runtime theme switching."""

import os
import subprocess
import sys
from dataclasses import fields
from textwrap import dedent

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QColor, QImage, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QInputDialog,
    QListView,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScrollBar,
    QSlider,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QStyleOptionComboBox,
    QWidget,
)

from iOpenPod.app.backups.models import SnapshotInfo
from iOpenPod.app.core.settings.definitions import (
    AppearanceMode,
    DarkTheme,
    LightTheme,
)
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import (
    DeviceSettingsStore,
    GlobalSettingsStore,
)
from iOpenPod.app.scrobbling.models import ScrobbleResult
from iOpenPod.GUI.dialogs.linux_identity_setup import (
    LinuxIdentitySetupDialog,
    LinuxIdentityUninstallDialog,
)
from iOpenPod.GUI.dialogs.playlist_export import PlaylistExportDialog
from iOpenPod.GUI.dialogs.scrobble_report import ScrobbleReportDialog
from iOpenPod.GUI.pages.backup_page import BackupSnapshotCard
from iOpenPod.GUI.presentation.theme.backup_styles import render_backup_page_style
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.stylesheet import render_stylesheet
from iOpenPod.GUI.presentation.theme.tokens import (
    DARK_TOKENS,
    LAYOUT,
    LIGHT_TOKENS,
    ORIGINAL_DARK_TOKENS,
    Theme,
    ThemeTokens,
    resolve_typography,
    tokens_for,
)
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.player_bar import (
    _SeekSlider,  # pyright: ignore[reportPrivateUsage]
)
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    ActionButtonState,
    IconButton,
    IconButtonKind,
    apply_action_button_kind,
)


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()
ALL_THEMES: tuple[Theme, ...] = (*LightTheme, *DarkTheme)
ALL_TOKENS = tuple(tokens_for(theme) for theme in ALL_THEMES)


def test_runtime_theme_switch_updates_palette_and_stylesheet() -> None:
    original_palette = APPLICATION.palette()
    original_stylesheet = APPLICATION.styleSheet()
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    manager = ThemeManager(APPLICATION, settings)

    try:
        manager.set_mode(AppearanceMode.LIGHT)
        _assert_effective_theme(manager, LightTheme.PORCELAIN)
        assert APPLICATION.palette().color(QPalette.ColorRole.Window) == QColor(
            LIGHT_TOKENS.window
        )
        assert APPLICATION.palette().color(QPalette.ColorRole.Base) == QColor(
            LIGHT_TOKENS.surface
        )
        assert APPLICATION.palette().color(QPalette.ColorRole.AlternateBase) == QColor(
            LIGHT_TOKENS.surface_alt
        )
        assert APPLICATION.palette().color(QPalette.ColorRole.Link) == QColor(
            LIGHT_TOKENS.accent
        )
        assert APPLICATION.palette().color(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.Text,
        ) == QColor(LIGHT_TOKENS.text_disabled)

        manager.set_mode(AppearanceMode.DARK)
        _assert_effective_theme(manager, DarkTheme.SLATE)
        assert APPLICATION.palette().color(QPalette.ColorRole.Window) == QColor(
            DARK_TOKENS.window
        )

        manager.set_dark_theme(DarkTheme.ORIGINAL)
        _assert_effective_theme(manager, DarkTheme.ORIGINAL)
        assert APPLICATION.palette().color(QPalette.ColorRole.Window) == QColor(
            ORIGINAL_DARK_TOKENS.window
        )
        assert APPLICATION.styleSheet().startswith("/* Hallmark · macrostructure")
    finally:
        APPLICATION.setPalette(original_palette)
        APPLICATION.setStyleSheet(original_stylesheet)


@pytest.mark.parametrize("theme", ALL_THEMES)
def test_semantic_color_pairs_meet_contrast_floors(theme: Theme) -> None:
    tokens = tokens_for(theme)
    _assert_contrast(tokens)
    for field in fields(tokens):
        color = QColor(getattr(tokens, field.name))
        assert color.isValid() and color.alpha() == 255


@pytest.mark.parametrize("theme", ALL_THEMES)
def test_every_exact_theme_updates_the_live_application(theme: Theme) -> None:
    original_palette = APPLICATION.palette()
    original_stylesheet = APPLICATION.styleSheet()
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    manager = ThemeManager(APPLICATION, settings)
    changes: list[str] = []
    manager.effectiveThemeChanged.connect(changes.append)
    try:
        if isinstance(theme, LightTheme):
            manager.set_mode(AppearanceMode.DARK)
            manager.set_light_theme(theme)
            manager.set_mode(AppearanceMode.LIGHT)
        else:
            manager.set_mode(AppearanceMode.LIGHT)
            manager.set_dark_theme(theme)
            manager.set_mode(AppearanceMode.DARK)
        _assert_effective_theme(manager, theme)
        assert changes[-1] == theme.value
        tokens = tokens_for(theme)
        palette = APPLICATION.palette()
        assert palette.color(QPalette.ColorRole.Window) == QColor(tokens.window)
        assert palette.color(QPalette.ColorRole.Base) == QColor(tokens.surface)
        assert palette.color(QPalette.ColorRole.Highlight) == QColor(tokens.accent)
        assert palette.color(QPalette.ColorRole.HighlightedText) == QColor(
            tokens.accent_ink
        )
        assert palette.color(
            QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text
        ) == QColor(tokens.text_disabled)
        assert APPLICATION.styleSheet() == render_stylesheet(tokens, manager.typography)
    finally:
        manager.close()
        APPLICATION.setPalette(original_palette)
        APPLICATION.setStyleSheet(original_stylesheet)


@pytest.mark.parametrize(
    ("light_theme", "dark_theme"),
    (
        (LightTheme.CATPPUCCIN_LATTE, DarkTheme.CATPPUCCIN_MOCHA),
        (LightTheme.DUNE_PLOVER, DarkTheme.GRAVITY),
        (LightTheme.SEA_GLASS, DarkTheme.ORCHID),
    ),
)
def test_system_appearance_uses_the_saved_exact_themes(
    light_theme: LightTheme,
    dark_theme: DarkTheme,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_palette = APPLICATION.palette()
    original_stylesheet = APPLICATION.styleSheet()
    hints = APPLICATION.styleHints()
    scheme = Qt.ColorScheme.Light
    monkeypatch.setattr(hints, "colorScheme", lambda: scheme)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    manager = ThemeManager(APPLICATION, settings)
    try:
        manager.set_mode(AppearanceMode.SYSTEM)
        manager.set_light_theme(light_theme)
        manager.set_dark_theme(dark_theme)
        _assert_effective_theme(manager, light_theme)
        scheme = Qt.ColorScheme.Dark
        hints.colorSchemeChanged.emit(scheme)
        _assert_effective_theme(manager, dark_theme)
        scheme = Qt.ColorScheme.Light
        hints.colorSchemeChanged.emit(scheme)
        _assert_effective_theme(manager, light_theme)
    finally:
        manager.close()
        APPLICATION.setPalette(original_palette)
        APPLICATION.setStyleSheet(original_stylesheet)


@pytest.mark.parametrize(
    ("theme", "window", "surface", "accent"),
    (
        (LightTheme.CATPPUCCIN_LATTE, "#EFF1F5", "#E7E9EF", "#1E66F5"),
        (DarkTheme.CATPPUCCIN_FRAPPE, "#303446", "#34384A", "#8CAAEE"),
        (DarkTheme.CATPPUCCIN_MACCHIATO, "#24273A", "#282B3F", "#8AADF4"),
        (DarkTheme.CATPPUCCIN_MOCHA, "#1E1E2E", "#222333", "#89B4FA"),
        (LightTheme.DUNE_PLOVER, "#F5EEDC", "#F7F1E3", "#456D67"),
        (LightTheme.SEA_GLASS, "#EDF6F7", "#E7F1F2", "#167C9C"),
        (DarkTheme.GRAVITY, "#030507", "#0E1D2E", "#A9D8F5"),
        (DarkTheme.NORTHERN_LIGHTS, "#0B1726", "#102439", "#78E0A4"),
        (DarkTheme.ORCHID, "#111018", "#252231", "#C56BD8"),
    ),
)
def test_original_palette_identity_is_preserved(
    theme: Theme, window: str, surface: str, accent: str
) -> None:
    tokens = tokens_for(theme)
    assert (tokens.window, tokens.surface, tokens.accent) == (window, surface, accent)


def test_typography_uses_a_positive_platform_point_scale() -> None:
    typography = resolve_typography()
    stylesheet = render_stylesheet(LIGHT_TOKENS, typography)
    font_size_rules = (
        line.strip() for line in stylesheet.splitlines() if "font-size:" in line
    )

    assert typography.body
    assert typography.display
    assert typography.mono
    assert 0 < typography.small_pt < typography.body_pt
    assert typography.table_header_pt >= typography.body_pt
    assert typography.album_card_detail_pt >= typography.body_pt
    assert typography.album_card_title_pt > typography.album_card_detail_pt
    assert typography.table_header_pt >= 12.0
    assert typography.album_card_detail_pt >= 12.0
    assert typography.album_card_title_pt >= 14.0
    assert typography.body_pt < typography.heading_pt < typography.title_pt
    assert all(rule.endswith("pt;") for rule in font_size_rules)


def test_layout_tokens_define_one_compact_desktop_scale() -> None:
    spacing = (
        LAYOUT.space_3xs,
        LAYOUT.space_2xs,
        LAYOUT.space_xs,
        LAYOUT.space_sm,
        LAYOUT.space_md,
        LAYOUT.space_lg,
        LAYOUT.space_xl,
        LAYOUT.space_2xl,
        LAYOUT.space_3xl,
    )

    assert spacing == tuple(sorted(set(spacing)))
    assert spacing[0] == 2
    assert all(value % 4 == 0 for value in spacing[1:])
    assert (
        LAYOUT.control_height_compact
        < LAYOUT.control_height
        < LAYOUT.control_height_large
    )
    assert LAYOUT.control_height_large == LAYOUT.minimum_touch_target
    assert LAYOUT.checkbox_indicator_size > LAYOUT.icon_size
    assert LAYOUT.checkbox_indicator_size < LAYOUT.control_height_compact
    assert LAYOUT.combo_indicator_width == LAYOUT.control_height
    assert LAYOUT.icon_button_size == LAYOUT.control_height
    assert LAYOUT.scrollbar_extent < LAYOUT.control_height_compact
    assert LAYOUT.radius_control < LAYOUT.radius_panel < LAYOUT.radius_pill
    assert LAYOUT.sidebar_width >= 7 * LAYOUT.control_height
    assert LAYOUT.source_list_width > LAYOUT.sidebar_width
    assert LAYOUT.artwork_source_list_width >= LAYOUT.source_list_width
    assert LAYOUT.player_height > LAYOUT.control_height_large
    assert LAYOUT.player_surface_height == LAYOUT.player_height
    assert LAYOUT.player_surface_maximum_width == 1200
    assert LAYOUT.player_artwork_size < LAYOUT.player_surface_height
    assert LAYOUT.player_skip_icon_size < LAYOUT.player_play_icon_size
    assert LAYOUT.player_volume_minimum_width < LAYOUT.player_volume_width
    assert LAYOUT.page_header_height > LAYOUT.control_height
    assert (
        LAYOUT.album_card_padding,
        LAYOUT.album_caption_gap,
        LAYOUT.album_artwork_size,
        LAYOUT.album_card_width,
        LAYOUT.album_card_minimum_height,
    ) == (6, 6, 168, 180, 228)
    assert LAYOUT.album_card_width == (
        LAYOUT.album_artwork_size + (2 * LAYOUT.album_card_padding)
    )
    assert LAYOUT.album_card_minimum_height > LAYOUT.album_card_width
    assert LAYOUT.track_row_height == LAYOUT.control_height
    assert LAYOUT.track_table_header_height > LAYOUT.track_row_height
    assert LAYOUT.track_list_handle_height == LAYOUT.minimum_touch_target


@pytest.mark.parametrize(
    "tokens",
    ALL_TOKENS,
)
def test_player_depth_is_derived_from_every_semantic_theme(
    tokens: ThemeTokens,
) -> None:
    stylesheet = render_stylesheet(tokens, resolve_typography())

    assert f"stop: 0.5 {tokens.surface_alt}" in stylesheet
    assert f"stop: 0.52 {tokens.surface}" in stylesheet
    assert f"border: 1px solid {tokens.border_strong};" in stylesheet
    assert f"border-color: {tokens.scrollbar_hover};" in stylesheet
    assert "QFrame#playerBar QSlider::groove:horizontal" in stylesheet
    assert "QFrame#playerBar QSlider::sub-page:horizontal" in stylesheet
    assert "QFrame#playerBar QSlider::add-page:horizontal" in stylesheet
    assert "QFrame#playerBar QSlider::handle:horizontal" in stylesheet
    assert "border-radius: 8px;" in stylesheet


@pytest.mark.parametrize("tokens", ALL_TOKENS)
@pytest.mark.parametrize("slider_type", (QSlider, _SeekSlider))
def test_player_scrubber_track_stays_neutral_with_either_paint_path(
    tokens: ThemeTokens, slider_type: type[QSlider]
) -> None:
    # Also exercise ordinary Qt painting so the design cannot depend on the
    # fractional-position painter accidentally omitting the progress fill.
    player = QFrame()
    player.setObjectName("playerBar")
    player.setStyleSheet(render_stylesheet(tokens, resolve_typography()))
    progress = slider_type(Qt.Orientation.Horizontal, player)
    progress.setObjectName("playerProgress")
    progress.resize(300, 30)
    progress.setRange(0, 100)
    progress.setValue(50)
    volume = QSlider(Qt.Orientation.Horizontal, player)
    volume.setObjectName("volumeSlider")
    volume.resize(300, 30)
    volume.setRange(0, 100)
    volume.setValue(50)

    try:
        track = progress.grab().toImage()
        volume_track = volume.grab().toImage()
        before = track.width() // 4
        after = 3 * track.width() // 4
        center = track.height() // 2
        assert track.pixelColor(before, center) == track.pixelColor(after, center)
        assert track.pixelColor(before, center) != track.pixelColor(before, 0)
        assert volume_track.pixelColor(before, center) != volume_track.pixelColor(
            after, center
        )
    finally:
        player.close()


def test_modern_controls_use_logical_theme_geometry() -> None:
    original_stylesheet = APPLICATION.styleSheet()
    stylesheet = render_stylesheet(LIGHT_TOKENS, resolve_typography())
    APPLICATION.setStyleSheet(stylesheet)

    combo = AppComboBox()
    scrollbar = QScrollBar()
    try:
        combo.addItems(["System default", "Light", "Dark"])
        combo.insertSeparator(1)
        combo.resize(320, LAYOUT.control_height)
        combo.ensurePolished()
        option = QStyleOptionComboBox()
        combo.initStyleOption(option)
        indicator_rect = combo.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxArrow,
            combo,
        )
        combo.view().ensurePolished()
        scrollbar.ensurePolished()

        assert combo.property("themedIndicator") is True
        assert isinstance(combo.view(), QListView)
        assert combo.view().property("themedComboPopup") is True
        assert isinstance(combo.view().itemDelegate(), QStyledItemDelegate)
        assert combo.view().sizeHintForRow(0) == LAYOUT.control_height
        assert combo.view().sizeHintForRow(1) == (2 * LAYOUT.space_2xs) + 1
        assert indicator_rect.width() == LAYOUT.combo_indicator_width
        assert scrollbar.sizeHint().width() == LAYOUT.scrollbar_extent
        assert "QScrollBar::handle:vertical:hover" in stylesheet
        assert "QScrollBar::handle:vertical:pressed" in stylesheet
        assert "QScrollBar::add-line:vertical" in stylesheet
        assert 'QComboBox[themedIndicator="true"]::down-arrow' in stylesheet
        assert 'QListView[themedComboPopup="true"]::item:hover' in stylesheet
        assert 'QListView[themedComboPopup="true"]::item:selected' in stylesheet
        assert 'QTableView[trackTable="true"]::item:selected:hover' in stylesheet
        assert 'QPushButton[kind="danger"]' in stylesheet
        assert 'QPushButton[kind="inline"]' in stylesheet
        assert f"border-radius: {LAYOUT.control_height_compact // 2}px;" in stylesheet
        assert 'QPushButton[kind="secondary"]' in stylesheet
        assert 'QPushButton[state="loading"]' in stylesheet
        assert 'QPushButton[state="error"]' in stylesheet
        assert 'QPushButton[state="success"]' in stylesheet
        assert 'QToolButton[iconButton="true"][kind="quiet"]' in stylesheet
        assert 'QToolButton[iconButton="true"][kind="subtle"]' in stylesheet
        assert 'QToolButton[iconButton="true"][kind="danger"]' in stylesheet
        assert f"background-color: {LIGHT_TOKENS.surface_alt};" in stylesheet
        assert "QFrame#nowPlayingSurface" in stylesheet
        assert f"border-left: 1px solid {LIGHT_TOKENS.border};" in stylesheet
        assert f"border-right: 1px solid {LIGHT_TOKENS.border};" in stylesheet
        assert "QFrame#playerBar QSlider::groove:horizontal" in stylesheet
        assert "QFrame#playerBar QSlider::sub-page:horizontal" in stylesheet
        assert "QFrame#playerBar QSlider::add-page:horizontal" in stylesheet
        assert "QFrame#playerBar QSlider::handle:horizontal" in stylesheet
        assert "background: qlineargradient(" in stylesheet
        assert f"stop: 0.5 {LIGHT_TOKENS.surface_alt}" in stylesheet
        assert f"stop: 0.52 {LIGHT_TOKENS.surface}" in stylesheet
        assert f"border: 1px solid {LIGHT_TOKENS.border_strong};" in stylesheet
        assert "border-radius: 8px;" in stylesheet
        assert "QToolButton#newPlaylistButton:focus" in stylesheet
        assert 'QPushButton[navItem="true"]:focus' in stylesheet
        assert (
            'QFrame[viewModes="true"] QToolButton[iconButton="true"]:focus'
            in stylesheet
        )
        assert 'QWidget#smartRuleGroup[ruleGroupTone="base"]' in stylesheet
        assert 'QWidget#smartRuleGroup[ruleGroupTone="alternate"]' in stylesheet
        assert (
            f"selection-background-color: {LIGHT_TOKENS.surface_selected};"
            in stylesheet
        )
    finally:
        combo.close()
        scrollbar.close()
        APPLICATION.setStyleSheet(original_stylesheet)


def test_export_popup_surfaces_are_opaque_and_theme_owned() -> None:
    stylesheet = render_stylesheet(DARK_TOKENS, resolve_typography())

    assert "QDialog#playlistExportDialog" in stylesheet
    assert "QFileDialog" in stylesheet
    assert "QProgressDialog#libraryExportProgress" in stylesheet
    assert "QMessageBox" in stylesheet
    assert "QLabel#dialogTitle" in stylesheet
    assert "QRadioButton::indicator:checked" in stylesheet
    assert "QProgressDialog#libraryExportProgress QProgressBar::chunk" in stylesheet
    assert f"background-color: {DARK_TOKENS.window};" in stylesheet


@pytest.mark.parametrize(
    "tokens",
    ALL_TOKENS,
)
def test_backup_note_popup_renders_the_active_theme_background(
    tokens: ThemeTokens,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_stylesheet = APPLICATION.styleSheet()
    typography = resolve_typography()
    APPLICATION.setStyleSheet(render_stylesheet(tokens, typography))
    card = BackupSnapshotCard(
        SnapshotInfo("snapshot-1", "2026-09-12", "roadpod", "RoadPod", note="Keep"),
        can_restore=False,
        restore_hint="",
    )
    card.setStyleSheet(render_backup_page_style(tokens, typography))
    rendered: list[QImage] = []

    def capture_dialog(dialog: QInputDialog) -> int:
        dialog.show()
        APPLICATION.processEvents()
        rendered.append(dialog.grab().toImage())
        dialog.hide()
        return QInputDialog.DialogCode.Rejected

    monkeypatch.setattr(QInputDialog, "exec", capture_dialog)

    try:
        edit = card.findChild(QAction, "backupEditNote")
        assert edit is not None
        edit.trigger()
        assert len(rendered) == 1
        assert rendered[0].pixelColor(2, 2) == QColor(tokens.window)
    finally:
        card.close()
        card.deleteLater()
        APPLICATION.setStyleSheet(original_stylesheet)


@pytest.mark.parametrize(
    "tokens",
    ALL_TOKENS,
)
def test_export_popup_surfaces_render_the_active_theme_background(
    tokens: ThemeTokens,
) -> None:
    original_stylesheet = APPLICATION.styleSheet()
    APPLICATION.setStyleSheet(render_stylesheet(tokens, resolve_typography()))
    options = PlaylistExportDialog(2)
    file_dialog = QFileDialog()
    file_dialog.setOption(QFileDialog.Option.DontUseNativeDialog, on=True)
    file_dialog.setFileMode(QFileDialog.FileMode.Directory)
    progress = QProgressDialog("Exporting", "Cancel", 0, 2)
    progress.setObjectName("libraryExportProgress")
    message = QMessageBox(QMessageBox.Icon.Information, "Done", "Export complete")
    popups = (options, file_dialog, progress, message)

    try:
        for popup in popups:
            popup.resize(360, 180)
            popup.show()
            popup.ensurePolished()
        APPLICATION.processEvents()

        for popup in popups:
            rendered = popup.grab().toImage()
            assert rendered.pixelColor(2, 2) == QColor(tokens.window)
    finally:
        for popup in popups:
            popup.close()
        APPLICATION.setStyleSheet(original_stylesheet)


@pytest.mark.parametrize(
    "tokens",
    ALL_TOKENS,
)
def test_linux_identity_setup_renders_the_active_theme_background(
    tokens: ThemeTokens,
) -> None:
    original_stylesheet = APPLICATION.styleSheet()
    APPLICATION.setStyleSheet(render_stylesheet(tokens, resolve_typography()))
    dialogs = (LinuxIdentitySetupDialog(), LinuxIdentityUninstallDialog())

    try:
        for dialog in dialogs:
            dialog.show()
            dialog.ensurePolished()
        APPLICATION.processEvents()

        for dialog in dialogs:
            rendered = dialog.grab().toImage()
            assert rendered.pixelColor(2, 2) == QColor(tokens.window)
    finally:
        for dialog in dialogs:
            dialog.close()
        APPLICATION.setStyleSheet(original_stylesheet)


def test_scrobble_report_renders_and_switches_with_every_app_theme() -> None:
    original_palette = APPLICATION.palette()
    original_stylesheet = APPLICATION.styleSheet()
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    manager = ThemeManager(APPLICATION, settings)
    parent = QWidget()
    dialog = ScrobbleReportDialog(ScrobbleResult(accepted=39, adjusted=39), parent)
    report = dialog.findChild(QPlainTextEdit, "scrobbleReportText")
    assert report is not None
    dialog.show()
    try:
        for theme in ALL_THEMES:
            if isinstance(theme, LightTheme):
                manager.set_light_theme(theme)
                manager.set_mode(AppearanceMode.LIGHT)
            else:
                manager.set_dark_theme(theme)
                manager.set_mode(AppearanceMode.DARK)
            APPLICATION.processEvents()
            tokens = tokens_for(theme)
            background = dialog.grab().toImage()
            assert background.pixelColor(2, 2) == QColor(tokens.window), theme
            viewport = report.viewport().grab().toImage()
            assert viewport.pixelColor(
                viewport.width() // 2, viewport.height() // 2
            ) == QColor(tokens.surface), theme
            frame = report.grab().toImage()
            assert frame.pixelColor(0, frame.height() // 2) == QColor(tokens.border), (
                theme
            )
            palette = report.palette()
            assert palette.color(QPalette.ColorRole.Text) == QColor(tokens.text), theme
            assert palette.color(QPalette.ColorRole.Highlight) == QColor(
                tokens.surface_selected
            ), theme
            assert palette.color(QPalette.ColorRole.HighlightedText) == QColor(
                tokens.text
            ), theme
    finally:
        dialog.close()
        parent.close()
        parent.deleteLater()
        manager.close()
        APPLICATION.setPalette(original_palette)
        APPLICATION.setStyleSheet(original_stylesheet)


def test_action_button_exposes_global_semantic_kind() -> None:
    button = ActionButton("Continue")
    try:
        assert button.kind is ActionButtonKind.SECONDARY
        assert button.property("kind") == "secondary"
        assert button.state is ActionButtonState.DEFAULT
        assert button.property("state") == "default"

        button.set_kind(ActionButtonKind.DANGER)
        button.set_state(ActionButtonState.ERROR)
        assert button.property("kind") == "danger"
        assert button.property("state") == "error"
        button.set_kind(ActionButtonKind.INLINE)
        assert button.property("kind") == "inline"
        assert button.cursor().shape() is Qt.CursorShape.PointingHandCursor
        button.setEnabled(False)
        assert button.cursor().shape() is Qt.CursorShape.ArrowCursor
    finally:
        button.close()


def test_qt_created_button_accepts_the_same_global_semantic_kind() -> None:
    button = QPushButton("Apply")
    try:
        apply_action_button_kind(button, ActionButtonKind.PRIMARY)

        assert button.property("kind") == "primary"
        assert button.cursor().shape() is Qt.CursorShape.PointingHandCursor
    finally:
        button.close()


def test_icon_button_exposes_global_semantic_kind() -> None:
    button = IconButton("grid", "Grid view", kind=IconButtonKind.QUIET)
    try:
        assert button.kind is IconButtonKind.QUIET
        assert button.property("kind") == "quiet"
        assert button.property("primary") is False
    finally:
        button.close()


def test_subtle_icon_button_uses_supporting_text_color() -> None:
    original_palette = APPLICATION.palette()
    original_stylesheet = APPLICATION.styleSheet()
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    manager = ThemeManager(APPLICATION, settings)
    button = IconButton("skip-back", "Previous", kind=IconButtonKind.SUBTLE)

    try:
        manager.set_mode(AppearanceMode.DARK)
        manager.set_mode(AppearanceMode.LIGHT)
        APPLICATION.processEvents()

        assert button.kind is IconButtonKind.SUBTLE
        assert button.property("kind") == "subtle"
        icon = button.icon().pixmap(button.iconSize()).toImage()
        assert QColor(LIGHT_TOKENS.text_secondary).rgba() in {
            icon.pixelColor(x, y).rgba()
            for y in range(icon.height())
            for x in range(icon.width())
        }
    finally:
        button.close()
        APPLICATION.setPalette(original_palette)
        APPLICATION.setStyleSheet(original_stylesheet)


def test_action_button_kinds_paint_from_each_global_theme() -> None:
    original_stylesheet = APPLICATION.styleSheet()
    secondary = ActionButton("Secondary")
    primary = ActionButton("Primary", kind=ActionButtonKind.PRIMARY)
    danger = ActionButton("Danger", kind=ActionButtonKind.DANGER)
    inline = ActionButton("Inline", kind=ActionButtonKind.INLINE)
    buttons = (secondary, primary, danger, inline)
    for button in buttons:
        button.resize(140, LAYOUT.control_height_large)
        button.show()

    try:
        for tokens in (LIGHT_TOKENS, DARK_TOKENS, ORIGINAL_DARK_TOKENS):
            APPLICATION.setStyleSheet(render_stylesheet(tokens, resolve_typography()))
            APPLICATION.processEvents()

            secondary_colors = _button_colors(secondary)
            primary_colors = _button_colors(primary)
            danger_colors = _button_colors(danger)
            inline_colors = _button_colors(inline)
            assert QColor(tokens.surface).rgba() in secondary_colors
            assert QColor(tokens.border_strong).rgba() in secondary_colors
            assert QColor(tokens.accent).rgba() in primary_colors
            assert QColor(tokens.danger).rgba() in danger_colors
            assert QColor(tokens.accent).rgba() in inline_colors

            primary.activateWindow()
            primary.setFocus(Qt.FocusReason.TabFocusReason)
            APPLICATION.processEvents()
            assert QColor(tokens.focus).rgba() in _button_colors(primary)

            secondary.setEnabled(False)
            APPLICATION.processEvents()
            disabled_colors = _button_colors(secondary)
            assert QColor(tokens.surface_alt).rgba() in disabled_colors
            assert QColor(tokens.border).rgba() in disabled_colors
            secondary.setEnabled(True)
    finally:
        for button in buttons:
            button.close()
        APPLICATION.setStyleSheet(original_stylesheet)


def test_action_button_glyph_follows_theme_and_disabled_colors() -> None:
    original_palette = APPLICATION.palette()
    original_stylesheet = APPLICATION.styleSheet()
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    manager = ThemeManager(APPLICATION, settings)
    button = ActionButton("Play Next", glyph="play-next")
    button.show()
    try:
        for mode in (AppearanceMode.LIGHT, AppearanceMode.DARK):
            manager.set_mode(mode)
            for enabled in (True, False):
                button.setEnabled(enabled)
                APPLICATION.processEvents()
                group = (
                    QPalette.ColorGroup.Active
                    if enabled
                    else QPalette.ColorGroup.Disabled
                )
                expected = button.palette().color(group, QPalette.ColorRole.ButtonText)
                icon = button.icon().pixmap(button.iconSize()).toImage()
                assert expected.rgba() in {
                    icon.pixelColor(x, y).rgba()
                    for y in range(icon.height())
                    for x in range(icon.width())
                }
    finally:
        button.close()
        APPLICATION.setPalette(original_palette)
        APPLICATION.setStyleSheet(original_stylesheet)


def test_checkbox_indicator_remains_visible_when_checked_in_each_theme() -> None:
    original_palette = APPLICATION.palette()
    original_stylesheet = APPLICATION.styleSheet()
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    manager = ThemeManager(APPLICATION, settings)
    checkbox = QCheckBox("Live updating")
    checkbox.resize(180, LAYOUT.control_height_large)
    checkbox.show()

    try:
        for theme in ALL_THEMES:
            if isinstance(theme, LightTheme):
                manager.set_light_theme(theme)
                manager.set_mode(AppearanceMode.LIGHT)
            else:
                manager.set_dark_theme(theme)
                manager.set_mode(AppearanceMode.DARK)
            tokens = tokens_for(theme)
            checkbox.setChecked(False)
            checkbox.clearFocus()
            APPLICATION.processEvents()
            indicator_size = _checkbox_indicator_size(checkbox)
            painted_size = _checkbox_indicator_painted_size(checkbox, tokens.window)
            unchecked = _checkbox_indicator_colors(checkbox, tokens.window)

            checkbox.setChecked(True)
            APPLICATION.processEvents()
            checked = _checkbox_indicator_colors(checkbox, tokens.window)

            assert _contains_any_color(
                unchecked,
                tokens.surface,
                tokens.surface_hover,
            )
            assert _contains_any_color(
                unchecked,
                tokens.border_strong,
                tokens.text_secondary,
            )
            assert indicator_size == (
                LAYOUT.checkbox_indicator_size,
                LAYOUT.checkbox_indicator_size,
            )
            assert painted_size[0] >= 18
            assert painted_size[1] >= 18
            assert _contains_any_color(
                checked,
                tokens.accent,
                tokens.accent_hover,
            )
            assert QColor(tokens.border_strong).rgba() in checked
            assert QColor(tokens.accent_ink).rgba() in checked
    finally:
        checkbox.close()
        manager.close()
        APPLICATION.setPalette(original_palette)
        APPLICATION.setStyleSheet(original_stylesheet)


def test_context_menu_paints_semantic_surface_and_hover_states() -> None:
    original_palette = APPLICATION.palette()
    original_stylesheet = APPLICATION.styleSheet()
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    manager = ThemeManager(APPLICATION, settings)
    manager.set_mode(AppearanceMode.DARK)
    menu = QMenu()

    try:
        action = menu.addAction("Resize Column to Fit")
        menu.addSeparator()
        menu.addMenu("Add Column").addAction("Size")
        menu.popup(QPoint(100, 100))
        APPLICATION.processEvents()

        resting = menu.grab().toImage()
        action_rect = menu.actionGeometry(action)
        menu.setActiveAction(action)
        APPLICATION.processEvents()
        hovered = menu.grab().toImage()

        resting_colors = {
            resting.pixelColor(x, y).rgba()
            for y in range(action_rect.top(), action_rect.bottom() + 1)
            for x in range(action_rect.left(), action_rect.right() + 1)
        }
        hovered_colors = {
            hovered.pixelColor(x, y).rgba()
            for y in range(action_rect.top(), action_rect.bottom() + 1)
            for x in range(action_rect.left(), action_rect.right() + 1)
        }

        assert QColor(DARK_TOKENS.surface).rgba() in resting_colors
        assert QColor(DARK_TOKENS.surface_hover).rgba() in hovered_colors
        assert any(
            resting.pixelColor(x, y) != hovered.pixelColor(x, y)
            for y in range(action_rect.top(), action_rect.bottom() + 1)
            for x in range(action_rect.left(), action_rect.right() + 1)
        )
    finally:
        menu.close()
        APPLICATION.setPalette(original_palette)
        APPLICATION.setStyleSheet(original_stylesheet)


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="The invalid point-size warning is emitted by Qt's Windows popup path.",
)
def test_combobox_popup_does_not_emit_invalid_point_size_warning() -> None:
    probe = dedent(
        """
        from PySide6.QtCore import qInstallMessageHandler
        from PySide6.QtWidgets import QApplication, QComboBox

        from iOpenPod.GUI.presentation.theme.stylesheet import render_stylesheet
        from iOpenPod.GUI.presentation.theme.tokens import (
            LIGHT_TOKENS,
            resolve_typography,
        )

        messages = []

        def capture(_kind, _context, message):
            messages.append(message)

        previous = qInstallMessageHandler(capture)
        application = QApplication([])
        application.setStyleSheet(
            render_stylesheet(LIGHT_TOKENS, resolve_typography())
        )
        combo = QComboBox()
        combo.addItems(["System default", "Light", "Dark"])
        combo.show()
        combo.showPopup()
        application.processEvents()
        combo.hidePopup()
        combo.close()
        qInstallMessageHandler(previous)

        print("\\n".join(messages))
        """
    )
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "windows"
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    output = completed.stdout + completed.stderr

    assert completed.returncode == 0, output
    assert "QFont::setPointSize: Point size <= 0" not in output


def _assert_contrast(tokens: ThemeTokens) -> None:
    assert _contrast_ratio(tokens.text, tokens.window) >= 7.0
    assert _contrast_ratio(tokens.text, tokens.surface) >= 7.0
    assert _contrast_ratio(tokens.text_secondary, tokens.window) >= 4.5
    assert _contrast_ratio(tokens.text_secondary, tokens.surface) >= 4.5
    assert _contrast_ratio(tokens.text_disabled, tokens.surface) >= 3.0
    for surface in (
        tokens.surface_alt,
        tokens.surface_hover,
        tokens.surface_pressed,
        tokens.surface_selected,
    ):
        assert _contrast_ratio(tokens.text, surface) >= 4.5
        assert _contrast_ratio(tokens.text_secondary, surface) >= 4.5
    for accent_fill in (
        tokens.accent,
        tokens.accent_hover,
        tokens.accent_pressed,
    ):
        assert _contrast_ratio(tokens.accent_ink, accent_fill) >= 4.5
    assert _contrast_ratio(tokens.focus, tokens.window) >= 3.0
    assert _contrast_ratio(tokens.focus, tokens.surface) >= 3.0
    assert _contrast_ratio(tokens.border_strong, tokens.surface) >= 3.0
    assert _contrast_ratio(tokens.scrollbar, tokens.window) >= 3.0
    assert _contrast_ratio(tokens.scrollbar, tokens.surface) >= 3.0
    assert _contrast_ratio(tokens.scrollbar_hover, tokens.surface) >= 4.5
    assert _contrast_ratio(tokens.accent, tokens.surface) >= 3.0
    assert _contrast_ratio(tokens.accent, tokens.surface_selected) >= 3.0
    for status in (tokens.danger, tokens.warning, tokens.success):
        assert _contrast_ratio(status, tokens.surface) >= 4.5


def _assert_effective_theme(manager: ThemeManager, expected: Theme) -> None:
    assert manager.effective_theme is expected


def _checkbox_indicator_colors(
    checkbox: QCheckBox,
    background: str,
) -> set[int]:
    option = QStyleOptionButton()
    checkbox.initStyleOption(option)
    indicator_rect = checkbox.style().subElementRect(
        QStyle.SubElement.SE_CheckBoxIndicator,
        option,
        checkbox,
    )
    image = QImage(checkbox.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor(background))
    painter = QPainter(image)
    checkbox.render(painter, QPoint())
    painter.end()
    return {
        image.pixelColor(x, y).rgba()
        for y in range(indicator_rect.top(), indicator_rect.bottom() + 1)
        for x in range(indicator_rect.left(), indicator_rect.right() + 1)
    }


def _checkbox_indicator_size(checkbox: QCheckBox) -> tuple[int, int]:
    option = QStyleOptionButton()
    checkbox.initStyleOption(option)
    indicator_rect = checkbox.style().subElementRect(
        QStyle.SubElement.SE_CheckBoxIndicator,
        option,
        checkbox,
    )
    return indicator_rect.width(), indicator_rect.height()


def _checkbox_indicator_painted_size(
    checkbox: QCheckBox,
    background: str,
) -> tuple[int, int]:
    option = QStyleOptionButton()
    checkbox.initStyleOption(option)
    indicator_rect = checkbox.style().subElementRect(
        QStyle.SubElement.SE_CheckBoxIndicator,
        option,
        checkbox,
    )
    image = QImage(checkbox.size(), QImage.Format.Format_ARGB32)
    background_color = QColor(background)
    image.fill(background_color)
    painter = QPainter(image)
    checkbox.render(painter, QPoint())
    painter.end()
    painted = [
        (x, y)
        for y in range(indicator_rect.top(), indicator_rect.bottom() + 1)
        for x in range(indicator_rect.left(), indicator_rect.right() + 1)
        if image.pixelColor(x, y) != background_color
    ]
    assert painted
    xs, ys = zip(*painted, strict=True)
    return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def _button_colors(button: QPushButton) -> set[int]:
    image = button.grab().toImage()
    return {
        image.pixelColor(x, y).rgba()
        for y in range(image.height())
        for x in range(image.width())
    }


def _contains_any_color(pixels: set[int], *colors: str) -> bool:
    return any(QColor(color).rgba() in pixels for color in colors)


def _contrast_ratio(foreground: str, background: str) -> float:
    lighter = max(_relative_luminance(foreground), _relative_luminance(background))
    darker = min(_relative_luminance(foreground), _relative_luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


def _relative_luminance(color_value: str) -> float:
    color = QColor(color_value)
    red = float(color.redF())
    green = float(color.greenF())
    blue = float(color.blueF())
    channels = tuple(_linearize(channel) for channel in (red, green, blue))
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _linearize(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return float(((channel + 0.055) / 1.055) ** 2.4)
