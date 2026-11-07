"""First-run setup, persistence, dismissal, and startup ordering."""

from pathlib import Path

import pytest
from PySide6.QtCore import QLocale, QPoint, Qt, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QLabel,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.app import (
    _start_interactive_session,  # pyright: ignore[reportPrivateUsage]
)
from iOpenPod.app.core.settings.definitions import (
    APPLICATION_LANGUAGE,
    DRAFT_ALL_CHANGES,
    IPOD_LIBRARY_VIEW_MODE,
    ITUNES_107_ARTWORK,
    LOSSY_QUALITY,
    NAVIGATION_STYLE,
    ONBOARDING_COMPLETE,
    IPodLibraryViewMode,
    NavigationStyle,
)
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import (
    DeviceSettingsStore,
    GlobalSettingsStore,
    JsonSettingsStore,
)
from iOpenPod.GUI.dialogs.help_support import HelpSupportDialog, HelpSupportPage
from iOpenPod.GUI.dialogs.onboarding import OnboardingDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.settings_page import SettingsPage
from iOpenPod.GUI.presentation.i18n.manager import I18nManager
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, IconButton
from storage import AtomicHostFile


def _dialog(settings: SettingsService) -> OnboardingDialog:
    manager = I18nManager(APPLICATION, settings)
    dialog = OnboardingDialog(settings, manager)
    manager.setParent(dialog)
    dialog.finished.connect(manager.close)
    return dialog


def _button(dialog: OnboardingDialog, name: str) -> ActionButton:
    result = dialog.findChild(ActionButton, f"onboarding{name}")
    assert result is not None
    return result


def _pages(dialog: OnboardingDialog) -> QStackedWidget:
    result = dialog.findChild(QStackedWidget, "onboardingPages")
    assert result is not None
    return result


def _choose(dialog: OnboardingDialog, index: int) -> None:
    button = _page(dialog).findChild(QRadioButton, f"onboardingChoice{index}")
    assert button is not None
    button.click()


def _page(dialog: OnboardingDialog) -> QWidget:
    page = _pages(dialog).currentWidget()
    assert page is not None
    return page


def _finish_page(dialog: OnboardingDialog) -> None:
    while _pages(dialog).currentIndex() < _pages(dialog).count() - 1:
        _button(dialog, "Next").click()
    assert _pages(dialog).currentIndex() == _pages(dialog).count() - 1
    assert _button(dialog, "Next").text() == dialog.tr("Finish")


