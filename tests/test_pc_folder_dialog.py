from iopenpod.gui.widgets.syncReview import PCFolderDialog
from iopenpod.infrastructure.media_folders import (
    MEDIA_TYPE_MUSIC,
    MEDIA_TYPE_PHOTO,
    MEDIA_TYPE_PLAYLISTS,
    MEDIA_TYPE_VIDEO,
)


def test_pc_folder_dialog_settings_only_mode_disables_sync_actions(qtbot, tmp_path) -> None:
    media_dir = tmp_path / "Media"
    media_dir.mkdir()
    dialog = PCFolderDialog(None, [], sync_available=False)
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == "Media Folders"
    assert dialog._sync_action_buttons
    assert all(not button.isEnabled() for button in dialog._sync_action_buttons)

    emitted: list[list[dict[str, object]]] = []
    dialog.foldersChanged.connect(lambda entries: emitted.append(entries))

    dialog._add_folder(str(media_dir))
    assert emitted[-1] == [
        {
            "directory": str(media_dir),
            "recurse": True,
            "media_types": [
                MEDIA_TYPE_MUSIC,
                MEDIA_TYPE_VIDEO,
                MEDIA_TYPE_PHOTO,
                MEDIA_TYPE_PLAYLISTS,
            ],
        }
    ]

    dialog._set_folder_recurse(str(media_dir), False)
    assert emitted[-1][0]["recurse"] is False

    dialog._set_folder_media_type(str(media_dir), MEDIA_TYPE_VIDEO, False)
    assert emitted[-1][0]["media_types"] == [
        MEDIA_TYPE_MUSIC,
        MEDIA_TYPE_PHOTO,
        MEDIA_TYPE_PLAYLISTS,
    ]

    dialog._remove_folder(str(media_dir))
    assert emitted[-1] == []
