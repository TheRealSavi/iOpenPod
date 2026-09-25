"""Dialog for managing selected-Photo membership across user Photo Albums."""

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.photo_album_membership_model import (
    PhotoAlbumMembershipModel,
)
from iOpenPod.GUI.presentation.photo_provider import PhotoPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.photo_album_membership_grid import (
    PhotoAlbumMembershipGrid,
)
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButtonKind,
    apply_action_button_kind,
)


class PhotoAlbumManagerDialog(QDialog):
    """Apply immediate, reversible membership edits to the Library Draft."""

    def __init__(
        self,
        workspace: LibraryWorkspace,
        photo_ids: tuple[int, ...],
        theme_manager: ThemeManager,
        photo_provider: PhotoPixmapProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not photo_ids:
            raise ValueError("Select at least one Photo to manage its Photo Albums.")
        self.setObjectName("photoAlbumManager")
        self.setModal(True)
        self.resize(780, 560)
        self.setMinimumSize(560, 400)
        self._workspace = workspace
        self._generation = workspace.generation
        self._model = PhotoAlbumMembershipModel(workspace, photo_ids, self)

        self._description = QLabel(self)
        self._description.setObjectName("pageDescription")
        self._description.setWordWrap(True)
        self._grid = PhotoAlbumMembershipGrid(
            self._model,
            theme_manager,
            photo_provider,
            self,
        )
        self._empty = QLabel(self)
        self._empty.setObjectName("photoAlbumManagerEmpty")
        self._empty.setWordWrap(True)
        self._error = QLabel(self)
        self._error.setObjectName("photoAlbumManagerError")
        self._error.setWordWrap(True)

        self._buttons = QDialogButtonBox(self)
        self._done = self._buttons.addButton(
            "",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        apply_action_button_kind(self._done, ActionButtonKind.PRIMARY)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
        )
        layout.setSpacing(LAYOUT.space_sm)
        layout.addWidget(self._description)
        layout.addWidget(self._grid, 1)
        layout.addWidget(self._empty, 1)
        layout.addWidget(self._error)
        layout.addWidget(self._buttons)

        self._buttons.accepted.connect(self.accept)
        self._model.membershipEditFailed.connect(self._show_error)
        self._model.modelReset.connect(self._refresh_empty_state)
        workspace.changed.connect(self._workspace_changed)
        workspace.photosChanged.connect(self._photos_changed)
        self.retranslate_ui()
        self._refresh_empty_state()
        self._workspace_changed()

    @property
    def model(self) -> PhotoAlbumMembershipModel:
        return self._model

    @property
    def grid(self) -> PhotoAlbumMembershipGrid:
        return self._grid

    def retranslate_ui(self) -> None:
        count = len(self._model.photo_ids)
        self.setWindowTitle(self.tr("Manage Albums"))
        self._description.setText(
            self.tr("Choose which Photo Albums contain this Photo.")
            if count == 1
            else self.tr(
                "Choose which Photo Albums contain the %n selected Photos.",
                None,
                count,
            )
        )
        self._empty.setText(self.tr("This iPod has no user Photo Albums."))
        self._done.setText(self.tr("Done"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _workspace_changed(self) -> None:
        if self._generation != self._workspace.generation:
            self.reject()
            return
        self._grid.setEnabled(not self._workspace.locked)

    def _photos_changed(self, _photos: object) -> None:
        if self._generation != self._workspace.generation:
            self.reject()

    def _refresh_empty_state(self) -> None:
        empty = self._model.rowCount() == 0
        self._grid.setVisible(not empty)
        self._empty.setVisible(empty)

    def _show_error(self, message: str) -> None:
        self._error.setText(message)


__all__ = ["PhotoAlbumManagerDialog"]
