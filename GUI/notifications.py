"""
System notifications for iOpenPod.

Uses QSystemTrayIcon for cross-platform desktop notifications.
Falls back gracefully if tray icon is not supported.
"""

import logging
from typing import Optional

from PyQt6.QtWidgets import QSystemTrayIcon, QApplication
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QObject

logger = logging.getLogger(__name__)


class Notifier(QObject):
    """
    Desktop notification manager using Qt's system tray.

    Usage:
        notifier = Notifier.get_instance()
        notifier.notify("Sync Complete", "25 tracks added to iPod")
    """

    _instance: Optional["Notifier"] = None

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._tray: Optional[QSystemTrayIcon] = None
        self._available = False
        self._setup()

    def _setup(self):
        """Initialize system tray icon if supported."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.info("System tray not available - notifications disabled")
            return

        app = QApplication.instance()
        icon = app.windowIcon() if isinstance(app, QApplication) else QIcon()

        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("iOpenPod")
        self._tray.show()
        self._available = True

    @classmethod
    def get_instance(cls, parent: Optional[QObject] = None) -> "Notifier":
        if cls._instance is None:
            cls._instance = Notifier(parent)
        return cls._instance

    @classmethod
    def shutdown(cls):
        """Clean up tray icon on app exit."""
        if cls._instance and cls._instance._tray:
            cls._instance._tray.hide()
            cls._instance._tray = None
        cls._instance = None

    @property
    def available(self) -> bool:
        return self._available

    def notify(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
        duration_ms: int = 5000,
    ):
        """
        Show a desktop notification.

        Args:
            title: Notification title
            message: Notification body text
            icon: Icon type (Information, Warning, Critical)
            duration_ms: How long to show (platform-dependent)
        """
        if not self._available or not self._tray:
            logger.debug("Notification skipped (tray unavailable): %s", title)
            return

        try:
            self._tray.showMessage(title, message, icon, duration_ms)
        except Exception:
            logger.debug("Failed to show notification", exc_info=True)

    def notify_sync_complete(self, added: int, removed: int, updated: int, errors: int):
        """Convenience: notify about sync completion."""
        parts = []
        if added:
            parts.append(f"{added} added")
        if removed:
            parts.append(f"{removed} removed")
        if updated:
            parts.append(f"{updated} updated")

        summary = ", ".join(parts) if parts else "No changes"

        if errors:
            self.notify(
                "Sync Completed with Errors",
                f"{summary}\n{errors} error(s) occurred",
                QSystemTrayIcon.MessageIcon.Warning,
            )
        else:
            self.notify("Sync Complete", summary)

    def notify_sync_error(self, error_msg: str):
        """Convenience: notify about sync failure."""
        # Truncate long error messages for notification
        short = error_msg[:150] + "..." if len(error_msg) > 150 else error_msg
        self.notify(
            "Sync Failed",
            short,
            QSystemTrayIcon.MessageIcon.Critical,
        )
