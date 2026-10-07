"""Exercise settings scopes with user controls, including the moving selector."""

from collections.abc import Iterator
from types import TracebackType

import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent, QPropertyAnimation, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea, QTabWidget, QWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.context import AppContext
from iOpenPod.app.core.settings.definitions import (
    COMPUTE_SOUND_CHECK,
    LOSSY_ENCODER,
    MAX_BACKUPS,
    TRANSCODE_LOSSLESS_TO_LOSSY,
    AppearanceMode,
)
from iOpenPod.app.core.settings.service import SettingSource, SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.core.settings.transcoding import encoder_bitrate_mode
from iOpenPod.app.media.transcoding import LossyEncoder
from iOpenPod.GUI.pages.settings_page import SettingsPage
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.settings_scope import SettingsScopeSwitcher


@pytest.fixture
def context() -> Iterator[AppContext]:
    context = build_context()
    yield context
    context.shutdown()


def _tabs(page: SettingsPage) -> QTabWidget:
    tabs = page.findChild(QTabWidget, "settingsTabs")
    assert tabs is not None
    return tabs


def _switch(page: SettingsPage, device: bool) -> None:
    button = page.findChild(
        QPushButton, "ipodSettingsButton" if device else "hostSettingsButton"
    )
    assert button is not None
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    APPLICATION.processEvents()


def _category(page: SettingsPage, name: str) -> None:
    scroll = page.findChild(QScrollArea, name)
    assert scroll is not None
    _tabs(page).setCurrentWidget(scroll)


