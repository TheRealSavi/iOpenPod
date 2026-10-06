"""Original-inspired Track metadata editing with atomic draft apply."""

from __future__ import annotations

from dataclasses import fields, replace
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QT_TRANSLATE_NOOP,
    QCoreApplication,
    QEvent,
    Qt,
    QThreadPool,
    Slot,
)
from PySide6.QtGui import QShowEvent, QStandardItemModel
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.library_workspace import LibraryWorkspace, TrackUpdate
from iOpenPod.app.lyrics_work import LyricsReadWork
from iOpenPod.app.metadata_fields import (
    FieldKind,
    MetadataField,
    field_value,
    metadata_fields,
)
from iOpenPod.app.track_conversion import media_type_choices
from iOpenPod.app.track_playback_policy import requires_track_playback_policy
from iOpenPod.GUI.dialogs.artwork_editor import ArtworkEditor
from iOpenPod.GUI.presentation.i18n.text import (
    changed_field_count_text,
    english_count_fallback,
)
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.metadata_field_editor import FieldEditor
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
)
from iPodDB.library import MediaType, TrackFieldEdit

if TYPE_CHECKING:
    from iOpenPod.app.playback.backend import PlaybackSourceProvider
    from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider

_GROUP_DESCRIPTIONS = {
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Metadata")): str(
        QT_TRANSLATE_NOOP(
            "MetadataEditorDialog", "Titles, artists, albums, genres, and tags"
        )
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Sorting")): str(
        QT_TRANSLATE_NOOP(
            "MetadataEditorDialog", "Sort overrides used by the iPod Library"
        )
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Playback")): str(
        QT_TRANSLATE_NOOP(
            "MetadataEditorDialog", "Rating, counts, timing, and playback position"
        )
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Options")): str(
        QT_TRANSLATE_NOOP(
            "MetadataEditorDialog",
            "Media type, advisory, shuffle, resume, and gapless settings",
        )
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Video")): str(
        QT_TRANSLATE_NOOP("MetadataEditorDialog", "Show, episode, and TV metadata")
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Podcast")): str(
        QT_TRANSLATE_NOOP(
            "MetadataEditorDialog", "Podcast feeds, categories, and playback markers"
        )
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Dates")): str(
        QT_TRANSLATE_NOOP(
            "MetadataEditorDialog",
            "Added, modified, released, played, and skipped timestamps",
        )
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Chapters")): str(
        QT_TRANSLATE_NOOP(
            "MetadataEditorDialog", "Chapter markers stored in the iPod database"
        )
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Store")): str(
        QT_TRANSLATE_NOOP(
            "MetadataEditorDialog",
            "Store and purchase metadata preserved from the database",
        )
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Artwork")): str(
        QT_TRANSLATE_NOOP(
            "MetadataEditorDialog",
            "Choose, crop, replace, or clear the Track cover image",
        )
    ),
    str(QT_TRANSLATE_NOOP("EditorLabels", "Technical details")): str(
        QT_TRANSLATE_NOOP(
            "MetadataEditorDialog",
            "Read-only values retained with the selected Track data",
        )
    ),
}

_SUBGROUPS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Metadata")): (
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Core Metadata")),
            ("title", "artist", "album", "album_artist", "genre", "metadata.composer"),
        ),
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Track & Disc")),
            (
                "year",
                "track_number",
                "metadata.total_tracks",
                "metadata.disc_number",
                "metadata.total_discs",
            ),
        ),
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Tags")),
            ("metadata.grouping", "metadata.bpm"),
        ),
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Notes & Lyrics")),
            ("metadata.comment", "metadata.lyrics"),
        ),
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Sorting")): (
        (str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Sort Overrides")), ()),
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Playback")): (
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Rating & Counts")),
            (
                "rating",
                "play_count",
                "metadata.skip_count",
                "metadata.unscrobbled_play_count",
            ),
        ),
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Timing")),
            ("metadata.start_time_ms", "metadata.stop_time_ms"),
        ),
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Resume Position")),
            ("metadata.bookmark_time_ms",),
        ),
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Volume & Sound Check")),
            ("metadata.volume_adjustment_percent", "metadata.normalization_gain_db"),
        ),
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Equalizer")),
            ("metadata.equalizer",),
        ),
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Options")): (
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Media Type")),
            ("media_types",),
        ),
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Advisory & Library")),
            ("metadata.compilation", "metadata.checked", "metadata.content_advisory"),
        ),
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Playback Flags")),
            ("metadata.skip_shuffle", "metadata.remember_position"),
        ),
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Gapless")),
            ("metadata.gapless_album",),
        ),
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Video")): (
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Show Details")),
            (
                "show",
                "episode",
                "season_number",
                "episode_number",
                "metadata.tv_network",
                "metadata.track_keywords",
                "metadata.show_locale",
            ),
        ),
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Descriptions")),
            ("metadata.subtitle", "metadata.description"),
        ),
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Podcast")): (
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Feed")),
            ("metadata.podcast_enclosure_url", "metadata.podcast_rss_url"),
        ),
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Category & Display")),
            ("metadata.category", "metadata.podcast"),
        ),
        (
            str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Playback")),
            ("metadata.played",),
        ),
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Dates")): (
        (str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Dates")), ()),
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Chapters")): (
        (str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Chapter Timeline")), ()),
    ),
    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Store")): (
        (str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Store")), ()),
    ),
}


