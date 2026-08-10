from types import SimpleNamespace
from typing import Any, cast

from PyQt6.QtWidgets import QFrame

from iopenpod.gui.styles import paint_css
from iopenpod.gui.widgets.ipodTagFixDialog import IpodLibraryTagFixDialog
from iopenpod.gui.widgets.ipodTagNormalizer import IpodLibraryTagSuggestion, ipod_tag_profile


def test_tag_fix_search_matches_symbol_variants() -> None:
    track = {"Title": "John’s Song"}
    dialog = SimpleNamespace(
        _tracks=[track],
        _suggestion=SimpleNamespace(
            changes_by_track={id(track): {"Title": "John’s Song (Live)"}},
        ),
        _selected_field=None,
        _search_text="john's",
        _preview_search_text=lambda *args: IpodLibraryTagFixDialog._preview_search_text(
            cast(Any, dialog),
            *args,
        ),
    )

    rows, count = IpodLibraryTagFixDialog._filtered_preview_rows(cast(Any, dialog))

    assert count == 1
    assert len(rows) == 1


def test_tag_fix_dialog_uses_resolved_info_notice_paints(qtbot) -> None:
    track = {"Title": "Untitled", "Artist": "Example"}
    suggestion = IpodLibraryTagSuggestion(
        profile=ipod_tag_profile(),
        changes_by_track={id(track): {"Title": "Example title"}},
    )

    dialog = IpodLibraryTagFixDialog([track], suggestion)
    qtbot.addWidget(dialog)

    explanation = dialog.findChild(QFrame, "tagFixerExplanation")

    assert explanation is not None
    assert paint_css("notice.info.fill") in explanation.styleSheet()
    assert paint_css("notice.info.border") in explanation.styleSheet()
