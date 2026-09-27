"""Runtime translation of model fallbacks and structured Backup outcomes."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QPersistentModelIndex, Qt, QTranslator
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from iOpenPod.app.backups.models import BackupExportResult
from iOpenPod.app.backups.outcomes import (
    BackupDiagnostic,
    BackupFailure,
    BackupFailureCode,
    BackupImportCounts,
    CaptureFailed,
    ExportCompleted,
    ImportCompleted,
)
from iOpenPod.app.display_text import source_text
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.playlist_tree_model import PlaylistTreeModel
from iOpenPod.app.models.podcast_list_models import (
    ALL_PODCASTS_SOURCE_ID,
    PodcastListRole,
    PodcastSubscriptionListModel,
)
from iOpenPod.app.models.sync_plan_table_model import SyncPlanColumn, SyncPlanTableModel
from iOpenPod.app.podcasts.models import PodcastSubscription, SubscriptionSource
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
)
from iOpenPod.GUI.presentation.backup_messages import backup_message_for
from iPodDB.library import LibrarySnapshot, Playlist, PlaylistKind


class _Translator(QTranslator):
    def isEmpty(self) -> bool:
        return False

    def translate(
        self,
        context: str,
        source_text: str,
        /,
        disambiguation: str | None = None,
        n: int = -1,
    ) -> str | None:
        del disambiguation, n
        return {
            ("PodcastSubscriptionListModel", "All Podcasts"): "Alle Podcasts",
            ("PlaylistTreeModel", "Untitled Playlist"): "Unbenannte Playlist",
            ("SyncPlanTableModel", "Add"): "Hinzufügen",
            ("SyncPlanTableModel", "Track"): "Titel",
            ("SyncPlanTableModel", "Only in Host Media Library"): "Nur auf dem Host",
            ("BackupMessages", "Backup Failed"): "Sicherung fehlgeschlagen",
            (
                "Workflow",
                "The backup location is unavailable.",
            ): "Speicherort nicht verfügbar.",
            (
                "Workflow",
                "Reconnect and retry.",
            ): "Erneut verbinden und versuchen.",
            (
                "Workflow",
                "Could not import {device_id}/{snapshot_id}.",
            ): "{snapshot_id} von {device_id} konnte nicht importiert werden.",
            (
                "BackupMessages",
                "Exported %n file(s) to {destination}.",
            ): "%n Dateien nach {destination} exportiert.",
        }.get((context, source_text))


@pytest.fixture
def translated_application() -> Iterator[QApplication]:
    existing = QApplication.instance()
    application = existing if isinstance(existing, QApplication) else QApplication([])
    translator = _Translator()
    assert application.installTranslator(translator)
    try:
        yield application
    finally:
        application.removeTranslator(translator)


def test_podcast_aggregate_translates_display_and_search_without_changing_identity(
    translated_application: QApplication,
) -> None:
    model = PodcastSubscriptionListModel()
    model.replace(
        (
            PodcastSubscription(
                "show", "https://example.test/feed", "My Show", SubscriptionSource.USER
            ),
        ),
        include_all=True,
    )
    aggregate = model.index(0, 0)
    changed = QSignalSpy(model.dataChanged)

    model.retranslate()

    assert aggregate.data() == "Alle Podcasts"
    assert aggregate.data(PodcastListRole.SEARCH_TEXT) == "alle podcasts"
    assert aggregate.data(PodcastListRole.IDENTITY) == ALL_PODCASTS_SOURCE_ID
    assert model.index(1, 0).data() == "My Show"
    assert changed.count() == 1


def test_nested_playlist_fallback_refresh_keeps_indexes_and_drag_lifetime(
    translated_application: QApplication,
) -> None:
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(
            playlists=(
                Playlist(1, "Folder", PlaylistKind.FOLDER),
                Playlist(2, "", parent_id=1),
            )
        )
    )
    model = PlaylistTreeModel(workspace)
    child = model.index_for_id(2)
    retained = QPersistentModelIndex(child)
    drag = model.mimeData([child])
    changed = QSignalSpy(model.dataChanged)
    resets = QSignalSpy(model.modelReset)

    model.retranslate()

    assert retained.isValid()
    assert retained.data() == "Unbenannte Playlist"
    assert retained.data(Qt.ItemDataRole.AccessibleTextRole) == "Unbenannte Playlist"
    assert retained.parent().data() == "Folder"
    assert changed.count() == 1
    assert resets.count() == 0
    assert model.canDropMimeData(
        drag, Qt.DropAction.MoveAction, -1, 0, model.index(-1, 0)
    )


def test_sync_labels_use_the_same_catalog_context_as_the_table(
    translated_application: QApplication,
) -> None:
    model = SyncPlanTableModel()
    model.replace_plan(
        SyncPlan(
            (
                SyncPlanItem(
                    SyncPlanAction.ADD,
                    SyncPlanMediaKind.TRACK,
                    SyncPlanBasis.HOST_ONLY,
                    "My Track",
                    host_path="C:/My Track.mp3",
                ),
            )
        )
    )

    assert model.index(0, SyncPlanColumn.ACTION).data() == "Hinzufügen"
    assert model.index(0, SyncPlanColumn.MEDIA).data() == "Titel"
    assert model.index(0, SyncPlanColumn.REASON).data() == "Nur auf dem Host"
    assert "Hinzufügen" in str(model.index(0, 0).data(Qt.ItemDataRole.ToolTipRole))
    assert model.index(0, SyncPlanColumn.NAME).data() == "My Track"


def test_backup_messages_translate_templates_before_substitution_and_keep_raw_details(
    translated_application: QApplication,
) -> None:
    message = backup_message_for(
        CaptureFailed(
            BackupFailure(
                BackupFailureCode.ARCHIVE_UNAVAILABLE,
                "The backup location is unavailable.",
                "Reconnect and retry.",
                "raw diagnostic",
            )
        )
    )
    exported = backup_message_for(
        ExportCompleted(BackupExportResult(Path("My Export"), 3, 10))
    )

    assert message.title == "Sicherung fehlgeschlagen"
    assert message.body == "Speicherort nicht verfügbar."
    assert message.next_step == "Erneut verbinden und versuchen."
    assert "raw diagnostic" in message.diagnostic_detail
    assert exported.body == "3 Dateien nach My Export exportiert."


def test_backup_diagnostic_translates_retained_template_before_formatting(
    translated_application: QApplication,
) -> None:
    outcome = ImportCompleted(
        BackupImportCounts(),
        BackupImportCounts(),
        (
            BackupDiagnostic(
                "legacy.import_failed",
                source_text(
                    "Could not import {device_id}/{snapshot_id}.",
                    device_id="My iPod",
                    snapshot_id="snapshot-1",
                ),
                "raw diagnostic",
            ),
        ),
    )

    message = backup_message_for(outcome)

    assert (
        "snapshot-1 von My iPod konnte nicht importiert werden."
        in message.diagnostic_detail
    )
    assert "raw diagnostic" in message.diagnostic_detail