def test_choice_tiles_support_full_surface_clicks_and_arrow_keys() -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    dialog = _dialog(settings)
    dialog.show()
    APPLICATION.processEvents()
    first, second = _page(dialog).findChildren(QRadioButton)
    first.click()
    # The empty space beyond the label is part of the choice's hit target.
    QTest.mouseClick(
        second,
        Qt.MouseButton.LeftButton,
        pos=QPoint(second.width() - 8, second.height() // 2),
    )
    assert second.isChecked() and not first.isChecked()
    second.setFocus()
    QTest.keyClick(second, Qt.Key.Key_Left)
    assert first.isChecked() and not second.isChecked()
    assert first.hasFocus()
    dialog.reject()


def test_language_menu_translates_every_page_and_keeps_unfinished_choices() -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.set_global(APPLICATION_LANGUAGE, "en")
    dialog = _dialog(settings)
    dialog.show()
    _choose(dialog, 1)
    _button(dialog, "Next").click()
    _choose(dialog, 0)
    _button(dialog, "Next").click()
    _choose(dialog, 1)
    _finish_page(dialog)
    language = dialog.findChild(IconButton, "onboardingLanguage")
    assert language is not None and not language.icon().isNull()
    menu = language.menu()
    assert {action.data() for action in menu.actions()} == {"system", "en", "de", "es"}
    for index in reversed(range(_pages(dialog).count())):
        assert language.isVisibleTo(dialog)
        before = _page(dialog).findChild(QLabel, "dialogTitle")
        assert before is not None
        before_text = before.text()
        tag = "de" if index % 2 == 0 else "es"
        menu.aboutToShow.emit()
        next(action for action in menu.actions() if action.data() == tag).trigger()
        APPLICATION.processEvents()
        assert _pages(dialog).currentIndex() == index
        title = _page(dialog).findChild(QLabel, "dialogTitle")
        assert title is not None and title.text() != before_text
        assert settings.get(APPLICATION_LANGUAGE) == tag
        assert not settings.get(ONBOARDING_COMPLETE)
        if index < 3:
            expected = (1, 0, 1)[index]
            assert _page(dialog).findChildren(QRadioButton)[expected].isChecked()
        if index:
            _button(dialog, "Back").click()
    # Language is applied immediately; other preferences are still staged.
    assert settings.get(NAVIGATION_STYLE) == NavigationStyle.COMPACT_TOP_BAR.value
    _finish_page(dialog)
    _button(dialog, "Next").click()
    assert settings.get(NAVIGATION_STYLE) == NavigationStyle.SIDEBAR.value
    assert settings.get(IPOD_LIBRARY_VIEW_MODE) == IPodLibraryViewMode.SPLIT_TABLE.value
    assert settings.get(ITUNES_107_ARTWORK) is True


def test_language_choice_survives_dismissal_and_a_new_settings_session(
    tmp_path: Path,
) -> None:
    host_file = AtomicHostFile(tmp_path / "settings.json")
    settings = SettingsService(JsonSettingsStore(host_file), DeviceSettingsStore())
    dialog = _dialog(settings)
    dialog.show()
    language = dialog.findChild(IconButton, "onboardingLanguage")
    assert language is not None
    menu = language.menu()
    next(action for action in menu.actions() if action.data() == "es").trigger()
    _button(dialog, "Later").click()
    restored = SettingsService(JsonSettingsStore(host_file), DeviceSettingsStore())
    assert restored.get(APPLICATION_LANGUAGE) == "es"
    assert not restored.get(ONBOARDING_COMPLETE)


def test_failed_language_save_keeps_the_current_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = GlobalSettingsStore()
    settings = SettingsService(store, DeviceSettingsStore())
    settings.set_global(APPLICATION_LANGUAGE, "en")
    dialog = _dialog(settings)
    dialog.show()

    def fail() -> None:
        raise OSError("Disk full")

    monkeypatch.setattr(store, "sync", fail)
    language = dialog.findChild(IconButton, "onboardingLanguage")
    assert language is not None
    menu = language.menu()
    next(action for action in menu.actions() if action.data() == "de").trigger()
    assert settings.get(APPLICATION_LANGUAGE) == "en"
    assert (
        next(action for action in menu.actions() if action.isChecked()).data() == "en"
    )
    error = dialog.findChild(QLabel, "onboardingError")
    assert error is not None and error.isVisible()
    assert "language" in error.text()
    dialog.reject()


def test_completion_and_choices_survive_a_new_settings_session(tmp_path: Path) -> None:
    host_file = AtomicHostFile(tmp_path / "settings-v2.json")
    settings = SettingsService(JsonSettingsStore(host_file), DeviceSettingsStore())
    assert settings.get(ONBOARDING_COMPLETE) is False
    dialog = _dialog(settings)
    dialog.show()
    assert not _button(dialog, "Back").isEnabled()
    assert _pages(dialog).count() == 9
    title = _page(dialog).findChild(QLabel, "dialogTitle")
    assert title is not None and title.text() == "Choose your navigation style"
    assert any(
        label.text() == "You can always change this later in settings"
        for label in dialog.findChildren(QLabel, "onboardingCaption")
    )
    _choose(dialog, 1)
    # Enter advances from navigation without completing onboarding.
    QTest.keyClick(dialog, Qt.Key.Key_Return)
    assert _pages(dialog).currentIndex() == 1
    _choose(dialog, 0)
    _button(dialog, "Next").click()
    _choose(dialog, 1)
    _button(dialog, "Back").click()
    assert _page(dialog).findChildren(QRadioButton)[0].isChecked()
    _button(dialog, "Next").click()
    assert _page(dialog).findChildren(QRadioButton)[1].isChecked()
    _button(dialog, "Next").click()
    _finish_page(dialog)
    assert not host_file.path.exists()
    _button(dialog, "Next").click()

    restored = SettingsService(JsonSettingsStore(host_file), DeviceSettingsStore())
    assert restored.get(ONBOARDING_COMPLETE) is True
    assert restored.get(NAVIGATION_STYLE) == NavigationStyle.SIDEBAR.value
    assert restored.get(IPOD_LIBRARY_VIEW_MODE) == IPodLibraryViewMode.SPLIT_TABLE.value
    assert restored.get(ITUNES_107_ARTWORK) is True
    assert restored.get(DRAFT_ALL_CHANGES) is False
    assert not dialog.isVisible()


@pytest.mark.parametrize("draft_edits", [False, True])
def test_tutorials_explain_transcoding_and_sync_without_changing_their_settings(
    draft_edits: bool,
) -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.set_global(DRAFT_ALL_CHANGES, draft_edits)
    settings.set_global(LOSSY_QUALITY, "compact")
    dialog = _dialog(settings)
    dialog.show()
    pages = _pages(dialog)
    for index, expected in enumerate(
        (
            "Transcoding settings",
            "1. Open Sync with Host",
            "2. Choose your media folders",
            "3. Select your media",
            "4. Review, then sync",
        ),
        start=3,
    ):
        pages.setCurrentIndex(index)
        title = _page(dialog).findChild(QLabel, "dialogTitle")
        assert title is not None and title.text() == expected
        assert not _page(dialog).findChildren(QRadioButton)
    _finish_page(dialog)
    _button(dialog, "Next").click()
    assert settings.get(ONBOARDING_COMPLETE)
    assert settings.get(DRAFT_ALL_CHANGES) is draft_edits
    assert settings.get(LOSSY_QUALITY) == "compact"


def test_help_links_open_the_expected_destinations_without_finishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []

    def open_url(url: QUrl) -> bool:
        opened.append(url.toString())
        return True

    monkeypatch.setattr("iOpenPod.GUI.dialogs.help_support.open_desktop_url", open_url)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    dialog = _dialog(settings)
    dialog.show()
    _finish_page(dialog)
    title = _page(dialog).findChild(QLabel, "dialogTitle")
    assert title is not None and title.text() == "Help and support"
    assert not opened
    for name, url in (
        ("Website", "https://iopenpod.com"),
        ("Discord", "https://discord.gg/9Yy499Tf5d"),
        ("Issues", "https://github.com/TheRealSavi/iOpenPod/issues"),
        ("Kofi", "https://ko-fi.com/johngibbons"),
        ("Star", "https://github.com/TheRealSavi/iOpenPod"),
    ):
        _button(dialog, name).click()
        assert opened[-1] == url
        assert dialog.isVisible()
        assert not settings.get(ONBOARDING_COMPLETE)
    _button(dialog, "Next").click()
    assert settings.get(ONBOARDING_COMPLETE)


@pytest.mark.parametrize("complete", [False, True])
def test_about_help_shows_only_help_and_preserves_onboarding(complete: bool) -> None:
    context = build_context()
    context.settings.set_global(ONBOARDING_COMPLETE, complete)
    context.settings.set_global(NAVIGATION_STYLE, NavigationStyle.SIDEBAR.value)
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        button = window.findChild(ActionButton, "helpSupport")
        assert button is not None and button.text() == "Help and support"
        button.click()
        dialog = window.findChild(HelpSupportDialog)
        assert dialog is not None and dialog.isVisible() and dialog.isModal()
        assert dialog.findChild(HelpSupportPage) is not None
        assert dialog.findChild(QStackedWidget) is None
        assert dialog.findChild(ActionButton, "onboardingNext") is None
        assert window.findChild(OnboardingDialog) is None
        dialog.resize(560, 440)
        APPLICATION.processEvents()
        scroll = dialog.findChild(QScrollArea)
        assert scroll is not None and scroll.horizontalScrollBar().maximum() == 0
        close = dialog.findChild(ActionButton, "helpSupportClose")
        assert close is not None
        close.click()
        assert not dialog.isVisible()
        assert context.settings.get(ONBOARDING_COMPLETE) is complete
        assert context.settings.get(NAVIGATION_STYLE) == NavigationStyle.SIDEBAR.value
    finally:
        window.close()
        context.shutdown()


def test_settings_reminder_is_only_visible_on_choice_pages() -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    dialog = _dialog(settings)
    dialog.show()
    reminder = next(
        label
        for label in dialog.findChildren(QLabel)
        if label.text() == "You can always change this later in settings"
    )
    for index in range(_pages(dialog).count()):
        assert reminder.isVisible() is (index < 3)
        if index < _pages(dialog).count() - 1:
            _button(dialog, "Next").click()
    while _pages(dialog).currentIndex() > 2:
        _button(dialog, "Back").click()
    assert reminder.isVisible()
    dialog.reject()


@pytest.mark.parametrize("dismissal", ["later", "escape", "close"])
def test_dismissal_keeps_existing_preferences_and_onboarding_due(
    dismissal: str,
) -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.set_global(NAVIGATION_STYLE, NavigationStyle.SIDEBAR.value)
    dialog = _dialog(settings)
    dialog.show()
    assert _page(dialog).findChildren(QRadioButton)[1].isChecked()
    _choose(dialog, 0)
    if dismissal == "later":
        _button(dialog, "Later").click()
    elif dismissal == "escape":
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
    else:
        dialog.close()
    assert settings.get(NAVIGATION_STYLE) == NavigationStyle.SIDEBAR.value
    assert settings.get(ONBOARDING_COMPLETE) is False


@pytest.mark.parametrize("failed_key", [NAVIGATION_STYLE.key, ONBOARDING_COMPLETE.key])
def test_failed_save_stays_open_incomplete_and_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_key: str
) -> None:
    host_file = AtomicHostFile(tmp_path / "settings-v2.json")
    store = JsonSettingsStore(host_file)
    settings = SettingsService(store, DeviceSettingsStore())
    original_sync = store.sync

    def fail() -> None:
        if store.has(failed_key):
            raise OSError("Disk full")
        original_sync()

    monkeypatch.setattr(store, "sync", fail)
    dialog = _dialog(settings)
    dialog.show()
    _finish_page(dialog)
    _button(dialog, "Next").click()
    assert dialog.isVisible()
    assert settings.get(ONBOARDING_COMPLETE) is False
    assert not store.has(ONBOARDING_COMPLETE.key)
    error = dialog.findChild(QLabel, "onboardingError")
    assert error is not None and error.isVisible()
    restored = SettingsService(JsonSettingsStore(host_file), DeviceSettingsStore())
    assert restored.get(ONBOARDING_COMPLETE) is False
    monkeypatch.setattr(store, "sync", original_sync)
    _button(dialog, "Next").click()
    assert not dialog.isVisible()
    restored = SettingsService(JsonSettingsStore(host_file), DeviceSettingsStore())
    assert restored.get(ONBOARDING_COMPLETE) is True


