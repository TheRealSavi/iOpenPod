"""Login forms preserve retries, mask pasted secrets and clear on completion."""

from typing import cast

from PySide6.QtWidgets import QCheckBox, QLabel, QLineEdit, QPushButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.GUI.test_podcast_page import PodcastControllerStub

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.podcasts.controller import (
    PodcastController,
    PodcastOperation,
    PodcastOperationFailure,
)
from iOpenPod.app.podcasts.models import PodcastSnapshot
from iOpenPod.GUI.dialogs.podcast_search import PodcastSearchDialog
from iOpenPod.GUI.presentation.theme.manager import ThemeManager


def test_pasted_credentials_are_masked_and_failed_subscription_can_retry() -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    controller = PodcastControllerStub(PodcastSnapshot(writable=True))
    dialog = PodcastSearchDialog(cast("PodcastController", controller), theme)
    try:
        dialog.show()
        toggle = dialog.findChild(QPushButton, "podcastToggleRss")
        url = dialog.findChild(QLineEdit, "podcastRssUrl")
        username = dialog.findChild(QLineEdit, "podcastUsername")
        password = dialog.findChild(QLineEdit, "podcastPassword")
        login = dialog.findChild(QCheckBox, "podcastRequiresLogin")
        add = dialog.findChild(QPushButton, "podcastAddRss")
        status = dialog.findChild(QLabel, "podcastSearchStatus")
        assert toggle and url and username and password and login and add and status
        toggle.click()
        url.setText("https://tony:p%40ss@publisher.test/feed")
        url.textEdited.emit(url.text())
        APPLICATION.processEvents()
        assert url.text() == "https://publisher.test/feed"
        assert username.text() == "tony"
        assert password.text() == "p@ss"
        assert password.echoMode() is QLineEdit.EchoMode.Password
        assert "p@ss" not in password.displayText()
        assert login.isChecked() and password.isVisible()
        assert password.geometry().top() > username.geometry().bottom()
        remember = dialog.findChild(QCheckBox, "podcastRememberLogin")
        assert remember is not None
        assert remember.geometry().top() > password.geometry().bottom()
        add.click()
        assert dialog.isVisible()
        controller.operationFailed.emit(
            PodcastOperationFailure(PodcastOperation.SUBSCRIBE, "Login rejected")
        )
        assert dialog.isVisible() and status.text() == "Login rejected"
        assert password.text() == "p@ss"
        password.setText("corrected")
        add.click()
        controller.operationSucceeded.emit(PodcastOperation.SUBSCRIBE)
        assert not dialog.isVisible()
        assert not username.text() and not password.text() and not url.text()
        assert controller.subscribe_calls == ["https://publisher.test/feed"] * 2
    finally:
        dialog.close()
        theme.close()
