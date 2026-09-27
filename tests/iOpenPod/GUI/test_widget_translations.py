"""Translated editor copy preserves user data and changes already in progress."""

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QLocale, Qt, QTranslator
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTableView,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.core.settings.definitions import LOSSY_ENCODER
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.display_text import SourceText
from iOpenPod.app.host_media_library import (
    PlaylistExternalReference,
    _review_reference,  # pyright: ignore[reportPrivateUsage]
)
from iOpenPod.app.library_export import PlaylistFileType
from iOpenPod.app.library_workspace import LibraryWorkspace, TrackUpdate
from iOpenPod.app.metadata_fields import FieldKind, MetadataField
from iOpenPod.app.tag_normalization_controller import TagNormalizationController
from iOpenPod.app.tag_normalizer import TagProfile, TagSuggestion, normalize_tags
from iOpenPod.GUI.dialogs.artwork_editor import ConsolidateArtworkDialog
from iOpenPod.GUI.dialogs.external_playlist_files import ExternalPlaylistFilesDialog
from iOpenPod.GUI.dialogs.metadata_editor import MetadataEditorDialog
from iOpenPod.GUI.dialogs.photo_metadata_editor import PhotoMetadataEditorDialog
from iOpenPod.GUI.dialogs.playlist_editor import PlaylistEditorDialog
from iOpenPod.GUI.dialogs.playlist_export import PlaylistExportDialog
from iOpenPod.GUI.dialogs.tag_normalizer import TagNormalizerDialog
from iOpenPod.GUI.presentation.i18n.text import (
    format_count_text,
    remove_tracks_text,
    tag_changes_available_text,
)
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.metadata_field_editor import FieldEditor
from iOpenPod.GUI.widgets.photo_inspector import (
    _format_bytes,  # pyright: ignore[reportPrivateUsage]
)
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iOpenPod.GUI.widgets.sync_settings import TranscodingSettings
from iPodDB.library import (
    ContentAdvisory,
    LibrarySnapshot,
    MediaType,
    Photo,
    PhotoLibrary,
    Playlist,
    PlaylistKind,
    Track,
    TrackFieldEdit,
)
from storage import HostPath


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
        del disambiguation
        if source_text == "Original date":
            return "Originaldatum" if context == "MetadataFields" else None
        if context == "Counts":
            if source_text == "Remove %n Track(s) from iPod":
                return "%n Titel vom iPod entfernen"
            if source_text == "%n format(s)":
                return "%n Format" if n == 1 else "%n Formate"
            if source_text == "%Ln tag change(s) available":
                return (
                    "%Ln Änderung verfügbar" if n == 1 else "%Ln Änderungen verfügbar"
                )
        if source_text == "Technical details":
            return "Technische Details" if context == "EditorLabels" else None
        if (
            context == "ConsolidateArtworkDialog"
            and source_text == "Used by %n Track(s)"
        ):
            return (
                "%n Titel verwendet dieses Bild"
                if n == 1
                else "%n Titel verwenden dieses Bild"
            )
        if context == "TagNormalizerDialog":
            if source_text == "Apply all %Ln change(s)":
                return "%Ln Änderung anwenden" if n == 1 else "%Ln Änderungen anwenden"
            if (
                source_text
                == "Showing %1 of %Ln change(s). Applying includes all %Ln change(s)."
            ):
                return "%1 von %Ln Änderungen. Alle %Ln werden angewendet."
        return {
            "Title": "Titel",
            "Metadata": "Metadaten",
            "Core Metadata": "Zentrale Metadaten",
            "Titles, artists, albums, genres, and tags": "Titel und weitere Tags",
            "Compilation": "Zusammenstellung",
            "Yes": "Ja",
            "No": "Nein",
            "Explicit": "Explizit",
            "Playlist file type": "Playlist-Dateityp",
            "Copy Tracks": "Titel kopieren",
            "M3U — Extended M3U": "M3U — Erweitertes M3U",
            "Available": "Verfügbar",
            "File": "Datei",
            "Accept All": "Alle zulassen",
            "%1 bytes": "%1 Oktette",
            "EPUB Book": "EPUB-Buch",
            "PDF Book": "PDF-Buch",
            "Edit %1": "%1 bearbeiten",
            "New %1": "Neue %1",
            "Lower values mean higher quality and larger files for LAME MP3.": "MP3-Qualität",
            "Higher values mean higher quality and larger files for this AAC encoder.": "AAC-Qualität",
            "Normalization gain (dB)": "Normalisierungsverstärkung (dB)",
            "Use a finite number.": "Eine endliche Zahl eingeben.",
            "Unavailable or unsafe file: {error}": "Nicht verfügbare Datei: {error}",
            "Album Artist is preserved, but this profile treats Artist as the safer iPod grouping field.": "Album-Interpret bleibt erhalten.",
            "Cover Flow devices are sensitive to Artist+Album differences and same-name albums.": "Cover Flow berücksichtigt Unterschiede bei Interpret und Album.",
            "Edit Track": "Titel bearbeiten",
            "Edit Photo": "Foto bearbeiten",
            "Edit %n Track(s)": "%n Titel bearbeiten",
            "Edit %n Photo(s)": "%n Fotos bearbeiten",
            "%n selected track(s)": "%n ausgewählte Titel",
            "%n selected Photo(s)": "%n ausgewählte Fotos",
        }.get(source_text)


