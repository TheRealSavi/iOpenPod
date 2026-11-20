"""Device Summary's mod selection and independently observed installed state."""

from functools import partial

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.firmware.capture import RegistryStatus
from iOpenPod.app.firmware.catalog import BASES, CATALOG, CORE_ID, PLATFORM_VERSION
from iOpenPod.app.firmware.models import FirmwareBuildPlan
from iOpenPod.app.firmware.planner import plan_firmware
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import ActionButton


class FirmwareModsPanel(QFrame):
    """Review a build selection; never imply compilation or installation occurred."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("firmwareModsPanel")
        self._active: ActiveIPod | None = None
        self._requested: set[str] = set()
        self._plan: FirmwareBuildPlan | None = None
        self._busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.setSpacing(LAYOUT.space_sm)
        self._title = self._label("firmwareModsTitle")
        self._version = self._label("firmwarePlatformVersion")
        self._installed = self._label("firmwareInstalledMods")
        self._selection_label = self._label("firmwareSelectionTitle")
        for widget in (
            self._title,
            self._version,
            self._installed,
            self._selection_label,
        ):
            layout.addWidget(widget)
        self._choices: dict[str, QCheckBox] = {}
        for mod in CATALOG:
            if mod.id == CORE_ID:
                continue
            choice = QCheckBox(self)
            choice.setObjectName("firmwareMod_" + mod.id)
            choice.toggled.connect(partial(self._toggle, mod.id))
            self._choices[mod.id] = choice
            layout.addWidget(choice)
        self._status = self._label("firmwareBuildStatus")
        layout.addWidget(self._status)
        self._review = ActionButton(parent=self)
        self._review.setObjectName("reviewFirmwareBuild")
        self._review.clicked.connect(self._review_build)
        layout.addWidget(self._review, 0, Qt.AlignmentFlag.AlignLeft)
        self._clear = ActionButton(parent=self)
        self._clear.setObjectName("clearFirmwareSelection")
        self._clear.clicked.connect(self._clear_selection)
        layout.addWidget(self._clear, 0, Qt.AlignmentFlag.AlignLeft)
        self._refresh()

    def _label(self, name: str) -> QLabel:
        label = QLabel(self)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    @property
    def build_plan(self) -> FirmwareBuildPlan | None:
        return self._plan

    def set_active_ipod(self, active: ActiveIPod | None) -> None:
        old = self._active
        changed = (
            old is None
            or active is None
            or (
                old.candidate.id != active.candidate.id
                or old.firmware_target != active.firmware_target
                or old.firmware_registry != active.firmware_registry
            )
        )
        self._active = active
        if changed:
            self._requested.clear()
            if active is not None and active.firmware_registry.registry is not None:
                self._requested.update(active.firmware_registry.registry.requested)
                self._requested.discard(CORE_ID)
        self._refresh()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._refresh()

    def _toggle(self, mod_id: str, checked: bool) -> None:
        if checked:
            self._requested.add(mod_id)
        else:
            self._requested.discard(mod_id)
        self._refresh()

    def _clear_selection(self) -> None:
        if self._busy:
            return
        self._requested.clear()
        self._refresh()

    def _refresh(self) -> None:
        active = self._active
        self.setVisible(active is not None)
        self._title.setText(self.tr("Firmware mods"))
        self._selection_label.setText(self.tr("Include in next build"))
        self._review.setText(self.tr("Review build"))
        self._clear.setText(self.tr("Clear selection"))
        self._clear.setEnabled(bool(self._requested) and not self._busy)
        self._plan = None
        version = self.tr("Unavailable")
        installed = self.tr("Installed mods have not been inspected.")
        base = None
        if active is not None:
            observation = active.firmware_registry
            base = (
                BASES.get(active.firmware_target)
                if active.firmware_target is not None
                else None
            )
            if observation.registry is not None:
                registry = observation.registry
                version = registry.platform_version
                names = ", ".join(f"{mod.name} {mod.version}" for mod in registry.mods)
                installed = self.tr("Recorded installed build: {mods}").format(
                    mods=names or self.tr("No mods")
                )
            elif observation.status is RegistryStatus.MISSING:
                version = self.tr("Not recorded")
                installed = self.tr("No installed-mod registry was found.")
            elif observation.status is RegistryStatus.UNREADABLE:
                installed = self.tr("The installed-mod registry could not be read.")
        self._version.setText(
            self.tr("Mod platform version: {version}").format(version=version)
        )
        self._installed.setText(installed)
        error = ""
        if base is not None:
            try:
                self._plan = plan_firmware(
                    base, PLATFORM_VERSION, CATALOG, (CORE_ID, *self._requested)
                )
            except ValueError as problem:
                error = str(problem)
        effective = (
            {mod.id for mod in self._plan.mods}
            if self._plan is not None
            else set(self._requested)
        )
        for mod in CATALOG:
            choice = self._choices.get(mod.id)
            if choice is None:
                continue
            supported = base is not None and base.target_id in mod.targets
            required = mod.id in effective and mod.id not in self._requested
            previous = choice.blockSignals(True)
            choice.setChecked(mod.id in effective)
            choice.blockSignals(previous)
            choice.setText(workflow_text(mod.name))
            choice.setToolTip(
                self.tr("Required by another selected mod.")
                if required
                else workflow_text(mod.description)
            )
            choice.setEnabled(supported and not required and not self._busy)
        if error:
            status = error
        elif base is None:
            status = self.tr(
                "Firmware mod builds are not yet available for this device and Apple firmware version."
            )
        else:
            status = self.tr(
                "Choose mods to review the next build. Firmware compilation and installation are still in development; selections do not change your iPod."
            )
        self._status.setText(status)
        self._review.setEnabled(self._plan is not None and not self._busy)

    def _review_build(self) -> None:
        plan = self._plan
        if plan is None or self._busy:
            return
        details = [
            self.tr("Apple firmware: {version}").format(version=plan.apple.version),
            self.tr("Mod platform: {version}").format(version=plan.platform_version),
            "",
            *(f"{workflow_text(mod.name)} {mod.version}" for mod in plan.mods),
        ]
        if (
            self._active is not None
            and self._active.firmware_registry.registry is not None
        ):
            installed = self._active.firmware_registry.registry
            removed = [
                mod.name
                for mod in installed.mods
                if mod.id not in {item.id for item in plan.mods}
            ]
            if removed:
                details.extend(
                    (
                        "",
                        self.tr("Removed in this build: {mods}").format(
                            mods=", ".join(removed)
                        ),
                    )
                )
        details.extend(
            (
                "",
                self.tr(
                    "This is a build plan. No firmware has been built or installed."
                ),
            )
        )
        dialog = QMessageBox(self)
        dialog.setWindowTitle(self.tr("Review firmware build"))
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText("\n".join(details))
        dialog.setStandardButtons(QMessageBox.StandardButton.Close)
        dialog.exec()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._refresh()
        super().changeEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        layout = self.layout()
        if layout is not None:
            padding = LAYOUT.space_xs if self.width() < 480 else LAYOUT.space_lg
            layout.setContentsMargins(
                padding, LAYOUT.space_lg, padding, LAYOUT.space_lg
            )
        super().resizeEvent(event)
