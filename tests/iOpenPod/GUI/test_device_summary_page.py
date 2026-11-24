"""Device summary identity, responsive layout, and conditional firmware actions."""

from collections.abc import Iterator
from dataclasses import replace
from itertools import pairwise
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QLocale, QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea, QWidget
from tests.iOpenPod.boot_report_helpers import report_xml

from device_registry import DEFAULT_DEVICE_REGISTRY, IdentificationStatus
from iOpenPod.app.core.settings.definitions import AppearanceMode
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.firmware.bootloader_report import read_bootloader_report
from iOpenPod.app.firmware.shared_bootloader import VERSION as BOOTLOADER_VERSION
from iOpenPod.app.firmware.shared_controller import SharedFirmwareController
from iOpenPod.app.firmware.shared_release import MOD_VERSION
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iOpenPod.GUI.pages.device_summary import DeviceSummaryPage
from iOpenPod.GUI.presentation.i18n.manager import I18nManager
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iPodDB.library import LibrarySnapshot, MediaType, Track, TrackMetadata
from storage import FileFingerprint


def _application() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication([])


APPLICATION = _application()


def summary_active_ipod() -> ActiveIPod:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MB565")
    assert profile is not None
    candidate = DeviceCandidate(
        DeviceCandidateId("summary-page"),
        "Test iPod",
        "USB iPod",
        "usb",
        IdentificationStatus.EXACT,
        DeviceReadiness.READY,
        profile,
        120_000_000_000,
        70_000_000_000,
    )
    tracks = tuple(
        Track(
            index,
            f"Track {index}",
            "Artist",
            "Album",
            1_000,
            size_bytes=size,
            media_types=(kind,),
            metadata=TrackMetadata(location=f"iPod_Control/Music/F00/{index}.m4a"),
        )
        for index, (kind, size) in enumerate(
            (
                (MediaType.AUDIO, 30_000_000_000),
                (MediaType.VIDEO, 10_000_000_000),
                (MediaType.PODCAST, 3_000_000_000),
                (MediaType.AUDIOBOOK, 2_000_000_000),
            ),
            start=1,
        )
    )
    return ActiveIPod(
        candidate,
        profile,
        LibrarySnapshot(device_name="John's iPod", tracks=tracks),
        "iTunesDB",
        FileFingerprint(1024, 0, 0, 0, "0" * 64),
        firmware_version="2.0.1",
        firmware_version_current=True,
        updater_family_current=True,
        updater_family_id=33,
        serial_number="8K123ABC9ZS",
        game_storage_bytes=1_000_000_000,
        album_artwork_storage_bytes=500_000_000,
    )


@pytest.fixture
def page() -> Iterator[DeviceSummaryPage]:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    theme.set_mode(AppearanceMode.LIGHT)
    installer = Mock(spec=SharedFirmwareController)
    installer.needs_attention = False
    installer.can_install.return_value = False
    installer.recorded_hardware_family.return_value = None
    widget = DeviceSummaryPage(theme=theme, shared_firmware_controller=installer)
    widget.resize(900, 800)
    widget.set_active_ipod(summary_active_ipod())
    widget.show()
    APPLICATION.processEvents()
    try:
        yield widget
    finally:
        widget.close()
        theme.close()


def _label(page: QWidget, name: str) -> QLabel:
    label = page.findChild(QLabel, name)
    assert label is not None
    return label


