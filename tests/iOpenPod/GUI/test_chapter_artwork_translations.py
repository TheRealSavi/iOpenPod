"""Compiled catalogs retranslate chapter artwork without changing the draft."""

from pathlib import Path

import pytest
from PySide6.QtCore import QTranslator
from PySide6.QtWidgets import QDoubleSpinBox, QLabel
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.GUI.dialogs.artwork_editor import ArtworkEditor
from iOpenPod.GUI.dialogs.metadata_editor import MetadataEditorDialog
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.metadata_field_editor import ChapterEditor
from iPodDB.library import (
    ArtworkPixels,
    LibrarySnapshot,
    Track,
    TrackChapter,
    TrackMetadata,
)


@pytest.mark.parametrize(
    ("language", "column", "tooltip", "unassigned", "empty_status"),
    (
        (
            "de",
            "Cover",
            "Cover für dieses Kapitel auswählen",
            "Nicht zugewiesenes Cover",
            "Diesem Kapitel ist kein Cover zugewiesen.",
        ),
        (
            "es",
            "Portada",
            "Elegir una portada para este capítulo",
            "Portada sin asignar",
            "Este capítulo no tiene ninguna portada asignada.",
        ),
    ),
)
def test_live_chapter_artwork_translation_keeps_titles_selection_and_pending_images(
    language: str, column: str, tooltip: str, unassigned: str, empty_status: str
) -> None:
    chapters = (TrackChapter("Opening", 0), TrackChapter("User chapter title", 6000))
    track = Track(
        1,
        "Episode",
        "Host",
        "Series",
        10_000,
        metadata=TrackMetadata(chapters=chapters),
    )
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot((track,)))
    dialog = MetadataEditorDialog(workspace, (1,))
    translator = QTranslator()
    catalog = (
        Path(__file__).resolve().parents[3]
        / "src/iOpenPod/GUI/presentation/i18n/translations"
        / f"iopenpod_{language}.qm"
    )
    try:
        artwork = dialog.findChild(ArtworkEditor)
        chapter_editor = dialog.rows["metadata.chapters"].editor
        assert artwork is not None and isinstance(chapter_editor, ChapterEditor)
        entries = artwork.findChild(AppComboBox, "metadataArtworkEntries")
        assert entries is not None
        artwork.set_pending_artwork(ArtworkPixels(1, 1, b"\xff\x00\x00"))
        artwork.add_pending_artwork(ArtworkPixels(1, 1, b"\x00\x00\xff"), 3000)
        assert artwork.select_chapter(6000)
        pending = artwork.edit()
        dialog.show()
        APPLICATION.processEvents()
        assert translator.load(str(catalog))
        assert APPLICATION.installTranslator(translator)
        APPLICATION.processEvents()

        assert entries.currentData() == 6000
        assert entries.currentText() == "2. User chapter title"
        assert entries.itemText(entries.findData(3000)).startswith(unassigned)
        header = chapter_editor.table.horizontalHeaderItem(2)
        cell = chapter_editor.table.item(1, 2)
        assert header is not None and header.text() == column
        assert cell is not None and cell.toolTip() == tooltip
        assert empty_status in [label.text() for label in artwork.findChildren(QLabel)]
        assert artwork.findChild(QDoubleSpinBox, "metadataArtworkTime") is None
        assert chapter_editor.value() == chapters
        assert not dialog.rows["metadata.chapters"].is_modified()
        assert artwork.edit() == pending
        assert workspace.track(1) == track
    finally:
        APPLICATION.removeTranslator(translator)
        APPLICATION.processEvents()
        dialog.close()
