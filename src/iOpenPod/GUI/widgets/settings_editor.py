"""Scope-aware settings editing, separate from the application's effective values."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QSignalBlocker, Signal

from iOpenPod.app.core.settings.service import SettingSource, SettingsService

if TYPE_CHECKING:
    from collections.abc import Sequence

    from iOpenPod.app.core.settings.definitions import SettingDefinition
    from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
    from iOpenPod.GUI.widgets.setting_group import SettingRow
    from iOpenPod.GUI.widgets.toggle_switch import ToggleSwitch


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
        *,
        host_switch: ToggleSwitch | None = None,
    ) -> None:
        super().__init__(row)
        self._editor = editor
        self._definition = definition
        self._row = row
        self._combo = combo
        self._host_switch = host_switch
        self._choices: tuple[tuple[str, Value], ...] = ()
        editor.changed.connect(self.refresh)
        combo.currentIndexChanged.connect(self._selected)
        if host_switch is not None:
            host_switch.toggled.connect(self._host_toggled)

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
        device = self._editor.device
        # Observe effective values so device selection notifies runtime consumers too.
        effective = settings.get(definition)
        host = settings.get_global(definition)
        value = self._editor.get(definition)
        overridden = (
            settings.device_edit_value(definition)[1]
            if device
            else settings.source(definition) is SettingSource.DEVICE
        )
        switch = self._host_switch
        if switch is not None and isinstance(host, bool):
            switch.set_value(host)
            active, inactive = (
                (self._combo, switch) if device else (switch, self._combo)
            )
            if inactive.hasFocus():
                self._row.setFocus()
            inactive.hide()
            active.show()
            self._row.control.setFocusProxy(active)
        if switch is None or device:
            self._refresh_combo(host, value, device=device, overridden=overridden)
        self._set_enabled(not device or settings.device_writable)

        hint = ""
        if device:
            if not overridden:
                hint = self.tr("Following Host changes automatically")
        elif overridden:
            hint = self.tr("The Active iPod has its own override. Set to: %1.").replace(
                "%1", self._label(effective)
            )
        self._row.set_scope_hint(hint, warning=not device and overridden)

    def _label(self, value: Value) -> str:
        return next(
            (label for label, item in self._choices if item == value), str(value)
        )

    def _refresh_combo(
        self, host: Value, value: Value, *, device: bool, overridden: bool
    ) -> None:
        combo = self._combo
        with QSignalBlocker(combo):
            combo.clear()
            if device:
                combo.addItem(
                    self.tr("Use Host · %1").replace("%1", self._label(host)), None
                )
            for label, item in self._choices:
                combo.addItem(label, item)
            if combo.findData(value) < 0:
                combo.addItem(str(value), value)
            combo.setCurrentIndex(
                0 if device and not overridden else combo.findData(value)
            )

    def _set_enabled(self, enabled: bool) -> None:
        if not enabled and self._combo.hasFocus():
            # Disabling the focused control otherwise walks focus through every
            # remaining control, scrolling the form to the bottom. Its row can
            # hold focus until editing resumes without adding a Tab stop.
            self._row.setFocus()
        self._combo.setEnabled(enabled)
        if enabled and self._row.hasFocus():
            self._row.control.setFocus()

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
        elif self._host_switch is None and self._definition.validate(value):
            settings.set_global(self._definition, value)

    def _host_toggled(self, value: bool) -> None:
        if not self._editor.device and self._definition.validate(value):
            self._editor.settings.set_global(self._definition, value)