def test_summary_shows_bootloader_setup_before_firmware_install(
    page: DeviceSummaryPage,
) -> None:
    assert _label(page, "deviceSummaryName").text() == "John's iPod"
    assert _label(page, "deviceSummary_model").text() == "MB565"
    assert _label(page, "deviceSummary_model_name").text() == "iPod Classic 6.5th Gen"
    assert _label(page, "deviceSummary_firmware").text() == "2.0.1"
    assert _label(page, "deviceSummary_updater_family").text() == "33"
    assert _label(page, "deviceSummary_serial").text() == "8K123ABC9ZS"
    for key in ("mod_version", "hardware_family", "bootloader_version"):
        assert _label(page, f"deviceSummary_{key}").text() == "Unavailable"
    assert not _label(page, "deviceSummaryPortrait").pixmap().isNull()
    actions = page.findChild(QWidget, "deviceFirmwareActions")
    assert actions is not None
    buttons = actions.findChildren(QPushButton)
    assert {button.objectName() for button in buttons} == {
        "unlockBootloader",
        "installSharedFirmware",
    }
    assert {button.text() for button in buttons} == {
        "Install unlocked bootloader",
        "Install universal 2.0.5",
    }
    assert all(not button.isEnabled() for button in buttons)
    assert [button.objectName() for button in buttons if button.isVisible()] == [
        "unlockBootloader"
    ]
    assert not _label(page, "deviceFirmwareCurrent").isVisible()
    for name in (
        "restoreDevice",
        "updateDevice",
        "checkDeviceFirmware",
        "deviceFirmwareStatus",
        "deviceFirmwareDownload",
        "deviceFirmwareHint",
        "deviceBootloaderStatus",
    ):
        assert page.findChild(QWidget, name) is None
    assert page.findChild(QWidget, "firmwareModsPanel") is None
    assert _label(page, "deviceFirmwareTitle").text() == "Firmware"
    page.set_active_ipod(None)
    assert all(not button.isVisible() for button in buttons)
    page.set_active_ipod(summary_active_ipod())
    page.set_busy(True)
    page.set_busy(False)
    assert all(not button.isEnabled() for button in buttons)


def test_portrait_is_left_of_vertical_facts_with_aligned_colons(
    page: DeviceSummaryPage,
) -> None:
    portrait = _label(page, "deviceSummaryPortrait")
    labels = page.findChildren(QLabel, "deviceSummaryFieldLabel")
    assert len(labels) == 11
    right_edges = {label.mapTo(page, label.rect().topRight()).x() for label in labels}
    assert len(right_edges) == 1
    assert all(
        label.text().endswith(":") and label.alignment() & Qt.AlignmentFlag.AlignRight
        for label in labels
    )
    positions = [label.mapTo(page, QPoint(0, 0)) for label in labels]
    assert all(first.y() < second.y() for first, second in pairwise(positions))
    assert portrait.mapTo(page, portrait.rect().topRight()).x() < positions[0].x()


def test_unknown_firmware_and_serial_are_explicitly_unavailable(
    page: DeviceSummaryPage,
) -> None:
    page.set_active_ipod(
        replace(
            summary_active_ipod(),
            firmware_version="",
            updater_family_id=None,
            serial_number="",
        )
    )
    assert _label(page, "deviceSummary_firmware").text() == "Unavailable"
    assert _label(page, "deviceSummary_updater_family").text() == "Unavailable"
    assert _label(page, "deviceSummary_serial").text() == "Unavailable"


def test_draft_name_updates_without_reclassifying_unsaved_storage(
    page: DeviceSummaryPage,
) -> None:
    bar = page.findChild(QWidget, "deviceCapacityBar")
    assert bar is not None
    before = bar.accessibleDescription()
    page.set_device_name("Renamed")
    assert _label(page, "deviceSummaryName").text() == "Renamed"
    assert bar.accessibleDescription() == before
    assert "Music" in before and "Videos" in before and "Other" in before
    assert "Games" in before
    games = page.findChild(QWidget, "storageCategory_games")
    assert games is not None and games.isVisible()
    artwork = page.findChild(QWidget, "storageCategory_album_artwork")
    assert artwork is not None and artwork.isVisible()
    assert "Album artwork" in before
    assert "estimated" in _label(page, "deviceStorageNote").text()


def test_disconnect_clears_identity_capacity_and_category_legend(
    page: DeviceSummaryPage,
) -> None:
    page.set_active_ipod(None)
    APPLICATION.processEvents()
    assert _label(page, "deviceSummaryName").text() == "No Active iPod"
    assert _label(page, "deviceSummary_model").text() == "—"
    assert _label(page, "deviceSummary_updater_family").text() == "—"
    for key in ("mod_version", "hardware_family", "bootloader_version"):
        assert _label(page, f"deviceSummary_{key}").text() == "—"
    assert not _label(page, "deviceFirmwareCurrent").isVisible()
    assert _label(page, "deviceStorageCapacity").text() == "Capacity unavailable"
    assert all(
        not label.isVisible()
        for label in page.findChildren(QLabel, "deviceStorageLegend")
    )
    bar = page.findChild(QWidget, "deviceCapacityBar")
    assert bar is not None and bar.toolTip() == ""


