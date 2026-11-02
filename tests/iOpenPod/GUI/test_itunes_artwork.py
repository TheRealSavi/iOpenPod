"""The artwork preference is shared by every device image surface."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel, QListWidget, QWidget
from tests.iOpenPod.app.services.test_first_artwork_save import bare_device
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.backups.models import (
    BackupCatalog,
    BackupDeviceInfo,
    BackupDeviceMetadata,
    BackupInventory,
)
from iOpenPod.app.core.device_artwork import device_artwork_path
from iOpenPod.app.core.settings.definitions import ITUNES_107_ARTWORK
from iOpenPod.GUI.dialogs.device_picker import DevicePickerDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.pages.settings_page import SettingsPage
from iOpenPod.GUI.presentation.device_images import device_icon, device_pixmap
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iOpenPod.GUI.widgets.sync_storage_bar import SyncStorageBar


@pytest.mark.parametrize(
    ("name", "enabled", "expected"),
    (
        ("iPod3-Blue.png", False, "iPod3-Blue.png"),
        ("iPod3-Blue.png", True, "107/iPod3-Blue.png"),
        ("iPod18A-Blue.png", True, "iPod18A-Blue.png"),
        ("iPod128.png", True, "107/iPod128.png"),
        ("missing.png", False, "iPodGeneric.png"),
        ("missing.png", True, "107/iPodGeneric.png"),
        ("../iPod3-Blue.png", True, "107/iPodGeneric.png"),
        ("107\\iPod3-Blue.png", True, "107/iPodGeneric.png"),
    ),
)
def test_model_fallback_precedes_generic_artwork(
    name: str, enabled: bool, expected: str
) -> None:
    root = device_artwork_path("iPodGeneric.png").parent
    assert device_artwork_path(name, itunes_107=enabled) == root / expected


def test_switch_refreshes_all_visible_device_artwork(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = bare_device(tmp_path)
    context = build_context(device_coordinator=device.coordinator)
    window = MainWindow(context, auto_discover=False)
    sync = SyncStorageBar(context.theme_manager, window)
    try:
        backup_device = BackupDeviceInfo(
            "test-ipod",
            "Test iPod",
            snapshot_count=0,
            metadata=BackupDeviceMetadata(
                product_image=device.active.profile.product_image
            ),
        )
        catalog = BackupCatalog(backup_device, (), stored_size=0)

        def load_catalog(device_id: str) -> None:
            assert device_id == backup_device.device_id
            context.backup_controller.catalogChanged.emit(catalog)

        monkeypatch.setattr(context.backup_controller, "load_catalog", load_catalog)
        context.backup_controller.inventoryChanged.emit(
            BackupInventory((backup_device,))
        )
        APPLICATION.processEvents()
        page = window.findChild(SettingsPage)
        sidebar = window.findChild(Sidebar)
        picker = window.findChild(DevicePickerDialog)
        assert page is not None and sidebar is not None and picker is not None
        combo = page.findChild(AppComboBox, "itunes107ArtworkCombo")
        assert combo is not None and combo.currentData() is False
        assert context.settings.get(ITUNES_107_ARTWORK) is False
        sidebar.set_active_ipod(device.active)
        picker.set_discovery(context.device_coordinator.discovery)
        sync.set_device(device.active)
        backup_browser = window.findChild(QWidget, "backupBrowserPage")
        assert backup_browser is not None
        backup_art = backup_browser.findChild(QLabel, "backupDeviceArt")
        assert backup_art is not None
        sidebar_art = sidebar.findChild(QLabel, "deviceIcon")
        assert sidebar_art is not None
        sync_art = next(
            label for label in sync.findChildren(QLabel) if not label.pixmap().isNull()
        )
        labels = [sidebar_art, sync_art, backup_art]
        originals = [label.pixmap().toImage() for label in labels]
        candidates = picker.findChild(QListWidget, "deviceCandidateList")
        assert candidates is not None
        selected = candidates.currentRow()
        image_name = device.active.profile.product_image

        combo.setCurrentIndex(combo.findData(True))
        APPLICATION.processEvents()
        assert context.settings.get(ITUNES_107_ARTWORK) is True
        for label, original in zip(labels, originals, strict=True):
            assert label.pixmap().toImage() != original
            assert (
                label.pixmap().toImage()
                == device_pixmap(
                    image_name,
                    label.width(),
                    label.devicePixelRatioF(),
                    itunes_107=True,
                ).toImage()
            )
        item = candidates.currentItem()
        assert candidates.currentRow() == selected
        size = candidates.iconSize()
        assert (
            item.icon().pixmap(size).toImage()
            == device_icon(
                image_name, size.width(), picker.devicePixelRatioF(), itunes_107=True
            )
            .pixmap(size)
            .toImage()
        )

        # An external settings update also updates the control and existing widgets.
        context.settings.set_global(ITUNES_107_ARTWORK, False)
        assert combo.currentData() is False
        for label, original in zip(labels, originals, strict=True):
            assert label.pixmap().toImage() == original
    finally:
        window.close()
        context.shutdown()


def test_cached_pixmaps_keep_styles_separate_and_use_standard_fallback() -> None:
    name = "iPod3-Blue.png"
    standard = device_pixmap(name, 64, 2.0).toImage()
    angled = device_pixmap(name, 64, 2.0, itunes_107=True).toImage()
    assert standard != angled
    assert device_pixmap(name, 64, 2.0).toImage() == standard
    assert (
        device_pixmap("iPod18A-Blue.png", 64, itunes_107=True).toImage()
        == device_pixmap("iPod18A-Blue.png", 64).toImage()
    )
