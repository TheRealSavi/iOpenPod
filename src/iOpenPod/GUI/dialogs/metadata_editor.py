"""Original-inspired Track metadata editing with atomic draft apply."""

from __future__ import annotations

from dataclasses import fields, replace
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel
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
from iOpenPod.app.metadata_fields import (
    FieldKind,
    MetadataField,
    field_value,
    metadata_fields,
)
from iOpenPod.app.track_conversion import media_type_choices
from iOpenPod.app.track_playback_policy import requires_track_playback_policy
from iOpenPod.GUI.dialogs.artwork_editor import ArtworkEditor
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.metadata_field_editor import FieldEditor
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
)
from iPodDB.library import MediaType, TrackFieldEdit

if TYPE_CHECKING:
    from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider

_GROUP_DESCRIPTIONS = {
    "Metadata": "Titles, artists, albums, genres, and tags",
    "Sorting": "Sort overrides used by the iPod Library",
    "Playback": "Rating, counts, timing, and playback position",
    "Options": "Media type, advisory, shuffle, resume, and gapless settings",
    "Video": "Show, episode, and TV metadata",
    "Podcast": "Podcast feeds, categories, and playback markers",
    "Dates": "Added, modified, released, played, and skipped timestamps",
    "Chapters": "Chapter markers stored in the iPod database",
    "Store": "Store and purchase metadata preserved from the database",
    "Artwork": "Choose, crop, replace, or clear the Track cover image",
    "Technical details": "Read-only values retained with the selected Track data",
}

_SUBGROUPS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "Metadata": (
        (
            "Core Metadata",
            ("title", "artist", "album", "album_artist", "genre", "metadata.composer"),
        ),
        (
            "Track & Disc",
            (
                "year",
                "track_number",
                "metadata.total_tracks",
                "metadata.disc_number",
                "metadata.total_discs",
            ),
        ),
        ("Tags", ("metadata.grouping", "metadata.bpm")),
        ("Notes & Lyrics", ("metadata.comment", "metadata.lyrics")),
    ),
    "Sorting": (("Sort Overrides", ()),),
    "Playback": (
        (
            "Rating & Counts",
            (
                "rating",
                "play_count",
                "metadata.skip_count",
                "metadata.unscrobbled_play_count",
            ),
        ),
        ("Timing", ("metadata.start_time_ms", "metadata.stop_time_ms")),
        ("Resume Position", ("metadata.bookmark_time_ms",)),
        (
            "Volume & Sound Check",
            ("metadata.volume_adjustment_percent", "metadata.normalization_gain_db"),
        ),
        ("Equalizer", ("metadata.equalizer",)),
    ),
    "Options": (
        ("Media Type", ("media_types",)),
        (
            "Advisory & Library",
            ("metadata.compilation", "metadata.checked", "metadata.content_advisory"),
        ),
        (
            "Playback Flags",
            ("metadata.skip_shuffle", "metadata.remember_position"),
        ),
        ("Gapless", ("metadata.gapless_album",)),
    ),
    "Video": (
        (
            "Show Details",
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
        ("Descriptions", ("metadata.subtitle", "metadata.description")),
    ),
    "Podcast": (
        (
            "Feed",
            ("metadata.podcast_enclosure_url", "metadata.podcast_rss_url"),
        ),
        ("Category & Display", ("metadata.category", "metadata.podcast")),
        ("Playback", ("metadata.played",)),
    ),
    "Dates": (("Dates", ()),),
    "Chapters": (("Chapter Timeline", ()),),
    "Store": (("Store", ()),),
}


