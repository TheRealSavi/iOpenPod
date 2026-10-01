"""Read-only Settings tab consuming application-owned preferences summaries."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.setting_group import SettingGroup, SettingRow


class IPodPreferencesView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active: ActiveIPod | None = None
        self.setObjectName("ipodPreferencesView")
        self.setMaximumWidth(960)
        self._title = QLabel(self)
        self._title.setObjectName("sectionTitle")
        self._status = QLabel(self)
        self._status.setObjectName("ipodPreferencesStatus")
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setWordWrap(True)
        self._note = QLabel(self)
        self._note.setObjectName("settingDescription")
        self._note.setWordWrap(True)
        self._body = QWidget(self)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(LAYOUT.space_sm)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_sm)
        layout.addWidget(self._title)
        layout.addWidget(self._status)
        layout.addWidget(self._note)
        layout.addWidget(self._body)
        self.retranslate_ui()

    def set_active_ipod(self, active: ActiveIPod | None) -> None:
        self._active = active
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self._title.setText(self.tr("iPod Preferences"))
        self._note.setText(
            self.tr(
                "Read-only settings stored on your iPod, captured when it was loaded. "
                "Some settings may not be available for every model."
            )
        )
        self._note.setVisible(self._active is not None)
        while item := self._body_layout.takeAt(0):
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        active = self._active
        if active is None:
            self._status.setText(
                self.tr("Connect and select an iPod to view its preferences.")
            )
            return
        self._status.setText(active.display_name)
        if not active.preferences:
            label = QLabel(
                self.tr("Preferences have not been loaded for this iPod."), self._body
            )
            label.setWordWrap(True)
            self._body_layout.addWidget(label)
            return
        for section in active.preferences:
            title = QLabel(workflow_text(section.title), self._body)
            title.setObjectName("sectionTitle")
            self._body_layout.addWidget(title)
            if section.detail:
                detail = QLabel(workflow_text(section.detail), self._body)
                detail.setObjectName(f"ipodPreferenceStatus_{section.key}")
                detail.setTextFormat(Qt.TextFormat.PlainText)
                detail.setWordWrap(True)
                self._body_layout.addWidget(detail)
            if not section.rows:
                continue
            group = SettingGroup(self._body)
            for row in section.rows:
                value = QLabel(workflow_text(row.value), group)
                value.setObjectName(f"ipodPreference_{section.key}_{row.key}")
                value.setAccessibleName(workflow_text(row.title))
                value.setTextFormat(Qt.TextFormat.PlainText)
                value.setWordWrap(True)
                value.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                    | Qt.TextInteractionFlag.TextSelectableByKeyboard
                )
                group.add_row(SettingRow(workflow_text(row.title), "", value, group))
            self._body_layout.addWidget(group)
