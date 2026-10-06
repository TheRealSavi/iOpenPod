"""Application Settings page composed from reusable setting rows."""

import sys
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QSignalBlocker,
    QSize,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.core.logging import active_log_path
from iOpenPod.app.core.settings.definitions import (
    BACKUP_LOCATION,
    DRAFT_ALL_CHANGES,
    IPOD_LIBRARY_VIEW_MODE,
    LIBRARY_DOUBLE_CLICK_SHORTCUT,
    MANAGE_VOLUME_PRESENTATION,
    MAX_BACKUPS,
    PLAYER_POSITION,
    AppearanceMode,
    DarkTheme,
    IPodLibraryViewMode,
    LibraryDoubleClickShortcut,
    LightTheme,
    PlayerPosition,
    TrackTitleBarStyle,
)
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.version import get_version
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.scrobbling.controller import ScrobbleController
from iOpenPod.app.services.linux_identity import (
    UDEV_RULE_DESTINATION,
    UdevRuleStatus,
    UdevRuleStatusKind,
    inspect_udev_rule,
)
from iOpenPod.app.services.media_tools import MediaToolSetup
from iOpenPod.app.updates.backend import InstallChannel
from iOpenPod.GUI.dialogs.linux_identity_setup import (
    LinuxIdentityUninstallDialog,
)
from iOpenPod.GUI.presentation.i18n.manager import I18nManager
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.browser_chrome import PageHeader
from iOpenPod.GUI.widgets.ipod_preferences import IPodPreferencesView
from iOpenPod.GUI.widgets.media_tools_settings import MediaToolsSettings
from iOpenPod.GUI.widgets.scrobbling_settings import ScrobblingSettings
from iOpenPod.GUI.widgets.setting_group import SettingGroup, SettingRow
from iOpenPod.GUI.widgets.sync_settings import SyncSettings, TranscodingSettings
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

_ISSUES_URL = "https://github.com/TheRealSavi/iOpenPod/issues"
_DONATION_URL = "https://ko-fi.com/johngibbons"


