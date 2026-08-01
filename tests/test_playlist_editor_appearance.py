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