def _language_change(widget: QWidget) -> None:
    APPLICATION.sendEvent(widget, QEvent(QEvent.Type.LanguageChange))


@pytest.mark.parametrize("count", [1, 2])
def test_editor_and_artwork_counts_use_translator_numerus(count: int) -> None:
    ids = tuple(range(1, count + 1))
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(
            tuple(Track(i, "Song", "Artist", "Album", 1000) for i in ids),
            photos=PhotoLibrary(photos=tuple(Photo(i) for i in ids)),
        )
    )
    translator = _Translator()
    assert APPLICATION.installTranslator(translator)
    tracks = MetadataEditorDialog(workspace, ids)
    photos = PhotoMetadataEditorDialog(workspace, ids)
    artwork = ConsolidateArtworkDialog((101,) * count, ())
    try:
        assert tracks.windowTitle() == (
            "Titel bearbeiten" if count == 1 else "2 Titel bearbeiten"
        )
        assert photos.windowTitle() == (
            "Foto bearbeiten" if count == 1 else "2 Fotos bearbeiten"
        )
        if count == 2:
            assert "2 ausgewählte Titel" in {
                label.text() for label in tracks.findChildren(QLabel)
            }
            assert "2 ausgewählte Fotos" in {
                label.text() for label in photos.findChildren(QLabel)
            }
        grid = artwork.findChild(QListWidget, "artworkConsolidationGrid")
        assert grid is not None
        assert (
            grid.item(0)
            .text()
            .endswith(
                "1 Titel verwendet dieses Bild"
                if count == 1
                else "2 Titel verwenden dieses Bild"
            )
        )
    finally:
        APPLICATION.removeTranslator(translator)
        for dialog in (tracks, photos, artwork):
            dialog.close()


@pytest.mark.parametrize("count", [1, 2])
def test_normalizer_apply_and_result_counts_use_numerus(count: int) -> None:
    tracks = tuple(
        Track(i, "Song", "Artist", "Album", 1000) for i in range(1, count + 1)
    )
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot(tracks))
    controller = TagNormalizationController(workspace)
    controller.tracks = tracks
    controller.suggestion = TagSuggestion(
        TagProfile(),
        tuple(
            TrackUpdate(track.track_id, (TrackFieldEdit("title", "New"),))
            for track in tracks
        ),
        (),
    )
    dialog = TagNormalizerDialog(controller)
    translator = _Translator()
    try:
        dialog.show()
        controller.changed.emit()
        apply = dialog.findChild(QPushButton, "applyNormalization")
        assert apply is not None
        assert apply.text() == f"Apply all {count} change{'s' if count != 1 else ''}"
        assert APPLICATION.installTranslator(translator)
        controller.changed.emit()
        assert apply.text() == (
            "1 Änderung anwenden" if count == 1 else "2 Änderungen anwenden"
        )
        assert f"{count} von {count} Änderungen. Alle {count} werden angewendet." in {
            label.text() for label in dialog.findChildren(QLabel)
        }
    finally:
        APPLICATION.removeTranslator(translator)
        dialog.close()
        controller.shutdown()


