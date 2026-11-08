"""Preferences drafts retain unknown values and stay bound to one Active iPod."""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QObject, Qt, QTranslator
from PySide6.QtWidgets import QLabel, QPushButton, QSpinBox, QTabWidget, QWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from device_registry import DEFAULT_DEVICE_REGISTRY, IdentificationStatus
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iOpenPod.app.models.ipod_preferences import (
    IPodPreference,
    IPodPreferenceChoice,
    IPodPreferenceEdit,
    IPodPreferenceEditSpec,
    IPodPreferencesCatalog,
    IPodPreferenceSection,
    PreferenceFileStatus,
)
from iOpenPod.app.preferences_controller import PreferencesController
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.ipod_preferences import IPodPreferencesView
from iOpenPod.GUI.widgets.search_field import SearchField
from iPodDB.library import LibrarySnapshot
from storage import FileFingerprint

pytestmark = pytest.mark.usefixtures("enable_ipod_preferences_writes")


def _active() -> ActiveIPod:
    profile = next(
        p for p in DEFAULT_DEVICE_REGISTRY.profiles if p.model_number == "MB565"
    )
    candidate = DeviceCandidate(
        DeviceCandidateId("preferences-gui"),
        "Test iPod",
        "USB",
        "usb",
        IdentificationStatus.EXACT,
        DeviceReadiness.READY,
        profile,
        120_000_000_000,
        60_000_000_000,
    )
    return ActiveIPod(
        candidate,
        profile,
        LibrarySnapshot(),
        "iTunesDB",
        FileFingerprint(0, 0, 0, 0, "0" * 64),
    )


def _catalog(*, raw: int = 255) -> IPodPreferencesCatalog:
    return IPodPreferencesCatalog(
        sections=(
            IPodPreferenceSection(
                "device",
                "Device settings",
                PreferenceFileStatus.AVAILABLE,
                (
                    IPodPreference(
                        "repeat",
                        "Repeat",
                        f"Unknown ({raw})",
                        IPodPreferenceEditSpec(
                            raw,
                            choices=(
                                IPodPreferenceChoice(0, "Off"),
                                IPodPreferenceChoice(1, "All"),
                                IPodPreferenceChoice(2, "One"),
                            ),
                        ),
                    ),
                    IPodPreference(
                        "brightness",
                        "Brightness",
                        "Unknown (255)",
                        IPodPreferenceEditSpec(255, minimum=0, maximum=16),
                    ),
                    IPodPreference("timezone", "Timezone", "Retained city"),
                ),
            ),
        )
    )


class _Controller(PreferencesController):
    def __init__(self) -> None:
        QObject.__init__(self)
        self.current: ActiveIPod | None = _active()
        self.view = _catalog()
        self.working = False
        self.allowed = True
        self.error = ""
        self.edits: list[tuple[IPodPreferenceEdit, ...]] = []
        self.refreshes = 0

    @property
    def active_ipod(self) -> ActiveIPod | None:
        return self.current

    @property
    def catalog(self) -> IPodPreferencesCatalog:
        return self.view

    @property
    def busy(self) -> bool:
        return self.working

    @property
    def message(self) -> str:
        return self.error

    @property
    def can_write(self) -> bool:
        return self.current is not None and self.allowed and not self.working

    def refresh(self) -> None:
        self.refreshes += 1

    def save(self, changes: tuple[IPodPreferenceEdit, ...]) -> bool:
        self.edits.append(changes)
        self.working = True
        self.changed.emit()
        return True


def _find[T: QObject](parent: QObject, cls: type[T], name: str) -> T:
    result = parent.findChild(cls, name)
    assert isinstance(result, cls)
    return result


def test_opening_preferences_does_not_show_discarded_sections_as_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _Controller()

    def refresh() -> None:
        # Reserving a device read changes write availability before work starts.
        controller.allowed = False
        controller.changed.emit()
        controller.working = True
        controller.changed.emit()

    monkeypatch.setattr(controller, "refresh", refresh)
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "Other")
    view = IPodPreferencesView(controller=controller)
    tabs.addTab(view, "iPod Preferences")
    extra_windows: list[str] = []

    class WindowObserver(QObject):
        def eventFilter(self, watched: QObject, event: QEvent) -> bool:
            if (
                event.type() == QEvent.Type.Show
                and isinstance(watched, QWidget)
                and watched is not tabs
                and watched.isWindow()
            ):
                extra_windows.append(watched.metaObject().className())
            return False

    observer = WindowObserver()
    try:
        tabs.show()
        APPLICATION.processEvents()
        APPLICATION.installEventFilter(observer)
        tabs.setCurrentWidget(view)
        APPLICATION.processEvents()
        assert not extra_windows
        assert _find(view, QLabel, "ipodPreference_device_timezone").isVisible()
    finally:
        APPLICATION.removeEventFilter(observer)
        tabs.close()