def test_inconsistent_capacity_explains_unavailable_categories(
    page: DeviceSummaryPage,
) -> None:
    active = summary_active_ipod()
    page.set_active_ipod(
        replace(
            active, candidate=replace(active.candidate, available_bytes=119_000_000_000)
        )
    )
    bar = page.findChild(QWidget, "deviceCapacityBar")
    assert bar is not None
    assert "Music" not in bar.accessibleDescription()
    assert "Other" in bar.accessibleDescription()
    assert "exceed used storage" in _label(page, "deviceStorageNote").text()


@pytest.mark.parametrize("mod_version", [None, "0.8.2-dev", MOD_VERSION])
@pytest.mark.parametrize("width", [320, 375, 414, 768, 1200])
def test_summary_reflows_without_horizontal_overflow(
    page: DeviceSummaryPage, width: int, mod_version: str | None
) -> None:
    if mod_version is not None:
        page.set_active_ipod(_reported_ipod(mod_version))
    page.resize(width, 900)
    for _ in range(3):
        APPLICATION.processEvents()
    scroll = page.findChild(QScrollArea, "deviceSummaryScroll")
    assert scroll is not None
    assert page.width() == width
    canvas = scroll.widget()
    assert canvas is not None
    assert canvas.width() <= scroll.viewport().width()
    assert scroll.horizontalScrollBar().maximum() == 0
    title = _label(page, "deviceFirmwareTitle")
    for name in ("unlockBootloader", "installSharedFirmware"):
        button = page.findChild(QPushButton, name)
        assert button is not None
        if button.isVisible():
            assert button.width() >= button.sizeHint().width()
            assert button.height() >= LAYOUT.control_height_large
            position = button.mapTo(page, QPoint(0, 0))
            if width >= 640:
                assert position.x() > title.mapTo(page, title.rect().topRight()).x()
            else:
                assert position.y() > title.mapTo(page, title.rect().bottomLeft()).y()


@pytest.mark.parametrize("width", [320, 375, 414, 768])
def test_name_uses_available_width_before_wrapping(
    page: DeviceSummaryPage, width: int
) -> None:
    page.resize(width, 900)
    for _ in range(3):
        APPLICATION.processEvents()
    name = _label(page, "deviceSummaryName")
    row = name.parentWidget()
    rename = page.findChild(QWidget, "deviceSummaryRename")
    assert row is not None and rename is not None
    available = max(0, row.width() - rename.width() - 2 * LAYOUT.space_2xs)
    assert name.width() >= min(
        available, name.fontMetrics().horizontalAdvance(name.text())
    )


@pytest.mark.parametrize("language", ["de", "es"])
@pytest.mark.parametrize("width", [320, 768])
@pytest.mark.parametrize("mod_version", [None, "0.8.2-dev", MOD_VERSION])
def test_translated_storage_heading_and_legend_fit_after_switch(
    page: DeviceSummaryPage, language: str, width: int, mod_version: str | None
) -> None:
    original_locale = QLocale()
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    manager = I18nManager(APPLICATION, settings)
    try:
        if mod_version is not None:
            page.set_active_ipod(_reported_ipod(mod_version))
        page.resize(width, 900)
        manager.set_language(language)
        for _ in range(3):
            APPLICATION.processEvents()
        scroll = page.findChild(QScrollArea, "deviceSummaryScroll")
        assert scroll is not None
        canvas = scroll.widget()
        assert canvas is not None and canvas.width() <= scroll.viewport().width()
        for name in ("unlockBootloader", "installSharedFirmware"):
            button = page.findChild(QPushButton, name)
            assert button is not None
            if button.isVisible():
                assert button.width() >= button.sizeHint().width()
        title = _label(page, "sectionTitle")
        assert title.width() >= title.fontMetrics().horizontalAdvance(title.text())
        legends = [
            label
            for label in page.findChildren(QLabel, "deviceStorageLegend")
            if label.isVisible()
        ]
        assert len(legends) == 8
        assert any(
            ("Spiele" if language == "de" else "Juegos") in label.text()
            for label in legends
        )
        assert any(
            ("Albumcover" if language == "de" else "Portada del álbum") in label.text()
            for label in legends
        )
        for label in legends:
            text_bounds = label.fontMetrics().boundingRect(
                QRect(0, 0, label.width(), 10_000),
                Qt.TextFlag.TextWordWrap,
                label.text(),
            )
            assert label.height() >= text_bounds.height()
    finally:
        manager.close()
        QLocale.setDefault(original_locale)


