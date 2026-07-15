from types import SimpleNamespace

from iopenpod.application.sync_review_model import (
    ACTION_ADD_TO_IPOD,
    ACTION_REMOVE_FROM_IPOD,
    ACTION_UPDATE_FILE,
    ACTION_UPDATE_METADATA,
    count_sync_actions,
    group_by_media_type,
    metadata_change_parts,
    sync_action_key,
    sync_item_size_delta,
)
from iopenpod.gui.widgets.syncReview import SyncTrackRow
from iopenpod.sync.contracts import SyncAction, SyncItem


def _enum_like(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def _item(action: object, **values: object) -> SimpleNamespace:
    return SimpleNamespace(action=action, **values)


def test_sync_action_key_accepts_enum_like_actions_and_strings() -> None:
    assert sync_action_key(_item(_enum_like(ACTION_ADD_TO_IPOD))) == ACTION_ADD_TO_IPOD
    assert (
        sync_action_key(_item(f"SyncAction.{ACTION_REMOVE_FROM_IPOD}"))
        == ACTION_REMOVE_FROM_IPOD
    )


def test_group_by_media_type_uses_stable_display_order() -> None:
    podcast = _item(
        ACTION_ADD_TO_IPOD,
        pc_track=SimpleNamespace(is_podcast=True, is_audiobook=False, is_video=False),
    )
    video = _item(ACTION_REMOVE_FROM_IPOD, ipod_track={"media_type": 0x02})
    music = _item(
        ACTION_ADD_TO_IPOD,
        pc_track=SimpleNamespace(is_podcast=False, is_audiobook=False, is_video=False),
    )

    groups = group_by_media_type([podcast, video, music])

    assert [(key, len(items)) for key, items in groups] == [
        ("music", 1),
        ("podcast", 1),
        ("video", 1),
    ]


def test_sync_item_size_delta_counts_adds_removes_and_file_updates() -> None:
    add = _item(ACTION_ADD_TO_IPOD, estimated_size=123, pc_track=None)
    remove = _item(ACTION_REMOVE_FROM_IPOD, ipod_track={"size": 45})
    file_update = _item(
        ACTION_UPDATE_FILE,
        estimated_size=None,
        pc_track=SimpleNamespace(size=67),
    )
    metadata = _item(ACTION_UPDATE_METADATA)

    assert sync_item_size_delta(add) == (123, 0)
    assert sync_item_size_delta(remove) == (0, 45)
    assert sync_item_size_delta(file_update) == (67, 0)
    assert sync_item_size_delta(metadata) == (0, 0)


def test_count_sync_actions_counts_known_actions() -> None:
    counts = count_sync_actions(
        [
            _item(ACTION_ADD_TO_IPOD),
            _item(ACTION_ADD_TO_IPOD),
            _item(ACTION_REMOVE_FROM_IPOD),
            _item(ACTION_UPDATE_METADATA),
            _item("UNKNOWN"),
        ]
    )

    assert counts.add_to_ipod == 2
    assert counts.remove_from_ipod == 1
    assert counts.update_metadata == 1
    assert counts.update_file == 0


def test_metadata_change_parts_summarizes_single_chapter_title_change() -> None:
    item = _item(
        ACTION_UPDATE_METADATA,
        metadata_changes={
            "chapter_data": (
                {
                    "chapters": [
                        {"startpos": 0, "title": "01. New Title"},
                        {"startpos": 1000, "title": "02. Same"},
                    ]
                },
                {
                    "chapters": [
                        {"startpos": 0, "title": "01. Old Title"},
                        {"startpos": 1000, "title": "02. Same"},
                    ]
                },
            )
        },
    )

    assert metadata_change_parts(item) == [
        'Chapter title: "01. Old Title" -> "01. New Title"'
    ]


def test_metadata_change_parts_summarizes_multiple_chapter_title_changes() -> None:
    item = _item(
        ACTION_UPDATE_METADATA,
        metadata_changes={
            "chapter_data": (
                {
                    "chapters": [
                        {"startpos": 0, "title": "One"},
                        {"startpos": 1000, "title": "Two"},
                    ]
                },
                {
                    "chapters": [
                        {"startpos": 0, "title": "Old One"},
                        {"startpos": 1000, "title": "Old Two"},
                    ]
                },
            )
        },
    )

    assert metadata_change_parts(item) == ["Chapter titles: 2 changed"]


def test_sync_track_row_shows_chaptered_album_metadata_update_when_ipod_title_is_blank(qtbot) -> None:
    item = SyncItem(
        action=SyncAction.UPDATE_METADATA,
        db_track_id=42,
        ipod_track={"Title": "", "length": 120000},
        metadata_changes={
            "chapter_data": (
                {"chapters": [{"startpos": 0, "title": "01. New Title"}]},
                {"chapters": [{"startpos": 0, "title": "01. Old Title"}]},
            )
        },
        description="Update chapter titles: Album",
        aggregate_kind="chaptered_album",
    )

    row = SyncTrackRow(item, "#8844ff")
    qtbot.addWidget(row)

    assert row.title_label.text() == "Update chapter titles: Album"
    assert "Update chapter titles: Album" in row.detail_label.text()
    assert 'Chapter title: "01. Old Title" -> "01. New Title"' in row.detail_label.text()


def test_sync_track_row_metadata_update_fallback_handles_loose_item(qtbot) -> None:
    item = SimpleNamespace(
        action=SyncAction.UPDATE_METADATA,
        description="Update chapter titles: Album",
        aggregate_kind="chaptered_album",
        metadata_changes={
            "chapter_data": (
                {"chapters": [{"title": "New"}]},
                {"chapters": [{"title": "Old"}]},
            )
        },
    )

    row = SyncTrackRow(item, "#8844ff")
    qtbot.addWidget(row)

    assert row.title_label.text() == "Update chapter titles: Album"
    assert row.detail_label.text()


def test_sync_track_row_shows_aggregate_file_update_without_pc_track(qtbot) -> None:
    item = SyncItem(
        action=SyncAction.UPDATE_FILE,
        db_track_id=42,
        ipod_track={
            "Title": "",
            "Artist": "Artist",
            "Album": "Album",
            "length": 120000,
        },
        estimated_size=123456,
        description="Rebuild chaptered album: Album",
        aggregate_kind="chaptered_album",
    )

    row = SyncTrackRow(item, "#8844ff")
    qtbot.addWidget(row)

    assert row.title_label.text() == "Rebuild chaptered album: Album"
    assert "Rebuild chaptered album: Album" in row.detail_label.text()
