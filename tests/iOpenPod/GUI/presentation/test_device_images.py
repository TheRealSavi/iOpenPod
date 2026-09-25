"""DPR-aware rendering for packaged iPod product images."""

import shlex
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QToolButton,
)

from device_registry import DEFAULT_DEVICE_REGISTRY, IdentificationStatus
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceCandidateIssue,
    DeviceCandidateIssueCode,
    DeviceDiscovery,
    DeviceReadiness,
)
from iOpenPod.GUI.dialogs.device_picker import DevicePickerDialog
from iOpenPod.GUI.dialogs.linux_identity_setup import (
    LinuxIdentitySetupDialog,
    LinuxIdentityUninstallDialog,
)
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.presentation.device_images import device_icon
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iPodDB.library import LibrarySnapshot
from storage import FileFingerprint


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()
ASSET_ROOT = Path(__file__).parents[4] / "src" / "iOpenPod" / "assets" / "ipod_images"

_FULL_SIZE_IMAGE_BY_IDENTITY = {
    ("1st Gen", "White"): "iPod1.png",
    ("2nd Gen", "White"): "iPod1.png",
    ("3rd Gen", "White"): "iPod2.png",
    ("4th Gen (mono)", "White"): "iPod4-White.png",
    ("4th Gen (mono)", "U2"): "iPod4-BlackRed.png",
    ("4th Gen (photo)", "White"): "iPod5-White.png",
    ("4th Gen (color)", "White"): "iPod5-White.png",
    ("4th Gen (color)", "U2"): "iPod5-BlackRed.png",
    ("5th Gen", "White"): "iPod6-White.png",
    ("5th Gen", "Black"): "iPod6-Black.png",
    ("5th Gen", "U2"): "iPod6-BlackRed.png",
    ("5.5th Gen", "White"): "iPod6-White.png",
    ("5.5th Gen", "Black"): "iPod6-Black.png",
    ("5.5th Gen", "U2"): "iPod6-BlackRed.png",
}


def test_every_profile_image_is_packaged() -> None:
    missing = {
        profile.product_image
        for profile in DEFAULT_DEVICE_REGISTRY.profiles
        if not (ASSET_ROOT / profile.product_image).is_file()
    }

    assert missing == set()
    assert (ASSET_ROOT / "iPodGeneric.png").is_file()


def test_full_size_profiles_use_original_product_images() -> None:
    profiles = (
        profile
        for profile in DEFAULT_DEVICE_REGISTRY.profiles
        if profile.family == "iPod"
    )

    for profile in profiles:
        identity = (profile.generation, profile.finish)
        assert profile.product_image == _FULL_SIZE_IMAGE_BY_IDENTITY[identity]


def test_device_icon_contains_visible_high_dpi_pixels() -> None:
    icon = device_icon("iPod11-Silver.png", 44, 2.0)
    image = icon.pixmap(QSize(44, 44)).toImage()

    assert not icon.isNull()
    assert image.devicePixelRatio() >= 1.0
    assert any(
        image.pixelColor(x, y).alpha() > 0
        for x in range(image.width())
        for y in range(image.height())
    )


def test_profile_image_appears_in_device_picker_and_active_sidebar() -> None:
    profile = next(
        profile
        for profile in DEFAULT_DEVICE_REGISTRY.profiles
        if profile.model_number == "MB565"
    )
    candidate = DeviceCandidate(
        id=DeviceCandidateId("generation-1"),
        display_name="Test iPod",
        host_description="USB iPod",
        bus="usb",
        identification_status=IdentificationStatus.EXACT,
        readiness=DeviceReadiness.READY,
        profile=profile,
        total_bytes=80_000_000_000,
        available_bytes=40_000_000_000,
    )
    discovery = DeviceDiscovery(candidates=(candidate,))
    library = LibrarySnapshot()
    active = ActiveIPod(
        candidate=candidate,
        profile=profile,
        library=library,
        database_name="iTunesDB",
        database_fingerprint=FileFingerprint(
            size=profile.capabilities.database.max_database_bytes // 2,
            modified_ns=0,
            device=0,
            inode=0,
            sha256="0" * 64,
        ),
    )
    picker = DevicePickerDialog()
    sidebar = Sidebar()

    try:
        picker.set_discovery(discovery)
        candidates = picker.findChild(QListWidget, "deviceCandidateList")
        setup = picker.findChild(QPushButton, "linuxIdentitySetupButton")
        assert candidates is not None
        assert setup is not None and setup.isHidden()
        assert not candidates.item(0).icon().isNull()

        icon_label = sidebar.findChild(QLabel, "deviceIcon")
        assert icon_label is not None
        initial = icon_label.pixmap()
        assert not initial.isNull()
        initial_cache_key = initial.cacheKey()

        sidebar.set_active_ipod(active)
        eject = sidebar.findChild(QToolButton, "ejectActiveIPod")
        assert eject is not None and not eject.isEnabled()
        ejected: list[bool] = []
        sidebar.ejectRequested.connect(lambda: ejected.append(True))
        sidebar.set_eject_available(True)
        assert eject.isEnabled()
        eject.click()
        assert ejected == [True]
        sidebar.set_eject_available(False)
        assert not eject.isEnabled()
        product = icon_label.pixmap()
        assert not product.isNull()
        assert product.cacheKey() != initial_cache_key

        database = sidebar.findChild(QProgressBar, "deviceDatabase")
        database_value = sidebar.findChild(QLabel, "deviceDatabaseValue")
        assert database is not None
        assert database_value is not None
        assert database.value() == 50
        assert "used" in database_value.text()

        video_pages = (
            PageId.MOVIES,
            PageId.TV_SHOWS,
            PageId.MUSIC_VIDEOS,
            PageId.VIDEOS,
        )
        assert all(
            _page_button(sidebar, page).isVisibleTo(sidebar) for page in video_pages
        )

        mini_profile = next(
            item
            for item in DEFAULT_DEVICE_REGISTRY.profiles
            if item.model_number == "M9160"
        )
        mini_candidate = replace(candidate, profile=mini_profile)
        sidebar.set_active_ipod(
            replace(active, candidate=mini_candidate, profile=mini_profile)
        )
        assert all(_page_button(sidebar, page).isHidden() for page in video_pages)
        assert _page_button(sidebar, PageId.PHOTOS).isHidden()
        assert not _page_button(sidebar, PageId.PODCASTS).isHidden()
    finally:
        picker.close()
        sidebar.close()


