"""Jellyfin sign-in and play count sync controls within Settings → Sync."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from iOpenPod.app.jellyfin.settings import JELLYFIN_SERVER_URL, JELLYFIN_USERNAME
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.setting_group import SettingGroup, SettingRow
from iOpenPod.GUI.widgets.themed_buttons import ActionButton

if TYPE_CHECKING:
    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.jellyfin.controller import JellyfinController


class JellyfinSettings(QWidget):
    def __init__(
        self,
        settings: SettingsService,
        controller: JellyfinController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._controller = controller
        self._title = QLabel(self)
        self._title.setObjectName("sectionTitle")
        self._status = QLabel(self)
        self._status.setObjectName("jellyfinStatus")
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._status.setWordWrap(True)
        self._server = QLineEdit(settings.get(JELLYFIN_SERVER_URL), self)
        self._server.setObjectName("jellyfinServer")
        self._server.setPlaceholderText("http://192.168.1.20:8096")
        self._username = QLineEdit(settings.get(JELLYFIN_USERNAME), self)
        self._username.setObjectName("jellyfinUsername")
        self._password = QLineEdit(self)
        self._password.setObjectName("jellyfinPassword")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        for field in (self._server, self._username, self._password):
            field.setMaxLength(256)
        self._server_row = SettingRow("", "", self._server, self)
        self._username_row = SettingRow("", "", self._username, self)
        self._password_row = SettingRow("", "", self._password, self)
        self._connect = ActionButton(parent=self)
        self._connect.setObjectName("connectJellyfin")
        self._disconnect = ActionButton(parent=self)
        self._disconnect.setObjectName("disconnectJellyfin")
        self._account_row = SettingRow(
            "Jellyfin", "", self._buttons(self._connect, self._disconnect), self
        )
        self._sync = ActionButton(parent=self)
        self._sync.setObjectName("syncJellyfinPlayCounts")
        self._cancel = ActionButton(parent=self)
        self._cancel.setObjectName("cancelJellyfinPlayCounts")
        self._sync_row = SettingRow(
            "", "", self._buttons(self._sync, self._cancel), self
        )
        group = SettingGroup(self)
        group.setMaximumWidth(960)
        for row in (
            self._server_row,
            self._username_row,
            self._password_row,
            self._account_row,
            self._sync_row,
        ):
            group.add_row(row)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_xs)
        for widget in (self._title, group, self._status):
            layout.addWidget(widget)
        self._connect.clicked.connect(self._connect_account)
        self._password.returnPressed.connect(self._connect_account)
        self._disconnect.clicked.connect(controller.disconnect_account)
        self._sync.clicked.connect(controller.sync_now)
        self._cancel.clicked.connect(controller.cancel)
        controller.changed.connect(self._refresh)
        controller.message.connect(self._status.setText)
        settings.settingChanged.connect(self._refresh)
        self.retranslate_ui()

    def _buttons(self, *buttons: ActionButton) -> QWidget:
        widget = QWidget(self)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_xs)
        for button in buttons:
            layout.addWidget(button)
        return widget

    def _connect_account(self) -> None:
        self._controller.connect_account(
            self._server.text(), self._username.text(), self._password.text()
        )

    def _refresh(self) -> None:
        username = self._settings.get(JELLYFIN_USERNAME)
        server = self._settings.get(JELLYFIN_SERVER_URL)
        connected = bool(username)
        available = self._controller.available
        self._account_row.set_copy(
            "Jellyfin",
            self.tr("Connected as {username} on {server}").format(
                username=username, server=server
            )
            if connected
            else self.tr("Not connected"),
        )
        for row in (self._server_row, self._username_row, self._password_row):
            row.setVisible(not connected)
        if connected:
            self._password.clear()
        self._connect.setVisible(not connected)
        self._disconnect.setVisible(connected)
        for widget in (
            self._connect,
            self._disconnect,
            self._server,
            self._username,
            self._password,
        ):
            widget.setEnabled(available)
        self._sync_row.setVisible(connected)
        self._sync.setEnabled(self._controller.can_sync)
        self._cancel.setVisible(self._controller.syncing)

    def retranslate_ui(self) -> None:
        self._title.setText(self.tr("Jellyfin"))
        self._server_row.set_copy(
            self.tr("Server address"),
            self.tr("The address you open Jellyfin with, including the port."),
        )
        self._username_row.set_copy(self.tr("Username"), "")
        self._password_row.set_copy(
            self.tr("Password"),
            self.tr(
                "Used once to sign in. iOpenPod keeps only a sign-in token in your OS keyring."
            ),
        )
        self._server.setAccessibleName(self.tr("Jellyfin server address"))
        self._username.setAccessibleName(self.tr("Jellyfin username"))
        self._password.setAccessibleName(self.tr("Jellyfin password"))
        self._sync_row.set_copy(
            self.tr("Play counts"),
            self.tr(
                "Adds the plays from the Active iPod and Jellyfin together and saves the total on both."
            ),
        )
        self._connect.setText(self.tr("Connect"))
        self._disconnect.setText(self.tr("Disconnect"))
        self._sync.setText(self.tr("Sync play counts now"))
        self._cancel.setText(QCoreApplication.translate("CommonActions", "Cancel"))
        self._refresh()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
