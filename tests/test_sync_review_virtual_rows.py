from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QStyleOptionViewItem, QVBoxLayout, QWidget

from iopenpod.gui.widgets.syncReview import (
    SyncCategoryCard,
    SyncReviewWidget,
    SyncTrackRow,
    _virtual_track_row_content,
)
from iopenpod.sync.contracts import SyncAction, SyncItem, SyncPlan
from iopenpod.sync.pc_library import PCTrack
from iopenpod.sync.transcoder import TranscodePlan, TranscodeTarget


def _review_widget(qtbot) -> SyncReviewWidget:
    widget = SyncReviewWidget(cast(Any, object()), cast(Any, object()))
    qtbot.addWidget(widget)
    return widget


def _track(index: int) -> PCTrack:
    return PCTrack(
        path=f"/Music/Artist/Album/track-{index}.mp3",
        relative_path=f"Artist/Album/track-{index}.mp3",
        filename=f"track-{index}.mp3",
        extension="mp3",
        mtime=0,
        size=5_000_000,
        title=f"Track {index}",
        artist="Artist",
        album="Album",
        album_artist=None,
        genre=None,
        year=None,
        track_number=None,
        track_total=None,
        disc_number=None,
        disc_total=None,
        duration_ms=0,
        bitrate=None,
        sample_rate=None,
        rating=None,
    )


def test_large_category_uses_a_virtualized_bounded_row_view(qtbot) -> None:
    widget = _review_widget(qtbot)
    plan = SyncPlan(
        to_add=[SyncItem(SyncAction.ADD_TO_IPOD, pc_track=_track(index)) for index in range(1_000)],
        total_pc_tracks=1_000,
    )

    widget.show_plan(plan)

    card = widget._category_cards[0]
    assert card._rows_model.rowCount() == 1_000
    assert not card.findChildren(SyncTrackRow)
    assert len(card.findChildren(QWidget)) < 20
    option = QStyleOptionViewItem()
    viewport = card._rows_view.viewport()
    delegate = card._rows_view.itemDelegate()
    assert viewport is not None
    assert delegate is not None
    option.rect.setWidth(viewport.width())
    assert card._rows_view.height() == sum(
        delegate.sizeHint(option, card._rows_model.index(index, 0)).height() for index in range(5)
    )

    card._toggle_expanded()
    qtbot.waitUntil(lambda: card._expanded)

    card._rows_model.toggle(card._rows_model.index(0, 0))
    assert len(card.get_checked_items()) == 999
    assert card._select_all_cb.checkState() == Qt.CheckState.PartiallyChecked


def test_short_virtual_rows_size_to_their_content(qtbot) -> None:
    widget = _review_widget(qtbot)
    widget.resize(1_100, 760)
    widget.show()
    plan = SyncPlan(to_add=[SyncItem(SyncAction.ADD_TO_IPOD, pc_track=_track(1))])

    widget.show_plan(plan)
    qtbot.wait(10)

    card = widget._category_cards[0]
    option = QStyleOptionViewItem()
    viewport = card._rows_view.viewport()
    delegate = card._rows_view.itemDelegate()
    assert viewport is not None
    assert delegate is not None
    option.rect.setWidth(viewport.width())

    row_height = delegate.sizeHint(option, card._rows_model.index(0, 0)).height()
    assert row_height < 100
    assert card._rows_view.height() == row_height


def test_sync_review_shows_spoken_word_transcode_target_and_reason(qtbot) -> None:
    track = _track(1)
    track.is_audiobook = True
    track.extension = "m4b"
    item = SyncItem(
        SyncAction.ADD_TO_IPOD,
        pc_track=track,
        transcode_plan=cast(
            TranscodePlan,
            SimpleNamespace(
                target=TranscodeTarget.AAC,
                cache_bitrate_kbps=64,
                is_spoken=True,
                mono_for_spoken=True,
            ),
        ),
    )
    row = SyncTrackRow(item, "add")
    qtbot.addWidget(row)
    row.show()

    assert row.transfer_panel.isVisible()
    assert row.transfer_panel.source_label.text() == "M4B"
    assert row.transfer_panel.target_label.text() == "AAC"
    assert row.transfer_panel.target_detail_label.text() == "64 kbps · Mono"
    assert row.transfer_panel.reason_label.text() == "Why: Audiobook media uses your spoken-word quality setting."

    virtual_detail = _virtual_track_row_content(item)[1]
    assert "M4B → AAC · 64 kbps · Mono" in virtual_detail
    assert "Why: Audiobook media uses your spoken-word quality setting." in virtual_detail


