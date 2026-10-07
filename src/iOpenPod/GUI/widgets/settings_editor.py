"""Scope-aware settings editing, separate from the application's effective values."""

from collections.abc import Sequence

from PySide6.QtCore import QObject, QSignalBlocker, Signal

from iOpenPod.app.core.settings.definitions import SettingDefinition
from iOpenPod.app.core.settings.service import SettingSource, SettingsService
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.setting_group import SettingRow


class SettingsEditor(QObject):
    changed = Signal()

    def __init__(self, settings: SettingsService, parent: QObject) -> None:
        super().__init__(parent)
        self.settings = settings
        self.device = False
        settings.settingChanged.connect(self._setting_changed)
        # A direct signal connection is removed when this editor is deleted.
        settings.deviceStateChanged.connect(self.changed)

    def _setting_changed(self, _key: str, _value: object) -> None:
        self.changed.emit()

    def set_device(self, device: bool) -> None:
        self.device = device
        self.changed.emit()

    def get[Value](self, definition: SettingDefinition[Value]) -> Value:
        return (
            self.settings.device_edit_value(definition)[0]
            if self.device
            else self.settings.get_global(definition)
        )


class ScopedSettingBinding[Value](QObject):
    """Absence means inheritance; false, zero and equal values remain overrides."""

    def __init__(
        self,
        editor: SettingsEditor,
        definition: SettingDefinition[Value],
        row: SettingRow,
        combo: AppComboBox,
    ) -> None:
        super().__init__(row)
        self._editor = editor
        self._definition = definition
        self._row = row
        self._combo = combo
        self._choices: tuple[tuple[str, Value], ...] = ()
        editor.changed.connect(self.refresh)
        combo.currentIndexChanged.connect(self._selected)

    def configure(
        self,
        choices: Sequence[tuple[str, Value]],
        definition: SettingDefinition[Value] | None = None,
    ) -> None:
        if definition is not None:
            self._definition = definition
        self._choices = tuple(choices)
        self.refresh()

    def refresh(self) -> None:
        if not self._choices:
            return
        settings = self._editor.settings
        definition = self._definition
        # Observe effective values so device selection notifies runtime consumers too.
        settings.get(definition)
        host = settings.get_global(definition)
        value = self._editor.get(definition)
        overridden = (
            settings.device_edit_value(definition)[1]
            if self._editor.device
            else settings.source(definition) is SettingSource.DEVICE
        )
        host_label = next(
            (label for label, item in self._choices if item == host), str(host)
        )
        blocker = QSignalBlocker(self._combo)
        self._combo.clear()
        if self._editor.device:
            self._combo.addItem(
                self.tr("Use Host · %1").replace("%1", host_label), None
            )
        for label, item in self._choices:
            self._combo.addItem(label, item)
        if self._combo.findData(value) < 0:
            self._combo.addItem(str(value), value)
        self._combo.setCurrentIndex(
            0 if self._editor.device and not overridden else self._combo.findData(value)
        )
        self._set_enabled(not self._editor.device or settings.device_writable)
        hint = ""
        if self._editor.device:
            hint = (
                self.tr("Override for this iPod · Host: %1").replace("%1", host_label)
                if overridden
                else self.tr("Following Host changes automatically")
            )
        elif overridden:
            hint = self.tr("The Active iPod has its own override.")
        self._row.set_scope_hint(hint)
        del blocker

    def _set_enabled(self, enabled: bool) -> None:
        if not enabled and self._combo.hasFocus():
            # Disabling the focused control otherwise walks focus through every
            # remaining control, scrolling the form to the bottom. Its row can
            # hold focus until editing resumes without adding a Tab stop.
            self._row.setFocus()
        self._combo.setEnabled(enabled)
        if enabled and self._row.hasFocus():
            self._combo.setFocus()

    def _selected(self, index: int) -> None:
        if index < 0:
            return
        value = self._combo.itemData(index)
        settings = self._editor.settings
        if self._editor.device:
            if not settings.device_writable:
                self.refresh()
            elif value is None:
                settings.reset_device(self._definition)
            elif self._definition.validate(value):
                settings.set_device(self._definition, value)
        elif self._definition.validate(value):
            settings.set_global(self._definition, value)