def test_normalizer_profile_warnings_retain_and_translate_their_source_copy() -> None:
    tracks = (Track(1, "Song", "Artist", "Album", 1000),)
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot(tracks))
    controller = TagNormalizationController(workspace)
    controller.tracks = tracks
    controller.suggestion = normalize_tags(tracks, TagProfile(has_cover_flow=True))
    assert all(
        isinstance(warning, SourceText) for warning in controller.suggestion.warnings
    )
    translator = _Translator()
    assert APPLICATION.installTranslator(translator)
    dialog = TagNormalizerDialog(controller)
    try:
        dialog.show()
        controller.changed.emit()
        warning = dialog.findChild(QLabel, "normalizationWarnings")
        assert warning is not None
        assert warning.text() == (
            "Album-Interpret bleibt erhalten.\n"
            "Cover Flow berücksichtigt Unterschiede bei Interpret und Album."
        )
    finally:
        APPLICATION.removeTranslator(translator)
        dialog.close()
        controller.shutdown()


@pytest.mark.parametrize("count", [1, 2])
def test_complete_count_phrases_have_readable_english_and_translated_plural_forms(
    count: int,
) -> None:
    assert (
        remove_tracks_text(count)
        == f"Remove {count} Track{'s' if count != 1 else ''} from iPod"
    )
    assert format_count_text(count) == f"{count} format{'s' if count != 1 else ''}"
    assert (
        tag_changes_available_text(count)
        == f"{count} tag change{'s' if count != 1 else ''} available"
    )
    sidebar = Sidebar()
    sidebar.set_normalization_count(count)
    translator = _Translator()
    assert APPLICATION.installTranslator(translator)
    try:
        _language_change(sidebar)
        assert remove_tracks_text(count) == f"{count} Titel vom iPod entfernen"
        assert format_count_text(count) == ("1 Format" if count == 1 else "2 Formate")
        expected = "1 Änderung verfügbar" if count == 1 else "2 Änderungen verfügbar"
        button = sidebar.findChild(QPushButton, "normalizationNavigation")
        assert button is not None and button.toolTip() == expected
        assert expected in button.accessibleName()
    finally:
        APPLICATION.removeTranslator(translator)
        sidebar.close()


def test_field_choices_retranslate_without_marking_or_resetting_edits() -> None:
    parent = QWidget()
    field = FieldEditor(
        MetadataField(
            "metadata.compilation", "Compilation", "Options", FieldKind.BOOLEAN
        ),
        False,
        False,
        parent,
    )
    advisory = FieldEditor(
        MetadataField(
            "metadata.content_advisory",
            "Content advisory",
            "Options",
            FieldKind.ADVISORY,
        ),
        ContentAdvisory.EXPLICIT,
        False,
        parent,
    )
    assert isinstance(field.editor, AppComboBox)
    field.editor.setCurrentIndex(field.editor.findData(True))
    changes = QSignalSpy(field.modifiedChanged)
    translator = _Translator()
    assert APPLICATION.installTranslator(translator)
    try:
        _language_change(field)
        _language_change(advisory)
        label = field.findChild(QLabel, "metadataFieldLabel")
        assert label is not None and label.text() == "Zusammenstellung"
        assert field.editor.currentText() == "Ja"
        assert field.value() is True and field.is_modified()
        assert changes.count() == 0
        assert isinstance(advisory.editor, AppComboBox)
        assert advisory.editor.currentText() == "Explizit"
        assert advisory.value() is ContentAdvisory.EXPLICIT
        assert not advisory.is_modified()
    finally:
        APPLICATION.removeTranslator(translator)
        parent.close()