class MetadataEditorDialog(QDialog):
    def __init__(
        self,
        workspace: LibraryWorkspace,
        track_ids: tuple[int, ...],
        parent: QWidget | None = None,
        *,
        artwork_provider: ArtworkPixmapProvider | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("metadataEditor")
        self._workspace = workspace
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
            else self.tr("Edit %1 Tracks").replace("%1", str(count))
        )
        self.resize(980, 740)
        self.setMinimumSize(860, 660)
        self.rows: dict[str, FieldEditor] = {}
        self._group_rows: dict[str, list[FieldEditor]] = {}
        self._group_items: dict[str, QListWidgetItem] = {}
        self._page_indices: dict[str, int] = {}
        self._section_rows: list[tuple[QFrame, list[FieldEditor]]] = []
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
        heading.setObjectName("metadataEditorTitle")
        title_wrap.addWidget(heading)
        subtitle = QLabel(self._selection_summary(), header)
        subtitle.setObjectName("metadataEditorSubtitle")
        title_wrap.addWidget(subtitle)
        header_layout.addLayout(title_wrap, 1)
        search = QLineEdit(self)
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
        self._change_label = QLabel(self.tr("No changes"), self)
        self._change_label.setObjectName("metadataChangeSummary")
        footer.addWidget(self._change_label)
        self._reset_button = ActionButton(self.tr("Reset Changes"), self)
        self._reset_button.setObjectName("resetMetadataChanges")
        self._reset_button.setEnabled(False)
        self._reset_button.clicked.connect(self._reset)
        footer.addWidget(self._reset_button)
        footer.addStretch(1)
        cancel = ActionButton(self.tr("Cancel"), self)
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        apply_button = ActionButton(
            self.tr("Apply"), self, kind=ActionButtonKind.PRIMARY
        )
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
            body_layout.addWidget(self._section_panel(self.tr("Other"), remaining))
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
        item = QListWidgetItem(group)
        item.setData(Qt.ItemDataRole.UserRole, group)
        self._nav.addItem(item)
        self._group_items[group] = item

    def _page_header(self, group: str) -> QFrame:
        header = QFrame(self)
        header.setObjectName("metadataPageHeader")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(3)
        title = QLabel(group, header)
        title.setObjectName("metadataGroupTitle")
        layout.addWidget(title)
        description = QLabel(_GROUP_DESCRIPTIONS.get(group, ""), header)
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
        heading = QLabel(title, panel)
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
        layout.addWidget(self._page_header(self.tr("Technical details")))
        technical = QTreeWidget(page)
        technical.setObjectName("metadataTechnicalDetails")
        technical.setHeaderLabels([self.tr("Read-only field"), self.tr("Value")])
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
                    else self.tr("Mixed values")
                )
                technical.addTopLevelItem(QTreeWidgetItem([path, text]))
        technical.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(technical, 1)
        self._pages.addWidget(page)
        self._technical_item = QListWidgetItem(self.tr("Technical details"))
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
        body_layout.addWidget(self._page_header(self.tr("Artwork")))

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
            return self.tr("%1 selected tracks").replace("%1", str(len(self._tracks)))
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
            summary = self.tr("No changes")
        elif count == 0:
            summary = self.tr("Artwork changed")
        elif artwork_changed:
            summary = (
                self.tr("1 changed field + artwork")
                if count == 1
                else self.tr("%1 changed fields + artwork").replace("%1", str(count))
            )
        else:
            summary = (
                self.tr("1 changed field")
                if count == 1
                else self.tr("%1 changed fields").replace("%1", str(count))
            )
        self._change_label.setText(summary)
        self._reset_button.setEnabled(count > 0 or artwork_changed)

    def _filter(self, query: str) -> None:
        query = query.casefold().strip()
        visible_groups: set[str] = set()
        for row in self.rows.values():
            visible = (
                query in f"{row.spec.label} {row.spec.path} {row.spec.group}".casefold()
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
                            raise ValueError("Choose a media type.")
                        media_type = value
                    else:
                        edits.append(TrackFieldEdit(row.spec.path, value))
                except (ValueError, OverflowError, OSError) as error:
                    errors.append(f"{row.spec.label}: {error}")
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
            self._error.setText(str(error))
            return
        super().accept()

    def done(self, result: int) -> None:
        self._artwork_editor.shutdown()
        super().done(result)
