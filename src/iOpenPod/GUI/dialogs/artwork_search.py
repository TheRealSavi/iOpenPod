"""Preview online album covers before assigning them through Library Workspace."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.artwork_search import ArtworkCandidate, ArtworkSource
from iOpenPod.app.artwork_search_controller import ArtworkSearchController
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iPodDB.library import ArtworkPixels

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.library_workspace import EditRevision, LibraryWorkspace


class ArtworkSearchDialog(QDialog):
    def __init__(
        self,
        workspace: LibraryWorkspace,
        track_ids: tuple[int, ...],
        revision: EditRevision,
        source: ArtworkSource,
        parent: QWidget | None = None,
        *,
        controller: ArtworkSearchController | None = None,
        on_selected: Callable[[ArtworkPixels, str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        workspace.require_revision(revision)
        tracks = tuple(workspace.track(i) for i in dict.fromkeys(track_ids))
        if not tracks or any(t is None for t in tracks):
            raise ValueError("Select tracks from the current Library.")
        self._workspace = workspace
        self._on_selected = on_selected
        self._revision = revision
        self._track_ids = tuple(dict.fromkeys(track_ids))
        self._controller = controller or ArtworkSearchController()
        self._pixels: ArtworkPixels | None = None
        self._candidate: ArtworkCandidate | None = None
        self._stale = False
        self.setObjectName("artworkSearchDialog")
        self.setWindowTitle(self.tr("Find Album Artwork"))
        self.resize(850, 640)
        layout = QVBoxLayout(self)
        heading = QLabel(
            self.tr("Find a cover, preview it, then use it in the metadata editor.")
            if on_selected is not None
            else self.tr("Find a cover, preview it, then apply it to this album.")
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)
        form = QFormLayout()
        self._form = form
        self.provider = AppComboBox()
        self.provider.addItem(self.tr("iTunes Store"), ArtworkSource.ITUNES)
        self.provider.addItem(self.tr("Discogs"), ArtworkSource.DISCOGS)
        self.provider.setCurrentIndex(0 if source is ArtworkSource.ITUNES else 1)
        form.addRow(self.tr("Search in"), self.provider)
        first = next(t for t in tracks if t is not None)
        self.term = QLineEdit(
            " ".join(
                value
                for value in (first.album_artist or first.artist, first.album)
                if value
            )
        )
        self.term.setMaxLength(300)
        self.term.setClearButtonEnabled(True)
        form.addRow(self.tr("Artist / album"), self.term)
        self.region = QLineEdit("US")
        self.region.setMaxLength(2)
        self.region.setMaximumWidth(90)
        self.region.setToolTip(
            self.tr("Two-letter store region, such as US, GB, or JP.")
        )
        form.addRow(self.tr("Store region"), self.region)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText(self.tr("Discogs personal access token"))
        form.addRow(self.tr("Discogs token"), self.token)
        self._token_help = QLabel(
            self.tr(
                'Create a token in <a href="https://www.discogs.com/settings/developers">Discogs developer settings</a>. '
                "It is kept only while this dialog is open."
            )
        )
        self._token_help.setOpenExternalLinks(True)
        self._token_help.setWordWrap(True)
        form.addRow(self._token_help)
        layout.addLayout(form)
        controls = QHBoxLayout()
        self.search_button = QPushButton(self.tr("Search"))
        self.search_button.setDefault(True)
        self.cancel_search = QPushButton(self.tr("Cancel Search"))
        self.cancel_search.setEnabled(False)
        controls.addWidget(self.search_button)
        controls.addWidget(self.cancel_search)
        controls.addStretch()
        layout.addLayout(controls)
        content = QHBoxLayout()
        self.results = QListWidget()
        self.results.setObjectName("artworkSearchResults")
        self.results.setAccessibleName(self.tr("Artwork search results"))
        content.addWidget(self.results, 1)
        preview_layout = QVBoxLayout()
        self.preview = QLabel(self.tr("Select a search result to preview its cover."))
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setObjectName("artworkSearchPreview")
        self.preview.setFixedSize(300, 300)
        self.preview.setWordWrap(True)
        preview_layout.addWidget(self.preview)
        self.dimensions = QLabel()
        preview_layout.addWidget(self.dimensions)
        self.open_source = QPushButton(self.tr("Open Album Page"))
        self.open_source.setEnabled(False)
        preview_layout.addWidget(self.open_source)
        preview_layout.addStretch()
        content.addLayout(preview_layout)
        layout.addLayout(content, 1)
        self.missing_only = QCheckBox(self.tr("Apply only to tracks without artwork"))
        self.missing_only.setChecked(
            any(t is not None and t.artwork_id == 0 for t in tracks)
        )
        self.missing_only.setToolTip(
            self.tr("Uncheck to replace the cover on every track in this album.")
        )
        layout.addWidget(self.missing_only)
        self.missing_only.setVisible(on_selected is None)
        self.status = QLabel(
            self.tr(
                "Choose Search to send the artist and album terms to the selected service."
            )
        )
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = buttons.addButton(
            self.tr("Use Artwork")
            if on_selected is not None
            else self.tr("Apply Artwork"),
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.apply_button.setEnabled(False)
        self.apply_button.setProperty("kind", "primary")
        layout.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.search_button.clicked.connect(self._search)
        self.term.returnPressed.connect(self._search)
        self.cancel_search.clicked.connect(self._cancel_search)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.results.currentItemChanged.connect(self._selected)
        self.open_source.clicked.connect(self._open_source)
        self.missing_only.toggled.connect(self._update_apply)
        self._controller.finished.connect(self._finished)
        self._controller.failed.connect(self._failed)
        self._controller.busyChanged.connect(self._busy_changed)
        workspace.changed.connect(self._workspace_changed)
        self._provider_changed()

    def _source(self) -> ArtworkSource:
        return (
            ArtworkSource.ITUNES
            if self.provider.currentIndex() == 0
            else ArtworkSource.DISCOGS
        )

    def _clear_preview(self) -> None:
        self._pixels = None
        self._candidate = None
        self.preview.setText(self.tr("Select a search result to preview its cover."))
        self.dimensions.clear()
        self.open_source.setEnabled(False)
        self._update_apply()

    def _provider_changed(self) -> None:
        self._controller.cancel()
        self.results.clear()
        self._clear_preview()
        discogs = self._source() is ArtworkSource.DISCOGS
        self.token.setEnabled(discogs)
        self._form.setRowVisible(self.token, discogs)
        self._form.setRowVisible(self._token_help, discogs)
        self.region.setEnabled(not discogs)
        self._form.setRowVisible(self.region, not discogs)
        self.status.setText(
            self.tr(
                "Choose Search to send the artist and album terms to the selected service."
            )
        )

    def _search(self) -> None:
        if self._stale or self._controller.busy:
            return
        self.results.clear()
        self._clear_preview()
        self.status.setText(self.tr("Searching…"))
        self._controller.search(
            self._source(),
            self.term.text(),
            country=self.region.text(),
            token=self.token.text(),
        )

    def _cancel_search(self) -> None:
        self._controller.cancel()
        self._clear_preview()
        self.results.setCurrentRow(-1)
        self.status.setText(self.tr("Search cancelled."))

    def _selected(
        self, item: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        self._controller.cancel()
        self._clear_preview()
        if item is None or self._stale:
            return
        candidate = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(candidate, ArtworkCandidate):
            return
        self._candidate = candidate
        self.open_source.setEnabled(bool(candidate.page_url))
        self.status.setText(self.tr("Loading artwork…"))
        self._controller.load(candidate)

    def _finished(self, result: object) -> None:
        if self._stale:
            return
        if isinstance(result, tuple):
            for candidate in result:
                if isinstance(candidate, ArtworkCandidate):
                    item = QListWidgetItem(
                        candidate.title
                        + ("\n" + candidate.detail if candidate.detail else "")
                    )
                    item.setData(Qt.ItemDataRole.UserRole, candidate)
                    self.results.addItem(item)
            if self.results.count():
                self.status.setText(
                    self.tr(
                        "Select a result to preview its cover. Up to 25 results are shown."
                    )
                )
            else:
                self.status.setText(
                    self.tr(
                        "No covers found. Try different terms, another region, or the other service."
                    )
                )
        elif isinstance(result, ArtworkPixels) and self._candidate is not None:
            self._pixels = result
            image = QImage(
                result.rgb888,
                result.width,
                result.height,
                result.width * 3,
                QImage.Format.Format_RGB888,
            ).copy()
            self.preview.setPixmap(
                QPixmap.fromImage(image).scaled(
                    self.preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.dimensions.setText(
                self.tr("%1 x %2 pixels")
                .replace("%1", str(result.width))
                .replace("%2", str(result.height))
            )
            self.status.setText(
                self.tr(
                    "Use Artwork returns this image to the metadata editor. Click Apply there to save your changes."
                )
                if self._on_selected is not None
                else self.tr(
                    "Apply Artwork uses this cover for the chosen tracks in this album."
                )
            )
            self._update_apply()

    def _failed(self, error: str) -> None:
        if not self._stale:
            self.status.setText(workflow_text(error))
        self._pixels = None
        self._update_apply()

    def _busy_changed(self, busy: bool) -> None:
        self.search_button.setEnabled(not busy and not self._stale)
        self.cancel_search.setEnabled(busy)
        self._update_apply()

    def _targets(self) -> tuple[int, ...]:
        return tuple(
            i
            for i in self._track_ids
            if (track := self._workspace.track(i)) is not None
            and (not self.missing_only.isChecked() or track.artwork_id == 0)
        )

    def _update_apply(self) -> None:
        self.apply_button.setEnabled(
            not self._stale
            and not self._controller.busy
            and self._pixels is not None
            and (self._on_selected is not None or bool(self._targets()))
        )

    def _workspace_changed(self) -> None:
        try:
            self._workspace.require_revision(self._revision)
        except ValueError as error:
            self._stale = True
            self._controller.cancel()
            self._clear_preview()
            self.status.setText(workflow_text(str(error)))
            self.search_button.setEnabled(False)
            for widget in (
                self.provider,
                self.term,
                self.region,
                self.token,
                self.results,
            ):
                widget.setEnabled(False)

    def _open_source(self) -> None:
        if self._candidate is not None and self._candidate.page_url:
            QDesktopServices.openUrl(QUrl(self._candidate.page_url))

    def accept(self) -> None:
        if self._stale or self._controller.busy or self._pixels is None:
            return
        try:
            self._workspace.require_revision(self._revision)
            if self._on_selected is not None:
                self._on_selected(
                    self._pixels,
                    "" if self._candidate is None else self._candidate.title,
                )
                super().accept()
                return
            targets = self._targets()
            if not targets:
                raise ValueError(
                    self.tr(
                        "No tracks without artwork remain. Uncheck the option to replace existing covers."
                    )
                )
            self._workspace.set_artwork(targets, self._pixels, self._revision)
        except ValueError as error:
            self.status.setText(workflow_text(str(error)))
            return
        super().accept()

    def done(self, result: int) -> None:
        self.token.clear()
        self._controller.shutdown()
        super().done(result)
