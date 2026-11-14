"""Metadata pickers edit civil fields without losing timestamp or batch semantics."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QDate, QLocale, Qt, QTime
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from whenever import SYSTEM_TZ, Instant

from iOpenPod.app.core.dates import HostDateZone, parse_iso_instant
from iOpenPod.app.metadata_fields import FieldKind, MetadataField
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_date_edit import AppDateEdit
from iOpenPod.GUI.widgets.metadata_date_edit import MetadataDateEdit
from iOpenPod.GUI.widgets.metadata_field_editor import FieldEditor


@pytest.fixture
def host() -> Iterator[QWidget]:
    widget = QWidget()
    QVBoxLayout(widget)
    widget.resize(520, 120)
    widget.show()
    yield widget
    widget.close()


def _row(host: QWidget, value: int, *, mixed: bool = False) -> FieldEditor:
    row = FieldEditor(
        MetadataField("metadata.date_added", "Date added", "Dates", FieldKind.DATE),
        value,
        mixed,
        host,
    )
    layout = host.layout()
    assert layout is not None
    layout.addWidget(row)
    APPLICATION.processEvents()
    return row


def _button(edit: MetadataDateEdit, name: str) -> QPushButton | QToolButton:
    button = edit.findChild(QPushButton, name) or edit.findChild(QToolButton, name)
    assert button is not None
    return button


def test_date_and_time_are_independently_editable_and_reset_together(
    host: QWidget,
) -> None:
    original = 1_700_001_234
    row = _row(host, original)
    edit = row.editor
    assert isinstance(edit, MetadataDateEdit)
    assert isinstance(edit.date, AppDateEdit)
    local = Instant.from_timestamp(original).to_tz(SYSTEM_TZ)
    assert edit.date.date() == QDate(local.year, local.month, local.day)
    assert edit.time.time() == QTime(local.hour, local.minute, local.second)
    assert edit.value() == original and not row.is_modified()

    edit.date.setDate(QDate(2026, 12, 13))
    assert edit.time.time() == QTime(local.hour, local.minute, local.second)
    edit.time.setTime(QTime(8, 15, 42))
    assert row.is_modified()
    assert (
        row.value()
        == parse_iso_instant(
            "2026-12-13T08:15:42", naive_zone=HostDateZone.SYSTEM
        ).timestamp()
    )
    row.reset()
    assert not row.is_modified() and row.value() == original
    assert edit.date.date() == QDate(local.year, local.month, local.day)
    assert edit.time.time() == QTime(local.hour, local.minute, local.second)


@pytest.mark.parametrize("value,mixed", [(0, False), (1_700_001_234, True)])
def test_unset_and_mixed_dates_require_an_explicit_edit(
    host: QWidget, value: int, mixed: bool
) -> None:
    row = _row(host, value, mixed=mixed)
    edit = row.editor
    assert isinstance(edit, MetadataDateEdit)
    assert not row.is_modified() and not edit.date.isVisible()
    status = edit.findChild(QLabel, "metadataDateStatus")
    assert status is not None
    assert status.text() == ("Mixed values — unchanged" if mixed else "Not set")
    QTest.mouseClick(_button(edit, "metadataDateSet"), Qt.MouseButton.LeftButton)
    assert row.is_modified() and edit.date.isVisible() and edit.time.isVisible()
    assert edit.time.time() == QTime(0, 0)
    edit.date.setDate(QDate(2025, 6, 19))
    edit.time.setTime(QTime(14, 25, 36))
    assert (
        row.value()
        == parse_iso_instant(
            "2025-06-19T14:25:36", naive_zone=HostDateZone.SYSTEM
        ).timestamp()
    )
    row.reset()
    assert not row.is_modified() and not edit.date.isVisible()
    assert status.text() == ("Mixed values — unchanged" if mixed else "Not set")


@pytest.mark.parametrize("mixed", [False, True])
def test_clear_is_explicit_and_reset_restores_original_state(
    host: QWidget, mixed: bool
) -> None:
    row = _row(host, 1_700_001_234, mixed=mixed)
    edit = row.editor
    assert isinstance(edit, MetadataDateEdit)
    QTest.mouseClick(_button(edit, "metadataDateClear"), Qt.MouseButton.LeftButton)
    assert row.is_modified() and row.value() == 0
    assert not edit.date.isVisible()
    row.reset()
    assert not row.is_modified() and edit.value() == 1_700_001_234
    assert edit.date.isVisible() is not mixed


@pytest.mark.parametrize("value", [-1, -11_676_096_000, 10**18])
def test_signed_and_unrepresentable_dates_are_preserved(
    host: QWidget, value: int
) -> None:
    row = _row(host, value)
    edit = row.editor
    assert isinstance(edit, MetadataDateEdit)
    assert row.value() == value and not row.is_modified()
    edit.clear()
    assert row.value() == 0 and row.is_modified()
    row.reset()
    assert row.value() == value and not row.is_modified()


def test_repeated_hour_retains_original_instant_when_edits_are_reverted(
    host: QWidget, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "iOpenPod.GUI.widgets.metadata_date_edit.SYSTEM_TZ", "America/New_York"
    )
    monkeypatch.setattr("iOpenPod.app.core.dates.SYSTEM_TZ", "America/New_York")
    original = Instant.parse_iso("2024-11-03T06:30:45Z").timestamp()
    row = _row(host, original)
    edit = row.editor
    assert isinstance(edit, MetadataDateEdit)
    assert edit.time.time() == QTime(1, 30, 45)
    edit.time.setTime(QTime(1, 30, 46))
    assert row.is_modified()
    edit.time.setTime(QTime(1, 30, 45))
    assert not row.is_modified() and row.value() == original
    edit.date.setDate(QDate(2024, 11, 4))
    assert row.value() == Instant.parse_iso("2024-11-04T06:30:45Z").timestamp()


def test_locale_changes_keep_seconds_visible_without_modifying_the_value(
    host: QWidget,
) -> None:
    row = _row(host, 1_700_001_234)
    edit = row.editor
    assert isinstance(edit, MetadataDateEdit)
    edit.setLocale(QLocale("en_US"))
    assert edit.time.displayFormat() == "h:mm:ss AP"
    edit.setLocale(QLocale("de_DE"))
    assert edit.time.displayFormat() == "h:mm:ss AP"
    assert "dd" in edit.date.displayFormat()
    assert not row.is_modified() and row.value() == 1_700_001_234


def test_time_can_be_typed_and_stepped_with_the_keyboard(host: QWidget) -> None:
    row = _row(host, 1_700_001_234)
    edit = row.editor
    assert isinstance(edit, MetadataDateEdit)
    original_date = edit.date.date()
    edit.time.setFocus()
    edit.time.setSelectedSection(QTimeEdit.Section.SecondSection)
    QTest.keyClicks(edit.time, "12")
    QTest.keyClick(edit.time, Qt.Key.Key_Tab)
    assert edit.time.time().second() == 12 and row.is_modified()
    assert edit.date.date() == original_date
    edit.time.setFocus()
    edit.time.setSelectedSection(QTimeEdit.Section.SecondSection)
    QTest.keyClick(edit.time, Qt.Key.Key_Up)
    assert edit.time.time().second() == 13


def test_clear_action_has_a_visible_glyph(host: QWidget) -> None:
    row = _row(host, 1_700_001_234)
    edit = row.editor
    assert isinstance(edit, MetadataDateEdit)
    clear = _button(edit, "metadataDateClear")
    icon = clear.icon().pixmap(24, 24).toImage()
    assert any(
        icon.pixelColor(x, y).alpha()
        for y in range(icon.height())
        for x in range(icon.width())
    )


@pytest.mark.parametrize("mixed", [False, True])
def test_date_actions_stay_grouped_at_the_leading_edge_when_resized(
    host: QWidget, mixed: bool
) -> None:
    row = _row(host, 0, mixed=mixed)
    edit = row.editor
    assert isinstance(edit, MetadataDateEdit)
    button = _button(edit, "metadataDateSet")
    for width in (520, 980):
        host.resize(width, 150)
        APPLICATION.processEvents()
        assert button.x() == 0
        assert button.width() < edit.width() / 2
    button.click()
    APPLICATION.processEvents()
    assert edit.date.x() == 0
    assert edit.time.x() - edit.date.geometry().right() <= LAYOUT.space_xs + 1
    clear = _button(edit, "metadataDateClear")
    assert clear.x() - edit.time.geometry().right() <= LAYOUT.space_xs + 1
    original_widths = edit.date.width(), edit.time.width()
    host.resize(1200, 150)
    APPLICATION.processEvents()
    assert (edit.date.width(), edit.time.width()) == original_widths
