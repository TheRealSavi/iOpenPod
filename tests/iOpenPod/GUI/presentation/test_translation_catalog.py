"""Exercise real Qt extraction and compiled catalogs, not only tr() wrappers."""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QCoreApplication, QTranslator
from PySide6.QtWidgets import QApplication
from scripts.update_translations import application_sources, extract_catalogs

from iOpenPod.app.display_text import source_text
from iOpenPod.GUI.presentation.i18n.text import track_count_text
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text

if TYPE_CHECKING:
    from pathlib import Path


def _application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


APPLICATION = _application()


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("catalog") / "iopenpod_de.ts"
    extract_catalogs([path])
    return path


def test_extraction_includes_dynamic_sources_in_runtime_contexts(catalog: Path) -> None:
    tree = ET.parse(catalog)
    messages = {
        (context.findtext("name"), message.findtext("source")): message
        for context in tree.findall("context")
        for message in context.findall("message")
    }
    expected = {
        ("DevicePickerDialog", "Ready to load"),
        ("SyncPlanTableModel", "Add"),
        ("PlaylistEditorDialog", "Smart Playlist"),
        ("Eta", "Waiting for progress…"),
        ("BackupMessages", "Backup Complete"),
        ("MetadataFields", "Volume adjustment (%)"),
        ("TrackTable", "Core Metadata"),
        ("Workflow", "Validating the selected Sync Plan…"),
        ("Workflow", "Let that operation finish, then retry."),
        ("Workflow", "Downloading {title}…"),
        ("CommonActions", "Cancel"),
        ("LibraryLabels", "Unknown Album"),
        ("Workflow", "Enter a name for the iPod."),
        ("Workflow", "No tag changes are needed."),
        ("Workflow", "Reparsing and verifying candidate output"),
        ("Workflow", "steps"),
        ("Workflow", "Rebuild descendant membership and direct-child rules."),
        ("EditorLabels", "Technical details"),
        ("PodcastPresentation", "Unknown publisher"),
    }
    assert not expected - messages.keys()
    assert ("dialog", "Ready to load") not in messages
    assert ("model", "Add") not in messages
    for source in (
        "%n track(s)",
        "Remove %n Track(s) from iPod",
        "%Ln tag change(s) available",
        "%n format(s)",
        "%n device(s) found",
        "%n show(s)",
        "%n result(s)",
        "%n Podcast(s) found.",
    ):
        assert messages["Counts", source].get("numerus") == "yes"
    for key in (
        ("MetadataEditorDialog", "Edit %n Track(s)"),
        ("MetadataEditorDialog", "%n selected track(s)"),
        ("PhotoMetadataEditorDialog", "Edit %n Photo(s)"),
        ("PhotoMetadataEditorDialog", "%n selected Photo(s)"),
        ("ConsolidateArtworkDialog", "Used by %n Track(s)"),
        ("TagNormalizerDialog", "Apply all %Ln change(s)"),
        (
            "TagNormalizerDialog",
            "Showing %1 of %Ln change(s). Applying includes all %Ln change(s).",
        ),
        ("SyncExecutionPage", "%n selected change(s) committed."),
        ("SyncExecutionPage", "%n Playlist(s) reconciled."),
        ("SyncExecutionPage", "…and %n more file(s)"),
        ("SyncWorkspace", " · %Ln Playlist change(s)"),
        (
            "SyncWorkspace",
            "%n Podcast(s) will sync using their saved settings. "
            "Episodes may be added or removed.",
        ),
        ("SyncPlanPage", "%1 of %Ln media change(s) selected"),
        ("BackupSnapshotCard", "%1\n%Ln file(s) · %3\n%4"),
        ("BackupPage", "Exported %Ln file(s) to:\n\n%1"),
        ("MainWindow", "Exported %n Photo(s) into individual folders."),
        ("MainWindow", "Wrote %n image file(s)."),
        ("MainWindow", "Exported %n Track file(s) beside it."),
        ("MainWindow", "Exported %n Track file(s)."),
    ):
        assert messages[key].get("numerus") == "yes"
    assert [key for key in messages if key[1] == "Cancel"] == [
        ("CommonActions", "Cancel")
    ]
    assert [key for key in messages if key[1] == "Unknown Album"] == [
        ("LibraryLabels", "Unknown Album")
    ]