def test_switcher_animates_both_directions_and_supports_keyboard() -> None:
    switcher = SettingsScopeSwitcher()
    switcher.show()
    APPLICATION.processEvents()
    host = switcher.findChild(QPushButton, "hostSettingsButton")
    device = switcher.findChild(QPushButton, "ipodSettingsButton")
    selector = switcher.findChild(QWidget, "settingsScopeSelector")
    animation = switcher.findChild(QPropertyAnimation)
    assert (
        host is not None
        and device is not None
        and selector is not None
        and animation is not None
    )
    try:
        start = selector.x()
        QTest.mouseClick(device, Qt.MouseButton.LeftButton)
        assert animation.state() is QAbstractAnimation.State.Running
        animation.setCurrentTime(animation.duration() // 2)
        assert start < selector.x() < device.x()
        # Reverse mid-animation; start at the current position without jumping.
        middle = selector.geometry()
        QTest.mouseClick(host, Qt.MouseButton.LeftButton)
        assert animation.startValue() == middle
        animation.setCurrentTime(animation.duration())
        assert selector.geometry() == host.geometry()
        QTest.keyClick(host, Qt.Key.Key_Right)
        assert device.isChecked() and device.hasFocus()
        animation.setCurrentTime(animation.duration())
        assert selector.geometry() == device.geometry()
        QTest.keyClick(device, Qt.Key.Key_Left)
        assert host.isChecked()
    finally:
        switcher.close()


def test_scope_changes_and_retranslation_never_write_settings(
    context: AppContext,
) -> None:
    context.settings.load_device("one", {})
    page = SettingsPage(context.settings, context.theme_manager, context.i18n_manager)
    page.resize(940, 620)
    page.show()
    changes = QSignalSpy(context.settings.settingChanged)
    try:
        for device in (True, False, True):
            _switch(page, device)
            APPLICATION.sendEvent(page, QEvent(QEvent.Type.LanguageChange))
        assert changes.count() == 0
        tabs = _tabs(page)
        assert [
            tabs.tabText(index)
            for index in range(tabs.count())
            if tabs.isTabVisible(index)
        ] == ["Library", "Transcoding", "Sync", "Backups", "iPod Preferences"]
        for name in ("draftAllChangesCombo", "backupLocation"):
            control = page.findChild(QWidget, name)
            assert control is not None and not control.isVisible()
    finally:
        page.close()


def test_host_values_are_separate_and_unset_tracks_future_host_changes(
    context: AppContext,
) -> None:
    context.settings.set_global(COMPUTE_SOUND_CHECK, True)
    context.settings.load_device("one", {COMPUTE_SOUND_CHECK.key: False})
    page = SettingsPage(context.settings, context.theme_manager, context.i18n_manager)
    page.show()
    control = page.findChild(AppComboBox, "computeSoundCheck")
    assert control is not None
    try:
        _category(page, "syncSettingsScroll")
        assert control.currentData() is True
        _switch(page, True)
        assert control.currentData() is False
        assert control.itemText(0) == "Use Host · On"
        control.setCurrentIndex(0)
        assert context.settings.source(COMPUTE_SOUND_CHECK) is SettingSource.GLOBAL
        assert context.settings.get(COMPUTE_SOUND_CHECK) is True
        _switch(page, False)
        control.setCurrentIndex(control.findData(False))
        _switch(page, True)
        assert (
            control.currentData() is None and control.currentText() == "Use Host · Off"
        )
        control.setCurrentIndex(control.findData(False))
        assert context.settings.source(COMPUTE_SOUND_CHECK) is SettingSource.DEVICE
        _switch(page, False)
        control.setCurrentIndex(control.findData(True))
        assert context.settings.get(COMPUTE_SOUND_CHECK) is False
        assert context.settings.get_global(COMPUTE_SOUND_CHECK) is True
    finally:
        page.close()


def test_encoder_dependencies_follow_the_edited_scope(context: AppContext) -> None:
    context.settings.load_device("one", {LOSSY_ENCODER.key: "libmp3lame"})
    page = SettingsPage(context.settings, context.theme_manager, context.i18n_manager)
    page.show()
    try:
        _category(page, "transcodingSettingsScroll")
        mode = page.findChild(AppComboBox, "bitrateMode")
        quality = page.findChild(AppComboBox, "lossyQuality")
        vbr = page.findChild(AppComboBox, "vbrQuality")
        assert mode is not None and quality is not None and vbr is not None
        assert quality.isVisible() and not mode.isVisible()
        _switch(page, True)
        assert mode.isVisible() and not quality.isVisible() and vbr.isVisible()
        assert (
            mode.currentData() is None
        )  # Inherit Host VBR; dependencies use effective VBR.
        mode.setCurrentIndex(mode.findData("cbr"))
        assert not vbr.isVisible()
        mode.setCurrentIndex(0)
        assert vbr.isVisible()
        assert (
            context.settings.source(encoder_bitrate_mode(LossyEncoder.MP3))
            is SettingSource.DEFAULT
        )
    finally:
        page.close()


def test_disconnect_and_read_only_states_do_not_allow_accidental_host_edits(
    context: AppContext,
) -> None:
    page = SettingsPage(context.settings, context.theme_manager, context.i18n_manager)
    page.show()
    try:
        _switch(page, True)
        assert not _tabs(page).isVisible()
        choose = page.findChild(QPushButton, "settingsChooseIPod")
        assert choose is not None and choose.isVisible()
        requested = QSignalSpy(page.chooseIPodRequested)
        choose.click()
        assert requested.count() == 1
        context.settings.load_device("one", {MAX_BACKUPS.key: 3}, writable=False)
        _category(page, "backupSettingsScroll")
        control = page.findChild(AppComboBox, "maxBackups")
        note = page.findChild(QLabel, "pageMeta")
        assert control is not None and note is not None
        assert _tabs(page).isVisible() and not control.isEnabled()
        assert "read-only" in note.text()
        context.settings.unload_device()
        assert not _tabs(page).isVisible() and choose.isVisible()
        _switch(page, False)
        assert control.isEnabled() and control.currentData() == 0
        context.theme_manager.set_mode(AppearanceMode.DARK)
        assert context.settings.get_global(MAX_BACKUPS) == 0
    finally:
        page.close()


def test_pending_edit_stays_visible_then_reverts_on_failure(
    context: AppContext,
) -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.load_device("one", {}, managed=True)
    page = SettingsPage(settings, context.theme_manager, context.i18n_manager)
    page.show()
    try:
        _switch(page, True)
        _category(page, "backupSettingsScroll")
        control = page.findChild(AppComboBox, "maxBackups")
        assert control is not None
        control.setCurrentIndex(control.findData(3))
        assert settings.device_busy and settings.get(MAX_BACKUPS) == 0
        assert control.currentData() == 3 and not control.isEnabled()
        _switch(page, False)
        assert control.currentData() == 0 and control.isEnabled()
        _switch(page, True)
        assert control.currentData() == 3 and not control.isEnabled()
        settings.complete_device_save(None, "Save failed")
        assert control.currentData() is None
        assert settings.get(MAX_BACKUPS) == 0
    finally:
        page.close()


@pytest.mark.parametrize(
    ("category", "name", "key"),
    (
        ("syncSettingsScroll", "computeSoundCheck", COMPUTE_SOUND_CHECK.key),
        (
            "transcodingSettingsScroll",
            "transcodeLosslessToLossy",
            TRANSCODE_LOSSLESS_TO_LOSSY.key,
        ),
    ),
)
@pytest.mark.parametrize("interaction", ("keyboard", "mouse"))
def test_device_save_preserves_scroll_and_keyboard_focus(
    context: AppContext, category: str, name: str, key: str, interaction: str
) -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.load_device("one", {}, managed=True)
    page = SettingsPage(settings, context.theme_manager, context.i18n_manager)
    page.resize(940, 500)
    page.show()
    try:
        _switch(page, True)
        _category(page, category)
        APPLICATION.processEvents()
        scroll = page.findChild(QScrollArea, category)
        control = page.findChild(AppComboBox, name)
        assert scroll is not None and control is not None
        control.setFocus()
        scroll.ensureWidgetVisible(control)
        APPLICATION.processEvents()
        bar = scroll.verticalScrollBar()
        before = bar.value()
        assert before < bar.maximum()
        assert control.hasFocus()

        if interaction == "keyboard":
            QTest.keyClick(control, Qt.Key.Key_End)
        else:
            QTest.mouseClick(control, Qt.MouseButton.LeftButton)
            APPLICATION.processEvents()
            view = control.view()
            choice = view.model().index(control.findData(True), 0)
            point = view.visualRect(choice).center()
            QTest.mouseMove(view.viewport(), point)
            QTest.mouseClick(
                view.viewport(),
                Qt.MouseButton.LeftButton,
                pos=point,
            )
        # The controller keeps writes reserved until its worker has finished,
        # after publication has cleared the service's pending value.
        settings.set_device_available(False)
        APPLICATION.processEvents()
        assert settings.device_busy
        assert control.currentData() is True
        assert bar.value() == before

        settings.complete_device_save({key: True})
        APPLICATION.processEvents()
        assert not control.isEnabled()
        assert bar.value() == before
        settings.set_device_available(True)
        APPLICATION.processEvents()
        assert bar.value() == before
        assert control.hasFocus()
    finally:
        page.close()


def test_save_completion_does_not_take_focus_from_scope_switcher(
    context: AppContext,
) -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.load_device("one", {}, managed=True)
    page = SettingsPage(settings, context.theme_manager, context.i18n_manager)
    page.show()
    try:
        _switch(page, True)
        _category(page, "backupSettingsScroll")
        APPLICATION.processEvents()
        control = page.findChild(AppComboBox, "maxBackups")
        host = page.findChild(QPushButton, "hostSettingsButton")
        assert control is not None and host is not None
        control.setFocus()
        control.setCurrentIndex(control.findData(3))
        assert settings.device_busy
        settings.set_device_available(False)

        _switch(page, False)
        assert host.hasFocus()
        settings.complete_device_save({MAX_BACKUPS.key: 3})
        settings.set_device_available(True)
        APPLICATION.processEvents()
        assert host.hasFocus()
        assert control.currentData() == 0
    finally:
        page.close()


@pytest.mark.parametrize("save_started", (False, True))
def test_device_save_after_page_deletion_has_no_stale_signal_callbacks(
    context: AppContext, monkeypatch: pytest.MonkeyPatch, save_started: bool
) -> None:
    errors: list[BaseException] = []

    def capture_error(
        _kind: type[BaseException],
        error: BaseException,
        _traceback: TracebackType | None,
    ) -> None:
        errors.append(error)

    monkeypatch.setattr("sys.excepthook", capture_error)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.load_device("one", {}, managed=True)
    page = SettingsPage(settings, context.theme_manager, context.i18n_manager)
    if save_started:
        settings.set_device(MAX_BACKUPS, 3)
    page.deleteLater()
    APPLICATION.sendPostedEvents(page, QEvent.Type.DeferredDelete)

    if not save_started:
        settings.set_device(MAX_BACKUPS, 3)
    settings.complete_device_save({MAX_BACKUPS.key: 3})
    APPLICATION.processEvents()

    assert not errors, [str(error) for error in errors]