def test_metadata_groups_and_filter_use_translations_and_preserve_track_edits() -> None:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot((Track(1, "Original", "Artist", "Album", 1000),)))
    dialog = MetadataEditorDialog(workspace, (1,))
    title = dialog.rows["title"]
    assert isinstance(title.editor, QLineEdit)
    title.editor.setText("My uncommitted title")
    translator = _Translator()
    assert APPLICATION.installTranslator(translator)
    try:
        _language_change(dialog)
        _language_change(title)
        navigation = dialog.findChild(QListWidget, "metadataSectionNav")
        assert navigation is not None and navigation.item(0).text() == "Metadaten"
        labels = {label.text() for label in dialog.findChildren(QLabel)}
        assert {"Zentrale Metadaten", "Titel und weitere Tags", "Titel"} <= labels
        assert "Technische Details" in {
            label.text() for label in dialog.findChildren(QLabel, "metadataGroupTitle")
        }
        search = dialog.findChild(QLineEdit, "metadataFieldSearch")
        assert search is not None
        search.setText("Titel")
        assert not title.isHidden()
        assert title.value() == "My uncommitted title"
        assert title.is_modified()
        retained = workspace.track(1)
        assert retained is not None and retained.title == "Original"
    finally:
        APPLICATION.removeTranslator(translator)
        dialog.close()


def test_playlist_export_retranslates_form_accessibility_and_retains_format() -> None:
    dialog = PlaylistExportDialog(2)
    dialog.file_type.setCurrentIndex(
        dialog.file_type.findData(PlaylistFileType.M3U.value)
    )
    changes = QSignalSpy(dialog.file_type.currentIndexChanged)
    translator = _Translator()
    assert APPLICATION.installTranslator(translator)
    try:
        _language_change(dialog)
        assert dialog.selected_file_type is PlaylistFileType.M3U
        assert dialog.file_type.currentText() == "M3U — Erweitertes M3U"
        assert dialog.file_type.accessibleName() == "Playlist-Dateityp"
        assert dialog.copy_tracks.accessibleName() == "Titel kopieren"
        assert "Playlist-Dateityp" in {
            label.text() for label in dialog.findChildren(QLabel)
        }
        assert changes.count() == 0
    finally:
        APPLICATION.removeTranslator(translator)
        dialog.close()


def test_external_playlist_review_retranslates_without_losing_scan_approval(
    tmp_path: Path,
) -> None:
    reference = PlaylistExternalReference(
        HostPath(tmp_path / "Track.mp3"), (HostPath(tmp_path / "Mix.m3u8"),), True
    )
    dialog = ExternalPlaylistFilesDialog((reference,))
    table = dialog.findChild(QTableView, "externalPlaylistFilesTable")
    assert table is not None
    model = table.model()
    assert model.setData(
        model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
    )
    headers = QSignalSpy(model.headerDataChanged)
    translator = _Translator()
    assert APPLICATION.installTranslator(translator)
    try:
        _language_change(dialog)
        assert dialog.accepted_paths == frozenset((reference.target,))
        assert model.headerData(1, Qt.Orientation.Horizontal) == "Datei"
        assert model.data(model.index(0, 3)) == "Verfügbar"
        assert headers.count() >= 1
    finally:
        APPLICATION.removeTranslator(translator)
        dialog.close()


def test_photo_byte_unit_translates_without_truncating_large_sizes() -> None:
    translator = _Translator()
    assert APPLICATION.installTranslator(translator)
    try:
        size = 2**32
        assert _format_bytes(size) == f"{QLocale().toString(size)} Oktette"
    finally:
        APPLICATION.removeTranslator(translator)


@pytest.mark.parametrize(
    "kind,label", [(MediaType.EPUB_BOOK, "EPUB-Buch"), (MediaType.PDF_BOOK, "PDF-Buch")]
)
def test_retained_book_classifications_translate_without_enabling_conversion(
    kind: MediaType, label: str
) -> None:
    parent = QWidget()
    translator = _Translator()
    assert APPLICATION.installTranslator(translator)
    try:
        field = FieldEditor(
            MetadataField("media_types", "Media type", "Options", FieldKind.MEDIA_TYPE),
            (kind,),
            False,
            parent,
        )
        assert isinstance(field.editor, AppComboBox)
        assert label in field.editor.currentText()
        assert not field.editor.isEnabled()
        assert field.initial == (kind,)
        assert not field.is_modified()
    finally:
        APPLICATION.removeTranslator(translator)
        parent.close()