class SettingsPage(QWidget):
    """Expose preferences while Theme and I18n modules own side effects."""

    mediaToolsRequested = Signal()
    mediaToolsCheckRequested = Signal()
    appUpdatesRequested = Signal()

    def __init__(
        self,
        settings: SettingsService,
        theme_manager: ThemeManager,
        i18n_manager: I18nManager,
        parent: QWidget | None = None,
        *,
        scrobbling: ScrobbleController | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._theme_manager = theme_manager
        self._i18n_manager = i18n_manager
        self._version = get_version()
        self._install_channel = InstallChannel.UNKNOWN
        self._update_busy = False

        self._header = PageHeader(self)
        self._appearance_title = QLabel(self)
        self._appearance_title.setObjectName("sectionTitle")

        self._mode_combo = AppComboBox(self)
        self._mode_combo.setObjectName("appearanceModeCombo")
        self._mode_row = SettingRow("", "", self._mode_combo, self)
        self._light_theme_combo = AppComboBox(self)
        self._light_theme_combo.setObjectName("lightThemeCombo")
        self._light_theme_row = SettingRow("", "", self._light_theme_combo, self)
        self._dark_theme_combo = AppComboBox(self)
        self._dark_theme_combo.setObjectName("darkThemeCombo")
        self._dark_theme_row = SettingRow("", "", self._dark_theme_combo, self)
        self._colorful_mode_combo = AppComboBox(self)
        self._colorful_mode_combo.setObjectName("colorfulModeCombo")
        self._colorful_mode_row = SettingRow(
            "",
            "",
            self._colorful_mode_combo,
            self,
        )
        self._track_title_bar_combo = AppComboBox(self)
        self._track_title_bar_combo.setObjectName("trackTitleBarStyleCombo")
        self._track_title_bar_row = SettingRow(
            "", "", self._track_title_bar_combo, self
        )
        self._player_position_combo = AppComboBox(self)
        self._player_position_combo.setObjectName("playerPositionCombo")
        self._player_position_row = SettingRow(
            "",
            "",
            self._player_position_combo,
            self,
        )
        self._language_combo = AppComboBox(self)
        self._language_row = SettingRow("", "", self._language_combo, self)

        self._library_title = QLabel(self)
        self._library_title.setObjectName("sectionTitle")
        self._draft_all_changes_combo = AppComboBox(self)
        self._draft_all_changes_combo.setObjectName("draftAllChangesCombo")
        self._draft_all_changes_row = SettingRow(
            "", "", self._draft_all_changes_combo, self
        )
        library = SettingGroup(self)
        library.setMaximumWidth(960)
        self._ipod_view_mode_combo = AppComboBox(self)
        self._ipod_view_mode_combo.setObjectName("ipodLibraryViewModeCombo")
        self._ipod_view_mode_row = SettingRow("", "", self._ipod_view_mode_combo, self)
        library.add_row(self._ipod_view_mode_row)
        self._double_click_combo = AppComboBox(self)
        self._double_click_combo.setObjectName("libraryDoubleClickShortcutCombo")
        self._double_click_row = SettingRow("", "", self._double_click_combo, self)
        library.add_row(self._double_click_row)
        library.add_row(self._draft_all_changes_row)
        self._volume_presentation_combo = AppComboBox(self)
        self._volume_presentation_combo.setObjectName("manageVolumePresentationCombo")
        self._volume_presentation_row = SettingRow(
            "", "", self._volume_presentation_combo, self
        )
        library.add_row(self._volume_presentation_row)

        self._backups_title = QLabel(self)
        self._backups_title.setObjectName("sectionTitle")
        backup_location_control = QWidget(self)
        backup_location_layout = QHBoxLayout(backup_location_control)
        backup_location_layout.setContentsMargins(0, 0, 0, 0)
        backup_location_layout.setSpacing(LAYOUT.space_xs)
        self._backup_location = QLineEdit(backup_location_control)
        self._backup_location.setObjectName("backupLocation")
        self._backup_location.setReadOnly(True)
        self._choose_backup_location = ActionButton(parent=backup_location_control)
        self._choose_backup_location.setObjectName("chooseBackupLocation")
        backup_location_layout.addWidget(self._backup_location, 1)
        backup_location_layout.addWidget(self._choose_backup_location)
        self._backup_location_row = SettingRow("", "", backup_location_control, self)
        self._max_backups = AppComboBox(self)
        self._max_backups.setObjectName("maxBackups")
        self._max_backups_row = SettingRow("", "", self._max_backups, self)

        appearance = SettingGroup(self)
        appearance.setMaximumWidth(960)
        appearance.add_row(self._mode_row)
        appearance.add_row(self._light_theme_row)
        appearance.add_row(self._dark_theme_row)
        appearance.add_row(self._colorful_mode_row)
        appearance.add_row(self._track_title_bar_row)
        appearance.add_row(self._player_position_row)
        appearance.add_row(self._language_row)

        self._donation_banner = QFrame(self)
        self._donation_banner.setObjectName("donationBanner")
        self._donation_banner.setMaximumWidth(960)
        donation_layout = QHBoxLayout(self._donation_banner)
        donation_layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_md,
            LAYOUT.space_lg,
            LAYOUT.space_md,
        )
        donation_layout.setSpacing(LAYOUT.space_md)
        self._donation_icon = QLabel(self._donation_banner)
        self._donation_icon.setObjectName("donationIcon")
        self._donation_icon.setFixedSize(
            LAYOUT.icon_button_size, LAYOUT.icon_button_size
        )
        self._donation_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        donation_layout.addWidget(self._donation_icon, 0, Qt.AlignmentFlag.AlignTop)
        donation_copy = QVBoxLayout()
        donation_copy.setContentsMargins(0, 0, 0, 0)
        donation_copy.setSpacing(LAYOUT.space_2xs)
        self._donation_title = QLabel(self._donation_banner)
        self._donation_title.setObjectName("donationTitle")
        self._donation_description = QLabel(self._donation_banner)
        self._donation_description.setObjectName("donationDescription")
        self._donation_description.setWordWrap(True)
        self._donation_description.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        donation_copy.addWidget(self._donation_title)
        donation_copy.addWidget(self._donation_description)
        donation_layout.addLayout(donation_copy, 1)
        self._donate = ActionButton(parent=self._donation_banner)
        self._donate.setObjectName("donate")
        donation_layout.addWidget(self._donate, 0, Qt.AlignmentFlag.AlignVCenter)

        backups = SettingGroup(self)
        backups.setMaximumWidth(960)
        backups.add_row(self._backup_location_row)
        backups.add_row(self._max_backups_row)

        self._linux_supported = sys.platform.startswith("linux")
        self._udev_rule_status: UdevRuleStatus | None = None
        self._linux_title = QLabel(self)
        self._linux_title.setObjectName("sectionTitle")
        self._check_udev_rule = ActionButton(parent=self)
        self._check_udev_rule.setObjectName("checkUdevRule")
        self._udev_status_row = SettingRow("", "", self._check_udev_rule, self)
        self._uninstall_udev_rule = ActionButton(
            parent=self,
            kind=ActionButtonKind.DANGER,
        )
        self._uninstall_udev_rule.setObjectName("uninstallUdevRule")
        self._udev_uninstall_row = SettingRow(
            "",
            "",
            self._uninstall_udev_rule,
            self,
        )
        linux_settings = SettingGroup(self)
        linux_settings.setMaximumWidth(960)
        linux_settings.add_row(self._udev_status_row)
        linux_settings.add_row(self._udev_uninstall_row)
        self._linux_section = QWidget(self)
        self._linux_section.setObjectName("linuxHostIntegrationSection")
        linux_layout = QVBoxLayout(self._linux_section)
        linux_layout.setContentsMargins(0, 0, 0, 0)
        linux_layout.setSpacing(LAYOUT.space_xs)
        linux_layout.addWidget(self._linux_title)
        linux_layout.addWidget(linux_settings)
        self._linux_section.setVisible(self._linux_supported)

        self._about_title = QLabel(self)
        self._about_title.setObjectName("sectionTitle")
        self._check_updates = ActionButton(parent=self)
        self._check_updates.setObjectName("checkAppUpdates")
        self._check_updates.clicked.connect(self.appUpdatesRequested.emit)
        self._version_row = SettingRow("", "", self._check_updates, self)
        self._version_row.setObjectName("currentAppVersion")
        self._update_message = QLabel(self)
        self._update_message.setObjectName("appUpdateMessage")
        self._update_message.setWordWrap(True)
        self._update_message.setTextFormat(Qt.TextFormat.PlainText)
        self._update_message.setMaximumWidth(960)
        self._update_message.hide()
        self._report_issue = ActionButton(parent=self)
        self._report_issue.setObjectName("reportIssue")
        self._report_issue_row = SettingRow("", "", self._report_issue, self)
        self._open_log_folder = ActionButton(parent=self)
        self._open_log_folder.setObjectName("openLogFolder")
        self._open_log_folder_row = SettingRow("", "", self._open_log_folder, self)
        about = SettingGroup(self)
        about.setMaximumWidth(960)
        about.add_row(self._version_row)
        about.add_row(self._open_log_folder_row)
        about.add_row(self._report_issue_row)

        self._credits = QLabel(self)
        self._credits.setObjectName("aboutCredits")
        self._credits.setMaximumWidth(960)
        self._credits.setWordWrap(True)
        self._credits.setTextFormat(Qt.TextFormat.RichText)
        self._credits.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self._credits.setOpenExternalLinks(True)

        self._saved_note = QLabel(self)
        self._saved_note.setObjectName("pageMeta")
        self._saved_note.setWordWrap(True)

        self._tabs = QTabWidget(self)
        self._tabs.setObjectName("settingsTabs")
        self._tabs.setDocumentMode(True)
        self._tabs.setUsesScrollButtons(True)
        self._tabs.tabBar().setExpanding(False)
        # Keep tab clicks from restoring an off-screen control and jumping the scroll.
        self._tabs.tabBar().setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._transcoding_settings = TranscodingSettings(settings, self)
        self._media_tools = MediaToolsSettings(self)
        self._media_tools.setupRequested.connect(self.mediaToolsRequested.emit)
        self._media_tools.checkRequested.connect(self.mediaToolsCheckRequested.emit)
        self._sync_settings = SyncSettings(settings, self)
        self._appearance_tab = self._add_tab(
            "appearanceSettingsScroll",
            self._appearance_title,
            appearance,
            self._donation_banner,
        )
        self._library_tab = self._add_tab(
            "librarySettingsScroll", self._library_title, library
        )
        self._transcoding_tab = self._add_tab(
            "transcodingSettingsScroll", self._transcoding_settings
        )
        self._media_tools_tab = self._add_tab(
            "mediaToolsSettingsScroll", self._media_tools
        )
        self._scrobbling_settings = (
            ScrobblingSettings(settings, scrobbling, self)
            if scrobbling is not None
            else None
        )
        self._sync_tab = self._add_tab(
            "syncSettingsScroll",
            self._sync_settings,
            *(
                (self._scrobbling_settings,)
                if self._scrobbling_settings is not None
                else ()
            ),
        )
        self._backups_tab = self._add_tab(
            "backupSettingsScroll", self._backups_title, backups
        )
        self._ipod_preferences = IPodPreferencesView(self)
        self._ipod_preferences_tab = self._add_tab(
            "ipodPreferencesScroll", self._ipod_preferences
        )
        self._linux_tab = (
            self._add_tab("linuxSettingsScroll", self._linux_section)
            if self._linux_supported
            else None
        )
        self._about_tab = self._add_tab(
            "aboutSettingsScroll",
            self._about_title,
            about,
            self._update_message,
            self._credits,
        )

        footer = QHBoxLayout()
        footer.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_sm, LAYOUT.space_lg, LAYOUT.space_sm
        )
        footer.addWidget(self._saved_note)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addWidget(self._tabs, 1)
        layout.addLayout(footer)

        self._mode_combo.currentIndexChanged.connect(self._mode_selected)
        self._light_theme_combo.currentIndexChanged.connect(self._light_theme_selected)
        self._dark_theme_combo.currentIndexChanged.connect(self._dark_theme_selected)
        self._colorful_mode_combo.currentIndexChanged.connect(
            self._colorful_mode_selected
        )
        self._player_position_combo.currentIndexChanged.connect(
            self._player_position_selected
        )
        self._track_title_bar_combo.currentIndexChanged.connect(
            self._track_title_bar_selected
        )
        self._language_combo.currentIndexChanged.connect(self._language_selected)
        self._draft_all_changes_combo.currentIndexChanged.connect(
            self._draft_all_changes_selected
        )
        self._volume_presentation_combo.currentIndexChanged.connect(
            self._volume_presentation_selected
        )
        self._ipod_view_mode_combo.currentIndexChanged.connect(
            self._ipod_view_mode_selected
        )
        self._double_click_combo.currentIndexChanged.connect(
            self._double_click_selected
        )
        self._choose_backup_location.clicked.connect(self._choose_backup_folder)
        self._max_backups.currentIndexChanged.connect(self._max_backups_selected)
        self._check_udev_rule.clicked.connect(self._inspect_udev_rule)
        self._uninstall_udev_rule.clicked.connect(self._show_udev_uninstall)
        self._report_issue.clicked.connect(self._open_issue_tracker)
        self._open_log_folder.clicked.connect(self._show_log_folder)
        self._donate.clicked.connect(self._open_donation_page)
        self._tabs.currentChanged.connect(self._update_saved_note)
        self._tabs.currentChanged.connect(self._check_media_tools_tab)
        settings.settingChanged.connect(self._setting_changed)
        theme_manager.modeChanged.connect(self._sync_mode_selection)
        theme_manager.lightThemeChanged.connect(self._sync_light_theme_selection)
        theme_manager.darkThemeChanged.connect(self._sync_dark_theme_selection)
        theme_manager.effectiveThemeChanged.connect(self._update_credits)
        theme_manager.effectiveThemeChanged.connect(self._update_donation_icon)
        theme_manager.colorfulModeChanged.connect(self._sync_colorful_mode_selection)
        theme_manager.trackTitleBarStyleChanged.connect(
            self._sync_track_title_bar_selection
        )
        i18n_manager.languageChanged.connect(self._language_changed)
        self.retranslate_ui()
        self._update_donation_icon()
        if self._linux_supported:
            self._inspect_udev_rule()

    def show_sync_settings(self) -> None:
        self._tabs.setCurrentIndex(self._sync_tab)

    def set_app_update_status(
        self, channel: InstallChannel, *, busy: bool, message: str
    ) -> None:
        self._install_channel = channel
        self._update_busy = busy
        self._update_message.setText(message)
        self._update_message.setVisible(bool(message))
        self._update_version()

    def _update_version(self) -> None:
        self._version_row.set_copy(
            self.tr("Version"),
            self.tr("%1 · %2")
            .replace("%1", self._version)
            .replace("%2", workflow_text(self._install_channel.display_name)),
        )
        self._check_updates.setText(
            self.tr("Checking…") if self._update_busy else self.tr("Check for updates")
        )
        self._check_updates.setEnabled(not self._update_busy)

    def set_media_tools_status(
        self, setup: MediaToolSetup | None, *, checking: bool, busy: bool, message: str
    ) -> None:
        self._media_tools.set_status(
            setup, checking=checking, busy=busy, message=message
        )

    def _check_media_tools_tab(self, index: int) -> None:
        if index == self._media_tools_tab:
            self.mediaToolsCheckRequested.emit()

    def _add_tab(self, name: str, *widgets: QWidget) -> int:
        scroll = QScrollArea(self._tabs)
        scroll.setObjectName(name)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.setSpacing(LAYOUT.space_xs)
        for widget in widgets:
            layout.addWidget(widget)
        layout.addStretch(1)
        scroll.setWidget(content)
        return self._tabs.addTab(scroll, "")

    def retranslate_ui(self) -> None:
        self._update_version()
        self._media_tools.retranslate_ui()
        self._header.set_title(self.tr("Settings"))
        self._tabs.setAccessibleName(self.tr("Settings categories"))
        self._tabs.setTabText(self._appearance_tab, self.tr("Appearance"))
        self._tabs.setTabText(self._library_tab, self.tr("Library"))
        self._tabs.setTabText(self._transcoding_tab, self.tr("Transcoding"))
        self._tabs.setTabText(self._media_tools_tab, self.tr("Media Tools"))
        self._tabs.setTabText(self._sync_tab, self.tr("Sync"))
        self._tabs.setTabText(self._backups_tab, self.tr("Backups"))
        self._tabs.setTabText(self._ipod_preferences_tab, self.tr("iPod Preferences"))
        if self._linux_tab is not None:
            self._tabs.setTabText(self._linux_tab, self.tr("Linux"))
        self._tabs.setTabText(self._about_tab, self.tr("About"))
        self._appearance_title.setText(self.tr("Appearance and language"))
        self._library_title.setText(self.tr("Library"))
        self._ipod_view_mode_row.set_copy(
            self.tr("iPod Library View Mode"),
            self.tr(
                "Show Tracks below Album and collection grids, or open them "
                "on a whole page like the Host Sync Library."
            ),
        )
        self._draft_all_changes_row.set_copy(
            self.tr("Draft all changes"),
            self.tr(
                "On: review and accept changes before saving to your iPod. "
                "Off: apply changes to your iPod immediately, including pending changes."
            ),
        )
        self._volume_presentation_row.set_copy(
            self.tr("Manage iPod drive appearance"),
            self.tr(
                "Use the iPod's name and model icon in desktop file managers. "
                "Turn off to preserve custom drive names, icons, and companion files."
            ),
        )
        self._double_click_row.set_copy(
            self.tr("Double click shortcut"),
            self.tr(
                "Choose what double-clicking selected Tracks, Albums, or collections does. "
                "Play now starts the first Track and puts the rest at the top of the Queue. "
                "Edit opens the metadata editor."
            ),
        )
        self._backups_title.setText(self.tr("Backup Snapshots"))
        self._linux_title.setText(self.tr("Linux Host Integration"))
        self._about_title.setText(self.tr("About iOpenPod"))
        self._update_credits()
        self._mode_row.set_copy(
            self.tr("Mode"),
            self.tr("Use Light or Dark appearance, or follow the Host automatically."),
        )
        self._light_theme_row.set_copy(
            self.tr("Light theme"),
            self.tr("Choose the exact theme used whenever Light appearance is active."),
        )
        self._dark_theme_row.set_copy(
            self.tr("Dark theme"),
            self.tr("Choose the exact theme used whenever Dark appearance is active."),
        )
        self._colorful_mode_row.set_copy(
            self.tr("Colorful mode"),
            self.tr(
                "Tint collection-card backgrounds and the Track-list title bar "
                "from their image."
            ),
        )
        self._player_position_row.set_copy(
            self.tr("Player position"),
            self.tr("Place the Player above or below the main application area."),
        )
        self._track_title_bar_row.set_copy(
            self.tr("Track-list title bar"),
            self.tr("Use a flat bar or rounded corners with a soft gradient."),
        )
        self._language_row.set_copy(
            self.tr("Language"),
            self.tr("Use the Host language or a packaged translation."),
        )
        self._backup_location_row.set_copy(
            self.tr("Backup location"),
            self.tr("Store native Backup Snapshots and Restore Recovery records here."),
        )
        self._max_backups_row.set_copy(
            self.tr("Snapshots per iPod"),
            self.tr(
                "Keep all manual snapshots, or prune the oldest regular snapshots "
                "after a new one is verified."
            ),
        )
        self._udev_status_row.set_copy(
            self.tr("iPod identity rule"),
            self._udev_status_description(),
        )
        self._udev_uninstall_row.set_copy(
            self.tr("Uninstall local rule"),
            self.tr(
                "Review a command that removes only iOpenPod's local /etc rule. "
                "Package-managed copies under /usr or /lib are preserved."
            ),
        )
        self._report_issue_row.set_copy(
            QCoreApplication.translate("CommonActions", "Report an Issue"),
            self.tr("Open the iOpenPod issue tracker on GitHub."),
        )
        self._open_log_folder_row.set_copy(
            self.tr("Log files"),
            self.tr("Open the folder containing the active iOpenPod log file."),
        )
        self._open_log_folder.setText(self.tr("Open Log Folder"))
        self._open_log_folder.setEnabled(active_log_path() is not None)
        self._donation_title.setText(self.tr("Support iOpenPod"))
        self._donation_description.setText(
            self.tr(
                "iOpenPod is and always will be completely free and open source. "
                "If you like it and would like to support me, it is so very appreciated."
            )
        )
        self._choose_backup_location.setText(self.tr("Choose…"))
        self._check_udev_rule.setText(self.tr("Check Again"))
        self._uninstall_udev_rule.setText(self.tr("Uninstall Rule"))
        self._report_issue.setText(
            QCoreApplication.translate("CommonActions", "Report an Issue")
        )
        self._donate.setText(self.tr("Support on Ko-fi ↗"))
        self._update_saved_note()
        self._ipod_preferences.retranslate_ui()
        self._rebuild_appearance_options()
        self._rebuild_player_position_options()
        self._rebuild_language_options()
        self._rebuild_backup_options()
        self._rebuild_draft_all_changes_options()
        self._rebuild_volume_presentation_options()
        self._rebuild_ipod_view_mode_options()
        self._rebuild_double_click_options()
        self._sync_backup_location(self._settings.get(BACKUP_LOCATION))
        self._transcoding_settings.retranslate_ui()
        self._sync_settings.retranslate_ui()

    def set_active_ipod(self, active: ActiveIPod | None) -> None:
        self._ipod_preferences.set_active_ipod(active)

    def _update_saved_note(self, _index: int = -1) -> None:
        text = (
            self.tr("Media tool status is read-only.")
            if self._tabs.currentIndex() == self._media_tools_tab
            else self.tr("iPod preferences are read-only.")
            if self._tabs.currentIndex() == self._ipod_preferences_tab
            else self.tr("Changes are saved automatically.")
        )
        if self._saved_note.text() != text:
            self._saved_note.setText(text)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _update_credits(self) -> None:
        self._credits.setText(
            f"<style>a {{ color: {self._theme_manager.tokens.accent}; }}</style>"
            + self.tr(
                "<p>iOpenPod is free software under {license}. "
                "You may modify and redistribute it under those terms. "
                "It comes without any warranty.</p>"
                "<p>Special thanks to {hashab} for the HASHAB WebAssembly "
                "implementation used by iOpenPod.</p>"
                "<p>An honorary thank-you to the {libgpod} and {gtkpod} "
                "contributors for their pioneering iPod support, documentation, "
                "and the references this project learned from.</p>"
                "<p>Application icon by DJShott, used with permission.</p>"
            ).format(
                license='<a href="https://www.gnu.org/licenses/gpl-3.0.html">'
                + self.tr("GPLv3 or later")
                + "</a>",
                hashab='<a href="https://github.com/dstaley/hashab">Dylan Staley (@dstaley)</a>',
                libgpod='<a href="https://github.com/gtkpod/libgpod">libgpod</a>',
                gtkpod='<a href="https://github.com/gtkpod/gtkpod">gtkpod</a>',
            )
        )

    def _update_donation_icon(self) -> None:
        size = LAYOUT.icon_size + LAYOUT.space_xs
        self._donation_icon.setPixmap(
            glyph_icon(
                "heart",
                size,
                QColor(self._theme_manager.tokens.accent),
                self._donation_icon.devicePixelRatioF(),
            ).pixmap(QSize(size, size), self._donation_icon.devicePixelRatioF())
        )

    def _rebuild_appearance_options(self) -> None:
        blockers = tuple(
            QSignalBlocker(combo)
            for combo in (
                self._mode_combo,
                self._light_theme_combo,
                self._dark_theme_combo,
                self._colorful_mode_combo,
                self._track_title_bar_combo,
            )
        )
        self._mode_combo.clear()
        self._mode_combo.addItem(self.tr("Auto"), AppearanceMode.SYSTEM.value)
        self._mode_combo.addItem(self.tr("Light"), AppearanceMode.LIGHT.value)
        self._mode_combo.addItem(self.tr("Dark"), AppearanceMode.DARK.value)
        self._light_theme_combo.clear()
        self._light_theme_combo.addItem(
            self.tr("Porcelain"),
            LightTheme.PORCELAIN.value,
        )
        self._light_theme_combo.addItem(
            self.tr("Catppuccin Latte"), LightTheme.CATPPUCCIN_LATTE.value
        )
        self._light_theme_combo.addItem(
            self.tr("Dune Plover"), LightTheme.DUNE_PLOVER.value
        )
        self._light_theme_combo.addItem(
            self.tr("Sea Glass"), LightTheme.SEA_GLASS.value
        )
        self._dark_theme_combo.clear()
        self._dark_theme_combo.addItem(self.tr("Slate"), DarkTheme.SLATE.value)
        self._dark_theme_combo.addItem(
            self.tr("Original iOpenPod"),
            DarkTheme.ORIGINAL.value,
        )
        self._dark_theme_combo.addItem(
            self.tr("Catppuccin Frappé"), DarkTheme.CATPPUCCIN_FRAPPE.value
        )
        self._dark_theme_combo.addItem(
            self.tr("Catppuccin Macchiato"), DarkTheme.CATPPUCCIN_MACCHIATO.value
        )
        self._dark_theme_combo.addItem(
            self.tr("Catppuccin Mocha"), DarkTheme.CATPPUCCIN_MOCHA.value
        )
        self._dark_theme_combo.addItem(self.tr("Gravity"), DarkTheme.GRAVITY.value)
        self._dark_theme_combo.addItem(
            self.tr("Northern Lights"), DarkTheme.NORTHERN_LIGHTS.value
        )
        self._dark_theme_combo.addItem(self.tr("Orchid"), DarkTheme.ORCHID.value)
        self._colorful_mode_combo.clear()
        self._colorful_mode_combo.addItem(self.tr("Off"), False)
        self._colorful_mode_combo.addItem(self.tr("On"), True)
        self._track_title_bar_combo.clear()
        self._track_title_bar_combo.addItem(
            self.tr("Flat"), TrackTitleBarStyle.FLAT.value
        )
        self._track_title_bar_combo.addItem(
            self.tr("Round"), TrackTitleBarStyle.ROUND.value
        )
        self._sync_mode_selection(self._theme_manager.mode.value)
        self._sync_light_theme_selection(self._theme_manager.light_theme.value)
        self._sync_dark_theme_selection(self._theme_manager.dark_theme.value)
        self._sync_colorful_mode_selection(self._theme_manager.colorful_mode)
        self._sync_track_title_bar_selection(
            self._theme_manager.track_title_bar_style.value
        )
        del blockers

    def _rebuild_language_options(self) -> None:
        blocker = QSignalBlocker(self._language_combo)
        self._language_combo.clear()
        for option in self._i18n_manager.available_languages():
            self._language_combo.addItem(option.label, option.language_tag)
        index = self._language_combo.findData(self._i18n_manager.language)
        self._language_combo.setCurrentIndex(max(0, index))
        del blocker

    def _rebuild_player_position_options(self) -> None:
        blocker = QSignalBlocker(self._player_position_combo)
        self._player_position_combo.clear()
        self._player_position_combo.addItem(
            self.tr("Top"),
            PlayerPosition.TOP.value,
        )
        self._player_position_combo.addItem(
            self.tr("Bottom"),
            PlayerPosition.BOTTOM.value,
        )
        self._sync_player_position_selection(self._settings.get(PLAYER_POSITION))
        del blocker

    def _rebuild_backup_options(self) -> None:
        blocker = QSignalBlocker(self._max_backups)
        self._max_backups.clear()
        self._max_backups.addItem(self.tr("Unlimited"), 0)
        for count in (1, 3, 5, 10, 20):
            self._max_backups.addItem(str(count), count)
        self._sync_max_backups(self._settings.get(MAX_BACKUPS))
        del blocker

    def _rebuild_draft_all_changes_options(self) -> None:
        blocker = QSignalBlocker(self._draft_all_changes_combo)
        self._draft_all_changes_combo.clear()
        self._draft_all_changes_combo.addItem(self.tr("Off"), False)
        self._draft_all_changes_combo.addItem(self.tr("On"), True)
        self._sync_draft_all_changes(self._settings.get(DRAFT_ALL_CHANGES))
        del blocker

    def _rebuild_ipod_view_mode_options(self) -> None:
        blocker = QSignalBlocker(self._ipod_view_mode_combo)
        self._ipod_view_mode_combo.clear()
        self._ipod_view_mode_combo.addItem(
            self.tr("Split Table"), IPodLibraryViewMode.SPLIT_TABLE.value
        )
        self._ipod_view_mode_combo.addItem(
            self.tr("Whole Page Table"), IPodLibraryViewMode.WHOLE_PAGE_TABLE.value
        )
        self._sync_ipod_view_mode(self._settings.get(IPOD_LIBRARY_VIEW_MODE))
        del blocker

    def _sync_ipod_view_mode(self, value: str) -> None:
        blocker = QSignalBlocker(self._ipod_view_mode_combo)
        self._ipod_view_mode_combo.setCurrentIndex(
            self._ipod_view_mode_combo.findData(value)
        )
        del blocker

    def _ipod_view_mode_selected(self, index: int) -> None:
        value = self._ipod_view_mode_combo.itemData(index)
        if isinstance(value, str):
            self._settings.set_global(IPOD_LIBRARY_VIEW_MODE, value)

    def _rebuild_double_click_options(self) -> None:
        blocker = QSignalBlocker(self._double_click_combo)
        self._double_click_combo.clear()
        for label, action in (
            (
                QCoreApplication.translate("CommonActions", "Add to Queue"),
                LibraryDoubleClickShortcut.ADD_TO_QUEUE,
            ),
            (self.tr("Play next"), LibraryDoubleClickShortcut.PLAY_NEXT),
            (self.tr("Play now"), LibraryDoubleClickShortcut.PLAY_NOW),
            (self.tr("Edit"), LibraryDoubleClickShortcut.EDIT),
        ):
            self._double_click_combo.addItem(label, action.value)
        self._sync_double_click(self._settings.get(LIBRARY_DOUBLE_CLICK_SHORTCUT))
        del blocker

    def _sync_double_click(self, value: str) -> None:
        blocker = QSignalBlocker(self._double_click_combo)
        self._double_click_combo.setCurrentIndex(
            self._double_click_combo.findData(value)
        )
        del blocker

    def _double_click_selected(self, index: int) -> None:
        value = self._double_click_combo.itemData(index)
        if isinstance(value, str):
            self._settings.set_global(LIBRARY_DOUBLE_CLICK_SHORTCUT, value)

    def _rebuild_volume_presentation_options(self) -> None:
        blocker = QSignalBlocker(self._volume_presentation_combo)
        self._volume_presentation_combo.clear()
        self._volume_presentation_combo.addItem(self.tr("Off"), False)
        self._volume_presentation_combo.addItem(self.tr("On"), True)
        self._sync_volume_presentation(self._settings.get(MANAGE_VOLUME_PRESENTATION))
        del blocker

    def _sync_volume_presentation(self, enabled: bool) -> None:
        blocker = QSignalBlocker(self._volume_presentation_combo)
        self._volume_presentation_combo.setCurrentIndex(
            self._volume_presentation_combo.findData(enabled)
        )
        del blocker

    def _volume_presentation_selected(self, index: int) -> None:
        value = self._volume_presentation_combo.itemData(index)
        if isinstance(value, bool):
            self._settings.set_global(MANAGE_VOLUME_PRESENTATION, value)

    def _sync_draft_all_changes(self, enabled: bool) -> None:
        blocker = QSignalBlocker(self._draft_all_changes_combo)
        self._draft_all_changes_combo.setCurrentIndex(
            self._draft_all_changes_combo.findData(enabled)
        )
        del blocker

    def _draft_all_changes_selected(self, index: int) -> None:
        value = self._draft_all_changes_combo.itemData(index)
        if isinstance(value, bool):
            self._settings.set_global(DRAFT_ALL_CHANGES, value)

    def _sync_mode_selection(self, mode_value: str) -> None:
        blocker = QSignalBlocker(self._mode_combo)
        index = self._mode_combo.findData(mode_value)
        self._mode_combo.setCurrentIndex(max(0, index))
        del blocker

    def _sync_light_theme_selection(self, theme_value: str) -> None:
        blocker = QSignalBlocker(self._light_theme_combo)
        index = self._light_theme_combo.findData(theme_value)
        self._light_theme_combo.setCurrentIndex(max(0, index))
        del blocker

    def _sync_dark_theme_selection(self, theme_value: str) -> None:
        blocker = QSignalBlocker(self._dark_theme_combo)
        index = self._dark_theme_combo.findData(theme_value)
        self._dark_theme_combo.setCurrentIndex(max(0, index))
        del blocker

    def _sync_colorful_mode_selection(self, enabled: bool) -> None:
        blocker = QSignalBlocker(self._colorful_mode_combo)
        index = self._colorful_mode_combo.findData(enabled)
        self._colorful_mode_combo.setCurrentIndex(max(0, index))
        del blocker

    def _mode_selected(self, index: int) -> None:
        value = self._mode_combo.itemData(index)
        if isinstance(value, str):
            self._theme_manager.set_mode(AppearanceMode(value))

    def _light_theme_selected(self, index: int) -> None:
        value = self._light_theme_combo.itemData(index)
        if isinstance(value, str):
            self._theme_manager.set_light_theme(LightTheme(value))

    def _dark_theme_selected(self, index: int) -> None:
        value = self._dark_theme_combo.itemData(index)
        if isinstance(value, str):
            self._theme_manager.set_dark_theme(DarkTheme(value))

    def _colorful_mode_selected(self, index: int) -> None:
        value = self._colorful_mode_combo.itemData(index)
        if isinstance(value, bool):
            self._theme_manager.set_colorful_mode(value)

    def _player_position_selected(self, index: int) -> None:
        value = self._player_position_combo.itemData(index)
        if isinstance(value, str):
            self._settings.set_global(PLAYER_POSITION, PlayerPosition(value).value)

    def _track_title_bar_selected(self, index: int) -> None:
        value = self._track_title_bar_combo.itemData(index)
        if isinstance(value, str):
            self._theme_manager.set_track_title_bar_style(TrackTitleBarStyle(value))

    def _sync_track_title_bar_selection(self, value: str) -> None:
        blocker = QSignalBlocker(self._track_title_bar_combo)
        self._track_title_bar_combo.setCurrentIndex(
            max(0, self._track_title_bar_combo.findData(value))
        )
        del blocker

    def _language_selected(self, index: int) -> None:
        value = self._language_combo.itemData(index)
        if isinstance(value, str):
            self._i18n_manager.set_language(value)

    def _choose_backup_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            self.tr("Choose Backup Location"),
            self._settings.get(BACKUP_LOCATION),
        )
        if selected:
            self._settings.set_global(BACKUP_LOCATION, str(Path(selected).resolve()))

    def _max_backups_selected(self, index: int) -> None:
        value = self._max_backups.itemData(index)
        if isinstance(value, int):
            self._settings.set_global(MAX_BACKUPS, value)

    def _inspect_udev_rule(self) -> None:
        if not self._linux_supported:
            return
        self._udev_rule_status = inspect_udev_rule()
        self._udev_status_row.set_copy(
            self.tr("iPod identity rule"),
            self._udev_status_description(),
        )
        self._uninstall_udev_rule.setEnabled(
            self._udev_rule_status.path == Path(UDEV_RULE_DESTINATION)
        )

    def _show_udev_uninstall(self) -> None:
        if not self._linux_supported:
            return
        LinuxIdentityUninstallDialog(self).exec()
        self._inspect_udev_rule()

    def _open_issue_tracker(self) -> None:
        QDesktopServices.openUrl(QUrl(_ISSUES_URL))

    def _show_log_folder(self) -> None:
        log_path = active_log_path()
        if log_path is None:
            return
        folder = log_path.parent
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            QMessageBox.warning(
                self,
                self.tr("Could Not Open Log Folder"),
                str(folder),
            )

    def _open_donation_page(self) -> None:
        QDesktopServices.openUrl(QUrl(_DONATION_URL))

    def _udev_status_description(self) -> str:
        status = self._udev_rule_status
        if status is None:
            return self.tr("Choose Check Again to inspect standard udev rule paths.")
        path = str(status.path) if status.path is not None else ""
        if status.kind is UdevRuleStatusKind.CURRENT:
            return self.tr("Installed and current at %1.").replace("%1", path)
        if status.kind is UdevRuleStatusKind.DIFFERENT:
            return self.tr(
                "A different or disabled copy takes priority at %1."
            ).replace("%1", path)
        if status.kind is UdevRuleStatusKind.UNREADABLE:
            return self.tr("A rule exists at %1, but it could not be read.").replace(
                "%1", path
            )
        return self.tr("Not installed in a standard udev rules directory.")

    def _language_changed(self, _language_tag: str) -> None:
        self.retranslate_ui()

    def _setting_changed(self, key: str, value: object) -> None:
        if key == IPOD_LIBRARY_VIEW_MODE.key and isinstance(value, str):
            self._sync_ipod_view_mode(value)
        elif key == LIBRARY_DOUBLE_CLICK_SHORTCUT.key and isinstance(value, str):
            self._sync_double_click(value)
        elif key == DRAFT_ALL_CHANGES.key and isinstance(value, bool):
            self._sync_draft_all_changes(value)
        elif key == MANAGE_VOLUME_PRESENTATION.key and isinstance(value, bool):
            self._sync_volume_presentation(value)
        elif key == PLAYER_POSITION.key and isinstance(value, str):
            self._sync_player_position_selection(value)
        elif key == BACKUP_LOCATION.key and isinstance(value, str):
            self._sync_backup_location(value)
        elif key == MAX_BACKUPS.key and isinstance(value, int):
            self._sync_max_backups(value)

    def _sync_player_position_selection(self, position_value: str) -> None:
        blocker = QSignalBlocker(self._player_position_combo)
        index = self._player_position_combo.findData(position_value)
        self._player_position_combo.setCurrentIndex(max(0, index))
        del blocker

    def _sync_backup_location(self, value: str) -> None:
        self._backup_location.setText(value)
        self._backup_location.setToolTip(value)

    def _sync_max_backups(self, value: int) -> None:
        blocker = QSignalBlocker(self._max_backups)
        index = self._max_backups.findData(value)
        if index < 0:
            self._max_backups.addItem(str(value), value)
            index = self._max_backups.findData(value)
        self._max_backups.setCurrentIndex(max(0, index))
        del blocker
