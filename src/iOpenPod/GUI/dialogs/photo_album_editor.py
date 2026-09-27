"""Themed name editor for creating or renaming one Photo Album."""

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButtonKind,
    apply_action_button_kind,
)


class PhotoAlbumEditorDialog(QDialog):
    """Collect a Photo Album name using the shared dialog visual language."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        album_name: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._renaming = album_name is not None
        self.setObjectName("photoAlbumEditor")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.resize(460, 260)

        self._title = QLabel(self)
        self._title.setObjectName("dialogTitle")
        self._description = QLabel(self)
        self._description.setObjectName("pageDescription")
        self._description.setWordWrap(True)
        self._name_label = QLabel(self)
        self.name = QLineEdit(self)
        self.name.setObjectName("photoAlbumName")
        self.name.setClearButtonEnabled(True)
        self._name_label.setBuddy(self.name)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self._buttons.setObjectName("photoAlbumEditorButtons")
        self._create = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        self._cancel = self._buttons.button(QDialogButtonBox.StandardButton.Cancel)
        apply_action_button_kind(self._create, ActionButtonKind.PRIMARY)
        apply_action_button_kind(self._cancel, ActionButtonKind.SECONDARY)
        self._create.setDefault(True)
        self._create.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
        )
        layout.setSpacing(LAYOUT.space_sm)
        layout.addWidget(self._title)
        layout.addWidget(self._description)
        layout.addSpacing(LAYOUT.space_xs)
        layout.addWidget(self._name_label)
        layout.addWidget(self.name)
        layout.addStretch(1)
        layout.addWidget(self._buttons)

        self.name.textChanged.connect(self._name_changed)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self.retranslate_ui()
        if album_name is not None:
            self.name.setText(album_name)
            self.name.selectAll()
        self.name.setFocus()

    @property
    def album_name(self) -> str:
        """Return the entered name; the Workspace owns canonical validation."""

        return self.name.text()

    def retranslate_ui(self) -> None:
        if self._renaming:
            self.setWindowTitle(self.tr("Rename Photo Album"))
            self._title.setText(self.tr("Rename Photo Album"))
            self._description.setText(
                self.tr("Choose a new name for this Photo Album.")
            )
        else:
            self.setWindowTitle(self.tr("New Photo Album"))
            self._title.setText(self.tr("Create a Photo Album"))
            self._description.setText(
                self.tr(
                    "Start with an empty album, then use Manage Albums to add Photos."
                )
            )
        self._name_label.setText(self.tr("Album name"))
        self.name.setAccessibleName(self.tr("Photo Album name"))
        self._create.setText(
            self.tr("Rename Album") if self._renaming else self.tr("Create Album")
        )
        self._cancel.setText(QCoreApplication.translate("CommonActions", "Cancel"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _name_changed(self, name: str) -> None:
        self._create.setEnabled(bool(name.strip()))


__all__ = ["PhotoAlbumEditorDialog"]