def test_completion_is_validated_and_cannot_be_overridden_by_a_device() -> None:
    store = GlobalSettingsStore()
    settings = SettingsService(store, DeviceSettingsStore())
    store.set(ONBOARDING_COMPLETE.key, "true")
    settings.load_device("sample", {ONBOARDING_COMPLETE.key: True})
    assert settings.get(ONBOARDING_COMPLETE) is False
    with pytest.raises(ValueError, match="not device-overridable"):
        settings.set_device(ONBOARDING_COMPLETE, True)


def test_small_dialog_keeps_actions_available_and_each_page_starts_at_top() -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    dialog = _dialog(settings)
    dialog.resize(560, 440)
    dialog.show()
    scroll = dialog.findChild(QScrollArea)
    assert scroll is not None
    for _ in range(_pages(dialog).count() - 1):
        APPLICATION.processEvents()
        assert scroll.horizontalScrollBar().maximum() == 0
        assert _button(dialog, "Next").isVisibleTo(dialog)
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        _button(dialog, "Next").click()
        assert scroll.verticalScrollBar().value() == 0
    APPLICATION.processEvents()
    assert scroll.horizontalScrollBar().maximum() == 0
    assert _button(dialog, "Next").isVisibleTo(dialog)
    scroll.ensureWidgetVisible(_button(dialog, "Star"))
    assert scroll.verticalScrollBar().value() > 0
    dialog.reject()


