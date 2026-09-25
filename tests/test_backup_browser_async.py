from types import SimpleNamespace
from typing import Any, cast

from PyQt6.QtWidgets import QLabel

from iopenpod.gui.styles import paint_css
from iopenpod.gui.widgets import backupBrowser as backup_browser
from iopenpod.gui.widgets.backupBrowser import (
    BackupBrowserWidget,
    SnapshotCard,
)


class _Button:
    def __init__(self) -> None:
        self.enabled = False
        self.text = ""

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def setText(self, text: str) -> None:
        self.text = text


class _Signal:
    def __init__(self) -> None:
        self.emissions = 0

    def emit(self) -> None:
        self.emissions += 1


def test_stale_catalog_result_is_ignored() -> None:
    applied: list[object] = []
    catalog = object()
    widget = SimpleNamespace(
        _archive_load_generation=8,
        _current_device_id="SELECTED",
        _is_busy=lambda: False,
        _apply_snapshot_catalog=applied.append,
    )

    BackupBrowserWidget._on_catalog_loaded(
        cast(Any, widget),
        cast(Any, catalog),
        7,
        "SELECTED",
    )

    assert applied == []


def test_catalog_result_for_changed_device_is_ignored() -> None:
    applied: list[object] = []
    catalog = object()
    widget = SimpleNamespace(
        _archive_load_generation=8,
        _current_device_id="NEW_DEVICE",
        _is_busy=lambda: False,
        _apply_snapshot_catalog=applied.append,
    )

    BackupBrowserWidget._on_catalog_loaded(
        cast(Any, widget),
        cast(Any, catalog),
        8,
        "OLD_DEVICE",
    )

    assert applied == []


def test_current_catalog_result_is_applied() -> None:
    applied: list[object] = []
    catalog = object()
    widget = SimpleNamespace(
        _archive_load_generation=8,
        _current_device_id="SELECTED",
        _is_busy=lambda: False,
        _apply_snapshot_catalog=applied.append,
    )

    BackupBrowserWidget._on_catalog_loaded(
        cast(Any, widget),
        cast(Any, catalog),
        8,
        "SELECTED",
    )

    assert applied == [catalog]


def test_invalid_snapshot_card_disables_delete_with_accessible_reason(qapp) -> None:
    del qapp
    snapshot = SimpleNamespace(
        id="20260101_120000",
        display_date="January 1, 2026",
        reason="manual",
        file_count=0,
        total_size=0,
        files_added=0,
        files_removed=0,
        files_changed=0,
        note="",
        is_valid=False,
        validation_error="Manifest checksum does not match",
    )

    card = SnapshotCard(cast(Any, snapshot))

    assert card._delete_btn.isEnabled() is False
    assert "catalog" in card._delete_btn.toolTip().lower()
    assert "checksum" in card._delete_btn.accessibleDescription().lower()
    assert paint_css("surface.inset") in card.styleSheet()
    invalid_details = card.findChild(QLabel, "invalidCatalogDetails")
    assert invalid_details is not None
    assert paint_css("status.danger.text") in invalid_details.styleSheet()


def test_snapshot_card_provides_an_empty_editable_note(qapp) -> None:
    del qapp
    snapshot = SimpleNamespace(
        id="20260101_120000",
        display_date="January 1, 2026",
        reason="manual",
        file_count=1,
        total_size=4,
        files_added=0,
        files_removed=0,
        files_changed=0,
        note="",
        is_valid=True,
        validation_error="",
    )
    card = SnapshotCard(cast(Any, snapshot))
    emitted: list[tuple[str, str]] = []
    card.note_changed.connect(lambda snapshot_id, note: emitted.append((snapshot_id, note)))

    assert card._note_edit.text() == ""
    card._note_edit.setText("Saved for later")
    card._note_edit.editingFinished.emit()

    assert emitted == [("20260101_120000", "Saved for later")]


def test_delete_worker_stays_pinned_until_finished() -> None:
    worker = object()
    refreshes: list[bool] = []
    action_states: list[bool] = []
    widget = SimpleNamespace(
        _delete_worker=worker,
        _delete_generation=3,
        _delete_result=None,
        _delete_error="",
        _progress_cancel_btn=_Button(),
        _set_archive_actions_enabled=action_states.append,
        refresh=lambda: refreshes.append(True),
    )

    BackupBrowserWidget._on_delete_worker_result(
        cast(Any, widget),
        cast(Any, worker),
        3,
        True,
    )

    assert widget._delete_worker is worker

    BackupBrowserWidget._on_delete_worker_finished(
        cast(Any, widget),
        cast(Any, worker),
        3,
    )

    assert widget._delete_worker is None
    assert action_states == [True]
    assert refreshes == [True]


def test_pending_restore_durability_triggers_safe_eject(
    monkeypatch,
) -> None:
    warnings: list[tuple[str, str]] = []
    closed = _Signal()
    eject = _Signal()
    refreshes: list[bool] = []
    action_states: list[bool] = []
    monkeypatch.setattr(
        backup_browser.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )
    widget = SimpleNamespace(
        _restore_worker=object(),
        _restore_committing=True,
        _progress_cancel_btn=_Button(),
        _set_archive_actions_enabled=action_states.append,
        closed=closed,
        safe_eject_required=eject,
        refresh=lambda: refreshes.append(True),
    )
    failure = SimpleNamespace(
        message="Final volume flush is pending.",
        device_changed=True,
        content_verified=True,
        requires_safe_eject=True,
        safety_snapshot_id="checkpoint-1",
    )

    BackupBrowserWidget._on_restore_error(
        cast(Any, widget),
        cast(Any, failure),
    )

    assert widget._restore_worker is None
    assert warnings
    assert "eject" in warnings[0][0].casefold()
    assert closed.emissions == 1
    assert eject.emissions == 1
    assert refreshes == []
