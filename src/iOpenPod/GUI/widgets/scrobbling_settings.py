"""Service sign-in controls within Settings → Sync."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

from iOpenPod.app.scrobbling.models import Service
from iOpenPod.app.scrobbling.settings import account_setting
from iOpenPod.GUI.dialogs.scrobble_report import show_scrobble_report
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.setting_group import SettingGroup, SettingRow
from iOpenPod.GUI.widgets.themed_buttons import ActionButton

if TYPE_CHECKING:
    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.scrobbling.controller import ScrobbleController


class ScrobblingSettings(QWidget):
    def __init__(
        self,
        settings: SettingsService,
        controller: ScrobbleController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._controller = controller
        self._title = QLabel(self)
        self._title.setObjectName("sectionTitle")
        self._status = QLabel(self)
        self._status.setObjectName("scrobblingStatus")
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._status.setWordWrap(True)
        self._details = ActionButton(parent=self)
        self._details.setObjectName("scrobbleReportButton")
        self._details.clicked.connect(self._show_report)
        self._key = QLineEdit(self)
        self._key.setObjectName("lastfmApiKey")
        self._secret = QLineEdit(self)
        self._secret.setObjectName("lastfmApiSecret")
        self._token = QLineEdit(self)
        self._token.setObjectName("listenbrainzToken")
        for field in (self._key, self._secret, self._token):
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setMaxLength(256)
        self._key_row = SettingRow("", "", self._key, self)
        self._secret_row = SettingRow("", "", self._secret, self)
        self._token_row = SettingRow("", "", self._token, self)
        self._lastfm = ActionButton(parent=self)
        self._lastfm.setObjectName("connectLastfm")
        self._finish = ActionButton(parent=self)
        self._finish.setObjectName("finishLastfm")
        self._lastfm_disconnect = ActionButton(parent=self)
        self._lastfm_disconnect.setObjectName("disconnectLastfm")
        self._lb = ActionButton(parent=self)
        self._lb.setObjectName("connectListenbrainz")
        self._lb_disconnect = ActionButton(parent=self)
        self._lb_disconnect.setObjectName("disconnectListenbrainz")
        self._lastfm_help = ActionButton(parent=self)
        self._lb_help = ActionButton(parent=self)
        self._lf_row = SettingRow(
            "Last.fm",
            "",
            self._buttons(
                self._lastfm, self._finish, self._lastfm_disconnect, self._lastfm_help
            ),
            self,
        )
        self._lb_row = SettingRow(
            "ListenBrainz",
            "",
            self._buttons(self._lb, self._lb_disconnect, self._lb_help),
            self,
        )
        group = SettingGroup(self)
        group.setMaximumWidth(960)
        for row in (
            self._key_row,
            self._secret_row,
            self._lf_row,
            self._token_row,
            self._lb_row,
        ):
            group.add_row(row)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_xs)
        for widget in (self._title, group, self._status):
            layout.addWidget(widget)
        layout.addWidget(self._details, alignment=Qt.AlignmentFlag.AlignLeft)
        self._lastfm.clicked.connect(
            lambda: controller.begin_lastfm(self._key.text(), self._secret.text())
        )
        self._finish.clicked.connect(controller.finish_lastfm)
        self._lb.clicked.connect(
            lambda: controller.connect_listenbrainz(self._token.text())
        )
        self._lastfm_disconnect.clicked.connect(
            lambda: controller.disconnect_service(Service.LASTFM)
        )
        self._lb_disconnect.clicked.connect(
            lambda: controller.disconnect_service(Service.LISTENBRAINZ)
        )
        self._lastfm_help.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://www.last.fm/api/account/create")
            )
        )
        self._lb_help.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://listenbrainz.org/settings/"))
        )
        controller.authorizationRequested.connect(self._open_authorization)
        controller.changed.connect(self._refresh)
        controller.message.connect(self._status.setText)
        settings.settingChanged.connect(self._refresh)
        self.retranslate_ui()

    def _buttons(self, *buttons: ActionButton) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_xs)
        for button in buttons:
            layout.addWidget(button)
        return widget

    def _show_report(self) -> None:
        result = self._controller.last_result
        if result is not None:
            show_scrobble_report(result, self)

    def _open_authorization(self, url: str) -> None:
        if not QDesktopServices.openUrl(QUrl(url)):
            self._status.setText(
                self.tr(
                    "The browser could not be opened. Enable your default browser and start signing in again."
                )
            )

    def _refresh(self) -> None:
        self._details.setVisible(self._controller.last_result is not None)
        available = self._controller.available
        for service, row, connect, disconnect in (
            (Service.LASTFM, self._lf_row, self._lastfm, self._lastfm_disconnect),
            (Service.LISTENBRAINZ, self._lb_row, self._lb, self._lb_disconnect),
        ):
            username = self._settings.get(account_setting(service))
            row.set_copy(
                service.label,
                self.tr("Connected as {username}").format(username=username)
                if username
                else self.tr("Not connected"),
            )
            connect.setVisible(not bool(username))
            disconnect.setVisible(bool(username))
            connect.setEnabled(available)
            disconnect.setEnabled(available)
            if service is Service.LASTFM:
                self._key_row.setVisible(not bool(username))
                self._secret_row.setVisible(not bool(username))
                if username:
                    self._key.clear()
                    self._secret.clear()
            else:
                self._token_row.setVisible(not bool(username))
                if username:
                    self._token.clear()
        self._finish.setVisible(self._controller.awaiting_authorization)
        self._finish.setEnabled(available)
        for field in (self._key, self._secret, self._token):
            field.setEnabled(available)

    def retranslate_ui(self) -> None:
        self._details.setText(self.tr("View last scrobble report"))
        self._title.setText(self.tr("Scrobbling accounts"))
        self._key_row.set_copy(
            self.tr("Last.fm API key"),
            self.tr(
                "Register a Last.fm application to obtain its key and shared secret."
            ),
        )
        self._secret_row.set_copy(self.tr("Last.fm shared secret"), "")
        self._token_row.set_copy(
            self.tr("ListenBrainz user token"),
            self.tr("Copy your user token from ListenBrainz settings."),
        )
        self._key.setAccessibleName(self.tr("Last.fm API key"))
        self._secret.setAccessibleName(self.tr("Last.fm shared secret"))
        self._token.setAccessibleName(self.tr("ListenBrainz user token"))
        self._lastfm.setText(self.tr("Sign in with Last.fm"))
        self._finish.setText(self.tr("Finish signing in"))
        self._lb.setText(self.tr("Connect ListenBrainz"))
        self._lastfm_disconnect.setText(self.tr("Disconnect"))
        self._lb_disconnect.setText(self.tr("Disconnect"))
        self._lastfm_help.setText(self.tr("Get API key"))
        self._lb_help.setText(self.tr("Get user token"))
        self._refresh()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
