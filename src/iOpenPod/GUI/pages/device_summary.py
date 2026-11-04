"""An Apple-inspired device portrait and Active iPod summary.

Hallmark: left product portrait and aligned specification list; existing theme;
side-rail navigation; capacity-strip footer; no decorative motion.
Pre-emit critique: philosophy 4, hierarchy 4, execution 4, specificity 5,
restraint 5, variety 4. Desktop pane reflow checked from 320 to 1200 pixels.
"""

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent, QResizeEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.library_workspace import EditRevision, LibraryWorkspace
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.services.device_summary import device_storage_breakdown
from iOpenPod.GUI.presentation.device_images import device_pixmap
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.browser_chrome import PageHeader
from iOpenPod.GUI.widgets.storage_breakdown import StorageBreakdown, format_capacity
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, IconButton, IconButtonKind


class DeviceSummaryPage(QWidget):
    """Compose device observations and revision-bound Library name editing."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        theme: ThemeManager,
        workspace: LibraryWorkspace | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("deviceSummaryPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._theme = theme
        self._active: ActiveIPod | None = None
        self._draft_name = ""
        self._workspace = workspace
        self._rename_revision: EditRevision | None = None
        self._busy = False
        self._header = PageHeader(self)
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("deviceSummaryScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        canvas = QWidget()
        canvas.setObjectName("deviceSummaryCanvas")
        canvas_layout = QHBoxLayout(canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        self._body = QWidget(canvas)
        canvas_layout.addWidget(self._body, 1)
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self._empty_title = self._label("deviceSummaryEmptyTitle")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_detail = self._label("deviceSummaryModel")
        self._empty_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(self._empty_title)
        body.addWidget(self._empty_detail)
        self._surface = QFrame(self._body)
        self._surface.setObjectName("deviceSummarySurface")
        self._surface_layout = QHBoxLayout(self._surface)
        self._identity_content = QWidget(self._surface)
        self._identity_content.setMaximumWidth(LAYOUT.device_summary_identity_width)
        self._identity = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._identity.setSpacing(LAYOUT.space_2xl)
        self._identity.setContentsMargins(0, 0, 0, 0)
        self._identity_content.setLayout(self._identity)
        self._surface_layout.addStretch(0)
        self._surface_layout.addWidget(self._identity_content, 1)
        self._surface_layout.addStretch(0)
        self._portrait = QLabel(self._body)
        self._portrait.setObjectName("deviceSummaryPortrait")
        self._portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._portrait.setFixedSize(
            LAYOUT.device_summary_image_size, LAYOUT.device_summary_image_size
        )
        self._identity.addWidget(self._portrait, 0, Qt.AlignmentFlag.AlignCenter)
        self._details = QWidget(self._body)
        self._grid = QGridLayout(self._details)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(LAYOUT.space_xs)
        self._grid.setVerticalSpacing(LAYOUT.space_xs)
        self._grid.setColumnStretch(1, 1)
        self._fields: list[tuple[QLabel, QLabel]] = []
        for index, key in enumerate(
            (
                "name",
                "capacity",
                "firmware",
                "serial",
                "model",
                "model_name",
                "finish",
            )
        ):
            label = self._label("deviceSummaryFieldLabel", self._details)
            label.setWordWrap(False)
            label.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
            )
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            value = self._label(
                "deviceSummaryName" if key == "name" else f"deviceSummary_{key}",
                self._details,
            )
            value.setProperty("deviceSummaryValue", True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._grid.addWidget(label, index, 0)
            self._grid.addWidget(value, index, 1)
            self._fields.append((label, value))
        self._name = self._fields[0][1]
        self._fields[0][0].setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._grid.removeWidget(self._name)
        name_panel = QWidget(self._details)
        name_layout = QVBoxLayout(name_panel)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(LAYOUT.space_2xs)
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(LAYOUT.space_2xs)
        self._name_edit = QLineEdit(name_panel)
        self._name_edit.setObjectName("deviceSummaryNameEdit")
        self._name_edit.setMinimumWidth(0)
        self._name_edit.installEventFilter(self)
        self._name_edit.editingFinished.connect(self._finish_rename)
        self._rename = IconButton("pencil", "", name_panel, kind=IconButtonKind.QUIET)
        self._rename.setObjectName("deviceSummaryRename")
        self._rename.clicked.connect(self._start_rename)
        self._rename_apply = IconButton("check-circle", "", name_panel)
        self._rename_apply.setObjectName("deviceSummaryRenameApply")
        self._rename_apply.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._rename_apply.clicked.connect(self._finish_rename)
        self._rename_cancel = IconButton("x", "", name_panel)
        self._rename_cancel.setObjectName("deviceSummaryRenameCancel")
        self._rename_cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._rename_cancel.clicked.connect(self._cancel_rename)
        name_row.addWidget(self._name, 1)
        name_row.addWidget(self._name_edit, 1)
        name_row.addWidget(self._rename)
        name_row.addWidget(self._rename_apply)
        name_row.addWidget(self._rename_cancel)
        self._name_spacer = QWidget(name_panel)
        name_row.addWidget(self._name_spacer, 1)
        self._rename_feedback = self._label("renameIPodFeedback", name_panel)
        self._rename_feedback.setProperty("error", True)
        name_layout.addLayout(name_row)
        name_layout.addWidget(self._rename_feedback)
        self._grid.addWidget(name_panel, 0, 1)
        self._cancel_rename()
        self._identity.addWidget(self._details, 1, Qt.AlignmentFlag.AlignVCenter)
        surface_row = QHBoxLayout()
        surface_row.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, 0
        )
        surface_row.addWidget(self._surface)
        body.addLayout(surface_row)
        self._restore_row = QFrame(self._body)
        self._restore_row.setObjectName("deviceRestoreRow")
        restore_layout = QHBoxLayout(self._restore_row)
        restore_layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        restore_layout.setSpacing(LAYOUT.space_sm)
        self._restore = ActionButton(parent=self._restore_row)
        self._restore.setObjectName("restoreDevice")
        self._restore.setEnabled(False)
        self._coming_soon = self._label("deviceRestoreComingSoon", self._restore_row)
        restore_layout.addWidget(self._restore)
        restore_layout.addWidget(self._coming_soon, 1)
        restore_surface_row = QHBoxLayout()
        restore_surface_row.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        restore_surface_row.addWidget(self._restore_row)
        body.addLayout(restore_surface_row)
        body.addStretch(1)
        self._scroll.setWidget(canvas)
        self._storage = StorageBreakdown(theme, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(self._storage)
        theme.deviceArtworkChanged.connect(self._refresh_portrait)
        if workspace is not None:
            workspace.changed.connect(self._rename_state_changed)
        self.retranslate_ui()

    def _label(self, name: str, parent: QWidget | None = None) -> QLabel:
        label = QLabel(parent or self._body)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    def set_active_ipod(self, active: ActiveIPod | None) -> None:
        self._cancel_rename()
        self._active = active
        self._draft_name = ""
        self._refresh()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._rename_state_changed()

    def _can_rename(self) -> bool:
        workspace = self._workspace
        return (
            self._active is not None
            and workspace is not None
            and workspace.snapshot is not None
            and not workspace.locked
            and not self._busy
        )

    def _rename_state_changed(self) -> None:
        workspace = self._workspace
        if self._rename_revision is not None and (
            not self._can_rename()
            or workspace is None
            or self._rename_revision.generation != workspace.generation
        ):
            self._cancel_rename()
        self._rename.setEnabled(self._can_rename())
        self._refresh_name()

    def _start_rename(self) -> None:
        workspace = self._workspace
        if not self._can_rename() or workspace is None:
            return
        self._rename_revision = workspace.edit_revision
        self._name_edit.setText(self._name.text())
        self._name.hide()
        self._rename.hide()
        self._name_spacer.hide()
        self._name_edit.show()
        self._rename_apply.show()
        self._rename_cancel.show()
        self._name_edit.selectAll()
        self._name_edit.setFocus()

    def _cancel_rename(self) -> None:
        self._rename_revision = None
        self._name_edit.hide()
        self._rename_apply.hide()
        self._rename_cancel.hide()
        self._rename_feedback.hide()
        self._name.show()
        self._rename.show()
        self._name_spacer.show()
        self._rename.setEnabled(self._can_rename())
        self._refresh_name()

    def _finish_rename(self) -> None:
        workspace, revision = self._workspace, self._rename_revision
        if workspace is None or revision is None:
            return
        try:
            workspace.rename_device(self._name_edit.text().strip(), revision)
        except ValueError as error:
            self._rename_feedback.setText(workflow_text(str(error)))
            self._rename_feedback.show()
            self._name_edit.setFocus()
            return
        self._cancel_rename()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self._name_edit
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
        ):
            self._cancel_rename()
            return True
        return super().eventFilter(watched, event)

    def set_device_name(self, name: str) -> None:
        """Reflect a name edit; capacity stays tied to the saved device state."""
        self._draft_name = name.strip()
        self._refresh_name()

    def retranslate_ui(self) -> None:
        self._name_edit.setAccessibleName(
            QCoreApplication.translate("DeviceCard", "iPod name")
        )
        for button, text in (
            (self._rename, QCoreApplication.translate("DeviceCard", "Rename iPod")),
            (
                self._rename_apply,
                QCoreApplication.translate("DeviceCard", "Apply iPod name"),
            ),
            (
                self._rename_cancel,
                QCoreApplication.translate("DeviceCard", "Cancel renaming"),
            ),
        ):
            button.setAccessibleName(text)
            button.setToolTip(text)
        self._header.set_title(self.tr("Summary"))
        self._restore.setText(self.tr("Restore iPod"))
        self._restore.setToolTip(self.tr("Coming soon"))
        self._coming_soon.setText(self.tr("Coming soon"))
        self._empty_title.setText(self.tr("No Active iPod"))
        self._empty_detail.setText(
            self.tr("Choose an iPod from the sidebar to see its details.")
        )
        labels = (
            self.tr("Name"),
            self.tr("Capacity"),
            self.tr("Software version"),
            self.tr("Serial number"),
            self.tr("Model number"),
            self.tr("Model"),
            self.tr("Color"),
        )
        for (label, _), text in zip(self._fields, labels, strict=True):
            label.setText(f"{text}:")
        self._refresh()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        elif event.type() in {
            QEvent.Type.DevicePixelRatioChange,
            QEvent.Type.ScreenChangeInternal,
        }:
            self._refresh_portrait()
        super().changeEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        for label, _ in self._fields:
            label.setWordWrap(self.width() < 480)
        padding = LAYOUT.space_xs if self.width() < 480 else LAYOUT.space_lg
        self._surface_layout.setContentsMargins(
            padding, LAYOUT.space_md, padding, LAYOUT.space_md
        )
        image_size = min(
            LAYOUT.device_summary_image_size,
            max(
                128,
                self.width()
                - 2 * LAYOUT.space_lg
                - 2 * padding
                - LAYOUT.scrollbar_extent
                - 2 * LAYOUT.device_summary_border_width,
            ),
        )
        if self._portrait.width() != image_size:
            self._portrait.setFixedSize(image_size, image_size)
            self._refresh_portrait()
        self._identity.setDirection(
            QBoxLayout.Direction.LeftToRight
            if self.width() >= 760
            else QBoxLayout.Direction.TopToBottom
        )

    def _refresh_name(self) -> None:
        active = self._active
        workspace = self._workspace
        name = (
            workspace.device_name
            if workspace is not None and workspace.snapshot is not None
            else self._draft_name
        )
        self._name.setText(
            (name or active.display_name) if active else self.tr("No Active iPod")
        )

        self._name.setMaximumWidth(
            self._name.fontMetrics().horizontalAdvance(self._name.text())
            + LAYOUT.space_2xs
        )

    def _refresh(self) -> None:
        active = self._active
        self._empty_title.setVisible(active is None)
        self._empty_detail.setVisible(active is None)
        self._details.setVisible(active is not None)
        self._restore_row.setVisible(active is not None)
        self._refresh_portrait()
        values = ("—",) * len(self._fields)
        if active is not None:
            values = (
                active.display_name,
                format_capacity(active.candidate.total_bytes)
                if active.candidate.total_bytes > 0
                else self.tr("Unavailable"),
                active.firmware_version or self.tr("Unavailable"),
                active.serial_number or self.tr("Unavailable"),
                active.profile.model_number,
                active.profile.display_name,
                active.profile.finish,
            )
        for (label, value), text in zip(self._fields, values, strict=True):
            value.setText(text)
            value.setAccessibleName(label.text().removesuffix(":"))
        self._refresh_name()
        self._rename_state_changed()
        self._storage.set_breakdown(
            device_storage_breakdown(
                active.candidate,
                active.library,
                game_storage_bytes=active.game_storage_bytes,
                album_artwork_storage_bytes=active.album_artwork_storage_bytes,
            )
            if active
            else None
        )

    def _refresh_portrait(self) -> None:
        active = self._active
        self._portrait.setPixmap(
            device_pixmap(
                active.profile.product_image if active else "iPodGeneric.png",
                self._portrait.width(),
                self.devicePixelRatioF(),
                itunes_107=self._theme.itunes_107_artwork,
            )
        )
        self._portrait.setAccessibleName(
            active.profile.display_name if active else self.tr("iPod")
        )
