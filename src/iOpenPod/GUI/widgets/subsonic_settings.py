"""Subsonic server credentials and playlist selection controls within Settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.subsonic.settings import (
    SUBSONIC_PLAYLIST_IDS,
    SUBSONIC_URL,
    SUBSONIC_USERNAME,
)
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.setting_group import SettingGroup, SettingRow
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

if TYPE_CHECKING:
    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.subsonic.controller import SubsonicController
    from iOpenPod.app.subsonic.models import SubsonicPlaylist


class SubsonicSettings(QWidget):
    """Configuration interface for Subsonic / OpenSubsonic server integration."""

    syncRequested = Signal()

    def __init__(
        self,
        settings: SettingsService,
        controller: SubsonicController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._controller = controller
        self._checkboxes: dict[str, QCheckBox] = {}
        self._remote_playlists: tuple[SubsonicPlaylist, ...] = ()

        self._setup_ui()
        self._load_saved_values()
        self._connect_signals()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_md)

        self._title = QLabel(self.tr("Subsonic Server"), self)
        self._title.setObjectName("sectionTitle")
        layout.addWidget(self._title)

        group = SettingGroup(self)

        self._url_edit = QLineEdit(self)
        self._url_edit.setPlaceholderText("https://music.example.com")
        self._url_row = SettingRow(
            self.tr("Server URL"),
            self.tr("Base URL of your Navidrome, Airsonic, or Subsonic server."),
            self._url_edit,
            self,
        )
        group.add_row(self._url_row)

        self._username_edit = QLineEdit(self)
        self._username_row = SettingRow(
            self.tr("Username"),
            self.tr("Subsonic account username."),
            self._username_edit,
            self,
        )
        group.add_row(self._username_row)

        self._password_edit = QLineEdit(self)
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_row = SettingRow(
            self.tr("Password"),
            "",
            self._password_edit,
            self,
        )
        group.add_row(self._password_row)

        test_panel = QWidget(self)
        test_layout = QHBoxLayout(test_panel)
        test_layout.setContentsMargins(0, 0, 0, 0)
        test_layout.setSpacing(LAYOUT.space_sm)

        self._test_button = ActionButton(parent=test_panel)
        self._test_button.setText(self.tr("Test Connection"))
        self._test_status = QLabel(self)
        self._test_status.setWordWrap(True)

        test_layout.addWidget(self._test_button)
        test_layout.addStretch(1)

        self._test_row = SettingRow(
            self.tr("Connection"),
            "",
            test_panel,
            self,
        )
        group.add_row(self._test_row)
        layout.addWidget(group)
        layout.addWidget(self._test_status)

        self._playlists_title = QLabel(self.tr("Subsonic Playlists"), self)
        self._playlists_title.setObjectName("sectionTitle")
        layout.addWidget(self._playlists_title)

        pl_group = SettingGroup(self)

        self._actions_panel = QWidget(self)
        actions_layout = QHBoxLayout(self._actions_panel)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(LAYOUT.space_xs)

        self._refresh_button = ActionButton(
            parent=self._actions_panel, kind=ActionButtonKind.QUIET
        )
        self._refresh_button.setText(self.tr("Refresh Playlists"))
        self._select_all_button = ActionButton(
            parent=self._actions_panel, kind=ActionButtonKind.QUIET
        )
        self._select_all_button.setText(self.tr("Select All"))
        self._deselect_all_button = ActionButton(
            parent=self._actions_panel, kind=ActionButtonKind.QUIET
        )
        self._deselect_all_button.setText(self.tr("Deselect All"))
        self._sync_button = ActionButton(
            parent=self._actions_panel, kind=ActionButtonKind.PRIMARY
        )
        self._sync_button.setText(self.tr("Sync to iPod"))

        actions_layout.addWidget(self._refresh_button)
        actions_layout.addWidget(self._select_all_button)
        actions_layout.addWidget(self._deselect_all_button)
        actions_layout.addWidget(self._sync_button)

        self._pl_actions_row = SettingRow(
            self.tr("Playlist Actions"),
            self.tr("Refresh playlist catalog from the server."),
            self._actions_panel,
            self,
        )
        self._actions_panel.setMinimumWidth(self._actions_panel.sizeHint().width())
        self._actions_panel.setMaximumWidth(16777215)
        self._actions_panel.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed
        )
        pl_group.add_row(self._pl_actions_row)

        self._scroll_frame = QFrame(pl_group)
        self._scroll_frame.setObjectName("settingRow")
        scroll_frame_layout = QVBoxLayout(self._scroll_frame)
        scroll_frame_layout.setContentsMargins(0, 0, 0, 0)

        self._pl_scroll = QScrollArea(self._scroll_frame)
        self._pl_scroll.setWidgetResizable(True)
        self._pl_scroll.setMaximumHeight(200)
        self._pl_scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self._pl_container = QWidget(self._pl_scroll)
        self._pl_container.setStyleSheet("background: transparent;")
        self._pl_list_layout = QVBoxLayout(self._pl_container)
        self._pl_list_layout.setContentsMargins(
            LAYOUT.space_md, LAYOUT.space_sm, LAYOUT.space_md, LAYOUT.space_sm
        )
        self._pl_list_layout.setSpacing(LAYOUT.space_xs)
        self._pl_scroll.setWidget(self._pl_container)

        self._no_playlists_label = QLabel(
            self.tr(
                "No playlists loaded. Click 'Test Connection' or 'Refresh Playlists' to load."
            ),
            self._pl_container,
        )
        self._no_playlists_label.setStyleSheet("color: gray;")
        self._pl_list_layout.addWidget(self._no_playlists_label)

        scroll_frame_layout.addWidget(self._pl_scroll)
        pl_group._layout.addWidget(self._scroll_frame)

        layout.addWidget(pl_group)

    def _load_saved_values(self) -> None:
        url = self._settings.get(SUBSONIC_URL)
        username = self._settings.get(SUBSONIC_USERNAME)
        password = self._controller.credentials.load_password(username)
        self._url_edit.setText(url)
        self._username_edit.setText(username)
        self._password_edit.setText(password)

    def _connect_signals(self) -> None:
        self._url_edit.editingFinished.connect(self._save_credentials)
        self._username_edit.editingFinished.connect(self._save_credentials)
        self._password_edit.editingFinished.connect(self._save_credentials)

        self._test_button.clicked.connect(self._on_test_clicked)
        self._refresh_button.clicked.connect(self._on_refresh_clicked)
        self._select_all_button.clicked.connect(self._select_all)
        self._deselect_all_button.clicked.connect(self._deselect_all)
        self._sync_button.clicked.connect(self._on_sync_clicked)

        self._controller.connectionTested.connect(
            self._on_connection_tested, Qt.ConnectionType.QueuedConnection
        )
        self._controller.playlistsLoaded.connect(
            self._on_playlists_loaded, Qt.ConnectionType.QueuedConnection
        )
        self._controller.error.connect(
            self._on_controller_error, Qt.ConnectionType.QueuedConnection
        )

    def _save_credentials(self) -> None:
        url = self._url_edit.text().strip()
        username = self._username_edit.text().strip()
        password = self._password_edit.text()
        self._settings.set_global(SUBSONIC_URL, url)
        self._settings.set_global(SUBSONIC_USERNAME, username)
        self._controller.credentials.save_password(username, password)

    @Slot()
    def _on_sync_clicked(self) -> None:
        self._save_credentials()
        self.syncRequested.emit()

    def set_active_ipod(self, active: object) -> None:
        self._sync_button.setEnabled(active is not None)
        if active is None:
            self._sync_button.setToolTip(self.tr("Select an Active iPod before Sync."))
        else:
            self._sync_button.setToolTip(
                self.tr("Sync selected Subsonic playlists to your iPod.")
            )

    @Slot()
    def _on_test_clicked(self) -> None:
        self._save_credentials()
        url = self._url_edit.text().strip()
        username = self._username_edit.text().strip()
        password = self._password_edit.text()
        if not url or not username:
            self._test_status.setText(
                self.tr("Please enter both server URL and username.")
            )
            self._test_status.setStyleSheet("color: red;")
            return

        self._test_button.setEnabled(False)
        self._test_status.setText(self.tr("Connecting…"))
        self._test_status.setStyleSheet("")
        self._controller.test_connection(url, username, password)

    @Slot(bool, str)
    def _on_connection_tested(self, success: bool, message: str) -> None:
        self._test_button.setEnabled(True)
        if success:
            self._test_status.setText(self.tr("Connected successfully!"))
            self._test_status.setStyleSheet("color: green;")
            self._on_refresh_clicked()
        else:
            self._test_status.setText(f"{self.tr('Connection failed')}: {message}")
            self._test_status.setStyleSheet("color: red;")

    @Slot()
    def _on_refresh_clicked(self) -> None:
        self._save_credentials()
        url = self._url_edit.text().strip()
        username = self._username_edit.text().strip()
        password = self._password_edit.text()
        if not url or not username:
            return
        self._refresh_button.setEnabled(False)
        self._controller.load_playlists(url, username, password)

    @Slot(object)
    def _on_playlists_loaded(self, playlists_obj: object) -> None:
        self._refresh_button.setEnabled(True)
        if not isinstance(playlists_obj, tuple):
            return
        self._remote_playlists = playlists_obj

        for cb in self._checkboxes.values():
            cb.setParent(None)
            cb.deleteLater()
        self._checkboxes.clear()

        if not self._remote_playlists:
            self._no_playlists_label.show()
            self._no_playlists_label.setText(self.tr("No playlists found on server."))
            return

        self._no_playlists_label.hide()
        playlist_ids: tuple[str, ...] = self._settings.get(SUBSONIC_PLAYLIST_IDS)
        saved_selected = set(playlist_ids)

        for pl in self._remote_playlists:
            cb = QCheckBox(f"{pl.name} ({pl.song_count} songs)", self._pl_container)
            cb.setChecked(pl.playlist_id in saved_selected)
            cb.stateChanged.connect(self._save_selected_playlists)
            self._pl_list_layout.addWidget(cb)
            self._checkboxes[pl.playlist_id] = cb

    @Slot(str)
    def _on_controller_error(self, error_msg: str) -> None:
        self._refresh_button.setEnabled(True)
        self._test_button.setEnabled(True)
        self._test_status.setText(error_msg)
        self._test_status.setStyleSheet("color: red;")

    def _save_selected_playlists(self) -> None:
        selected = tuple(pid for pid, cb in self._checkboxes.items() if cb.isChecked())
        self._settings.set_global(SUBSONIC_PLAYLIST_IDS, selected)

    def _select_all(self) -> None:
        for cb in self._checkboxes.values():
            cb.setChecked(True)
        self._save_selected_playlists()

    def _deselect_all(self) -> None:
        for cb in self._checkboxes.values():
            cb.setChecked(False)
        self._save_selected_playlists()

    def retranslate_ui(self) -> None:
        self._title.setText(self.tr("Subsonic Server"))
        self._url_row.set_copy(
            self.tr("Server URL"),
            self.tr("Base URL of your Navidrome, Airsonic, or Subsonic server."),
        )
        self._username_row.set_copy(
            self.tr("Username"),
            self.tr("Subsonic account username."),
        )
        self._password_row.set_copy(
            self.tr("Password"),
            "",
        )
        self._test_button.setText(self.tr("Test Connection"))
        self._playlists_title.setText(self.tr("Subsonic Playlists"))
        self._pl_actions_row.set_copy(
            self.tr("Playlist Actions"),
            self.tr("Refresh playlist catalog from the server."),
        )
        self._refresh_button.setText(self.tr("Refresh Playlists"))
        self._select_all_button.setText(self.tr("Select All"))
        self._deselect_all_button.setText(self.tr("Deselect All"))
        self._sync_button.setText(self.tr("Sync to iPod"))
        self._actions_panel.setMinimumWidth(self._actions_panel.sizeHint().width())

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