@pytest.mark.parametrize("language,next_label", [("de", "Weiter"), ("es", "Siguiente")])
def test_dialog_uses_the_selected_language_at_startup(
    language: str, next_label: str
) -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    locale = QLocale()
    manager = I18nManager(APPLICATION, settings)
    try:
        manager.set_language(language)
        dialog = OnboardingDialog(settings, manager)
        dialog.show()
        assert _button(dialog, "Next").text() == next_label
        assert _page(dialog).findChildren(QRadioButton)[0].text() != "Compact top bar"
        dialog.reject()
    finally:
        manager.close()
        QLocale.setDefault(locale)


@pytest.mark.parametrize("complete", [False, True])
def test_startup_waits_for_onboarding_only_when_due(
    monkeypatch: pytest.MonkeyPatch, complete: bool
) -> None:
    context = build_context()
    context.settings.set_global(ONBOARDING_COMPLETE, complete)
    window = MainWindow(context, auto_discover=False, defer_startup=True)
    calls: list[str] = []
    monkeypatch.setattr(
        window, "start_device_discovery", lambda: calls.append("devices")
    )
    monkeypatch.setattr(window, "check_app_updates", lambda: calls.append("updates"))
    monkeypatch.setattr(window, "check_media_tools", lambda: calls.append("media"))
    try:
        window.show()
        _start_interactive_session(window, context.settings, context.i18n_manager)
        dialog = window.findChild(OnboardingDialog)
        if complete:
            assert dialog is None
        else:
            assert dialog is not None and dialog.isVisible()
            assert dialog.isModal()
            APPLICATION.processEvents()
            assert not calls
            dialog.reject()
        APPLICATION.processEvents()
        assert calls == ["devices", "updates", "media"]
    finally:
        window.close()
        context.shutdown()


