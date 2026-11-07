"""Translated ID-based choices preserve raw Track EQ until explicitly edited."""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QTranslator
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QLineEdit
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iPodDB.library.test_video_flags import video_source

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.track_columns import TrackColumn, track_column_display_value
from iOpenPod.GUI.dialogs.metadata_editor import MetadataEditorDialog
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iPodDB.library import (
    EqualizerPreset,
    IPodLibrary,
    LibrarySnapshot,
    Track,
    TrackMetadata,
)


def _workspace(*values: str) -> LibraryWorkspace:
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(
            tuple(
                Track(
                    i,
                    "Song",
                    "Artist",
                    "Album",
                    1000,
                    metadata=TrackMetadata(equalizer=raw),
                )
                for i, raw in enumerate(values, 1)
            )
        )
    )
    return workspace


def test_dropdown_contains_all_presets_as_text_and_numeric_item_data() -> None:
    workspace = _workspace("#!#116#!#")
    dialog = MetadataEditorDialog(workspace, (1,))
    try:
        row = dialog.rows["metadata.equalizer"]
        combo = row.editor
        assert isinstance(combo, AppComboBox)
        assert not combo.isEditable()
        assert combo.count() == 23
        assert [combo.itemData(i) for i in range(combo.count())] == [
            0,
            *range(100, 122),
        ]
        assert combo.itemText(0) == "Use iPod setting"
        assert combo.currentText() == "Rock"
        assert combo.currentData() == 116
        assert not row.is_modified()
        for preset in EqualizerPreset:
            combo.setCurrentIndex(combo.findData(preset.value))
            assert combo.currentText() and not any(
                c.isdigit() for c in combo.currentText()
            )
            assert row.value() == ("" if preset.value == 0 else f"#!#{preset.value}#!#")
        row.reset()
        assert combo.currentText() == "Rock" and not row.is_modified()
        dialog.accept()
        assert not workspace.dirty
    finally:
        dialog.close()


@pytest.mark.parametrize(
    "raw", ["#!#999#!#", "Custom preset", "Rock", "116", "#!#116extra#!#"]
)
def test_unknown_eq_survives_reset_and_unrelated_edit(raw: str) -> None:
    workspace = _workspace(raw)
    dialog = MetadataEditorDialog(workspace, (1,))
    try:
        row = dialog.rows["metadata.equalizer"]
        combo = row.editor
        assert isinstance(combo, AppComboBox)
        assert combo.currentText() == "Unknown preset (preserved)"
        assert combo.currentData() is None and not row.is_modified()
        combo.setCurrentIndex(combo.findData(116))
        assert row.is_modified()
        row.reset()
        assert not row.is_modified() and combo.currentData() is None
        combo.setCurrentIndex(combo.findData(107))
        combo.setCurrentIndex(0)
        assert not row.is_modified()
        title = dialog.rows["title"].editor
        assert isinstance(title, QLineEdit)
        title.setText("Edited title")
        dialog.accept()
        assert workspace.tracks[0].title == "Edited title"
        assert workspace.tracks[0].metadata.equalizer == raw
    finally:
        dialog.close()


@pytest.mark.parametrize("choice,expected", [(None, None), (0, ""), (116, "#!#116#!#")])
def test_bulk_mixed_eq_is_preserved_or_explicitly_replaced(
    choice: int | None, expected: str | None
) -> None:
    values = ("#!#100#!#", "Unrecognized saved curve")
    workspace = _workspace(*values)
    dialog = MetadataEditorDialog(workspace, (1, 2))
    try:
        row = dialog.rows["metadata.equalizer"]
        combo = row.editor
        assert isinstance(combo, AppComboBox)
        assert combo.currentData() is None
        assert combo.currentText() == "Mixed values"
        if choice is not None:
            combo.setCurrentIndex(combo.findData(choice))
        dialog.accept()
        assert tuple(track.metadata.equalizer for track in workspace.tracks) == (
            values if expected is None else (expected, expected)
        )
    finally:
        dialog.close()


def test_editor_publishes_canonical_eq_through_existing_database_writer() -> None:
    source = video_source(video=False)
    workspace = LibraryWorkspace()
    workspace.load(source.snapshot)
    track = source.snapshot.tracks[0]
    dialog = MetadataEditorDialog(workspace, (track.track_id,))
    try:
        combo = dialog.rows["metadata.equalizer"].editor
        assert isinstance(combo, AppComboBox)
        combo.setCurrentIndex(combo.findData(116))
        dialog.accept()
        plan = source.analyze(source.begin_draft(workspace.desired_snapshot()))
        assert not plan.required_media
        result = source.prepare(plan)
        assert result.prepared is not None, result.issues
        saved = IPodLibrary(result.prepared.itunes).snapshot.tracks[0]
        assert saved.metadata.equalizer == "#!#116#!#"
        assert "#!#116#!#".encode("utf-16le") in result.prepared.itunes
        assert saved.metadata.location == track.metadata.location
    finally:
        dialog.close()


@pytest.mark.parametrize(
    "language,acoustic,bass,inherit,unknown",
    [
        (
            "de",
            "Akustik",
            "Bässe verstärken",
            "iPod-Einstellung verwenden",
            "Unbekannte Voreinstellung (beibehalten)",
        ),
        (
            "es",
            "Acústica",
            "Refuerzo de graves",
            "Usar ajuste del iPod",
            "Preajuste desconocido (conservado)",
        ),
    ],
)
def test_packaged_translations_preserve_selection_and_pending_edit(
    language: str, acoustic: str, bass: str, inherit: str, unknown: str
) -> None:
    workspace = _workspace("#!#100#!#")
    dialog = MetadataEditorDialog(workspace, (1,))
    translator = QTranslator()
    catalog = (
        Path(__file__).resolve().parents[3]
        / "src/iOpenPod/GUI/presentation/i18n/translations"
        / f"iopenpod_{language}.qm"
    )
    assert translator.load(str(catalog))
    row = dialog.rows["metadata.equalizer"]
    combo = row.editor
    assert isinstance(combo, AppComboBox)
    combo.setCurrentIndex(combo.findData(101))
    changes = QSignalSpy(row.modifiedChanged)
    assert APPLICATION.installTranslator(translator)
    try:
        APPLICATION.sendEvent(row, QEvent(QEvent.Type.LanguageChange))
        assert combo.currentText() == bass and combo.currentData() == 101
        assert combo.itemText(combo.findData(0)) == inherit
        assert row.is_modified() and row.value() == "#!#101#!#"
        assert changes.count() == 0
        track = workspace.tracks[0]
        assert track_column_display_value(track, TrackColumn.EQUALIZER) == acoustic
        assert (
            track_column_display_value(
                replace(track, metadata=TrackMetadata(equalizer="#!#999#!#")),
                TrackColumn.EQUALIZER,
            )
            == unknown
        )
        row.reset()
        assert combo.currentText() == acoustic and not row.is_modified()
    finally:
        APPLICATION.removeTranslator(translator)
        dialog.close()
