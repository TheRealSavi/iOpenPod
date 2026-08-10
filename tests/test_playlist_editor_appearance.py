from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame

from iopenpod.gui.styles import paint_css
from iopenpod.gui.widgets.playlistEditor import (
    NewPlaylistDialog,
    RegularPlaylistEditor,
    SmartPlaylistEditor,
)


def test_playlist_editors_use_resolved_panel_notice_and_modal_paints(qtbot) -> None:
    smart_editor = SmartPlaylistEditor()
    regular_editor = RegularPlaylistEditor()
    dialog = NewPlaylistDialog()
    qtbot.addWidget(smart_editor)
    qtbot.addWidget(regular_editor)
    qtbot.addWidget(dialog)

    rules_panel = smart_editor.findChild(QFrame, "smartPlaylistRulesPanel")
    add_tracks_note = regular_editor.findChild(QFrame, "regularPlaylistAddTracksNote")

    assert rules_panel is not None
    assert paint_css("surface.inset") in rules_panel.styleSheet()
    assert add_tracks_note is not None
    assert paint_css("notice.info.fill") in add_tracks_note.styleSheet()
    assert paint_css("notice.info.border") in add_tracks_note.styleSheet()
    assert paint_css("modal.background") in dialog.styleSheet()


def test_regular_editor_creates_a_folder_inside_another_folder(qtbot) -> None:
    editor = RegularPlaylistEditor()
    qtbot.addWidget(editor)
    playlists = [
        {"Title": "Root Folder", "playlist_id": 10, "is_folder": True},
        {
            "Title": "Second Folder",
            "playlist_id": 20,
            "is_folder": True,
        },
        {
            "Title": "Child Playlist",
            "playlist_id": 30,
            "parent_folder_playlist_id": 20,
        },
    ]
    editor.set_playlist_options(playlists)
    editor.new_folder()
    editor.name_input.setText("Favorites")
    assert not editor.parent_folder_combo.isHidden()
    assert editor.parent_folder_combo.isEnabled()
    editor.parent_folder_combo.setCurrentIndex(
        editor.parent_folder_combo.findData(10)
    )

    created = editor.get_playlist_data()

    assert created["Title"] == "Favorites"
    assert created["playlist_kind_flags"] == 0x0100
    assert created["podcast_flag"] == 0x0100
    assert created["is_folder"] is True
    assert created["is_podcast"] is False
    assert created["parent_folder_playlist_id"] == 10
    assert created["unk0x30_playlist_ref"] == 10
    assert created["items"] == []


def test_regular_editor_moves_folder_but_excludes_self_and_descendants(qtbot) -> None:
    editor = RegularPlaylistEditor()
    qtbot.addWidget(editor)
    playlists = [
        {"Title": "Root Folder", "playlist_id": 10, "is_folder": True},
        {
            "Title": "Editing Folder",
            "playlist_id": 20,
            "is_folder": True,
            "parent_folder_playlist_id": 10,
        },
        {
            "Title": "Child Folder",
            "playlist_id": 30,
            "is_folder": True,
            "parent_folder_playlist_id": 20,
        },
        {
            "Title": "Grandchild Folder",
            "playlist_id": 40,
            "is_folder": True,
            "parent_folder_playlist_id": 30,
        },
        {
            "Title": "Unrelated Folder",
            "playlist_id": 50,
            "is_folder": True,
        },
    ]
    editor.set_playlist_options(playlists)
    editor.edit_playlist(playlists[1])

    assert not editor.parent_folder_combo.isHidden()
    assert editor.parent_folder_combo.isEnabled()
    assert editor.parent_folder_combo.currentData() == 10
    assert editor.parent_folder_combo.findData(20) == -1
    assert editor.parent_folder_combo.findData(30) == -1
    assert editor.parent_folder_combo.findData(40) == -1
    assert editor.parent_folder_combo.findData(50) >= 0

    editor.parent_folder_combo.setCurrentIndex(
        editor.parent_folder_combo.findData(50)
    )
    editor.name_input.setText("Moved Folder")

    moved = editor.get_playlist_data()

    assert moved["playlist_id"] == 20
    assert moved["Title"] == "Moved Folder"
    assert moved["parent_folder_playlist_id"] == 50
    assert moved["unk0x30_playlist_ref"] == 50
    assert moved["is_folder"] is True


def test_regular_editor_moves_playlist_into_a_folder(qtbot) -> None:
    editor = RegularPlaylistEditor()
    qtbot.addWidget(editor)
    editor.set_playlist_options([
        {"Title": "Root Folder", "playlist_id": 10, "is_folder": True},
    ])
    editor.new_playlist()
    assert not editor.parent_folder_combo.isHidden()
    assert editor.parent_folder_combo.isEnabled()
    editor.parent_folder_combo.setCurrentIndex(
        editor.parent_folder_combo.findData(10)
    )
    assert editor.get_playlist_data()["parent_folder_playlist_id"] == 10


def test_new_playlist_dialog_offers_playlist_folder(qtbot) -> None:
    dialog = NewPlaylistDialog()
    qtbot.addWidget(dialog)

    qtbot.mouseClick(dialog.folder_btn, Qt.MouseButton.LeftButton)

    assert dialog.get_choice() == "folder"