def test_unknown_preferences_are_kept_until_an_explicit_edit() -> None:
    controller = _Controller()
    view = IPodPreferencesView(controller=controller)
    try:
        repeat = _find(view, AppComboBox, "ipodPreference_device_repeat")
        brightness = _find(view, QSpinBox, "ipodPreference_device_brightness")
        apply = _find(view, QPushButton, "ipodPreferencesApply")
        assert repeat.currentData() == 255
        assert repeat.currentText() == "Keep current setting"
        assert brightness.text() == "Keep current setting"
        assert not apply.isEnabled()
        assert not controller.edits
        assert (
            _find(view, QLabel, "ipodPreference_device_timezone").text()
            == "Retained city"
        )
        repeat.setCurrentIndex(repeat.findData(2))
        assert apply.isEnabled()
        assert not controller.edits
        apply.click()
        assert controller.edits == [(IPodPreferenceEdit("device", "repeat", 2),)]
        assert not apply.isEnabled()
    finally:
        view.close()


def test_numeric_unknown_can_be_explicitly_changed_or_reverted_without_clamping() -> (
    None
):
    controller = _Controller()
    view = IPodPreferencesView(controller=controller)
    try:
        brightness = _find(view, QSpinBox, "ipodPreference_device_brightness")
        brightness.setValue(8)
        _find(view, QPushButton, "ipodPreferencesRevert").click()
        restored = _find(view, QSpinBox, "ipodPreference_device_brightness")
        assert restored.text() == "Keep current setting"
        assert not _find(view, QPushButton, "ipodPreferencesApply").isEnabled()
        restored.setValue(0)
        _find(view, QPushButton, "ipodPreferencesApply").click()
        assert controller.edits == [(IPodPreferenceEdit("device", "brightness", 0),)]
    finally:
        view.close()


def test_failed_save_keeps_draft_and_verified_save_clears_it() -> None:
    controller = _Controller()
    view = IPodPreferencesView(controller=controller)
    try:
        repeat = _find(view, AppComboBox, "ipodPreference_device_repeat")
        repeat.setCurrentIndex(repeat.findData(1))
        _find(view, QPushButton, "ipodPreferencesApply").click()
        controller.working = False
        controller.error = "The file changed."
        controller.changed.emit()
        assert (
            _find(view, AppComboBox, "ipodPreference_device_repeat").currentData() == 1
        )
        assert _find(view, QPushButton, "ipodPreferencesApply").isEnabled()
        assert "file changed" in view.status_text
        controller.error = ""
        controller.view = _catalog(raw=1)
        controller.saved.emit()
        controller.changed.emit()
        assert "file saved" in view.status_text
        assert "after ejecting" in view.status_text
        assert not _find(view, QPushButton, "ipodPreferencesApply").isEnabled()
        assert (
            _find(view, AppComboBox, "ipodPreference_device_repeat").currentData() == 1
        )
    finally:
        view.close()


def test_retranslation_preserves_draft_but_device_change_drops_it() -> None:
    controller = _Controller()
    view = IPodPreferencesView(controller=controller)
    try:
        repeat = _find(view, AppComboBox, "ipodPreference_device_repeat")
        repeat.setCurrentIndex(repeat.findData(2))
        view.retranslate_ui()
        assert (
            _find(view, AppComboBox, "ipodPreference_device_repeat").currentData() == 2
        )
        original = controller.current
        assert original is not None
        controller.current = replace(
            original, library=replace(original.library, device_name="Other iPod")
        )
        controller.changed.emit()
        assert (
            _find(view, AppComboBox, "ipodPreference_device_repeat").currentData()
            == 255
        )
        # A queued signal from the detached old control cannot edit this device.
        repeat.setCurrentIndex(repeat.findData(1))
        assert not _find(view, QPushButton, "ipodPreferencesApply").isEnabled()
        assert not controller.edits
        controller.current = None
        controller.changed.emit()
        assert not view.findChildren(AppComboBox)
        assert not _find(view, QPushButton, "ipodPreferencesRefresh").isEnabled()
    finally:
        view.close()


def test_read_only_or_busy_device_disables_editors_and_actions() -> None:
    controller = _Controller()
    view = IPodPreferencesView(controller=controller)
    try:
        controller.allowed = False
        controller.changed.emit()
        assert not _find(view, AppComboBox, "ipodPreference_device_repeat").isEnabled()
        assert not _find(view, QSpinBox, "ipodPreference_device_brightness").isEnabled()
        assert "read-only" in view.status_text
        controller.allowed = True
        repeat = _find(view, AppComboBox, "ipodPreference_device_repeat")
        controller.changed.emit()
        repeat = _find(view, AppComboBox, "ipodPreference_device_repeat")
        repeat.setCurrentIndex(repeat.findData(1))
        controller.working = True
        controller.changed.emit()
        for name in (
            "ipodPreferencesApply",
            "ipodPreferencesRevert",
            "ipodPreferencesRefresh",
        ):
            assert not _find(view, QPushButton, name).isEnabled()
        assert "Reading or saving" in view.status_text
    finally:
        view.close()
        APPLICATION.processEvents()