def test_new_and_existing_playlist_titles_are_independently_translatable() -> None:
    translator = _Translator()
    assert APPLICATION.installTranslator(translator)
    dialogs: list[PlaylistEditorDialog] = []
    try:
        create = PlaylistEditorDialog(PlaylistKind.PLAYLIST)
        dialogs.append(create)
        edit = PlaylistEditorDialog(PlaylistKind.PLAYLIST, Playlist(1, "My playlist"))
        dialogs.append(edit)
        assert create.windowTitle() == "Neue Playlist"
        assert edit.windowTitle() == "Playlist bearbeiten"
        assert edit.name.text() == "My playlist"
    finally:
        APPLICATION.removeTranslator(translator)
        for dialog in dialogs:
            dialog.close()


def test_encoder_specific_quality_descriptions_translate_independently() -> None:
    translator = _Translator()
    assert APPLICATION.installTranslator(translator)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    parent = QWidget()
    try:
        widget = TranscodingSettings(settings, parent)
        settings.set_global(LOSSY_ENCODER, "libmp3lame")
        assert "MP3-Qualität" in {label.text() for label in widget.findChildren(QLabel)}
        settings.set_global(LOSSY_ENCODER, "aac")
        assert "AAC-Qualität" in {label.text() for label in widget.findChildren(QLabel)}
    finally:
        APPLICATION.removeTranslator(translator)
        parent.close()


def test_metadata_validation_translates_both_field_name_and_guidance() -> None:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot((Track(1, "Original", "Artist", "Album", 1000),)))
    translator = _Translator()
    assert APPLICATION.installTranslator(translator)
    dialog = MetadataEditorDialog(workspace, (1,))
    try:
        row = dialog.rows["metadata.normalization_gain_db"]
        assert isinstance(row.editor, QLineEdit)
        row.editor.setText("nan")
        dialog.accept()
        error = dialog.findChild(QLabel, "metadataEditError")
        assert error is not None
        assert (
            error.text()
            == "Normalisierungsverstärkung (dB): Eine endliche Zahl eingeben."
        )
        assert not workspace.dirty
    finally:
        APPLICATION.removeTranslator(translator)
        dialog.close()


def test_photo_date_label_uses_shared_metadata_translation_context() -> None:
    parent = QWidget()
    translator = _Translator()
    assert APPLICATION.installTranslator(translator)
    try:
        field = FieldEditor(
            MetadataField("original_date", "Original date", "Dates", FieldKind.DATE),
            0,
            False,
            parent,
        )
        label = field.findChild(QLabel, "metadataFieldLabel")
        assert label is not None and label.text() == "Originaldatum"
    finally:
        APPLICATION.removeTranslator(translator)
        parent.close()


def test_missing_external_file_retains_translatable_guidance_and_native_error(
    tmp_path: Path,
) -> None:
    reference = _review_reference(
        HostPath(tmp_path / "Missing.mp3"), (HostPath(tmp_path / "Mix.m3u8"),)
    )
    assert isinstance(reference.detail, SourceText)
    assert reference.detail.source == "Unavailable or unsafe file: {error}"
    native_error = dict(reference.detail.parameters)["error"]
    assert native_error
    translator = _Translator()
    assert APPLICATION.installTranslator(translator)
    dialog = ExternalPlaylistFilesDialog((reference,))
    try:
        table = dialog.findChild(QTableView, "externalPlaylistFilesTable")
        assert table is not None
        model = table.model()
        assert (
            model.data(model.index(0, 3)) == f"Nicht verfügbare Datei: {native_error}"
        )
        assert not model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsEnabled
    finally:
        APPLICATION.removeTranslator(translator)
        dialog.close()