class MetadataEditorDialog(QDialog):
    def __init__(
        self,
        workspace: LibraryWorkspace,
        track_ids: tuple[int, ...],
        parent: QWidget | None = None,
        *,
        artwork_provider: ArtworkPixmapProvider | None = None,
        lyrics_provider: PlaybackSourceProvider | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("metadataEditor")
        self._workspace = workspace
        self._lyrics_provider = lyrics_provider
        self._lyrics_work: LyricsReadWork | None = None
        self._lyrics_requested = False
        self._revision = workspace.edit_revision
        self._tracks = tuple(
            t for i in dict.fromkeys(track_ids) if (t := workspace.track(i)) is not None
        )
        if not self._tracks or len(self._tracks) != len(set(track_ids)):
            raise ValueError("Select tracks from the current Library.")
        count = len(self._tracks)
        self.setWindowTitle(
            self.tr("Edit Track")
            if count == 1
            else english_count_fallback(
                "Edit %n Track(s)", self.tr("Edit %n Track(s)", "", count), count
            )
        )
        self.resize(980, 740)
        self.setMinimumSize(860, 660)
        self.rows: dict[str, FieldEditor] = {}
        self._group_rows: dict[str, list[FieldEditor]] = {}
        self._group_items: dict[str, QListWidgetItem] = {}
        self._page_indices: dict[str, int] = {}
        self._section_rows: list[tuple[QFrame, list[FieldEditor]]] = []
        self._translated_labels: list[tuple[QLabel, str]] = []
        self._technical_mixed_items: list[QTreeWidgetItem] = []
        self._updating_playback_policy = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        header = QFrame(self)
        header.setObjectName("metadataEditorHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(12)
        title_wrap = QVBoxLayout()
        title_wrap.setContentsMargins(0, 0, 0, 0)
        title_wrap.setSpacing(3)
        heading = QLabel(self.windowTitle(), header)
        self._heading = heading
        heading.setObjectName("metadataEditorTitle")
        title_wrap.addWidget(heading)
        subtitle = QLabel(self._selection_summary(), header)
        self._subtitle = subtitle
        subtitle.setObjectName("metadataEditorSubtitle")
        title_wrap.addWidget(subtitle)
        header_layout.addLayout(title_wrap, 1)
        search = QLineEdit(self)
        self._search = search
        search.setObjectName("metadataFieldSearch")
        search.setPlaceholderText(self.tr("Filter fields"))
        search.setClearButtonEnabled(True)
        search.setFixedWidth(260)
        header_layout.addWidget(search, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addWidget(header)

        self._nav = QListWidget(self)
        self._nav.setObjectName("metadataSectionNav")
        self._nav.setFixedWidth(178)
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._nav.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._nav.setSpacing(0)
        self._pages = QStackedWidget(self)
        self._pages.setObjectName("metadataEditorPages")
        grouped: dict[str, list[MetadataField]] = {}
        for spec in metadata_fields():
            grouped.setdefault(spec.group, []).append(spec)
        for group, specs in grouped.items():
            self._add_group_page(group, specs)
        self._add_artwork_page(artwork_provider)
        self._add_technical_page()

        self._nav.currentRowChanged.connect(self._pages.setCurrentIndex)
        self._nav.setCurrentRow(0)
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        content_layout.addWidget(self._nav)
        content_layout.addWidget(self._pages, 1)
        outer.addLayout(content_layout, 1)
        search.textChanged.connect(self._filter)

        self._error = QLabel(self)
        self._error.setObjectName("metadataEditError")
        self._error.setTextFormat(Qt.TextFormat.PlainText)
        self._error.setWordWrap(True)
        outer.addWidget(self._error)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        self._change_label = QLabel(
            QCoreApplication.translate("EditorLabels", "No changes"), self
        )
        self._change_label.setObjectName("metadataChangeSummary")
        footer.addWidget(self._change_label)
        self._reset_button = ActionButton(
            QCoreApplication.translate("CommonActions", "Reset Changes"), self
        )
        self._reset_button.setObjectName("resetMetadataChanges")
        self._reset_button.setEnabled(False)
        self._reset_button.clicked.connect(self._reset)
        footer.addWidget(self._reset_button)
        footer.addStretch(1)
        cancel = ActionButton(
            QCoreApplication.translate("CommonActions", "Cancel"), self
        )
        self._cancel_button = cancel
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        apply_button = ActionButton(
            QCoreApplication.translate("CommonActions", "Apply"),
            self,
            kind=ActionButtonKind.PRIMARY,
        )
        self._apply_button = apply_button
        apply_button.setObjectName("applyMetadataChanges")
        apply_button.setDefault(True)
        apply_button.clicked.connect(self.accept)
        footer.addWidget(apply_button)
        outer.addLayout(footer)
        for path in ("metadata.skip_shuffle", "metadata.remember_position"):
            editor = self.rows[path].editor
            if isinstance(editor, AppComboBox):
                editor.currentIndexChanged.connect(self._update_playback_flag_policy)
        for path in ("media_types", "metadata.podcast"):
            editor = self.rows[path].editor
            if isinstance(editor, AppComboBox):
                editor.currentIndexChanged.connect(self._classification_changed)
        self._update_playback_flag_policy()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._load_lyrics_if_needed()

    def _load_lyrics_if_needed(self) -> None:
        if self._lyrics_requested or self._lyrics_provider is None:
            return
        self._lyrics_requested = True
        if len(self._tracks) != 1:
            return
        track = self._tracks[0]
        snapshot = self._workspace.snapshot
        original = (
            next(
                (item for item in snapshot.tracks if item.track_id == track.track_id),
                None,
            )
            if snapshot is not None
            else None
        )
        if original is not None and (
            original.metadata.lyrics != track.metadata.lyrics
            or (original.metadata.has_lyrics and not track.metadata.has_lyrics)
        ):
            return
        work = LyricsReadWork(0, self._lyrics_provider, track)
        work.signals.finished.connect(self._lyrics_loaded)
        self._lyrics_work = work
        QThreadPool.globalInstance().start(work)

    @Slot(int, str, bool)
    def _lyrics_loaded(self, token: int, text: str, succeeded: bool) -> None:
        work = self._lyrics_work
        self._lyrics_work = None
        if (
            work is None
            or token != work.token
            or not succeeded
            or not text
            or self._workspace.edit_revision != self._revision
            or self._workspace.track(work.track.track_id) != work.track
        ):
            return
        self.rows["metadata.lyrics"].adopt_loaded_text(text)

    def retranslate_ui(self) -> None:
        count = len(self._tracks)
        self.setWindowTitle(
            self.tr("Edit Track")
            if count == 1
            else english_count_fallback(
                "Edit %n Track(s)", self.tr("Edit %n Track(s)", "", count), count
            )
        )
        self._heading.setText(self.windowTitle())
        self._subtitle.setText(self._selection_summary())
        self._search.setPlaceholderText(self.tr("Filter fields"))
        for label, source in self._translated_labels:
            label.setText(self._label_text(source))
        for group, item in self._group_items.items():
            item.setText(self.tr(group))
        self._artwork_item.setText(self.tr("Artwork"))
        self._technical_item.setText(
            QCoreApplication.translate("EditorLabels", "Technical details")
        )
        self._technical.setHeaderLabels(
            [
                QCoreApplication.translate("EditorLabels", "Read-only field"),
                self.tr("Value"),
            ]
        )
        for technical_item in self._technical_mixed_items:
            technical_item.setText(
                1, QCoreApplication.translate("EditorLabels", "Mixed values")
            )
        self._reset_button.setText(
            QCoreApplication.translate("CommonActions", "Reset Changes")
        )
        self._cancel_button.setText(
            QCoreApplication.translate("CommonActions", "Cancel")
        )
        self._apply_button.setText(QCoreApplication.translate("CommonActions", "Apply"))
        self._update_change_summary()
        self._update_playback_flag_policy()
        self._filter(self._search.text())

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _classification_changed(self, _index: int) -> None:
        self._update_playback_flag_policy(
            stage=any(
                self.rows[path].is_modified()
                for path in ("media_types", "metadata.podcast")
            )
        )

    def _update_playback_flag_policy(
        self, _index: int | None = None, *, stage: bool = False
    ) -> None:
        if self._updating_playback_policy:
            return
        media_editor = self.rows["media_types"].editor
        podcast_editor = self.rows["metadata.podcast"].editor
        if not isinstance(media_editor, AppComboBox) or not isinstance(
            podcast_editor, AppComboBox
        ):
            return
        media_type = media_editor.currentData()
        podcast = podcast_editor.currentData()
        required = all(
            requires_track_playback_policy(
                replace(
                    track,
                    media_types=(MediaType(media_type),)
                    if isinstance(media_type, str)
                    else track.media_types,
                    metadata=replace(
                        track.metadata,
                        podcast=podcast
                        if isinstance(podcast, bool)
                        else track.metadata.podcast,
                    ),
                )
            )
            for track in self._tracks
        )
        self._updating_playback_policy = True
        try:
            for path in ("metadata.skip_shuffle", "metadata.remember_position"):
                editor = self.rows[path].editor
                if not isinstance(editor, AppComboBox):
                    continue
                if stage and required:
                    editor.setCurrentIndex(editor.findData(True))
                choices = editor.model()
                if isinstance(choices, QStandardItemModel):
                    no = choices.item(editor.findData(False))
                    no.setEnabled(not required)
                editor.setEnabled(not required or editor.currentData() is not True)
                editor.setToolTip(
                    self.tr(
                        "Podcasts and videos keep their place and are skipped "
                        "when shuffling."
                    )
                    if required
                    else ""
                )
        finally:
            self._updating_playback_policy = False

    def _add_group_page(self, group: str, specs: list[MetadataField]) -> None:
        page = QWidget(self)
        page.setObjectName("metadataEditorPage")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        body = QWidget(page)
        body.setObjectName("metadataPageBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)
        body_layout.addWidget(self._page_header(group))

        rows_by_path: dict[str, FieldEditor] = {}
        for spec in specs:
            values = tuple(field_value(t, spec.path) for t in self._tracks)
            choices = (
                tuple(
                    choice
                    for choice in media_type_choices(self._tracks[0])
                    if all(
                        choice in media_type_choices(track)
                        for track in self._tracks[1:]
                    )
                )
                if spec.kind is FieldKind.MEDIA_TYPE
                else ()
            )
            row = FieldEditor(
                spec,
                values[0],
                any(value != values[0] for value in values[1:]),
                body,
                media_type_choices=choices,
            )
            row.modifiedChanged.connect(self._update_change_summary)
            self.rows[spec.path] = row
            rows_by_path[spec.path] = row

        page_rows: list[FieldEditor] = []
        assigned: set[str] = set()
        subgroup_specs = _SUBGROUPS.get(group, ((group, ()),))
        for title, paths in subgroup_specs:
            subgroup_rows = [
                rows_by_path[path]
                for path in paths
                if path in rows_by_path and path not in assigned
            ]
            if not paths:
                subgroup_rows = [
                    rows_by_path[spec.path]
                    for spec in specs
                    if spec.path not in assigned
                ]
            if not subgroup_rows:
                continue
            assigned.update(row.spec.path for row in subgroup_rows)
            page_rows.extend(subgroup_rows)
            body_layout.addWidget(self._section_panel(title, subgroup_rows))

        remaining = [
            rows_by_path[spec.path] for spec in specs if spec.path not in assigned
        ]
        if remaining:
            page_rows.extend(remaining)
            body_layout.addWidget(
                self._section_panel(
                    str(QT_TRANSLATE_NOOP("MetadataEditorDialog", "Other")), remaining
                )
            )
        body_layout.addStretch(1)

        scroll = QScrollArea(page)
        scroll.setObjectName("metadataPageScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        page_layout.addWidget(scroll)
        index = self._pages.addWidget(page)
        self._page_indices[group] = index
        self._group_rows[group] = page_rows
        item = QListWidgetItem(self.tr(group))
        item.setData(Qt.ItemDataRole.UserRole, group)
        self._nav.addItem(item)
        self._group_items[group] = item

    def _label_text(self, source: str) -> str:
        if source == "Technical details":
            return QCoreApplication.translate("EditorLabels", "Technical details")
        return self.tr(source)

    def _page_header(self, group: str) -> QFrame:
        header = QFrame(self)
        header.setObjectName("metadataPageHeader")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(3)
        title = QLabel(self._label_text(group), header)
        self._translated_labels.append((title, group))
        title.setObjectName("metadataGroupTitle")
        layout.addWidget(title)
        description = QLabel(self.tr(_GROUP_DESCRIPTIONS.get(group, "")), header)
        self._translated_labels.append(
            (description, _GROUP_DESCRIPTIONS.get(group, ""))
        )
        description.setObjectName("metadataGroupDescription")
        description.setWordWrap(True)
        layout.addWidget(description)
        return header

    def _section_panel(self, title: str, rows: list[FieldEditor]) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("metadataSectionPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 10, 12, 12)
        panel_layout.setSpacing(10)
        heading = QLabel(self.tr(title), panel)
        self._translated_labels.append((heading, title))
        heading.setObjectName("metadataSectionTitle")
        panel_layout.addWidget(heading)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        position = 0
        for row in rows:
            wide = row.spec.kind in (FieldKind.LONG_TEXT, FieldKind.CHAPTERS)
            if wide and position % 2:
                position += 1
            grid.addWidget(row, position // 2, position % 2, 1, 2 if wide else 1)
            position += 2 if wide else 1
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        panel_layout.addLayout(grid)
        self._section_rows.append((panel, rows))
        return panel

    def _add_technical_page(self) -> None:
        page = QWidget(self)
        page.setObjectName("metadataEditorPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._page_header("Technical details"))
        technical = QTreeWidget(page)
        self._technical = technical
        technical.setObjectName("metadataTechnicalDetails")
        technical.setHeaderLabels(
            [
                QCoreApplication.translate("EditorLabels", "Read-only field"),
                self.tr("Value"),
            ]
        )
        editable = set(self.rows)
        track = self._tracks[0]
        for owner, prefix in (
            (track, ""),
            (track.metadata, "metadata."),
            (track.ipod, "ipod."),
        ):
            if owner is None:
                continue
            for field in fields(owner):
                path = prefix + field.name
                if path in editable or field.name in ("metadata", "ipod"):
                    continue
                technical_values = [
                    getattr(t.ipod, field.name, None)
                    if prefix == "ipod."
                    else getattr(t.metadata, field.name)
                    if prefix
                    else getattr(t, field.name)
                    for t in self._tracks
                ]
                text = (
                    str(technical_values[0])
                    if all(v == technical_values[0] for v in technical_values)
                    else QCoreApplication.translate("EditorLabels", "Mixed values")
                )
                item = QTreeWidgetItem([path, text])
                if any(v != technical_values[0] for v in technical_values):
                    self._technical_mixed_items.append(item)
                technical.addTopLevelItem(item)
        technical.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(technical, 1)
        self._pages.addWidget(page)
        self._technical_item = QListWidgetItem(
            QCoreApplication.translate("EditorLabels", "Technical details")
        )
        self._nav.addItem(self._technical_item)

    def _add_artwork_page(self, provider: ArtworkPixmapProvider | None) -> None:
        page = QWidget(self)
        page.setObjectName("metadataEditorPage")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        body = QWidget(page)
        body.setObjectName("metadataPageBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)
        body_layout.addWidget(self._page_header("Artwork"))

        panel = QFrame(body)
        panel.setObjectName("metadataSectionPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 12, 12, 12)
        self._artwork_editor = ArtworkEditor(
            self._tracks,
            self._workspace.artwork_assets,
            provider,
            panel,
        )
        self._artwork_editor.modifiedChanged.connect(self._update_change_summary)
        panel_layout.addWidget(self._artwork_editor)
        body_layout.addWidget(panel)
        body_layout.addStretch(1)

        scroll = QScrollArea(page)
        scroll.setObjectName("metadataPageScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        page_layout.addWidget(scroll)
        self._pages.addWidget(page)
        self._artwork_item = QListWidgetItem(self.tr("Artwork"))
        self._artwork_item.setData(Qt.ItemDataRole.UserRole, "Artwork")
        self._nav.addItem(self._artwork_item)

    def _selection_summary(self) -> str:
        if len(self._tracks) != 1:
            return english_count_fallback(
                "%n selected track(s)",
                self.tr("%n selected track(s)", "", len(self._tracks)),
                len(self._tracks),
            )
        track = self._tracks[0]
        return " • ".join(
            value
            for value in (track.title or self.tr("Untitled"), track.artist, track.album)
            if value
        )

    def _reset(self) -> None:
        for row in self.rows.values():
            row.reset()
        self._artwork_editor.reset()
        self._error.clear()
        self._update_change_summary()

    def _update_change_summary(self) -> None:
        count = sum(row.is_modified() for row in self.rows.values())
        artwork_changed = self._artwork_editor.is_modified()
        if count == 0 and not artwork_changed:
            summary = QCoreApplication.translate("EditorLabels", "No changes")
        elif count == 0:
            summary = self.tr("Artwork changed")
        else:
            summary = changed_field_count_text(count, artwork=artwork_changed)
        self._change_label.setText(summary)
        self._reset_button.setEnabled(count > 0 or artwork_changed)

    def _filter(self, query: str) -> None:
        query = query.casefold().strip()
        visible_groups: set[str] = set()
        for row in self.rows.values():
            visible = (
                query
                in f"{QCoreApplication.translate('MetadataFields', row.spec.label)} {row.spec.path} {self.tr(row.spec.group)}".casefold()
            )
            row.setVisible(visible)
            if visible:
                visible_groups.add(row.spec.group)
        for panel, rows in self._section_rows:
            panel.setVisible(any(not row.isHidden() for row in rows))
        for group, item in self._group_items.items():
            item.setHidden(bool(query) and group not in visible_groups)
        artwork_visible = (
            not query or query in self.tr("artwork cover image crop").casefold()
        )
        self._artwork_item.setHidden(not artwork_visible)
        self._technical_item.setHidden(bool(query))
        current = self._nav.currentItem()
        if query and current.isHidden():
            first_visible = next(
                (
                    self._group_items[group]
                    for group in self._group_rows
                    if group in visible_groups
                ),
                None,
            )
            if first_visible is None and artwork_visible:
                first_visible = self._artwork_item
            if first_visible is not None:
                self._nav.setCurrentItem(first_visible)

    def accept(self) -> None:
        if self._artwork_editor.busy:
            self._error.setText(
                self.tr("Wait for the selected artwork to finish loading.")
            )
            return
        edits: list[TrackFieldEdit] = []
        media_type: MediaType | None = None
        errors: list[str] = []
        for row in self.rows.values():
            if row.is_modified():
                try:
                    value = row.value()
                    if row.spec.kind is FieldKind.MEDIA_TYPE:
                        if not isinstance(value, MediaType):
                            raise ValueError(self.tr("Choose a media type."))
                        media_type = value
                    else:
                        edits.append(TrackFieldEdit(row.spec.path, value))
                except (ValueError, OverflowError, OSError) as error:
                    label = QCoreApplication.translate("MetadataFields", row.spec.label)
                    errors.append(f"{label}: {workflow_text(str(error))}")
        if errors:
            self._error.setText("\n".join(errors))
            return
        try:
            self._workspace.apply_track_edits(
                tuple(TrackUpdate(t.track_id, tuple(edits)) for t in self._tracks),
                self._revision,
                artwork=self._artwork_editor.edit(),
                media_type=media_type,
            )
        except ValueError as error:
            self._error.setText(workflow_text(str(error)))
            return
        super().accept()

    def done(self, result: int) -> None:
        if self._lyrics_work is not None:
            self._lyrics_work.cancelled.set()
        self._artwork_editor.shutdown()
        super().done(result)
