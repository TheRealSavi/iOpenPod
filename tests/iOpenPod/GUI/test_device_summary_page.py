"""Device summary state, responsive layout, and non-operational Restore control."""

from collections.abc import Iterator
from dataclasses import replace
from itertools import pairwise

import pytest
from PySide6.QtCore import QLocale, QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea, QWidget

from device_registry import DEFAULT_DEVICE_REGISTRY, IdentificationStatus
from iOpenPod.app.core.settings.definitions import AppearanceMode
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iOpenPod.GUI.pages.device_summary import DeviceSummaryPage
from iOpenPod.GUI.presentation.i18n.manager import I18nManager
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
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
        serial_number="8K123ABC9ZS",
        game_storage_bytes=1_000_000_000,
        album_artwork_storage_bytes=500_000_000,
    )


@pytest.fixture
def page() -> Iterator[DeviceSummaryPage]:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    theme.set_mode(AppearanceMode.LIGHT)
    widget = DeviceSummaryPage(theme=theme)
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


def test_summary_shows_device_values_and_restore_is_always_disabled(
    page: DeviceSummaryPage,
) -> None:
    assert _label(page, "deviceSummaryName").text() == "John's iPod"
    assert _label(page, "deviceSummary_model").text() == "MB565"
    assert _label(page, "deviceSummary_model_name").text() == "iPod Classic 6.5th Gen"
    assert _label(page, "deviceSummary_firmware").text() == "2.0.1"
    assert _label(page, "deviceSummary_serial").text() == "8K123ABC9ZS"
    assert not _label(page, "deviceSummaryPortrait").pixmap().isNull()
    restore = page.findChild(QPushButton, "restoreDevice")
    assert restore is not None and not restore.isEnabled()
    assert _label(page, "deviceRestoreComingSoon").text() == "Coming soon"
    page.set_active_ipod(None)
    page.set_active_ipod(summary_active_ipod())
    assert not restore.isEnabled()


def test_portrait_is_left_of_vertical_facts_with_aligned_colons(
    page: DeviceSummaryPage,
) -> None:
    portrait = _label(page, "deviceSummaryPortrait")
    labels = page.findChildren(QLabel, "deviceSummaryFieldLabel")
    assert len(labels) == 7
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
        replace(summary_active_ipod(), firmware_version="", serial_number="")
    )
    assert _label(page, "deviceSummary_firmware").text() == "Unavailable"
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


@pytest.mark.parametrize("width", [320, 375, 414, 768, 1200])
def test_summary_reflows_without_horizontal_overflow(
    page: DeviceSummaryPage, width: int
) -> None:
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
    restore = page.findChild(QPushButton, "restoreDevice")
    assert restore is not None and restore.width() >= restore.sizeHint().width()
    assert _label(page, "deviceRestoreComingSoon").width() > 0


@pytest.mark.parametrize("language", ["de", "es"])
@pytest.mark.parametrize("width", [320, 768])
def test_translated_storage_heading_and_legend_fit_after_switch(
    page: DeviceSummaryPage, language: str, width: int
) -> None:
    original_locale = QLocale()
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    manager = I18nManager(APPLICATION, settings)
    try:
        page.resize(width, 900)
        manager.set_language(language)
        for _ in range(3):
            APPLICATION.processEvents()
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
