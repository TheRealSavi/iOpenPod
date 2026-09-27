"""A familiar source-list sidebar for Playlists and nested folders."""

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.library_drag import TrackSelectionMimeData
from iOpenPod.app.models.playlist_tree_model import PlaylistRole, PlaylistTreeModel
from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import (
    IconButton,
    IconButtonKind,
    NavigationButton,
)
from iPodDB.library import PlaylistKind

_SPRING_LOAD_DELAY_MS = 500


def _disclosure_rect(rect: QRect) -> QRect:
    return QRect(
        rect.right() - LAYOUT.control_height_compact + 1,
        rect.top(),
        LAYOUT.control_height_compact,
        rect.height(),
    )


def _paint_disclosure(
    painter: QPainter, rect: QRect, *, expanded: bool, color: QColor
) -> None:
    """Paint only the chevron; the containing row owns its background."""

    center = QRectF(rect).center()
    span = LAYOUT.space_2xs
    path = QPainterPath()
    if expanded:
        path.moveTo(center.x() - span, center.y() - span / 2)
        path.lineTo(center.x(), center.y() + span / 2)
        path.lineTo(center.x() + span, center.y() - span / 2)
    else:
        path.moveTo(center.x() - span / 2, center.y() - span)
        path.lineTo(center.x() + span / 2, center.y())
        path.lineTo(center.x() - span / 2, center.y() + span)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawPath(path)
    painter.restore()