def test_cached_firmware_is_visibly_distinct_from_current_report(
    page: DeviceSummaryPage,
) -> None:
    page.set_active_ipod(
        replace(
            summary_active_ipod(),
            firmware_version_current=False,
            updater_family_current=False,
        )
    )
    assert _label(page, "deviceSummary_firmware").text() == "2.0.1 (cached)"
    assert _label(page, "deviceSummary_updater_family").text() == "33 (cached)"
    assert _label(page, "deviceSummary_bootloader_version").text() == "Unavailable"


@pytest.mark.parametrize("width", [320, 768])
def test_summary_displays_current_loader_and_clears_it_with_connection(
    page: DeviceSummaryPage,
    width: int,
) -> None:
    active = summary_active_ipod()
    active = replace(
        active,
        bootloader_report=read_bootloader_report(
            report_xml(DeviceSerial=active.serial_number),
            serial=active.serial_number,
            model=active.profile.model_number,
        ),
    )
    page.set_active_ipod(active)
    page.resize(width, 900)
    APPLICATION.processEvents()
    label = _label(page, "deviceSummary_bootloader_version")
    assert label.text() == BOOTLOADER_VERSION
    assert label.toolTip() == "Reported by firmware"
    assert _label(page, "deviceSummary_hardware_family").text() == "33"
    assert active.bootloader_report is not None
    assert (
        _label(page, "deviceSummary_mod_version").text()
        == active.bootloader_report.mod_version
    )
    scroll = page.findChild(QScrollArea, "deviceSummaryScroll")
    assert scroll is not None and scroll.horizontalScrollBar().maximum() == 0
    page.set_active_ipod(replace(active, bootloader_report=None))
    assert label.text() == "Unavailable"
    assert label.toolTip() == ""


def _reported_ipod(mod_version: str = MOD_VERSION) -> ActiveIPod:
    active = summary_active_ipod()
    return replace(
        active,
        firmware_version="2.0.5",
        updater_family_id=38,
        bootloader_report=read_bootloader_report(
            report_xml(DeviceSerial=active.serial_number, ModVersion=mod_version),
            serial=active.serial_number,
            model=active.profile.model_number,
        ),
    )


@pytest.mark.parametrize("mod_version", ["0.8.2-dev", MOD_VERSION])
@pytest.mark.parametrize("bootloader_version", ["2.0.0", BOOTLOADER_VERSION])
@pytest.mark.parametrize("qualified_body", [True, False])
def test_summary_offers_only_needed_updates(
    page: DeviceSummaryPage,
    mod_version: str,
    bootloader_version: str,
    qualified_body: bool,
) -> None:
    active = _reported_ipod(mod_version)
    report = active.bootloader_report
    assert report is not None and report.marker is not None
    active = replace(
        active,
        bootloader_report=replace(
            report,
            marker=replace(report.marker, version=bootloader_version),
            body_sha256=report.body_sha256 if qualified_body else "0" * 64,
        ),
    )
    page.set_active_ipod(active)
    unlock = page.findChild(QPushButton, "unlockBootloader")
    install = page.findChild(QPushButton, "installSharedFirmware")
    assert unlock is not None and install is not None
    loader_current = bootloader_version == BOOTLOADER_VERSION and qualified_body
    firmware_current = mod_version == MOD_VERSION
    assert unlock.isVisible() is (not loader_current)
    assert install.isVisible() is (loader_current and not firmware_current)
    assert unlock.text() == f"Update bootloader to {BOOTLOADER_VERSION}"
    assert install.text() == f"Update firmware to {MOD_VERSION}"
    assert _label(page, "deviceBootloaderHint").isVisible() is unlock.isVisible()
    assert _label(page, "deviceSharedFirmwareHint").isVisible() is install.isVisible()
    current = _label(page, "deviceFirmwareCurrent")
    assert current.isVisible() is (loader_current and firmware_current)
    assert current.text() == "Bootloader and firmware are up to date."
    assert _label(page, "deviceSummary_mod_version").text() == mod_version
    assert _label(page, "deviceSummary_bootloader_version").text() == bootloader_version
    assert _label(page, "deviceSummary_hardware_family").text() == "33"
    assert _label(page, "deviceSummary_updater_family").text() == "38"
    page.set_active_ipod(summary_active_ipod())
    assert unlock.isVisible() and not install.isVisible() and not current.isVisible()
