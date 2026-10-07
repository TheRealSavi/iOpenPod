"""Category navigation keeps Settings reachable without one long scrolling page."""

import logging
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPalette
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QTabWidget, QWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.context import AppContext
from iOpenPod.app.core.settings.definitions import (
    APPEARANCE_DARK_THEME,
    APPEARANCE_LIGHT_THEME,
    MANAGE_VOLUME_PRESENTATION,
    MAX_BACKUPS,
    AppearanceMode,
    DarkTheme,
    LightTheme,
)
from iOpenPod.app.services.linux_identity import UdevRuleStatus, UdevRuleStatusKind
from iOpenPod.GUI.pages import settings_page
from iOpenPod.GUI.pages.settings_page import SettingsPage
from iOpenPod.GUI.presentation.theme.tokens import tokens_for
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.browser_chrome import PageHeader
from iOpenPod.GUI.widgets.themed_buttons import ActionButton


@pytest.fixture
def context() -> Iterator[AppContext]:
    context = build_context()
    yield context
    context.shutdown()


def test_about_opens_active_log_folder(
    context: AppContext, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "current" / "iopenpod.log"
    log_path.parent.mkdir()
    handler = RotatingFileHandler(log_path)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    opened: list[str] = []

    def open_url(url: QUrl) -> bool:
        opened.append(url.toLocalFile())
        return True

    monkeypatch.setattr(QDesktopServices, "openUrl", open_url)
    try:
        page = SettingsPage(
            context.settings, context.theme_manager, context.i18n_manager
        )
        try:
            about = page.findChild(QScrollArea, "aboutSettingsScroll")
            assert about is not None
            button = about.findChild(ActionButton, "openLogFolder")
            assert button is not None and button.isEnabled()
            button.click()
            assert len(opened) == 1
            assert Path(opened[0]) == log_path.parent
        finally:
            page.close()
    finally:
        root_logger.removeHandler(handler)
        handler.close()


def test_appearance_lists_and_applies_every_theme_without_retranslation_reset(
    context: AppContext,
) -> None:
    page = SettingsPage(context.settings, context.theme_manager, context.i18n_manager)
    light = page.findChild(AppComboBox, "lightThemeCombo")
    dark = page.findChild(AppComboBox, "darkThemeCombo")
    assert light is not None and dark is not None
    try:
        assert [light.itemText(i) for i in range(light.count())] == [
            "Porcelain",
            "Catppuccin Latte",
            "Dune Plover",
            "Sea Glass",
        ]
        assert [dark.itemText(i) for i in range(dark.count())] == [
            "Slate",
            "Original iOpenPod",
            "Catppuccin Frappé",
            "Catppuccin Macchiato",
            "Catppuccin Mocha",
            "Gravity",
            "Northern Lights",
            "Orchid",
        ]
        for theme in (*LightTheme, *DarkTheme):
            if isinstance(theme, LightTheme):
                control, definition, mode = (
                    light,
                    APPEARANCE_LIGHT_THEME,
                    AppearanceMode.LIGHT,
                )
            else:
                control, definition, mode = (
                    dark,
                    APPEARANCE_DARK_THEME,
                    AppearanceMode.DARK,
                )
            context.theme_manager.set_mode(mode)
            control.setCurrentIndex(control.findData(theme.value))
            assert context.settings.get(definition) == theme.value
            assert context.theme_manager.effective_theme is theme
            assert APPLICATION.palette().color(QPalette.ColorRole.Window) == QColor(
                tokens_for(theme).window
            )
            changes = QSignalSpy(context.settings.settingChanged)
            APPLICATION.sendEvent(page, QEvent(QEvent.Type.LanguageChange))
            assert control.currentData() == theme.value
            assert changes.count() == 0
        assert light.currentData() == LightTheme.SEA_GLASS.value
        assert dark.currentData() == DarkTheme.ORCHID.value
    finally:
        page.close()


def test_donation_banner_is_at_bottom_of_appearance_and_follows_theme(
    context: AppContext,
) -> None:
    page = SettingsPage(context.settings, context.theme_manager, context.i18n_manager)
    page.resize(960, 600)
    page.show()
    try:
        tabs = page.findChild(QTabWidget, "settingsTabs")
        assert tabs is not None
        appearance = tabs.widget(0)
        about = tabs.widget(tabs.count() - 1)
        assert isinstance(appearance, QScrollArea)
        assert isinstance(about, QScrollArea)
        banner = appearance.findChild(QFrame, "donationBanner")
        settings_group = appearance.findChild(QFrame, "settingGroup")
        donate = appearance.findChild(ActionButton, "donate")
        title = appearance.findChild(QLabel, "donationTitle")
        description = appearance.findChild(QLabel, "donationDescription")
        icon = appearance.findChild(QLabel, "donationIcon")
        assert banner is not None
        assert settings_group is not None
        assert donate is not None
        assert title is not None
        assert description is not None
        assert icon is not None
        assert about.findChild(ActionButton, "donate") is None
        assert banner.parent() is not about
        assert (
            banner.mapTo(appearance, banner.rect().topLeft()).y()
            > settings_group.mapTo(appearance, settings_group.rect().bottomLeft()).y()
        )
        assert title.text() == "Support iOpenPod"
        assert description.text() == (
            "iOpenPod is and always will be completely free and open source. "
            "If you like it and would like to support me, it is so very appreciated."
        )
        assert donate.text() == "Support on Ko-fi ↗"
        context.theme_manager.set_mode(AppearanceMode.LIGHT)
        APPLICATION.processEvents()
        first_icon = icon.pixmap()
        assert not first_icon.isNull()

        context.theme_manager.set_mode(AppearanceMode.DARK)
        APPLICATION.processEvents()
        dark_icon = icon.pixmap()
        assert not dark_icon.isNull()
        assert dark_icon.cacheKey() != first_icon.cacheKey()
        assert f"background-color: {context.theme_manager.tokens.surface_alt}" in (
            APPLICATION.styleSheet()
        )
    finally:
        page.close()


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_drive_appearance_setting_defaults_on_and_updates_live(
    context: AppContext, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setattr(settings_page, "sys", SimpleNamespace(platform=platform))
    page = SettingsPage(context.settings, context.theme_manager, context.i18n_manager)
    try:
        library = page.findChild(QScrollArea, "librarySettingsScroll")
        assert library is not None
        control = library.findChild(AppComboBox, "manageVolumePresentationCombo")
        assert control is not None and control.currentData() is True
        assert context.device_coordinator.volume_presentation_enabled
        control.setCurrentIndex(control.findData(False))
        assert context.settings.get(MANAGE_VOLUME_PRESENTATION) is False
        assert not context.device_coordinator.volume_presentation_enabled
        changes = QSignalSpy(context.settings.settingChanged)
        APPLICATION.sendEvent(page, QEvent(QEvent.Type.LanguageChange))
        assert control.currentData() is False and changes.count() == 0
        context.settings.reset_global(MANAGE_VOLUME_PRESENTATION)
        assert control.currentData() is True
        assert context.device_coordinator.volume_presentation_enabled
    finally:
        page.close()


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_categories_show_only_their_controls_and_platform_integration(
    context: AppContext, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    checks: list[None] = []

    def inspect() -> UdevRuleStatus:
        checks.append(None)
        return UdevRuleStatus(UdevRuleStatusKind.MISSING)

    monkeypatch.setattr(settings_page, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(settings_page, "inspect_udev_rule", inspect)
    page = SettingsPage(context.settings, context.theme_manager, context.i18n_manager)
    page.resize(900, 600)
    page.show()
    APPLICATION.processEvents()
    tabs = page.findChild(QTabWidget, "settingsTabs")
    assert tabs is not None
    categories = [
        ("Appearance", "appearanceModeCombo"),
        ("Library", "ipodLibraryViewModeCombo"),
        ("Transcoding", "lossyEncoder"),
        ("Media Tools", "mediaToolsStatus"),
        ("Sync", "computeSoundCheck"),
        ("Backups", "maxBackups"),
    ]
    if platform == "linux":
        categories.append(("Linux", "checkUdevRule"))
    categories.append(("About", "currentAppVersion"))
    visible_indices = [
        index for index in range(tabs.count()) if tabs.isTabVisible(index)
    ]
    assert [tabs.tabText(index) for index in visible_indices] == [
        label for label, _ in categories
    ]
    assert len(checks) == (1 if platform == "linux" else 0)
    changes = QSignalSpy(context.settings.settingChanged)

    for index, (_, control_name) in zip(visible_indices, categories, strict=True):
        QTest.mouseClick(
            tabs.tabBar(),
            Qt.MouseButton.LeftButton,
            pos=tabs.tabBar().tabRect(index).center(),
        )
        APPLICATION.processEvents()
        assert tabs.currentIndex() == index
        for other, (_, other_name) in zip(visible_indices, categories, strict=True):
            control = page.findChild(QWidget, other_name)
            assert control is not None
            assert control.isVisible() == (other == index)
        assert tabs.currentWidget().findChild(QWidget, control_name) is not None

    tabs.tabBar().setFocus()
    QTest.keyClick(tabs.tabBar(), Qt.Key.Key_Left)
    assert tabs.currentIndex() == visible_indices[-2]
    assert changes.count() == 0
    page.close()


def test_category_scroll_keeps_navigation_visible_and_survives_switches(
    context: AppContext,
) -> None:
    page = SettingsPage(context.settings, context.theme_manager, context.i18n_manager)
    page.resize(960, 380)
    page.show()
    APPLICATION.processEvents()
    tabs = page.findChild(QTabWidget, "settingsTabs")
    header = page.findChild(PageHeader)
    note = page.findChild(QLabel, "pageMeta")
    appearance = page.findChild(QScrollArea, "appearanceSettingsScroll")
    assert tabs is not None and header is not None and note is not None
    assert appearance is not None
    header_position = header.pos()
    tab_position = tabs.tabBar().mapTo(page, tabs.tabBar().rect().topLeft())
    note_position = note.pos()
    scrollbar = appearance.verticalScrollBar()
    assert scrollbar.maximum() > 0
    scrollbar.setValue(scrollbar.maximum())
    saved_position = scrollbar.value()

    # Additional categories can overflow the tab bar. Navigate with focus on the
    # bar instead of synthesizing a mouse click outside its visible rectangle.
    tabs.tabBar().setFocus()
    for _ in range(tabs.count() - 1):
        QTest.keyClick(tabs.tabBar(), Qt.Key.Key_Right)
    APPLICATION.processEvents()
    assert header.isVisible() and header.pos() == header_position
    assert note.isVisible() and note.pos() == note_position
    assert tabs.tabBar().mapTo(page, tabs.tabBar().rect().topLeft()) == tab_position
    about = tabs.currentWidget()
    assert isinstance(about, QScrollArea)
    assert about.verticalScrollBar().value() == 0

    for _ in range(tabs.count() - 1):
        QTest.keyClick(tabs.tabBar(), Qt.Key.Key_Left)
    APPLICATION.processEvents()
    assert scrollbar.value() == saved_position
    page.close()


def test_about_displays_license_and_community_credits(context: AppContext) -> None:
    page = SettingsPage(context.settings, context.theme_manager, context.i18n_manager)
    page.resize(900, 600)
    page.show()
    try:
        tabs = page.findChild(QTabWidget, "settingsTabs")
        assert tabs is not None
        tabs.setCurrentIndex(tabs.count() - 1)
        APPLICATION.processEvents()
        credits = tabs.currentWidget().findChild(QLabel, "aboutCredits")
        assert credits is not None and credits.isVisible()
        assert credits.wordWrap() and credits.openExternalLinks()
        for expected in (
            "GPLv3 or later",
            "Dylan Staley (@dstaley)",
            "DJShott",
            "HASHAB WebAssembly",
            "https://github.com/dstaley/hashab",
            "https://github.com/gtkpod/libgpod",
            "https://github.com/gtkpod/gtkpod",
        ):
            assert expected in credits.text()
        assert credits.width() <= tabs.currentWidget().width()
        for mode in (AppearanceMode.LIGHT, AppearanceMode.DARK):
            context.theme_manager.set_mode(mode)
            APPLICATION.processEvents()
            assert context.theme_manager.tokens.accent in credits.text()
    finally:
        page.close()


def test_settings_and_category_survive_theme_changes_and_retranslation(
    context: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def translate(_page: SettingsPage, text: str) -> str:
        return f"Translated {text}"

    page = SettingsPage(context.settings, context.theme_manager, context.i18n_manager)
    tabs = page.findChild(QTabWidget, "settingsTabs")
    combo = page.findChild(AppComboBox, "maxBackups")
    assert tabs is not None and combo is not None
    backups = page.findChild(QScrollArea, "backupSettingsScroll")
    assert backups is not None
    tabs.setCurrentWidget(backups)
    combo.setCurrentIndex(combo.findData(10))
    assert context.settings.get(MAX_BACKUPS) == 10
    tabs.setCurrentIndex(0)
    tabs.setCurrentWidget(backups)
    context.theme_manager.set_mode(AppearanceMode.DARK)
    changes = QSignalSpy(context.settings.settingChanged)
    monkeypatch.setattr(SettingsPage, "tr", translate)
    APPLICATION.sendEvent(page, QEvent(QEvent.Type.LanguageChange))

    assert tabs.currentWidget() is backups
    assert tabs.tabText(tabs.currentIndex()) == "Translated Backups"
    assert tabs.tabText(tabs.count() - 1) == "Translated About"
    assert combo.currentData() == 10
    assert context.settings.get(MAX_BACKUPS) == 10
    assert changes.count() == 0
    page.close()