def test_device_picker_translates_issue_codes_instead_of_showing_raw_details() -> None:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    assert profile is not None
    candidate = DeviceCandidate(
        id=DeviceCandidateId("generation-setup"),
        display_name="Test iPod",
        host_description="USB iPod",
        bus="usb",
        identification_status=IdentificationStatus.EXACT,
        readiness=DeviceReadiness.READY,
        profile=profile,
        total_bytes=80_000_000_000,
        available_bytes=40_000_000_000,
        issues=(
            DeviceCandidateIssue(
                DeviceCandidateIssueCode.HARDWARE_PROBE_SETUP_REQUIRED,
                "untranslated-internal-detail",
            ),
        ),
    )
    picker = DevicePickerDialog()

    try:
        picker.set_discovery(DeviceDiscovery(candidates=(candidate,)))
        detail = picker.findChild(QLabel, "deviceCandidateDetail")
        setup = picker.findChild(QPushButton, "linuxIdentitySetupButton")
        assert detail is not None
        assert setup is not None
        assert "61-iopenpod.rules" in detail.text()
        assert "untranslated-internal-detail" not in detail.text()
        assert not setup.isHidden()
    finally:
        picker.close()


def test_linux_identity_setup_is_reviewable_and_copies_one_command() -> None:
    dialog = LinuxIdentitySetupDialog()

    try:
        command = dialog.findChild(QPlainTextEdit, "linuxIdentitySetupCommand")
        copy = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Copy Setup Command"
        )
        assert command is not None
        assert command.isReadOnly()
        assert command.toPlainText().startswith("/bin/sh -c ")
        command_parts = shlex.split(command.toPlainText())
        assert command_parts[:2] == ["/bin/sh", "-c"]
        setup_script = command_parts[2]
        assert "/etc/udev/rules.d/61-iopenpod.rules" in setup_script
        assert "Safely eject the iPod completely" in setup_script
        assert "mount the iPod again" in setup_script
        assert "Refresh in iOpenPod's device picker" in setup_script

        APPLICATION.clipboard().clear()
        copy.click()

        assert APPLICATION.clipboard().text() == command.toPlainText()
        status = dialog.findChild(QLabel, "linuxIdentitySetupStatus")
        assert status is not None
        assert status.text().startswith("Copied.")
    finally:
        dialog.close()


def test_linux_identity_uninstall_is_bounded_reviewable_and_copyable() -> None:
    dialog = LinuxIdentityUninstallDialog()

    try:
        command = dialog.findChild(QPlainTextEdit, "linuxIdentitySetupCommand")
        copy = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Copy Uninstall Command"
        )
        assert command is not None
        assert command.isReadOnly()
        assert command.toPlainText().startswith("/bin/sh -c ")
        assert 'rm -f -- "$RULE_DEST"' in command.toPlainText()
        assert "/etc/udev/rules.d/61-iopenpod.rules" in command.toPlainText()

        APPLICATION.clipboard().clear()
        copy.click()

        assert APPLICATION.clipboard().text() == command.toPlainText()
    finally:
        dialog.close()


def _page_button(sidebar: Sidebar, page_id: PageId) -> QPushButton:
    return next(
        button
        for button in sidebar.findChildren(QPushButton)
        if button.property("pageId") == page_id.value
    )
