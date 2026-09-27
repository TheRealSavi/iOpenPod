"""Three-pane Photo browser backed by the common Library Workspace."""

from PySide6.QtCore import (
    QByteArray,
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QLabel,
    QListView,
    QMenu,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.core.settings.definitions import PHOTOS_SPLITTER_STATE
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.photo_list_model import (
    PhotoAlbumListModel,
    PhotoAlbumRole,
    PhotoAlbumSummary,
    PhotoFilterProxyModel,
    PhotoListModel,
    PhotoRole,
    PhotoSortMode,
)
from iOpenPod.app.models.selection_grouping import SelectionGroupingProxyModel
from iOpenPod.GUI.delegates.selection_group_delegate import SelectionGroupDelegate
from iOpenPod.GUI.dialogs.photo_album_editor import PhotoAlbumEditorDialog
from iOpenPod.GUI.dialogs.photo_album_manager import PhotoAlbumManagerDialog
from iOpenPod.GUI.dialogs.photo_metadata_editor import PhotoMetadataEditorDialog
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.photo_provider import PhotoPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.browser_chrome import SourceListPanel
from iOpenPod.GUI.widgets.library_toolbar import LibraryToolbar, SortOption
from iOpenPod.GUI.widgets.photo_grid import PhotoGridView
from iOpenPod.GUI.widgets.photo_inspector import PhotoInspector
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind
from iPodDB.library import Photo, PhotoAlbum


class PhotoPage(QWidget):
    """Browse Photo Albums, virtualized Photo cards, and one selected Photo."""

    photoExportRequested = Signal(object)
    photoAlbumExportRequested = Signal(str, object)

    def __init__(
        self,
        workspace: LibraryWorkspace,
        settings: SettingsService,
        theme_manager: ThemeManager,
        photo_provider: PhotoPixmapProvider,
        parent: QWidget | None = None,
        *,
        source_actions: bool = True,
        selection_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("photosPage")
        self._workspace = workspace
        self._source_actions = source_actions
        self._selection_mode = selection_mode
        self._settings = settings
        self._generation = workspace.generation
        self._selected_album_id: int | None = None
        self._selected_photo_id: int | None = None
        self._photo_query = ""
        self._theme_manager = theme_manager
        self._photo_provider = photo_provider
        self._album_manager: PhotoAlbumManagerDialog | None = None
        self._albums_model = PhotoAlbumListModel(workspace, self)
        self._photos_model = PhotoListModel(workspace, self)
        self._photos_proxy = PhotoFilterProxyModel(self._photos_model, self)
        self._photo_grouping = (
            SelectionGroupingProxyModel(self._photos_proxy, self)
            if selection_mode
            else None
        )

        self._toolbar = LibraryToolbar(self)
        self._toolbar.set_namespace("photos")
        self._create_album = ActionButton(
            parent=self._toolbar,
            kind=ActionButtonKind.PRIMARY,
        )
        self._create_album.setObjectName("photoCreateAlbum")
        self._toolbar.add_action(self._create_album)

        album_panel = SourceListPanel(
            LAYOUT.photo_album_pane_width,
            self,
            minimum_width=LAYOUT.photo_album_pane_minimum_width,
        )
        album_panel.setObjectName("photoAlbumPanel")
        album_panel.title_label.setObjectName("photoAlbumHeading")
        album_panel.count_label.setObjectName("photoAlbumCount")
        self._album_panel = album_panel
        self._albums = QListView(album_panel)
        self._albums.setObjectName("photoAlbumList")
        self._albums.setModel(self._albums_model)
        self._albums.setUniformItemSizes(True)
        self._albums.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        if source_actions and not selection_mode:
            self._albums.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
            self._albums.setDefaultDropAction(Qt.DropAction.CopyAction)
            self._albums.setDragDropOverwriteMode(True)
            self._albums.setDropIndicatorShown(True)
        self._albums.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._photo_album_menu = QMenu(self._albums)
        self._photo_album_menu.setObjectName("photoAlbumContextMenu")
        self._export_photo_album = self._photo_album_menu.addAction("")
        self._export_photo_album.setObjectName("photoAlbumExport")
        self._export_photo_album.setEnabled(False)
        self._export_photo_album.triggered.connect(self._export_selected_photo_album)
        self._photo_album_menu.addSeparator()
        self._rename_photo_album = self._photo_album_menu.addAction("")
        self._rename_photo_album.setObjectName("photoAlbumRename")
        self._rename_photo_album.setEnabled(False)
        self._rename_photo_album.triggered.connect(self._rename_selected_photo_album)
        self._delete_photo_album = self._photo_album_menu.addAction("")
        self._delete_photo_album.setObjectName("photoAlbumDelete")
        self._delete_photo_album.setEnabled(False)
        self._delete_photo_album.triggered.connect(self._delete_selected_photo_album)
        album_panel.set_view(self._albums)

        grid_panel = QFrame(self)
        grid_panel.setObjectName("photoGridPanel")
        grid_layout = QVBoxLayout(grid_panel)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(0)
        self._grid = PhotoGridView(
            self._photos_proxy,
            theme_manager,
            photo_provider,
            grid_panel,
        )
        self._grid.set_library_workspace(workspace)
        self._grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._photo_menu = QMenu(self._grid)
        self._photo_menu.setObjectName("photoContextMenu")
        self._edit_photo_metadata = self._photo_menu.addAction("")
        self._edit_photo_metadata.setObjectName("photoEditMetadata")
        self._edit_photo_metadata.setShortcut(QKeySequence("Ctrl+E"))
        self._edit_photo_metadata.setShortcutVisibleInContextMenu(True)
        self._edit_photo_metadata.setEnabled(False)
        self._edit_photo_metadata.triggered.connect(self._open_metadata_editor)
        self._export_photos = self._photo_menu.addAction("")
        self._export_photos.setObjectName("photoExport")
        self._export_photos.setEnabled(False)
        self._export_photos.triggered.connect(self._export_selected_photos)
        self._manage_photo_albums = self._photo_menu.addAction("")
        self._manage_photo_albums.setObjectName("photoManageAlbums")
        self._manage_photo_albums.setEnabled(False)
        self._manage_photo_albums.triggered.connect(self._open_album_manager)
        self._photo_menu.addSeparator()
        self._delete_photos = self._photo_menu.addAction("")
        self._delete_photos.setObjectName("photoDelete")
        self._delete_photos.setEnabled(False)
        self._delete_photos.triggered.connect(self._delete_selected_photos)
        self._empty = QLabel(grid_panel)
        self._empty.setObjectName("photoBrowserEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._grid_stack = QStackedWidget(grid_panel)
        self._grid_stack.setObjectName("photoGridStack")
        self._grid_stack.addWidget(self._grid)
        self._grid_stack.addWidget(self._empty)
        grid_layout.addWidget(self._grid_stack)

        self._inspector = PhotoInspector(
            theme_manager,
            photo_provider,
            self,
        )
        if self._photo_grouping is not None:
            photo_delegate = self._grid.itemDelegate()
            self._grid.setModel(self._photo_grouping)
            self._grid.setItemDelegate(
                SelectionGroupDelegate(photo_delegate, theme_manager, self._grid)
            )
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.setObjectName("photoBrowserSplitter")
        self._splitter.setProperty("photoBrowser", True)
        self._splitter.setProperty("sourceListBrowser", True)
        self._splitter.setHandleWidth(LAYOUT.source_list_splitter_handle_width)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(album_panel)
        self._splitter.addWidget(grid_panel)
        self._splitter.addWidget(self._inspector)
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)
        self._splitter.setCollapsible(2, False)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.setSizes(
            (
                LAYOUT.photo_album_pane_width,
                700,
                LAYOUT.photo_inspector_width,
            )
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._splitter, 1)

        self._splitter_save_timer = QTimer(self)
        self._splitter_save_timer.setSingleShot(True)
        self._splitter_save_timer.setInterval(250)
        self._splitter.splitterMoved.connect(self._splitter_moved)
        self._splitter_save_timer.timeout.connect(self._save_splitter_state)
        self._albums.selectionModel().currentChanged.connect(self._album_selected)
        self._albums.customContextMenuRequested.connect(
            self._show_photo_album_context_menu
        )
        self._grid.selectionModel().currentChanged.connect(self._photo_selected)
        if not selection_mode:
            self._grid.customContextMenuRequested.connect(self._show_photo_context_menu)
        self._toolbar.queryChanged.connect(self._set_photo_query)
        self._toolbar.sortModeChanged.connect(self._set_photo_sort)
        self._toolbar.sortDirectionChanged.connect(
            self._photos_proxy.set_sort_direction
        )
        self._toolbar.selectionGroupingChanged.connect(self._set_selection_grouping)
        self._create_album.clicked.connect(self._create_photo_album)
        edit_shortcut = QShortcut(QKeySequence("Ctrl+E"), self._grid)
        edit_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        edit_shortcut.setProperty("photoAction", "edit")
        edit_shortcut.activated.connect(self._open_metadata_editor)
        workspace.changed.connect(self._refresh_create_album_state)
        workspace.photosChanged.connect(self._photos_changed)

        splitter_state = settings.get(PHOTOS_SPLITTER_STATE)
        if not splitter_state.isEmpty():
            self._splitter.restoreState(splitter_state)
        self.retranslate_ui()
        self._toolbar.set_selection_grouping(selection_mode)

    def retranslate_ui(self) -> None:
        selected_album_id = self._selected_album_id
        selected_photo_id = self._selected_photo_id
        self._toolbar.retranslate_ui()
        self._toolbar.configure(
            grid_title=self.tr("Photos"),
            grid_search_label=self.tr("Search Photos"),
            supports_list=False,
            supports_selection_grouping=self._selection_mode,
            sort_accessible_name=self.tr("Sort Photos"),
            sort_options=(
                SortOption(
                    self.tr("Photo order"),
                    PhotoSortMode.SOURCE_ORDER.value,
                ),
                SortOption(
                    self.tr("Newest first"),
                    PhotoSortMode.DATE_TAKEN.value,
                ),
                SortOption(
                    self.tr("Highest rated"),
                    PhotoSortMode.RATING.value,
                ),
                SortOption(
                    self.tr("Largest files"),
                    PhotoSortMode.SOURCE_SIZE.value,
                ),
            ),
        )
        self._album_panel.set_title(self.tr("PHOTO ALBUMS"))
        self._albums_model.retranslate()
        self._album_panel.set_count(max(0, self._albums_model.rowCount() - 1))
        self._photos_model.retranslate()
        self._photos_proxy.invalidate()
        if self._photo_grouping is not None:
            self._photo_grouping.retranslate()
        self._inspector.retranslate_ui()
        self._edit_photo_metadata.setText(self.tr("Edit Metadata…"))
        self._export_photos.setText(self.tr("Export Selected Photos…"))
        self._export_photo_album.setText(self.tr("Export Photo Album…"))
        self._rename_photo_album.setText(self.tr("Rename Photo Album…"))
        self._delete_photo_album.setText(self.tr("Delete Photo Album…"))
        self._manage_photo_albums.setText(self.tr("Manage Albums…"))
        self._delete_photos.setText(self.tr("Delete Photos…"))
        self._create_album.setText(self.tr("New Album"))
        self._create_album.setAccessibleName(self.tr("Create a new Photo Album"))
        self._refresh_create_album_state()
        self._selected_album_id = selected_album_id
        self._selected_photo_id = selected_photo_id
        self._restore_selection()

    def set_sync_selection(self, selection: object) -> None:
        """Bind Host Photo cards to the Sync Workspace selection state."""

        from iOpenPod.app.models.sync_selection import SyncSelection

        self._photos_model.set_sync_selection(
            selection if isinstance(selection, SyncSelection) else None
        )
        self._grid.setDragEnabled(False)
        self._grid.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self._albums.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _album_selected(
        self,
        current: QModelIndex,
        _previous: QModelIndex,
    ) -> None:
        summary = current.data(PhotoAlbumRole.SUMMARY)
        if not isinstance(summary, PhotoAlbumSummary):
            return
        previous_photo_id = self._selected_photo_id
        self._selected_album_id = summary.album_id
        self._photos_model.set_album_id(summary.album_id)
        self._select_photo(previous_photo_id)
        self._refresh_empty_state()

    def _set_photo_query(self, query: str) -> None:
        selected_photo_id = self._selected_photo_id
        self._photo_query = query.strip()
        self._photos_proxy.set_query(query)
        self._select_photo(selected_photo_id)
        self._refresh_empty_state()

    def _set_photo_sort(self, value: str) -> None:
        selected_photo_id = self._selected_photo_id
        self._photos_proxy.set_sort_mode(PhotoSortMode(value))
        self._select_photo(selected_photo_id)

    def _set_selection_grouping(self, enabled: bool) -> None:
        if self._photo_grouping is None:
            return
        selected_photo_id = self._selected_photo_id
        self._photos_proxy.set_group_by_selection(enabled)
        self._photo_grouping.set_grouping_enabled(enabled)
        self._grid.set_sectioned_layout(enabled)
        self._select_photo(selected_photo_id)

    def _photo_selected(
        self,
        current: QModelIndex,
        _previous: QModelIndex,
    ) -> None:
        photo = current.data(PhotoRole.PHOTO)
        if not isinstance(photo, Photo):
            return
        self._selected_photo_id = photo.photo_id
        self._inspector.set_photo(photo, self._workspace.photos)

    def _show_photo_context_menu(self, point: QPoint) -> None:
        index = self._grid.indexAt(point)
        if not index.isValid():
            return
        selection = self._grid.selectionModel()
        if not selection.isSelected(index):
            selection.setCurrentIndex(
                index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect,
            )
        selected = self._selected_photos()
        can_edit = bool(selected) and not self._workspace.locked
        self._edit_photo_metadata.setEnabled(can_edit)
        self._edit_photo_metadata.setToolTip(
            self.tr("Wait for the current Library save to finish.")
            if self._workspace.locked
            else ""
        )
        self._export_photos.setEnabled(bool(selected) and self._source_actions)
        self._export_photos.setToolTip(
            ""
            if self._source_actions
            else self.tr("These Photos are already on the Host.")
        )
        has_user_albums = self._albums_model.rowCount() > 1
        can_manage = bool(selected) and has_user_albums and not self._workspace.locked
        self._manage_photo_albums.setEnabled(can_manage)
        if self._workspace.locked:
            manage_tooltip = self.tr("Wait for the current Library save to finish.")
        elif not has_user_albums:
            manage_tooltip = self.tr("This iPod has no user Photo Albums.")
        else:
            manage_tooltip = ""
        self._manage_photo_albums.setToolTip(manage_tooltip)
        can_delete = bool(selected) and not self._workspace.locked
        self._delete_photos.setEnabled(can_delete)
        self._delete_photos.setToolTip(
            self.tr("Wait for the current Library save to finish.")
            if self._workspace.locked
            else ""
        )
        self._photo_menu.popup(self._grid.viewport().mapToGlobal(point))

    def _show_photo_album_context_menu(self, point: QPoint) -> None:
        index = self._albums.indexAt(point)
        if not index.isValid():
            return
        self._albums.setCurrentIndex(index)
        summary = index.data(PhotoAlbumRole.SUMMARY)
        if not isinstance(summary, PhotoAlbumSummary):
            return
        self._export_photo_album.setText(
            self.tr("Export All Photos…")
            if summary.is_all_photos
            else self.tr("Export Photo Album…")
        )
        self._export_photo_album.setEnabled(
            summary.photo_count > 0 and self._source_actions
        )
        self._export_photo_album.setToolTip(
            self.tr("These Photos are already on the Host.")
            if not self._source_actions
            else ""
            if summary.photo_count > 0
            else self.tr("This Photo Album has no Photos to export.")
        )
        can_edit = not summary.is_all_photos and not self._workspace.locked
        self._rename_photo_album.setEnabled(can_edit)
        self._delete_photo_album.setEnabled(can_edit)
        if self._workspace.locked:
            edit_tooltip = self.tr("Wait for the current Library save to finish.")
        elif summary.is_all_photos:
            edit_tooltip = self.tr("All Photos cannot be renamed or deleted.")
        else:
            edit_tooltip = ""
        self._rename_photo_album.setToolTip(edit_tooltip)
        self._delete_photo_album.setToolTip(edit_tooltip)
        self._photo_album_menu.popup(self._albums.viewport().mapToGlobal(point))

    def _selected_photos(self) -> tuple[Photo, ...]:
        photos = (
            index.data(PhotoRole.PHOTO)
            for index in sorted(
                self._grid.selectionModel().selectedIndexes(),
                key=lambda item: item.row(),
            )
        )
        return tuple(
            {
                photo.photo_id: photo for photo in photos if isinstance(photo, Photo)
            }.values()
        )

    def _export_selected_photos(self) -> None:
        photos = self._selected_photos()
        if photos and self._source_actions:
            self.photoExportRequested.emit(photos)

    def _open_metadata_editor(self) -> None:
        photos = self._selected_photos()
        if not photos or self._workspace.locked:
            return
        try:
            dialog = PhotoMetadataEditorDialog(
                self._workspace,
                tuple(photo.photo_id for photo in photos),
                self,
            )
        except ValueError as error:
            QMessageBox.warning(
                self,
                self.tr("Could Not Edit Photo Metadata"),
                workflow_text(str(error)),
            )
            return
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.open()

    def _selected_photo_album(self) -> PhotoAlbum | None:
        summary = self._albums.currentIndex().data(PhotoAlbumRole.SUMMARY)
        if not isinstance(summary, PhotoAlbumSummary) or summary.album_id is None:
            return None
        return self._workspace.photo_album(summary.album_id)

    def _rename_selected_photo_album(self) -> None:
        album = self._selected_photo_album()
        if album is None or self._workspace.locked:
            return
        expected = self._workspace.edit_revision
        dialog = PhotoAlbumEditorDialog(self, album_name=album.name)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self._workspace.rename_photo_album(
                album.album_id,
                dialog.album_name,
                expected,
            )
        except ValueError as error:
            QMessageBox.warning(
                self,
                self.tr("Could Not Rename Photo Album"),
                workflow_text(str(error)),
            )
        finally:
            dialog.deleteLater()

    def _delete_selected_photo_album(self) -> None:
        album = self._selected_photo_album()
        if album is None or self._workspace.locked:
            return
        expected = self._workspace.edit_revision
        answer = QMessageBox.question(
            self,
            self.tr("Delete Photo Album?"),
            self.tr("Delete '%1'?").replace("%1", album.name)
            + "\n\n"
            + self.tr(
                "This removes the Photos from this album only. The Photos themselves stay on the iPod in All Photos and in any other Photo Albums."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._workspace.remove_photo_album(album.album_id, expected)
        except ValueError as error:
            QMessageBox.warning(
                self,
                self.tr("Could Not Delete Photo Album"),
                workflow_text(str(error)),
            )

    def _open_album_manager(self) -> None:
        photos = self._selected_photos()
        if not photos or self._albums_model.rowCount() <= 1 or self._workspace.locked:
            return
        if self._album_manager is not None:
            self._album_manager.show()
            self._album_manager.raise_()
            self._album_manager.activateWindow()
            return
        dialog = PhotoAlbumManagerDialog(
            self._workspace,
            tuple(photo.photo_id for photo in photos),
            self._theme_manager,
            self._photo_provider,
            self,
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(self._album_manager_destroyed)
        self._album_manager = dialog
        dialog.open()

    def _delete_selected_photos(self) -> None:
        photos = self._selected_photos()
        if not photos or self._workspace.locked:
            return
        expected = self._workspace.edit_revision
        count = len(photos)
        answer = QMessageBox.question(
            self,
            self.tr("Delete Photo?")
            if count == 1
            else self.tr("Delete Selected Photos?"),
            (
                self.tr(
                    "Remove this Photo from every Photo Album and delete any unshared full-resolution file from the iPod?"
                )
                if count == 1
                else self.tr(
                    "Remove these %1 Photos from every Photo Album and delete any unshared full-resolution files from the iPod?"
                ).replace("%1", str(count))
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._workspace.remove_photos(
                tuple(photo.photo_id for photo in photos),
                expected,
            )
        except ValueError as error:
            QMessageBox.warning(
                self,
                self.tr("Could Not Delete Photos"),
                workflow_text(str(error)),
            )

    def _create_photo_album(self) -> None:
        if self._workspace.photos is None or self._workspace.locked:
            return
        expected = self._workspace.edit_revision
        dialog = PhotoAlbumEditorDialog(self)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            album = self._workspace.create_photo_album(dialog.album_name, expected)
        except ValueError as error:
            QMessageBox.warning(
                self,
                self.tr("Could Not Create Photo Album"),
                workflow_text(str(error)),
            )
            return
        finally:
            dialog.deleteLater()
        self._selected_album_id = album.album_id
        self._restore_selection()

    def _refresh_create_album_state(self) -> None:
        has_photos = self._workspace.photos is not None
        has_policy = self._workspace.supports_photo_album_creation
        locked = self._workspace.locked
        self._create_album.setEnabled(has_policy and not locked)
        if locked:
            tooltip = self.tr("Wait for the current Library save to finish.")
        elif not has_photos:
            tooltip = self.tr("Choose an iPod with a readable Photo Database.")
        elif not has_policy:
            tooltip = self.tr("This iPod has no Photo Album creation policy.")
        else:
            tooltip = self.tr("Create an empty Photo Album.")
        self._create_album.setToolTip(tooltip)

    def _album_manager_destroyed(self, _value: object | None = None) -> None:
        self._album_manager = None

    def _export_selected_photo_album(self) -> None:
        if not self._source_actions:
            return
        summary = self._albums.currentIndex().data(PhotoAlbumRole.SUMMARY)
        library = self._workspace.photos
        if not isinstance(summary, PhotoAlbumSummary) or library is None:
            return
        if summary.is_all_photos:
            photos = library.photos
        else:
            album = (
                self._workspace.photo_album(summary.album_id)
                if summary.album_id is not None
                else None
            )
            by_id = {photo.photo_id: photo for photo in library.photos}
            photos = (
                ()
                if album is None
                else tuple(
                    photo
                    for photo_id in album.photo_ids
                    if (photo := by_id.get(photo_id)) is not None
                )
            )
        if photos:
            self.photoAlbumExportRequested.emit(summary.name, photos)

    def _photos_changed(self, _photos: object) -> None:
        if self._generation != self._workspace.generation:
            self._generation = self._workspace.generation
            self._selected_album_id = None
            self._selected_photo_id = None
        self._restore_selection()

    def _restore_selection(self) -> None:
        self._album_panel.set_count(max(0, self._albums_model.rowCount() - 1))
        album_index = next(
            (
                self._albums_model.index(row, 0)
                for row in range(self._albums_model.rowCount())
                if self._albums_model.index(row, 0).data(PhotoAlbumRole.ID)
                == self._selected_album_id
            ),
            self._albums_model.index(0, 0),
        )
        if album_index.isValid():
            self._albums.setCurrentIndex(album_index)
            summary = album_index.data(PhotoAlbumRole.SUMMARY)
            self._selected_album_id = (
                summary.album_id if isinstance(summary, PhotoAlbumSummary) else None
            )
            self._photos_model.set_album_id(self._selected_album_id)
        else:
            self._albums.setCurrentIndex(QModelIndex())
            self._selected_album_id = None
            self._photos_model.set_album_id(None)
        self._select_photo(self._selected_photo_id)
        self._refresh_empty_state()

    def _select_photo(self, photo_id: int | None) -> None:
        source_index = (
            self._photos_proxy.index_for_photo(photo_id)
            if photo_id is not None
            else QModelIndex()
        )
        index = (
            self._photo_grouping.mapFromSource(source_index)
            if self._photo_grouping is not None
            else source_index
        )
        if not index.isValid() and self._photos_proxy.rowCount() > 0:
            index = (
                self._photo_grouping.first_item_index()
                if self._photo_grouping is not None
                else self._photos_proxy.index(0, 0)
            )
        self._grid.setCurrentIndex(index)
        if index.isValid():
            photo = index.data(PhotoRole.PHOTO)
            if isinstance(photo, Photo):
                self._selected_photo_id = photo.photo_id
                self._inspector.set_photo(photo, self._workspace.photos)
                return
        self._selected_photo_id = None
        self._inspector.set_photo(None, self._workspace.photos)

    def _refresh_empty_state(self) -> None:
        empty = self._photos_proxy.rowCount() == 0
        self._grid_stack.setCurrentWidget(self._empty if empty else self._grid)
        if self._workspace.snapshot is None:
            message = self.tr("Connect and choose an iPod to browse its Photos.")
        elif self._workspace.photos is None:
            message = self.tr("This iPod has no readable Photo Database.")
        elif self._photo_query and self._photos_model.rowCount() > 0:
            message = self.tr("No Photos match your search.")
        elif self._selected_album_id is not None:
            message = self.tr("This Photo Album is empty.")
        else:
            message = self.tr("This iPod has no Photos.")
        self._empty.setText(message)

    def _save_splitter_state(self) -> None:
        state: QByteArray = self._splitter.saveState()
        self._settings.set_global(PHOTOS_SPLITTER_STATE, state)

    def _splitter_moved(self, _position: int, _index: int) -> None:
        self._splitter_save_timer.start()


__all__ = ["PhotoPage"]
