"""Library review translates presentation labels while retaining record identities."""

from PySide6.QtCore import QTranslator
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QTreeWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.display_text import SourceText, source_text
from iOpenPod.app.library_write import LibraryReview, WriteProgress
from iOpenPod.GUI.dialogs.library_review import LibraryReviewDialog
from iPodDB.library import LibraryChange, LibrarySnapshot, WriteEffect, WriteIssue
from iPodDB.library.writing import (
    LibraryDraft,
    LibraryResolution,
    LibraryWritePlan,
    LibraryWriteResult,
    WriteTarget,
)


class _ReviewTranslator(QTranslator):
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
        if context == "Workflow":
            return {
                "Rebuild descendant membership and direct-child rules.": "Mitgliedschaften und Regeln neu erstellen.",
                "Publishing Library files: {completed} of {total}": "Bibliotheksdateien: {completed} von {total}",
            }.get(source_text)
        if context != "LibraryReviewDialog":
            return None
        return {
            "Add": "Hinzufügen",
            "Edit": "Bearbeiten",
            "Delete": "Löschen",
            "Photo Album": "Fotoalbum",
            "Playlist": "Wiedergabeliste",
            "{action} · {subject}": "{subject}: {action}",
            "{subject} {record_id}": "{record_id} — {subject}",
            "Requested: {change} — {name} ({fields})": "Angefordert: {name} — {change} ({fields})",
            "Chunk {path} at {offset}": "Chunk {path} bei {offset}",
        }.get(source_text)


def test_review_translates_changes_effects_and_details_without_changing_navigation() -> (
    None
):
    context = build_context()
    snapshot = LibrarySnapshot()
    changes = tuple(
        LibraryChange("photo_album", 42, action, "My Album", ("name",))
        for action in ("add", "edit", "delete")
    )
    effect = WriteEffect(
        "playlist.folder_aggregate",
        "playlist",
        8,
        "Rebuild descendant membership and direct-child rules.",
        (1,),
        ("entries",),
    )
    issue = WriteIssue(
        "test.issue",
        "Issue message",
        subject="photo_album",
        record_id=42,
        chunk_path=(0, 2),
        offset=64,
    )
    context.library_write_controller.review = LibraryReview(
        LibraryWritePlan(
            LibraryDraft("revision", snapshot),
            WriteTarget(),
            changes,
            (),
            resolution=LibraryResolution(snapshot, (), (effect,), ()),
        ),
        LibraryWriteResult((issue,)),
    )
    translator = _ReviewTranslator()
    assert APPLICATION.installTranslator(translator)
    dialog = LibraryReviewDialog(context.library_write_controller)
    try:
        tree = dialog.findChild(QTreeWidget, "libraryReviewItems")
        details = dialog.findChild(QPlainTextEdit, "libraryReviewDetails")
        assert tree is not None and details is not None
        changed = tree.topLevelItem(0)
        consequences = tree.topLevelItem(1)
        errors = tree.topLevelItem(2)
        assert changed is not None and consequences is not None and errors is not None
        labels: list[str] = []
        for index in range(3):
            item = changed.child(index)
            assert item is not None
            labels.append(item.text(0))
        assert labels == [
            "Fotoalbum: Hinzufügen",
            "Fotoalbum: Bearbeiten",
            "Fotoalbum: Löschen",
        ]
        change_item = changed.child(1)
        assert change_item is not None and change_item.text(1) == "My Album"
        navigated = QSignalSpy(dialog.recordRequested)
        tree.itemDoubleClicked.emit(change_item, 0)
        assert navigated.count() == 1
        assert navigated.at(0) == ["photo_album", 42]

        generated = consequences.child(0)
        assert generated is not None
        assert generated.text(0) == "Mitgliedschaften und Regeln neu erstellen."
        assert generated.text(1) == "8 — Wiedergabeliste"
        tree.setCurrentItem(generated)
        assert "Mitgliedschaften und Regeln neu erstellen." in details.toPlainText()
        assert (
            "Angefordert: My Album — Fotoalbum: Bearbeiten (name)"
            in details.toPlainText()
        )

        error = errors.child(0)
        assert error is not None and error.text(1) == "42 — Fotoalbum"
        tree.setCurrentItem(error)
        assert details.toPlainText() == "Chunk (0, 2) bei 64"
    finally:
        dialog.close()
        APPLICATION.removeTranslator(translator)
        context.shutdown()


def test_controller_progress_preserves_template_until_the_dialog_translates_it() -> (
    None
):
    context = build_context()
    controller = context.library_write_controller
    translator = _ReviewTranslator()
    assert APPLICATION.installTranslator(translator)
    dialog = LibraryReviewDialog(controller)
    try:
        status = dialog.findChild(QLabel, "libraryReviewStatus")
        assert status is not None
        observed: list[object] = []
        controller.progressChanged.connect(observed.append)
        message = source_text(
            "Publishing Library files: {completed} of {total}", completed="2", total="5"
        )
        controller._progress(  # pyright: ignore[reportPrivateUsage]
            controller._token,  # pyright: ignore[reportPrivateUsage]
            WriteProgress("save.storage.publishing", message),
        )
        assert len(observed) == 1 and isinstance(observed[0], SourceText)
        assert status.text() == "Bibliotheksdateien: 2 von 5"
        controller.progressChanged.emit(None)
        assert status.text() == "Bibliotheksdateien: 2 von 5"
    finally:
        dialog.close()
        APPLICATION.removeTranslator(translator)
        context.shutdown()