def test_catalog_update_preserves_existing_translations(
    catalog: Path, tmp_path: Path
) -> None:
    tree = ET.parse(catalog)
    for context in tree.findall("context"):
        if context.findtext("name") != "CommonActions":
            continue
        for message in context.findall("message"):
            if message.findtext("source") == "Cancel":
                translation = message.find("translation")
                assert translation is not None
                translation.clear()
                translation.text = "Abbrechen"
    updated = tmp_path / "iopenpod_de.ts"
    tree.write(updated, encoding="utf-8", xml_declaration=True)
    extract_catalogs([updated])
    translations = {
        (context.findtext("name"), message.findtext("source")): message.findtext(
            "translation"
        )
        for context in ET.parse(updated).findall("context")
        for message in context.findall("message")
    }
    assert translations["CommonActions", "Cancel"] == "Abbrechen"


def test_compiled_catalog_translates_workflows_and_selects_plural_forms(
    catalog: Path, tmp_path: Path
) -> None:
    tree = ET.parse(catalog)
    tree.getroot().set("language", "de_DE")
    for context in tree.findall("context"):
        for message in context.findall("message"):
            translation = message.find("translation")
            assert translation is not None
            key = (context.findtext("name"), message.findtext("source"))
            if key == ("Counts", "%n track(s)"):
                translation.clear()
                ET.SubElement(translation, "numerusform").text = "%n Titel (einzeln)"
                ET.SubElement(translation, "numerusform").text = "%n Titel (mehrere)"
            elif key == ("Workflow", "Validating the selected Sync Plan…"):
                translation.clear()
                translation.text = "Auswahl prüfen…"
            elif key == ("Workflow", "Downloading {title}…"):
                translation.clear()
                translation.text = "{title} wird geladen…"
    source = tmp_path / "iopenpod_de.ts"
    compiled = tmp_path / "iopenpod_de.qm"
    tree.write(source, encoding="utf-8", xml_declaration=True)
    subprocess.run(
        ["pyside6-lrelease", "-silent", str(source), "-qm", str(compiled)],
        check=True,
    )
    translator = QTranslator()
    assert translator.load(str(compiled))
    assert APPLICATION.installTranslator(translator)
    try:
        assert track_count_text(0) == "0 Titel (mehrere)"
        assert track_count_text(1) == "1 Titel (einzeln)"
        assert track_count_text(2) == "2 Titel (mehrere)"
        assert workflow_text("Validating the selected Sync Plan…") == "Auswahl prüfen…"
        assert workflow_text("User's track.mp3") == "User's track.mp3"
        title = "My {title} %1 <episode>"
        assert workflow_text(source_text("Downloading {title}…", title=title)) == (
            title + " wird geladen…"
        )
    finally:
        APPLICATION.removeTranslator(translator)
    assert track_count_text(1) == "1 track"
    assert track_count_text(2) == "2 tracks"


def test_contract_extraction_keeps_display_copy_separate_from_identifiers(
    tmp_path: Path,
) -> None:
    source = tmp_path / "example.py"
    source.write_text(
        'WriteProgress("stable.phase", "Working…", unit="files")\n'
        'BackupFailure(code="stable.code", summary="Failed", action="Retry")\n'
        'WriteProgress("stable.phase", external_error)\n'
        "def emit(code, text, *, unit):\n"
        "    return WriteProgress(code, text, unit=unit)\n"
        'emit("private.phase", "Inspecting files", unit="steps")\n',
        encoding="utf-8",
    )
    assert application_sources(source) == {
        ("Workflow", "Working…"),
        ("Workflow", "files"),
        ("Workflow", "Failed"),
        ("Workflow", "Retry"),
        ("Workflow", "Inspecting files"),
        ("Workflow", "steps"),
    }


def test_english_fallback_does_not_replace_translated_plural_notation() -> None:
    from iOpenPod.GUI.presentation.i18n.text import english_count_fallback

    assert english_count_fallback("%n track(s)", "1 Titel(s)", 1) == "1 Titel(s)"
    assert QCoreApplication.translate("Counts", "%n track(s)", None, 1) == "1 track(s)"
