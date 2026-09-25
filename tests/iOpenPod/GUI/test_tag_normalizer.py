"""Friendly normalization review and the automatically refreshed Sidebar badge."""

from collections.abc import Callable
from threading import Event
from time import monotonic, sleep

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from device_registry import DEFAULT_DEVICE_REGISTRY, IdentificationStatus
from iOpenPod.app import tag_normalization_controller as workers
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iOpenPod.app.tag_normalization_controller import TagNormalizationController
from iOpenPod.app.tag_normalizer import TagProfile, TagSuggestion, normalize_tags
from iOpenPod.GUI.dialogs.tag_normalizer import TagNormalizerDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iPodDB.library import LibrarySnapshot, Track
from storage import FileFingerprint


def _wait(predicate: Callable[[], bool]) -> None:
    deadline = monotonic() + 5
    while not predicate() and monotonic() < deadline:
        APPLICATION.processEvents()
        sleep(0.005)
    assert predicate()


def test_preview_explains_empty_values_filters_and_the_full_apply_scope() -> None:
    context = build_context()
    workspace = context.library_workspace
    workspace.load(LibrarySnapshot((Track(1, " Song ", "The Artist", "Album", 100),)))
    controller = TagNormalizationController(workspace)
    dialog = TagNormalizerDialog(controller)
    try:
        dialog.start(TagProfile())
        _wait(lambda: not controller.scanning)
        assert dialog.model.rowCount() == 3
        values = [dialog.model.index(i, 2).data() for i in range(3)]
        assert "Not set" in values and "“ Song ”" in values
        search = dialog.findChild(QLineEdit)
        apply = dialog.findChild(QPushButton, "applyNormalization")
        assert search is not None and apply is not None
        search.setText("unmatched search")
        assert dialog.model.rowCount() == 0
        assert any(
            label.text() == "No matching changes" and label.isVisible()
            for label in dialog.findChildren(QLabel)
        )
        assert apply.isEnabled() and "all 3 changes" in apply.text()
        # Enter in a search field must not implicitly apply the complete batch.
        search.setFocus()
        QTest.keyClick(search, Qt.Key.Key_Return)
        assert not workspace.dirty
        clear = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Clear filters"
        )
        clear.click()
        assert dialog.model.rowCount() == 3 and search.text() == ""
        apply.click()
        assert workspace.tracks[0].title == "Song" and workspace.dirty
        assert not apply.isEnabled()
        dialog.start(TagProfile())
        _wait(lambda: not controller.scanning)
        assert any(
            label.text() == "All tidy" and label.isVisible()
            for label in dialog.findChildren(QLabel)
        )
    finally:
        dialog.close()
        controller.shutdown()
        context.shutdown()


def test_shell_checks_tags_without_opening_the_dialog_and_clears_on_disconnect() -> (
    None
):
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    profile = next(
        p for p in DEFAULT_DEVICE_REGISTRY.profiles if p.model_number == "MB565"
    )
    active = ActiveIPod(
        candidate=DeviceCandidate(
            id=DeviceCandidateId("normalization-test"),
            display_name="Test iPod",
            host_description="USB iPod",
            bus="usb",
            identification_status=IdentificationStatus.EXACT,
            readiness=DeviceReadiness.READY,
            profile=profile,
            total_bytes=80_000_000_000,
            available_bytes=40_000_000_000,
        ),
        profile=profile,
        library=LibrarySnapshot((Track(1, " Song ", "The Artist", "Album", 100),)),
        database_name="iTunesDB",
        database_fingerprint=FileFingerprint(
            size=100, modified_ns=0, device=0, inode=0, sha256="0" * 64
        ),
    )
    try:
        context.device_controller.activeIPodChanged.emit(active)
        controller = window.findChild(TagNormalizationController)
        dialog = window.findChild(TagNormalizerDialog)
        badge = window.findChild(QLabel, "normalizationBadge")
        button = window.findChild(QPushButton, "normalizationNavigation")
        assert (
            controller is not None
            and dialog is not None
            and badge is not None
            and button is not None
        )
        _wait(lambda: controller.suggestion is not None)
        assert not dialog.isVisible() and not badge.isHidden()
        assert int(badge.text()) == controller.pending_count > 0
        assert f"{controller.pending_count} tag changes" in button.toolTip()
        assert not context.library_workspace.dirty
        suggestion = controller.suggestion
        assert suggestion is not None
        dialog.start(suggestion.profile)
        assert controller.suggestion is suggestion
        dialog.close()
        assert controller.suggestion is suggestion and not badge.isHidden()
        controller.apply()
        assert badge.isHidden()
        _wait(lambda: controller.suggestion is not None)
        assert badge.isHidden()
        context.device_controller.activeIPodChanged.emit(None)
        assert badge.isHidden() and not button.isEnabled()
        assert not controller.monitoring and controller.pending_count == 0
    finally:
        window.close()
        context.shutdown()


def test_large_badge_keeps_the_exact_count_accessible_and_does_not_intercept_clicks() -> (
    None
):
    sidebar = Sidebar()
    try:
        sidebar.set_normalization_count(12_345)
        badge = sidebar.findChild(QLabel, "normalizationBadge")
        button = sidebar.findChild(QPushButton, "normalizationNavigation")
        assert badge is not None and button is not None
        assert badge.text() == "99+"
        assert "12,345" in button.toolTip() and "12,345" in button.accessibleName()
        assert badge.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        sidebar.set_normalization_count(0)
        assert badge.isHidden() and "12,345" not in button.accessibleName()
    finally:
        sidebar.close()


@pytest.mark.parametrize("fails", [False, True])
def test_closing_a_busy_preview_preserves_the_shared_scan_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch, fails: bool
) -> None:
    context = build_context()
    workspace = context.library_workspace
    workspace.load(LibrarySnapshot((Track(1, " Song ", "The Artist", "Album", 100),)))
    entered, release = Event(), Event()

    def delayed(
        tracks: tuple[Track, ...],
        profile: TagProfile,
        *,
        checkpoint: Callable[[], None],
    ) -> TagSuggestion:
        entered.set()
        assert release.wait(5)
        if fails:
            raise ValueError("Simulated scan failure")
        return normalize_tags(tracks, profile)

    monkeypatch.setattr(workers, "normalize_tags", delayed)
    controller = TagNormalizationController(workspace)
    dialog = TagNormalizerDialog(controller)
    try:
        controller.monitor(TagProfile())
        dialog.start(TagProfile())
        _wait(entered.is_set)
        apply = dialog.findChild(QPushButton, "applyNormalization")
        assert apply is not None and not apply.isEnabled()
        assert any(
            label.text() == "Finding the finishing touches" and label.isVisible()
            for label in dialog.findChildren(QLabel)
        )
        dialog.close()
        assert controller.scanning
        release.set()
        _wait(lambda: not controller.scanning)
        assert not workspace.dirty
        assert controller.failed is fails
        if fails:
            assert controller.pending_count == 0 and controller.suggestion is None
            dialog.show()
            assert any(
                label.text() == "We couldn't check your tags" and label.isVisible()
                for label in dialog.findChildren(QLabel)
            )
        else:
            assert controller.pending_count == 3
    finally:
        release.set()
        dialog.close()
        controller.shutdown()
        context.shutdown()