class _PlaylistSectionButton(NavigationButton):
    def __init__(
        self,
        text: str,
        glyph: str,
        workspace: LibraryWorkspace,
        parent: QWidget,
    ) -> None:
        super().__init__(text, glyph, parent)
        self._workspace = workspace
        self._spring_data: TrackSelectionMimeData | None = None
        self._spring_timer = QTimer(self)
        self._spring_timer.setSingleShot(True)
        self._spring_timer.setInterval(_SPRING_LOAD_DELAY_MS)
        self._spring_timer.timeout.connect(self._spring_open)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._continue_spring_load(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        self._cancel_spring_load()
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._continue_spring_load(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        self._cancel_spring_load()
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._cancel_spring_load()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._cancel_spring_load()
        event.ignore()

    def _continue_spring_load(self, data: object) -> bool:
        if (
            self.isChecked()
            or not isinstance(data, TrackSelectionMimeData)
            or not data.belongs_to(self._workspace)
        ):
            return False
        self._spring_data = data
        if not self._spring_timer.isActive():
            self._spring_timer.start()
        return True

    def _cancel_spring_load(self) -> None:
        self._spring_timer.stop()
        self._spring_data = None

    def _spring_open(self) -> None:
        data = self._spring_data
        self._spring_data = None
        if (
            not self.isChecked()
            and data is not None
            and data.belongs_to(self._workspace)
        ):
            self.setChecked(True)

    def _refresh_icon(self) -> None:
        group = (
            QPalette.ColorGroup.Active
            if self.isEnabled()
            else QPalette.ColorGroup.Disabled
        )
        self.setIcon(
            glyph_icon(
                self._glyph,
                LAYOUT.icon_size,
                self.palette().color(group, QPalette.ColorRole.ButtonText),
                self.devicePixelRatioF(),
            )
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        _paint_disclosure(
            painter,
            _disclosure_rect(self.rect()),
            expanded=self.isChecked(),
            color=self.palette().color(QPalette.ColorRole.ButtonText),
        )


class _PlaylistDelegate(QStyledItemDelegate):
    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        view = option.widget
        if not isinstance(view, QTreeView):
            return
        option = QStyleOptionViewItem(option)
        self.initStyleOption(option, index)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        color = option.palette.color(
            QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        )
        row = QRectF(option.rect).adjusted(0, 1, 0, -1)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if selected or option.state & QStyle.StateFlag.State_MouseOver:
            painter.setBrush(
                option.palette.color(
                    QPalette.ColorRole.Highlight
                    if selected
                    else QPalette.ColorRole.AlternateBase
                )
            )
            painter.drawRoundedRect(row, LAYOUT.radius_control, LAYOUT.radius_control)
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(QPen(option.palette.color(QPalette.ColorRole.Accent), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                row.adjusted(1, 1, -1, -1),
                LAYOUT.radius_control,
                LAYOUT.radius_control,
            )

        depth = 1
        parent = index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        # Keep a readable label at narrow widths even for deeply nested folders.
        left = min(
            LAYOUT.space_xs + depth * LAYOUT.space_md,
            max(LAYOUT.space_xs, option.rect.width() // 3),
        )
        icon_rect = QRect(
            left,
            option.rect.top() + (option.rect.height() - LAYOUT.icon_size) // 2,
            LAYOUT.icon_size,
            LAYOUT.icon_size,
        )
        kind = index.data(PlaylistRole.KIND)
        glyph = {
            PlaylistKind.PLAYLIST: "playlist",
            PlaylistKind.SMART: "smart-playlist",
            PlaylistKind.FOLDER: "folder",
        }.get(kind, "playlist")
        glyph_icon(glyph, LAYOUT.icon_size, color, view.devicePixelRatioF()).paint(
            painter, icon_rect
        )
        text_rect = option.rect.adjusted(
            icon_rect.right() + LAYOUT.space_xs, 0, -LAYOUT.control_height_compact, 0
        )
        painter.setPen(color)
        painter.setFont(option.font)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            option.fontMetrics.elidedText(
                option.text, Qt.TextElideMode.ElideRight, max(0, text_rect.width())
            ),
        )
        if index.model().hasChildren(index):
            _paint_disclosure(
                painter,
                _disclosure_rect(option.rect),
                expanded=view.isExpanded(index),
                color=color,
            )
        painter.restore()

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        del index
        return QSize(
            0,
            max(
                option.fontMetrics.height() + 2 * LAYOUT.space_2xs,
                LAYOUT.control_height_compact,
            ),
        )


class _PlaylistView(QTreeView):
    """Keep native tree navigation and drag/drop with one painted row surface."""

    def __init__(
        self,
        workspace: LibraryWorkspace,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._reclicked_folder = QPersistentModelIndex()
        self._spring_index = QPersistentModelIndex()
        self._spring_data: TrackSelectionMimeData | None = None
        self._spring_timer = QTimer(self)
        self._spring_timer.setSingleShot(True)
        self._spring_timer.setInterval(_SPRING_LOAD_DELAY_MS)
        self._spring_timer.timeout.connect(self._spring_open)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        super().dragEnterEvent(event)
        data = event.mimeData()
        if isinstance(data, TrackSelectionMimeData) and data.belongs_to(
            self._workspace
        ):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        super().dragMoveEvent(event)
        data = event.mimeData()
        if not isinstance(data, TrackSelectionMimeData) or not data.belongs_to(
            self._workspace
        ):
            self._cancel_spring_load()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        index = self.indexAt(event.position().toPoint())
        if (
            not index.isValid()
            or index.data(PlaylistRole.KIND) != PlaylistKind.FOLDER
            or not self.model().hasChildren(index)
            or self.isExpanded(index)
        ):
            self._cancel_spring_load()
            return
        persistent = QPersistentModelIndex(index)
        if persistent != self._spring_index:
            self._spring_index = persistent
            self._spring_data = data
            self._spring_timer.start()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._cancel_spring_load()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._cancel_spring_load()
        data = event.mimeData()
        if isinstance(data, TrackSelectionMimeData) and data.belongs_to(
            self._workspace
        ):
            model = self.model()
            target = self.indexAt(event.position().toPoint())
            if model.dropMimeData(
                data,
                Qt.DropAction.CopyAction,
                -1,
                0,
                target,
            ):
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
            else:
                event.ignore()
            return
        super().dropEvent(event)

    def _cancel_spring_load(self) -> None:
        self._spring_timer.stop()
        self._spring_index = QPersistentModelIndex()
        self._spring_data = None

    def _spring_open(self) -> None:
        index = self._spring_index
        data = self._spring_data
        self._cancel_spring_load()
        if (
            index.isValid()
            and data is not None
            and data.belongs_to(self._workspace)
            and not self.isExpanded(index)
        ):
            self.setExpanded(index, True)

    def drawBranches(
        self,
        painter: QPainter,
        rect: QRect,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        # Qt's branch primitive paints its own selection background on some styles.
        # Disclosure and indentation are both drawn by the row delegate instead.
        pass

    def mousePressEvent(self, event: QMouseEvent) -> None:
        index = self.indexAt(event.position().toPoint())
        folder_clicked = (
            event.button() == Qt.MouseButton.LeftButton
            and index.isValid()
            and self.model().hasChildren(index)
        )
        self._reclicked_folder = (
            QPersistentModelIndex(index)
            if folder_clicked and index == self.currentIndex()
            else QPersistentModelIndex()
        )
        if folder_clicked and _disclosure_rect(self.visualRect(index)).contains(
            event.position().toPoint()
        ):
            self._reclicked_folder = QPersistentModelIndex()
            self.setExpanded(index, not self.isExpanded(index))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        reclicked_folder = self._reclicked_folder
        self._reclicked_folder = QPersistentModelIndex()
        index = self.indexAt(event.position().toPoint())
        super().mouseReleaseEvent(event)
        if (
            event.button() == Qt.MouseButton.LeftButton
            and reclicked_folder.isValid()
            and reclicked_folder == index
        ):
            self.setExpanded(index, not self.isExpanded(index))

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        self._reclicked_folder = QPersistentModelIndex()
        super().startDrag(supported_actions)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.mousePressEvent(event)

    def scrollTo(
        self,
        index: QModelIndex | QPersistentModelIndex,
        hint: QAbstractItemView.ScrollHint = QAbstractItemView.ScrollHint.EnsureVisible,
    ) -> None:
        super().scrollTo(index, hint)
        # Expansion changes the outer layout; reveal after it has resized the
        # scroll content, rather than clamping to the old scrollbar range.
        QTimer.singleShot(0, self._reveal_current)

    def _reveal_current(self) -> None:
        index = self.currentIndex()
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        content = parent.widget() if parent is not None else None
        if parent is not None and content is not None and index.isValid():
            row = self.visualRect(index)
            point = self.viewport().mapTo(content, row.center())
            parent.ensureVisible(point.x(), point.y(), 0, row.height())


class PlaylistTree(QWidget):
    """Render the Workspace and emit editing intents for the application shell."""

    selected = Signal(object)
    createRequested = Signal(object)
    editRequested = Signal(object)
    removeRequested = Signal(object)

    def __init__(
        self,
        workspace: LibraryWorkspace,
        parent: QWidget | None = None,
        *,
        show_add_button: bool = True,
        show_context_menu: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("playlistSidebar")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._workspace = workspace
        self._generation = workspace.generation
        self._selected_id: int | None = None
        self._expanded_ids: set[int] = set()
        self._resetting = False
        self._model = PlaylistTreeModel(workspace, self)

        self._heading = _PlaylistSectionButton(
            self.tr("Playlists"), "playlist", workspace, self
        )
        self._heading.setObjectName("playlistSectionToggle")
        self._heading.setChecked(False)
        self._add = IconButton(
            "plus",
            self.tr("New Playlist"),
            self._heading,
            kind=IconButtonKind.QUIET,
        )
        self._add.setObjectName("newPlaylistButton")
        self._add.setVisible(show_add_button)
        self._add.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._create_menu = QMenu(self._add)
        self._create_actions: dict[PlaylistKind, QAction] = {}
        for kind in PlaylistKind:
            action = QAction(self._create_menu)
            action.setData(kind)
            action.triggered.connect(
                lambda _checked=False, kind=kind: self.createRequested.emit(kind)
            )
            self._create_menu.addAction(action)
            self._create_actions[kind] = action
        self._add.setMenu(self._create_menu)

        heading = QHBoxLayout(self._heading)
        heading.setContentsMargins(0, 0, LAYOUT.control_height_compact, 0)
        heading.setSpacing(0)
        heading.addStretch(1)
        heading.addWidget(self._add)

        self._tree = _PlaylistView(workspace, self)
        self._tree.setObjectName("playlistTree")
        self._tree.setModel(self._model)
        self._tree.setItemDelegate(_PlaylistDelegate(self._tree))
        self._tree.setHeaderHidden(True)
        self._tree.setFrameShape(QFrame.Shape.NoFrame)
        self._tree.setUniformRowHeights(True)
        self._tree.setAnimated(False)
        self._tree.setRootIsDecorated(False)
        self._tree.setIndentation(0)
        self._tree.setExpandsOnDoubleClick(False)
        self._tree.setIconSize(QSize(LAYOUT.icon_size, LAYOUT.icon_size))
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tree.setDragEnabled(True)
        self._tree.setAcceptDrops(True)
        self._tree.setDropIndicatorShown(True)
        self._tree.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._tree.setDragDropOverwriteMode(False)
        self._tree.setAutoExpandDelay(_SPRING_LOAD_DELAY_MS)
        self._tree.setMouseTracking(True)
        self._tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
            if show_context_menu
            else Qt.ContextMenuPolicy.PreventContextMenu
        )
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.selectionModel().currentChanged.connect(self._current_changed)
        self._tree.expanded.connect(self._folder_expanded)
        self._tree.collapsed.connect(self._folder_collapsed)
        self._model.modelAboutToBeReset.connect(self._before_reset)
        self._model.modelReset.connect(self._after_reset)

        self._edit_action = QAction(self)
        self._edit_action.setShortcut(QKeySequence(Qt.Key.Key_F2))
        self._edit_action.setShortcutContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self._edit_action.triggered.connect(self._edit_current)
        self.addAction(self._edit_action)

        self._empty = QLabel(self)
        self._empty.setObjectName("playlistSidebarEmpty")
        self._empty.setWordWrap(True)
        self._empty.setContentsMargins(
            LAYOUT.space_xs, 0, LAYOUT.space_xs, LAYOUT.space_xs
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_2xs)
        layout.addWidget(self._heading)
        layout.addWidget(self._empty)
        layout.addWidget(self._tree)
        self._heading.toggled.connect(self._refresh_empty_state)
        self.retranslate_ui()
        self._refresh_empty_state()

    def set_drag_drop_enabled(self, enabled: bool) -> None:
        """Enable reordering for editable workspaces or disable it for Sync browsing."""

        self._tree.setDragEnabled(enabled)
        self._tree.setAcceptDrops(enabled)
        self._tree.setDropIndicatorShown(enabled)
        self._tree.setDragDropMode(
            QAbstractItemView.DragDropMode.DragDrop
            if enabled
            else QAbstractItemView.DragDropMode.NoDragDrop
        )

    @property
    def current_playlist_id(self) -> int | None:
        return self._selected_id

    def select_playlist(self, playlist_id: int) -> None:
        index = self._model.index_for_id(playlist_id)
        if not index.isValid():
            return
        self._heading.setChecked(True)
        parent = index.parent()
        while parent.isValid():
            self._tree.expand(parent)
            parent = parent.parent()
        self._update_tree_height()
        self._tree.setCurrentIndex(index)
        self._tree.scrollTo(index)

    def clear_selection(self) -> None:
        self._tree.clearSelection()
        self._tree.setCurrentIndex(QModelIndex())
        self._selected_id = None

    def retranslate_ui(self) -> None:
        self._model.retranslate()
        self._heading.setText(self.tr("Playlists"))
        self._add.setAccessibleName(self.tr("New Playlist"))
        self._add.setToolTip(self.tr("New Playlist"))
        self._tree.setAccessibleName(self.tr("Playlists and Folders"))
        self._edit_action.setText(self.tr("Edit Playlist…"))
        self._create_actions[PlaylistKind.PLAYLIST].setText(self.tr("New Playlist…"))
        self._create_actions[PlaylistKind.SMART].setText(self.tr("New Smart Playlist…"))
        self._create_actions[PlaylistKind.FOLDER].setText(self.tr("New Folder…"))
        self._refresh_empty_state()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        if event.type() in {QEvent.Type.FontChange, QEvent.Type.StyleChange}:
            self._update_tree_height()
        super().changeEvent(event)

    def _current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if self._resetting:
            return
        self._selected_id = self._model.playlist_id(current)
        if self._selected_id is not None:
            self.selected.emit(self._selected_id)

    def _folder_expanded(self, index: QModelIndex) -> None:
        playlist_id = self._model.playlist_id(index)
        if playlist_id is not None:
            self._expanded_ids.add(playlist_id)
        self._update_tree_height()

    def _folder_collapsed(self, index: QModelIndex) -> None:
        if not self._resetting:
            playlist_id = self._model.playlist_id(index)
            if playlist_id is not None:
                self._expanded_ids.discard(playlist_id)
        self._update_tree_height()

    def _before_reset(self) -> None:
        self._resetting = True

    def _after_reset(self) -> None:
        if self._generation != self._workspace.generation:
            self._generation = self._workspace.generation
            mapping = self._workspace.saved_playlist_ids
            if mapping is None:
                self._expanded_ids.clear()
                self._selected_id = None
            else:
                self._expanded_ids = {mapping.get(i, i) for i in self._expanded_ids}
                if self._selected_id is not None:
                    self._selected_id = mapping.get(
                        self._selected_id, self._selected_id
                    )
        for playlist_id in tuple(self._expanded_ids):
            index = self._model.index_for_id(playlist_id)
            if index.isValid():
                self._tree.expand(index)
            else:
                self._expanded_ids.discard(playlist_id)
        if self._selected_id is not None:
            index = self._model.index_for_id(self._selected_id)
            if index.isValid():
                self._tree.setCurrentIndex(index)
            else:
                self._selected_id = None
        self._resetting = False
        self._refresh_empty_state()

    def _refresh_empty_state(self) -> None:
        available = self._workspace.snapshot is not None
        self._add.setEnabled(available and not self._workspace.locked)
        expanded = self._heading.isChecked()
        self._heading.setToolTip(
            self.tr("Collapse Playlists") if expanded else self.tr("Expand Playlists")
        )
        self._empty.setVisible(expanded and not self._workspace.playlists)
        self._empty.setText(
            self.tr("Add a playlist to start organizing your music.")
            if available
            else self.tr("Choose an iPod to see your playlists.")
        )
        self._tree.setVisible(expanded and bool(self._workspace.playlists))
        self._update_tree_height()

    def _update_tree_height(self) -> None:
        """Let the sidebar scroll the complete navigation as one surface."""

        count = 0
        parents = [QModelIndex()]
        while parents:
            parent = parents.pop()
            rows = self._model.rowCount(parent)
            count += rows
            for row in range(rows):
                index = self._model.index(row, 0, parent)
                if self._tree.isExpanded(index):
                    parents.append(index)
        height = max(
            self._tree.fontMetrics().height() + 2 * LAYOUT.space_2xs,
            LAYOUT.control_height_compact,
        )
        self._tree.setFixedHeight(count * height)

    def _edit_current(self) -> None:
        if self._selected_id is not None and not self._workspace.locked:
            self.editRequested.emit(self._selected_id)

    def _build_context_menu(self, position: QPoint) -> QMenu:
        index = self._tree.indexAt(position)
        playlist_id = self._model.playlist_id(index)
        menu = QMenu(self)
        menu.setEnabled(not self._workspace.locked)
        if playlist_id is None:
            for action in self._create_menu.actions():
                menu.addAction(action)
            menu.setEnabled(
                self._workspace.snapshot is not None and not self._workspace.locked
            )
            return menu
        self.select_playlist(playlist_id)
        generation = self._workspace.generation
        revision = self._workspace.revision
        kind = index.data(PlaylistRole.KIND)
        edit_label = (
            self.tr("Rename Folder…")
            if kind == PlaylistKind.FOLDER
            else self.tr("Edit Smart Playlist…")
            if kind == PlaylistKind.SMART
            else self.tr("Edit Playlist…")
        )
        edit = menu.addAction(edit_label)
        edit.triggered.connect(
            lambda _checked=False: self._request_edit(playlist_id, generation)
        )
        if index.parent().isValid():
            move = menu.addAction(self.tr("Move to Top Level"))
            move.setEnabled(self._workspace.can_move(playlist_id, None))
            move.triggered.connect(
                lambda _checked=False: self._move_to_root(playlist_id, generation)
            )
        menu.addSeparator()
        remove = menu.addAction(
            self.tr("Remove Folder…")
            if kind == PlaylistKind.FOLDER
            else self.tr("Remove Playlist…")
        )
        remove.triggered.connect(
            lambda _checked=False: self._request_remove(
                playlist_id, generation, revision
            )
        )
        return menu

    def _request_edit(self, playlist_id: int, generation: int) -> None:
        if generation == self._workspace.generation:
            self.editRequested.emit(playlist_id)

    def _move_to_root(self, playlist_id: int, generation: int) -> None:
        if generation == self._workspace.generation and self._workspace.can_move(
            playlist_id, None
        ):
            self._workspace.move(playlist_id, None)

    def _request_remove(self, playlist_id: int, generation: int, revision: int) -> None:
        if (
            generation == self._workspace.generation
            and revision == self._workspace.revision
            and not self._workspace.locked
            and self._workspace.playlist(playlist_id) is not None
        ):
            self.removeRequested.emit(playlist_id)

    def _show_context_menu(self, position: QPoint) -> None:
        menu = self._build_context_menu(position)
        menu.exec(self._tree.viewport().mapToGlobal(position))
        menu.deleteLater()


__all__ = ["PlaylistTree"]