def test_virtual_row_click_can_select_a_removal_and_fit_its_details(qtbot) -> None:
    widget = _review_widget(qtbot)
    widget.resize(1_100, 760)
    widget.show()
    plan = SyncPlan(
        to_remove=[
            SyncItem(
                SyncAction.REMOVE_FROM_IPOD,
                ipod_track={
                    "Title": "AIR RAID (FREESTYLE) 2022",
                    "Artist": "Lil Darkie",
                    "Album": "LOST SONGS",
                    "Location": ":iPod_Control:Music:F31:6STE.mp3",
                    "size": 17_400_000,
                },
                description="Removed from PC",
            )
        ],
        removals_pre_checked=False,
    )

    widget.show_plan(plan)
    card = widget._category_cards[0]
    card._toggle_expanded()
    qtbot.wait(10)

    qtbot.mouseClick(card._rows_view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    assert card.get_checked_items() == plan.to_remove
    qtbot.waitUntil(widget.apply_btn.isEnabled)
    assert widget.selection_label.text().startswith("1 of 1 selected")

    option = QStyleOptionViewItem()
    viewport = card._rows_view.viewport()
    delegate = card._rows_view.itemDelegate()
    assert viewport is not None
    assert delegate is not None
    option.rect.setWidth(viewport.width())
    assert delegate.sizeHint(option, card._rows_model.index(0, 0)).height() >= 72


def test_duplicate_card_expands_to_its_full_rich_block_height(qtbot) -> None:
    widget = _review_widget(qtbot)
    first = _track(1)
    duplicate = _track(2)
    plan = SyncPlan(
        to_add=[SyncItem(SyncAction.ADD_TO_IPOD, pc_track=first)],
        duplicates={"Artist|Album|Track 1": [first, duplicate]},
    )

    widget.show_plan(plan)

    duplicate_card: SyncCategoryCard | None = None
    for index in range(widget._cards_layout.count()):
        layout_item = widget._cards_layout.itemAt(index)
        if layout_item is None:
            continue
        candidate = layout_item.widget()
        if isinstance(candidate, SyncCategoryCard) and candidate._category == "duplicate":
            duplicate_card = candidate
            break

    assert duplicate_card is not None
    option = QStyleOptionViewItem()
    option.rect.setWidth(1_000)
    delegate = duplicate_card._rows_view.itemDelegate()
    assert delegate is not None
    expected_height = delegate.sizeHint(option, duplicate_card._rows_model.index(0, 0)).height()

    assert duplicate_card._rows_view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert duplicate_card._rows_view.height() >= expected_height


def test_duplicate_card_remeasures_full_height_when_its_width_changes(qtbot) -> None:
    container = QWidget()
    layout = QVBoxLayout(container)
    card = SyncCategoryCard(
        "warning-triangle",
        "Duplicates",
        2,
        "duplicate",
        checkable=False,
        start_expanded=True,
    )
    tracks = [_track(1), _track(2)]
    tracks[0].filename = "a duplicate filename long enough to wrap when the card is narrow.mp3"
    tracks[1].filename = "another duplicate filename long enough to wrap when the card is narrow.mp3"
    card.add_duplicate_group("Long duplicate title", "Artist", "Album", tracks)
    layout.addWidget(card)
    layout.addStretch()
    qtbot.addWidget(container)
    container.resize(420, 800)
    container.show()
    qtbot.wait(10)

    option = QStyleOptionViewItem()
    viewport = card._rows_view.viewport()
    delegate = card._rows_view.itemDelegate()
    assert viewport is not None
    assert delegate is not None
    option.rect.setWidth(viewport.width())
    narrow_height = delegate.sizeHint(option, card._rows_model.index(0, 0)).height()
    assert card._rows_view.height() >= narrow_height

    container.resize(1_200, 800)
    qtbot.wait(10)
    viewport = card._rows_view.viewport()
    delegate = card._rows_view.itemDelegate()
    assert viewport is not None
    assert delegate is not None
    option.rect.setWidth(viewport.width())
    wide_height = delegate.sizeHint(option, card._rows_model.index(0, 0)).height()
    assert card._rows_view.height() >= wide_height
