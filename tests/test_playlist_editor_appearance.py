from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QLabel,
    QStyle,
    QStyleOptionFrame,
    QWidget,
)

from iopenpod.gui.styles import app_stylesheet, paint_css
from iopenpod.gui.widgets.playlistEditor import (
    NewPlaylistDialog,
    RegularPlaylistEditor,
    SmartPlaylistEditor,
    SmartRuleGroup,
)


def test_playlist_editors_use_resolved_rule_notice_and_modal_paints(qtbot) -> None:
    smart_editor = SmartPlaylistEditor()
    regular_editor = RegularPlaylistEditor()
    dialog = NewPlaylistDialog()
    qtbot.addWidget(smart_editor)
    qtbot.addWidget(regular_editor)
    qtbot.addWidget(dialog)
    smart_editor.resize(1200, 720)

    rules_panel = smart_editor.findChild(QFrame, "smartPlaylistRulesPanel")
    add_tracks_note = regular_editor.findChild(QFrame, "regularPlaylistAddTracksNote")
    settings_rail = smart_editor.findChild(QWidget, "smartPlaylistSettingsRail")

    assert rules_panel is not None
    assert paint_css("table.row.fill") in rules_panel.styleSheet()
    assert settings_rail is not None
    assert add_tracks_note is not None
    assert paint_css("notice.info.fill") in add_tracks_note.styleSheet()
    assert paint_css("notice.info.border") in add_tracks_note.styleSheet()
    assert paint_css("modal.background") in dialog.styleSheet()


def test_nested_rule_groups_alternate_the_track_table_row_paints(qtbot) -> None:
    editor = SmartPlaylistEditor()
    qtbot.addWidget(editor)
    editor.new_playlist()

    qtbot.mouseClick(editor.add_group_btn, Qt.MouseButton.LeftButton)
    outer = next(
        group
        for group in editor.findChildren(SmartRuleGroup)
        if group.property("ruleGroupDepth") == 1
    )
    qtbot.mouseClick(outer.add_group_btn, Qt.MouseButton.LeftButton)
    nested = next(
        group
        for group in outer.findChildren(SmartRuleGroup)
        if group.property("ruleGroupDepth") == 2
    )

    assert paint_css("table.row.alternate_fill") in outer.styleSheet()
    assert paint_css("table.row.fill") in nested.styleSheet()
    assert not editor.add_group_btn.icon().isNull()
    assert not outer.add_group_btn.icon().isNull()
    assert not outer.remove_btn.icon().isNull()
    assert outer.remove_btn.width() == outer.remove_btn.height()


def test_smart_rule_actions_have_consistent_control_surfaces(qtbot) -> None:
    editor = SmartPlaylistEditor()
    qtbot.addWidget(editor)
    editor.new_playlist()

    qtbot.mouseClick(editor.add_group_btn, Qt.MouseButton.LeftButton)
    group = next(
        group
        for group in editor.findChildren(SmartRuleGroup)
        if group.property("ruleGroupDepth") == 1
    )

    for action in (
        editor.add_rule_btn,
        editor.add_group_btn,
        group.add_rule_btn,
        group.add_group_btn,
    ):
        assert paint_css("control.secondary.fill") in action.styleSheet()
        assert paint_css("border.default") in action.styleSheet()
        assert paint_css("focus.border") in action.styleSheet()

    assert paint_css("surface.raised") in group.remove_btn.styleSheet()
    assert paint_css("border.subtle") in group.remove_btn.styleSheet()
    assert paint_css("focus.border") in group.remove_btn.styleSheet()


def test_playlist_title_fields_leave_vertical_clearance_around_glyphs(
    qtbot, qapp
) -> None:
    previous_stylesheet = qapp.styleSheet()
    qapp.setStyleSheet(app_stylesheet())
    try:
        editors = (SmartPlaylistEditor(), RegularPlaylistEditor())
        for editor in editors:
            qtbot.addWidget(editor)
            editor.resize(1040, 420)
            editor.name_input.setText("asdasd")
            editor.show()
            qtbot.wait(0)

            style_option = QStyleOptionFrame()
            editor.name_input.initStyleOption(style_option)
            resolved_style = editor.name_input.style()
            assert resolved_style is not None
            content_rect = resolved_style.subElementRect(
                QStyle.SubElement.SE_LineEditContents,
                style_option,
                editor.name_input,
            )

            assert (
                content_rect.height()
                >= editor.name_input.fontMetrics().height() + 8
            )
    finally:
        qapp.setStyleSheet(previous_stylesheet)


def test_regular_and_folder_editors_omit_redundant_editor_metadata(qtbot) -> None:
    editor = RegularPlaylistEditor()
    qtbot.addWidget(editor)

    for configure in (editor.new_playlist, editor.new_folder):
        configure()
        visible_copy = {label.text() for label in editor.findChildren(QLabel)}
        assert "Playlist Editor" not in visible_copy
        assert "Playlist Folder Editor" not in visible_copy
        assert "Manual track playlist" not in visible_copy
        assert "Groups playlists and aggregates their tracks" not in visible_copy


def test_smart_editor_stacks_behavior_rail_at_compact_widths(qtbot) -> None:
    editor = SmartPlaylistEditor()
    qtbot.addWidget(editor)
    editor.show()

    editor.resize(820, 720)
    qtbot.wait(0)
    assert editor._body_layout.direction() == QBoxLayout.Direction.TopToBottom
    assert editor._settings_rail.minimumWidth() == 0

    editor.resize(1200, 720)
    qtbot.wait(0)
    assert editor._body_layout.direction() == QBoxLayout.Direction.LeftToRight
    assert editor._settings_rail.maximumWidth() == 420


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
