from __future__ import annotations

from typing import Any, cast

from PyQt6.QtWidgets import QApplication

from iopenpod.gui.widgets.syncReview import SyncReviewWidget


def _review_widget(qtbot) -> SyncReviewWidget:
    widget = SyncReviewWidget(
        cast(Any, object()),
        cast(Any, object()),
    )
    qtbot.addWidget(widget)
    return widget


def test_progress_help_panel_tracks_explanatory_stage(qtbot) -> None:
    widget = _review_widget(qtbot)
    widget.show_loading()

    assert widget._progress_help_panel.isHidden()
    assert widget._progress_help_panel.objectName() == "syncProgressExplanation"
    assert widget._progress_help_title.text() == "What's this for?"
    assert widget._progress_help_mark.text() == "?"
    assert widget._progress_help_mark.size().width() == 28
    assert widget._progress_help_panel.minimumWidth() == 560
    assert not hasattr(widget, "_progress_help_btn")
    loading_layout = widget._progress_help_panel.parentWidget().layout()
    assert loading_layout is not None
    help_row_index = next(
        index
        for index in range(loading_layout.count())
        if loading_layout.itemAt(index).layout() is widget._progress_help_row
    )
    assert help_row_index > loading_layout.indexOf(widget.progress_detail)

    widget.update_progress(
        "bootstrap_mapping",
        2,
        10,
        "Analyzing existing iPod tracks...",
    )

    assert not widget._progress_help_panel.isHidden()
    assert widget._progress_help_stage == "bootstrap_mapping"
    assert widget._progress_help_body.isHidden()

    widget.update_progress("scan_pc", 3, 10, "Scanning media folders...")

    assert widget._progress_help_panel.isHidden()
    assert widget._progress_help_stage == ""


def test_progress_help_panel_expands_explanation_inline(qtbot) -> None:
    widget = _review_widget(qtbot)
    widget.resize(1100, 760)
    widget.show()
    widget.update_progress("bootstrap_mapping", 1, 2, "Analyzing...")
    QApplication.processEvents()

    assert widget._progress_help_body.isHidden()

    widget._toggle_progress_help()
    QApplication.processEvents()

    assert not widget._progress_help_body.isHidden()
    assert "one-time" in widget._progress_help_body.text()
    assert widget._progress_help_panel.height() >= widget._progress_help_panel.heightForWidth(
        widget._progress_help_panel.width()
    )
    assert widget._progress_help_body.height() >= widget._progress_help_body.heightForWidth(
        widget._progress_help_body.width()
    )
