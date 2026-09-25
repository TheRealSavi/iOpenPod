"""Read-only Photo preview, format selector, and semantic metadata inspector."""

from datetime import UTC, datetime

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.models.photos import FULL_RESOLUTION_REQUEST_ID
from iOpenPod.GUI.presentation.artwork import paint_artwork_placeholder
from iOpenPod.GUI.presentation.photo import paint_photo_pixmap
from iOpenPod.GUI.presentation.photo_provider import (
    PhotoPixmapProvider,
    PhotoPixmapState,
)
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonState
from iPodDB.library import (
    Photo,
    PhotoLibrary,
    PhotoRepresentation,
    PhotoRepresentationKind,
)


class _PhotoPreview(QWidget):
    """Paint only the currently selected Photo format, preserving aspect ratio."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        photo_provider: PhotoPixmapProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("photoInspectorPreview")
        self.setMinimumHeight(LAYOUT.photo_inspector_preview_minimum_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._theme_manager = theme_manager
        self._photo_provider = photo_provider
        self._photo_id: int | None = None
        self._format_id: int | None = None
        theme_manager.effectiveThemeChanged.connect(self._update_preview)
        photo_provider.photoChanged.connect(self._photo_changed)
        photo_provider.cleared.connect(self._update_preview)
        self._refresh_accessible_name()

    def set_photo(self, photo_id: int | None, format_id: int | None) -> None:
        if (photo_id, format_id) == (self._photo_id, self._format_id):
            return
        self._photo_id = photo_id
        self._format_id = format_id
        self._refresh_accessible_name()
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        photo_id = self._photo_id
        pixmap = (
            None
            if photo_id is None
            else self._photo_provider.pixmap(
                photo_id,
                max(1, min(self.width(), self.height())),
                self.devicePixelRatioF(),
                format_id=self._format_id,
            )
        )
        if pixmap is None:
            paint_artwork_placeholder(
                painter,
                rect,
                photo_id or 0,
                self._theme_manager.tokens,
                float(LAYOUT.radius_control),
            )
            state = self._photo_provider.state(
                photo_id or 0,
                format_id=self._format_id,
            )
            if state in (PhotoPixmapState.UNAVAILABLE, PhotoPixmapState.FAILED):
                self._paint_unavailable(painter, rect, state)
            return
        paint_photo_pixmap(
            painter,
            rect,
            pixmap,
            self._theme_manager.tokens,
            float(LAYOUT.radius_control),
        )

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._refresh_accessible_name()
        super().changeEvent(event)

    def _photo_changed(self, photo_id: int) -> None:
        if photo_id == self._photo_id:
            self._refresh_accessible_name()
            self.update()

    def _update_preview(self, *_args: object) -> None:
        self.update()

    def _refresh_accessible_name(self) -> None:
        if self._photo_id is None:
            self.setAccessibleName(self.tr("No Photo selected"))
            return
        name = self.tr("Photo %1 preview").replace("%1", str(self._photo_id))
        if self._format_id is not None:
            name = (
                self.tr("%1, format %2")
                .replace("%1", name)
                .replace("%2", str(self._format_id))
            )
        state = self._photo_provider.state(
            self._photo_id,
            format_id=self._format_id,
        )
        if state in (PhotoPixmapState.UNAVAILABLE, PhotoPixmapState.FAILED):
            name = self.tr("%1, unavailable").replace("%1", name)
        self.setAccessibleName(name)

    def _paint_unavailable(
        self,
        painter: QPainter,
        rect: QRectF,
        state: PhotoPixmapState,
    ) -> None:
        message = (
            self.tr("Could not load this format")
            if state is PhotoPixmapState.FAILED
            else self.tr("Format unavailable")
        )
        badge = rect.adjusted(
            LAYOUT.space_md,
            rect.height() / 2.0 - LAYOUT.control_height,
            -LAYOUT.space_md,
            -(rect.height() / 2.0 - LAYOUT.control_height),
        )
        fill = QColor(self._theme_manager.tokens.surface)
        fill.setAlpha(232)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QColor(self._theme_manager.tokens.warning))
        painter.setBrush(fill)
        painter.drawRoundedRect(
            badge,
            float(LAYOUT.radius_control),
            float(LAYOUT.radius_control),
        )
        painter.drawText(
            badge.adjusted(LAYOUT.space_sm, 0, -LAYOUT.space_sm, 0),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            message,
        )
        painter.restore()


class PhotoInspector(QFrame):
    """Inspect one Photo and switch among its exact device-rendered copies."""

    formatSelected = Signal(int)

    def __init__(
        self,
        theme_manager: ThemeManager,
        photo_provider: PhotoPixmapProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("photoInspector")
        self.setMinimumWidth(LAYOUT.photo_inspector_minimum_width)
        self._photo_provider = photo_provider
        self._photo: Photo | None = None
        self._library: PhotoLibrary | None = None
        self._selected_format_id: int | None = None
        self._format_buttons: dict[int, ActionButton] = {}

        self._title = QLabel(self)
        self._title.setObjectName("photoInspectorTitle")
        self._title.setProperty("browserTitle", True)
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._summary = QLabel(self)
        self._summary.setObjectName("photoInspectorSummary")
        self._summary.setTextFormat(Qt.TextFormat.PlainText)
        self._summary.setWordWrap(True)

        self._format_label = QLabel(self)
        self._format_label.setObjectName("photoFormatLabel")
        self._format_buttons_layout = QHBoxLayout()
        self._format_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._format_buttons_layout.setSpacing(LAYOUT.space_2xs)
        self._format_buttons_layout.addStretch(1)
        self._format_group = QButtonGroup(self)
        self._format_group.setExclusive(True)
        self._format_group.idClicked.connect(self._select_format)
        format_row = QHBoxLayout()
        format_row.setContentsMargins(0, 0, 0, 0)
        format_row.setSpacing(LAYOUT.space_xs)
        format_row.addWidget(self._format_label)
        format_row.addLayout(self._format_buttons_layout, 1)

        self._preview = _PhotoPreview(theme_manager, photo_provider, self)
        self._metadata = QTreeWidget(self)
        self._metadata.setObjectName("photoMetadata")
        self._metadata.setRootIsDecorated(True)
        self._metadata.setUniformRowHeights(True)
        self._metadata.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self._metadata.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._metadata.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._metadata.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_md,
            LAYOUT.space_md,
            LAYOUT.space_md,
            LAYOUT.space_md,
        )
        layout.setSpacing(LAYOUT.space_sm)
        layout.addWidget(self._title)
        layout.addWidget(self._summary)
        layout.addLayout(format_row)
        layout.addWidget(self._preview, 3)
        layout.addWidget(self._metadata, 2)
        photo_provider.photoChanged.connect(self._photo_state_changed)
        photo_provider.capacityAvailable.connect(self._preview.update)
        self.retranslate_ui()

    @property
    def photo_id(self) -> int | None:
        return None if self._photo is None else self._photo.photo_id

    @property
    def selected_format_id(self) -> int | None:
        return self._selected_format_id

    def set_photo(self, photo: Photo | None, library: PhotoLibrary | None) -> None:
        previous_format = (
            self._selected_format_id
            if self._photo is not None
            and photo is not None
            and self._photo.photo_id == photo.photo_id
            else None
        )
        self._photo = photo
        self._library = library
        format_ids = self._format_ids(photo)
        self._selected_format_id = (
            previous_format
            if previous_format in format_ids
            else format_ids[0]
            if format_ids
            else None
        )
        self._rebuild_format_buttons(format_ids)
        self._preview.set_photo(self.photo_id, self._selected_format_id)
        self._refresh_copy()
        self._populate_metadata()

    def retranslate_ui(self) -> None:
        self._format_label.setText(self.tr("Formats"))
        self._metadata.setHeaderLabels((self.tr("Detail"), self.tr("Value")))
        self._refresh_format_buttons()
        self._refresh_copy()
        self._populate_metadata()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _select_format(self, format_id: int) -> None:
        if format_id not in self._format_buttons:
            return
        if format_id == self._selected_format_id:
            photo_id = self.photo_id
            if photo_id is not None and self._photo_provider.state(
                photo_id,
                format_id=format_id,
            ) in (PhotoPixmapState.UNAVAILABLE, PhotoPixmapState.FAILED):
                self._photo_provider.retry(photo_id, format_id=format_id)
                self._preview.update()
            return
        self._selected_format_id = format_id
        self._preview.set_photo(self.photo_id, format_id)
        self._populate_metadata()
        self._refresh_format_buttons()
        self.formatSelected.emit(format_id)

    def _rebuild_format_buttons(self, format_ids: tuple[int, ...]) -> None:
        for button in self._format_buttons.values():
            self._format_group.removeButton(button)
            button.deleteLater()
        self._format_buttons.clear()
        while self._format_buttons_layout.count() > 1:
            item = self._format_buttons_layout.takeAt(0)
            widget = None if item is None else item.widget()
            if widget is not None:
                widget.deleteLater()
        for format_id in format_ids:
            is_full_resolution = format_id == FULL_RESOLUTION_REQUEST_ID
            button = ActionButton(
                self.tr("Full res") if is_full_resolution else str(format_id),
                self,
            )
            button.setObjectName(
                "photoFormatFullResolution"
                if is_full_resolution
                else f"photoFormat{format_id}"
            )
            button.setProperty("photoFormat", True)
            button.setCheckable(True)
            button.setAccessibleName(
                self.tr("Full-resolution Photo")
                if is_full_resolution
                else self.tr("Photo format %1").replace("%1", str(format_id))
            )
            self._format_group.addButton(button, format_id)
            self._format_buttons_layout.insertWidget(
                self._format_buttons_layout.count() - 1,
                button,
            )
            self._format_buttons[format_id] = button
        selected = self._selected_format_id
        if selected is not None:
            self._format_buttons[selected].setChecked(True)
        self._format_label.setVisible(bool(format_ids))
        for button in self._format_buttons.values():
            button.setVisible(bool(format_ids))
        self._refresh_format_buttons()

    def _refresh_format_buttons(self) -> None:
        photo_id = self.photo_id
        for format_id, button in self._format_buttons.items():
            state = (
                PhotoPixmapState.IDLE
                if photo_id is None
                else self._photo_provider.state(photo_id, format_id=format_id)
            )
            unavailable = state in (
                PhotoPixmapState.UNAVAILABLE,
                PhotoPixmapState.FAILED,
            )
            button.set_state(
                ActionButtonState.ERROR if unavailable else ActionButtonState.DEFAULT
            )
            is_full_resolution = format_id == FULL_RESOLUTION_REQUEST_ID
            button.setText(
                self.tr("Full res") if is_full_resolution else str(format_id)
            )
            button.setAccessibleName(
                self.tr("Full-resolution Photo")
                if is_full_resolution
                else self.tr("Photo format %1").replace("%1", str(format_id))
            )
            format_name = (
                self.tr("full-resolution Photo")
                if is_full_resolution
                else self.tr("Photo format %1").replace("%1", str(format_id))
            )
            button.setToolTip(
                self.tr("Click again to retry the %1").replace("%1", format_name)
                if unavailable and format_id == self._selected_format_id
                else self.tr("Show the %1").replace("%1", format_name)
            )

    def _refresh_copy(self) -> None:
        photo = self._photo
        if photo is None:
            self._title.setText(self.tr("No Photo Selected"))
            self._summary.setText(
                self.tr("Choose a Photo from the grid to inspect it.")
            )
            return
        self._title.setText(self.tr("Photo %1").replace("%1", str(photo.photo_id)))
        album_count = len(self._album_names(photo.photo_id))
        format_count = len(photo.representations)
        total_bytes = sum(item.size_bytes for item in photo.representations)
        self._summary.setText(
            self.tr("%1 albums · %2 formats · %3")
            .replace("%1", str(album_count))
            .replace("%2", str(format_count))
            .replace("%3", _format_bytes(total_bytes))
        )

    def _populate_metadata(self) -> None:
        self._metadata.clear()
        photo = self._photo
        if photo is None:
            return
        self._section(
            self.tr("Photo"),
            (
                (self.tr("Photo ID"), str(photo.photo_id)),
                (self.tr("Albums"), ", ".join(self._album_names(photo.photo_id))),
                (
                    self.tr("Rating"),
                    self.tr("%1 / 100").replace("%1", str(photo.rating)),
                ),
                (self.tr("Original date"), self._format_date(photo.original_date)),
                (self.tr("Taken date"), self._format_date(photo.taken_date)),
            ),
        )
        self._section(
            self.tr("Storage"),
            (
                (self.tr("Source size"), _format_bytes(photo.source_size_bytes)),
                (
                    self.tr("Stored copies"),
                    str(len(photo.representations)),
                ),
                (
                    self.tr("Stored copy bytes"),
                    _format_bytes(
                        sum(item.size_bytes for item in photo.representations)
                    ),
                ),
            ),
        )
        selected = self._selected_representation(photo)
        if selected is not None:
            self._section(
                self.tr("Selected Format"),
                self._representation_rows(selected),
            )
        all_formats = QTreeWidgetItem((self.tr("All Device Formats"), ""))
        all_formats.setFlags(all_formats.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._metadata.addTopLevelItem(all_formats)
        for representation in photo.representations:
            label = (
                self.tr("Full Resolution")
                if representation.kind is PhotoRepresentationKind.FULL_RESOLUTION
                else self.tr("Format %1").replace("%1", str(representation.format_id))
            )
            detail = self.tr("%1 x %2 · %3 · offset %4")
            detail = (
                detail.replace("%1", str(representation.width))
                .replace("%2", str(representation.height))
                .replace("%3", _format_bytes(representation.size_bytes))
                .replace("%4", f"{representation.offset:,}")
            )
            QTreeWidgetItem(all_formats, (label, detail))
        self._metadata.expandAll()

    def _photo_state_changed(self, photo_id: int) -> None:
        if photo_id != self.photo_id:
            return
        self._refresh_format_buttons()
        self._populate_metadata()

    def _section(
        self,
        title: str,
        rows: tuple[tuple[str, str], ...],
    ) -> None:
        section = QTreeWidgetItem((title, ""))
        section.setFlags(section.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self._metadata.addTopLevelItem(section)
        for label, value in rows:
            if value:
                QTreeWidgetItem(section, (label, value))

    def _representation_rows(
        self,
        representation: PhotoRepresentation,
    ) -> tuple[tuple[str, str], ...]:
        padding = self.tr("%1 horizontal, %2 vertical")
        padding = padding.replace("%1", str(representation.horizontal_padding)).replace(
            "%2", str(representation.vertical_padding)
        )
        request_id = (
            FULL_RESOLUTION_REQUEST_ID
            if representation.kind is PhotoRepresentationKind.FULL_RESOLUTION
            else representation.format_id
        )
        availability = self._availability_label(request_id)
        rows: tuple[tuple[str, str], ...] = (
            (self.tr("Kind"), self._kind_label(representation.kind)),
            (
                self.tr("Resolution"),
                self.tr("%1 x %2")
                .replace("%1", str(representation.width))
                .replace("%2", str(representation.height)),
            ),
            (self.tr("File"), representation.relative_path),
            (self.tr("Offset"), f"{representation.offset:,}"),
            (self.tr("Stored size"), _format_bytes(representation.size_bytes)),
            (self.tr("Padding"), padding),
        )
        if representation.kind is PhotoRepresentationKind.THUMBNAIL:
            rows = (
                rows[0],
                (self.tr("Format ID"), str(representation.format_id)),
                *rows[1:],
            )
        if availability is None:
            return rows
        return (*rows, (self.tr("Availability"), availability))

    def _availability_label(self, format_id: int) -> str | None:
        photo_id = self.photo_id
        if photo_id is None:
            return None
        state = self._photo_provider.state(photo_id, format_id=format_id)
        if state is PhotoPixmapState.UNAVAILABLE:
            return self.tr("Unavailable on this device")
        if state is PhotoPixmapState.FAILED:
            return self.tr("Load failed — click the selected format to retry")
        return None

    def _album_names(self, photo_id: int) -> tuple[str, ...]:
        library = self._library
        if library is None:
            return ()
        return tuple(
            album.name for album in library.albums if photo_id in album.photo_ids
        )

    def _selected_representation(self, photo: Photo) -> PhotoRepresentation | None:
        if self._selected_format_id == FULL_RESOLUTION_REQUEST_ID:
            return next(
                (
                    representation
                    for representation in photo.representations
                    if representation.kind is PhotoRepresentationKind.FULL_RESOLUTION
                ),
                None,
            )
        return next(
            (
                representation
                for representation in photo.representations
                if representation.kind is PhotoRepresentationKind.THUMBNAIL
                and representation.format_id == self._selected_format_id
            ),
            None,
        )

    def _format_ids(self, photo: Photo | None) -> tuple[int, ...]:
        if photo is None:
            return ()
        thumbnails = sorted(
            (
                item
                for item in photo.representations
                if item.kind is PhotoRepresentationKind.THUMBNAIL and item.format_id > 0
            ),
            key=lambda item: (
                -(item.width * item.height),
                item.format_id,
            ),
        )
        format_ids = tuple(dict.fromkeys(item.format_id for item in thumbnails))
        has_full_resolution = any(
            item.kind is PhotoRepresentationKind.FULL_RESOLUTION
            and bool(item.relative_path)
            for item in photo.representations
        )
        return (
            (*format_ids, FULL_RESOLUTION_REQUEST_ID)
            if has_full_resolution
            else format_ids
        )

    def _format_date(self, value: int) -> str:
        if value <= 0:
            return self.tr("Unknown")
        try:
            return datetime.fromtimestamp(value, UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        except (OverflowError, OSError, ValueError):
            return self.tr("Unknown")

    def _kind_label(self, kind: PhotoRepresentationKind) -> str:
        if kind is PhotoRepresentationKind.FULL_RESOLUTION:
            return self.tr("Full resolution")
        return self.tr("Thumbnail")


def _format_bytes(value: int) -> str:
    return f"{max(0, value):,} bytes"


__all__ = ["PhotoInspector"]