@pytest.mark.parametrize("finish", [False, True])
def test_about_retake_reopens_completed_onboarding_and_only_finish_saves(
    monkeypatch: pytest.MonkeyPatch, finish: bool
) -> None:
    context = build_context()
    context.settings.set_global(ONBOARDING_COMPLETE, True)
    context.settings.set_global(NAVIGATION_STYLE, NavigationStyle.SIDEBAR.value)
    window = MainWindow(context, auto_discover=False)

    def unexpected_startup() -> None:
        pytest.fail("Retaking onboarding must not restart device discovery")

    monkeypatch.setattr(window, "start_device_discovery", unexpected_startup)
    try:
        window.show()
        navigation = window.findChild(Sidebar)
        assert navigation is not None
        navigation.pageRequested.emit(PageId.SETTINGS.value)
        page = window.findChild(SettingsPage)
        assert page is not None
        about = page.findChild(QScrollArea, "aboutSettingsScroll")
        tabs = page.findChild(QTabWidget, "settingsTabs")
        assert about is not None and tabs is not None
        tabs.setCurrentWidget(about)
        retake = about.findChild(ActionButton, "retakeOnboarding")
        assert retake is not None and retake.isVisibleTo(window)
        retake.click()
        dialog = window.findChild(OnboardingDialog)
        assert dialog is not None and dialog.isVisible() and dialog.isModal()
        assert _pages(dialog).currentIndex() == 0
        assert _page(dialog).findChildren(QRadioButton)[1].isChecked()
        _choose(dialog, 0)
        if finish:
            for _ in range(_pages(dialog).count()):
                _button(dialog, "Next").click()
        else:
            dialog.reject()
        APPLICATION.processEvents()
        assert context.settings.get(ONBOARDING_COMPLETE) is True
        assert context.settings.get(NAVIGATION_STYLE) == (
            NavigationStyle.COMPACT_TOP_BAR.value
            if finish
            else NavigationStyle.SIDEBAR.value
        )
    finally:
        window.close()
        context.shutdown()