@pytest.mark.parametrize("language", ["de", "es"])
def test_shipped_language_change_preserves_unsaved_preferences(language: str) -> None:
    controller = _Controller()
    view = IPodPreferencesView(controller=controller)
    translator = QTranslator()
    catalog = (
        Path(__file__).resolve().parents[3]
        / "src/iOpenPod/GUI/presentation/i18n/translations"
        / f"iopenpod_{language}.qm"
    )
    try:
        repeat = _find(view, AppComboBox, "ipodPreference_device_repeat")
        repeat.setCurrentIndex(repeat.findData(1))
        assert translator.load(str(catalog))
        assert APPLICATION.installTranslator(translator)
        view.retranslate_ui()
        assert (
            _find(view, AppComboBox, "ipodPreference_device_repeat").currentData() == 1
        )
        assert _find(
            view, QSpinBox, "ipodPreference_device_brightness"
        ).text() == translator.translate("IPodPreferencesView", "Keep current setting")
        assert _find(view, QPushButton, "ipodPreferencesApply").isEnabled()
        assert not controller.edits
        _find(view, QPushButton, "ipodPreferencesApply").click()
        assert controller.edits == [(IPodPreferenceEdit("device", "repeat", 1),)]
    finally:
        APPLICATION.removeTranslator(translator)
        view.close()
        APPLICATION.processEvents()


def test_search_preserves_hidden_draft_and_matches_read_only_raw_values() -> None:
    controller = _Controller()
    section = controller.view.sections[0]
    controller.view = replace(
        controller.view,
        sections=(
            replace(
                section,
                rows=(
                    *section.rows[:2],
                    replace(
                        section.rows[2],
                        raw_value="205 (0xCD)",
                        detail="Saved city; geographic interpretation is unresolved.",
                        category="Date and time",
                    ),
                ),
            ),
        ),
    )
    view = IPodPreferencesView(controller=controller)
    try:
        repeat = _find(view, AppComboBox, "ipodPreference_device_repeat")
        repeat.setCurrentIndex(repeat.findData(2))
        search = _find(view, SearchField, "ipodPreferencesSearch")
        search.set_query("0xCD")
        search.queryChanged.emit(search.text())
        timezone = _find(view, QLabel, "ipodPreference_device_timezone")
        assert timezone.isVisibleTo(view)
        assert not repeat.isVisibleTo(view)
        assert not _find(view, QLabel, "ipodPreferencesNoMatches").isVisibleTo(view)
        view.retranslate_ui()
        assert _find(view, SearchField, "ipodPreferencesSearch").text() == "0xCD"
        repeat = _find(view, AppComboBox, "ipodPreference_device_repeat")
        assert repeat.currentData() == 2
        assert not repeat.isVisibleTo(view)
        search.set_query("not a preference")
        search.queryChanged.emit(search.text())
        assert _find(view, QLabel, "ipodPreferencesNoMatches").isVisibleTo(view)
        _find(view, QPushButton, "ipodPreferencesApply").click()
        assert controller.edits == [(IPodPreferenceEdit("device", "repeat", 2),)]
    finally:
        view.close()


def test_read_only_details_and_raw_xml_are_literal_and_accessible() -> None:
    controller = _Controller()
    controller.view = IPodPreferencesCatalog(
        sections=(
            IPodPreferenceSection(
                "timer",
                "Timer settings",
                PreferenceFileStatus.AVAILABLE,
                (
                    IPodPreference(
                        "Timer.DateTime",
                        "Timer deadline",
                        "<b>invalid date</b>",
                        detail="Calendar meaning is unresolved; source is retained.",
                        raw_value='<img src="file:///private">',
                        category="Date and time",
                    ),
                ),
            ),
        )
    )
    view = IPodPreferencesView(controller=controller)
    try:
        value = _find(view, QLabel, "ipodPreference_timer_Timer.DateTime")
        assert value.text() == "<b>invalid date</b>"
        assert value.textFormat() is Qt.TextFormat.PlainText
        assert "&lt;img" in value.toolTip() and "<img" not in value.toolTip()
        assert "Calendar meaning is unresolved" in value.accessibleDescription()
        assert '<img src="file:///private">' in value.accessibleDescription()
        assert not view.findChildren(AppComboBox)
        assert not view.findChildren(QSpinBox)
        assert not _find(view, QPushButton, "ipodPreferencesApply").isEnabled()
    finally:
        view.close()
