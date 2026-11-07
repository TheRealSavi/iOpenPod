"""Ask how to handle Track occurrences already in a destination Playlist."""

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox, QWidget


def choose_playlist_additions(
    existing_ids: tuple[int, ...], track_ids: tuple[int, ...], parent: QWidget
) -> tuple[int, ...] | None:
    """Keep occurrence order; return None when the user cancels the addition."""

    existing = frozenset(existing_ids)
    if not existing.intersection(track_ids):
        return track_ids

    dialog = QMessageBox(parent)
    dialog.setWindowTitle(
        QCoreApplication.translate("PlaylistDuplicates", "Songs already in playlist")
    )
    dialog.setIcon(QMessageBox.Icon.Warning)
    dialog.setText(
        QCoreApplication.translate(
            "PlaylistDuplicates",
            "Some songs are already in this playlist, would you like to add those "
            "again, or skip them?",
        )
    )
    add_again = dialog.addButton(
        QCoreApplication.translate("PlaylistDuplicates", "Add Again"),
        QMessageBox.ButtonRole.AcceptRole,
    )
    skip = dialog.addButton(
        QCoreApplication.translate("PlaylistDuplicates", "Skip"),
        QMessageBox.ButtonRole.ActionRole,
    )
    cancel = dialog.addButton(QMessageBox.StandardButton.Cancel)
    dialog.setDefaultButton(skip)
    dialog.setEscapeButton(cancel)
    try:
        dialog.exec()
        if dialog.clickedButton() is add_again:
            return track_ids
        if dialog.clickedButton() is skip:
            return tuple(track_id for track_id in track_ids if track_id not in existing)
        return None
    finally:
        dialog.deleteLater()
