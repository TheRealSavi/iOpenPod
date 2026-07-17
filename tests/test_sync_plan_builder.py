from types import SimpleNamespace

from iopenpod.application.sync_plan_builder import (
    build_podcast_removal_sync_plan,
    build_removal_sync_plan,
)
from iopenpod.sync.fingerprint_diff_engine import SyncAction, SyncItem, SyncPlan
from iopenpod.sync.integrity import IntegrityReport
from iopenpod.sync.photos import (
    PCPhotoLibrary,
    PhotoAlbumChange,
    PhotoMembershipChange,
    PhotoSyncItem,
    PhotoSyncPlan,
)
from iopenpod.sync.review_selection import (
    build_filtered_sync_plan,
    build_selected_photo_plan,
)


def _item(action: SyncAction, description: str) -> SyncItem:
    return SyncItem(action=action, description=description)


def test_build_removal_sync_plan_marks_removals_prechecked() -> None:
    plan = build_removal_sync_plan(
        [
            {
                "db_track_id": 101,
                "Title": "Song A",
                "Artist": "Artist A",
                "Size": 123,
            },
            {
                "db_id": 202,
                "Title": "Song B",
                "size": 456,
            },
        ]
    )

    assert plan.removals_pre_checked is True
    assert plan.storage.bytes_to_remove == 579
    assert [item.db_track_id for item in plan.to_remove] == [101, 202]
    assert plan.to_remove[0].description == "Remove: Artist A - Song A"
    assert plan.to_remove[1].description == "Remove: Song B"


def test_build_podcast_removal_sync_plan_matches_episode_device_ids() -> None:
    plan = build_podcast_removal_sync_plan(
        [
            SimpleNamespace(ipod_db_track_id=101, title="Episode A"),
            SimpleNamespace(ipod_db_track_id=999, title="Missing"),
        ],
        [
            {"db_track_id": 101, "Title": "Episode A", "size": 123},
            {"db_track_id": 202, "Title": "Other", "size": 456},
        ],
        "Feed Name",
    )

    assert plan is not None
    assert plan.storage.bytes_to_remove == 123
    assert len(plan.to_remove) == 1
    assert plan.to_remove[0].action == SyncAction.REMOVE_FROM_IPOD
    assert plan.to_remove[0].db_track_id == 101
    assert plan.to_remove[0].description == "\U0001f399 Feed Name \u2014 Episode A"


def test_build_podcast_removal_sync_plan_returns_none_without_matches() -> None:
    plan = build_podcast_removal_sync_plan(
        [SimpleNamespace(ipod_db_track_id=999, title="Missing")],
        [{"db_track_id": 101, "Title": "Episode A", "size": 123}],
        "Feed Name",
    )

    assert plan is None


def test_build_filtered_sync_plan_groups_selected_actions_and_preserves_context(
) -> None:
    add = _item(SyncAction.ADD_TO_IPOD, "add")
    remove = _item(SyncAction.REMOVE_FROM_IPOD, "remove")
    metadata = _item(SyncAction.UPDATE_METADATA, "metadata")
    file_update = _item(SyncAction.UPDATE_FILE, "file")
    artwork = _item(SyncAction.UPDATE_ARTWORK, "artwork")
    playcount = _item(SyncAction.SYNC_PLAYCOUNT, "playcount")
    rating = _item(SyncAction.SYNC_RATING, "rating")
    stale_entries = [("abc", 1)]
    integrity_removals = [_item(SyncAction.REMOVE_FROM_IPOD, "integrity")]
    integrity_report = IntegrityReport()
    photo_plan = object()

    original = SyncPlan(
        matched_pc_paths={1: "C:/Music/song.m4a"},
        _stale_mapping_entries=stale_entries,
        _integrity_removals=integrity_removals,
        _mapping_requires_persistence=True,
        integrity_report=integrity_report,
        playlists_to_add=[{"name": "New"}],
        playlists_to_edit=[{"name": "Edit"}],
        playlists_to_remove=[{"name": "Remove"}],
    )

    filtered = build_filtered_sync_plan(
        original,
        [add, remove, metadata, file_update, artwork, playcount, rating],
        include_playlists=True,
        selected_photo_plan=photo_plan,
    )

    assert filtered.to_add == [add]
    assert filtered.to_remove == [remove]
    assert filtered.to_update_metadata == [metadata]
    assert filtered.to_update_file == [file_update]
    assert filtered.to_update_artwork == [artwork]
    assert filtered.to_sync_playcount == [playcount]
    assert filtered.to_sync_rating == [rating]
    assert filtered.matched_pc_paths == {1: "C:/Music/song.m4a"}
    assert filtered._stale_mapping_entries == stale_entries
    assert filtered._integrity_removals == integrity_removals
    assert filtered._mapping_requires_persistence is True
    assert filtered.integrity_report is integrity_report
    assert filtered.playlists_to_add == [{"name": "New"}]
    assert filtered.playlists_to_edit == [{"name": "Edit"}]
    assert filtered.playlists_to_remove == [{"name": "Remove"}]
    assert filtered.photo_plan is photo_plan


def test_build_filtered_sync_plan_can_exclude_playlists() -> None:
    original = SyncPlan(
        playlists_to_add=[{"name": "New"}],
        playlists_to_edit=[{"name": "Edit"}],
        playlists_to_remove=[{"name": "Remove"}],
    )

    filtered = build_filtered_sync_plan(
        original,
        [_item(SyncAction.ADD_TO_IPOD, "add")],
        include_playlists=False,
    )

    assert filtered.playlists_to_add == []
    assert filtered.playlists_to_edit == []
    assert filtered.playlists_to_remove == []


def test_build_filtered_sync_plan_can_filter_selected_playlists() -> None:
    original = SyncPlan(
        playlists_to_add=[{"name": "New A"}, {"name": "New B"}],
        playlists_to_edit=[{"name": "Edit A"}, {"name": "Edit B"}],
        playlists_to_remove=[{"name": "Remove A"}, {"name": "Remove B"}],
    )

    filtered = build_filtered_sync_plan(
        original,
        [_item(SyncAction.ADD_TO_IPOD, "add")],
        selected_playlists={
            "playlists_to_add": [original.playlists_to_add[1]],
            "playlists_to_edit": [original.playlists_to_edit[0]],
            "playlists_to_remove": [],
        },
    )

    assert filtered.playlists_to_add == [{"name": "New B"}]
    assert filtered.playlists_to_edit == [{"name": "Edit A"}]
    assert filtered.playlists_to_remove == []


def test_build_filtered_sync_plan_recomputes_selected_storage() -> None:
    add = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        estimated_size=100,
    )
    file_update = SyncItem(
        action=SyncAction.UPDATE_FILE,
        estimated_size=200,
    )
    remove = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        ipod_track={"size": 50},
    )
    photo_plan = PhotoSyncPlan()
    photo_plan.photos_to_add = [PhotoSyncItem("hash-a", "A")]
    photo_plan.thumb_bytes_to_add = 300

    filtered = build_filtered_sync_plan(
        SyncPlan(),
        [add, file_update, remove],
        selected_photo_plan=photo_plan,
    )

    assert filtered.storage.bytes_to_add == 400
    assert filtered.storage.bytes_to_update == 200
    assert filtered.storage.bytes_to_remove == 50


def test_build_filtered_sync_plan_accepts_single_pass_iterables() -> None:
    add = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        estimated_size=100,
    )

    filtered = build_filtered_sync_plan(
        SyncPlan(),
        (item for item in [add]),
    )

    assert filtered.to_add == [add]
    assert filtered.storage.bytes_to_add == 100


def test_build_selected_photo_plan_filters_checked_groups() -> None:
    desired_library = PCPhotoLibrary(sync_root="C:/Photos")
    original = PhotoSyncPlan(
        skipped_files=[("missing.jpg", "not found")],
        desired_library=desired_library,
    )
    original.albums_to_add = [PhotoAlbumChange(album_name="New")]
    original.photos_to_add = [PhotoSyncItem("hash-a", "A")]
    original.photos_to_remove = [PhotoSyncItem("hash-b", "B")]
    original.photos_to_update = [PhotoSyncItem("hash-c", "C")]
    original.album_membership_adds = [
        PhotoMembershipChange("hash-a", "New", "A")
    ]
    original.album_membership_removes = [
        PhotoMembershipChange("hash-b", "Old", "B")
    ]
    original.thumb_bytes_to_add = 111
    original.thumb_bytes_to_remove = 222

    selected = build_selected_photo_plan(
        original,
        {"photos_to_add", "album_membership_removes"},
    )

    assert selected is not None
    assert selected.skipped_files == [("missing.jpg", "not found")]
    assert selected.current_db is None
    assert selected.desired_library is desired_library
    assert selected.photos_to_add == [PhotoSyncItem("hash-a", "A")]
    assert selected.album_membership_removes == [
        PhotoMembershipChange("hash-b", "Old", "B")
    ]
    assert selected.albums_to_add == []
    assert selected.photos_to_remove == []
    assert selected.photos_to_update == []
    assert selected.album_membership_adds == []
    assert selected.thumb_bytes_to_add == 111
    assert selected.thumb_bytes_to_remove == 0

    original.photos_to_add[0].display_name = "Changed"
    assert selected.photos_to_add == [PhotoSyncItem("hash-a", "A")]


def test_build_selected_photo_plan_filters_checked_rows() -> None:
    original = PhotoSyncPlan()
    add_a = PhotoSyncItem("hash-a", "A", size=111)
    add_b = PhotoSyncItem("hash-b", "B", size=222, estimated_size=444)
    remove_a = PhotoSyncItem("hash-c", "C", size=333)
    album_a = PhotoAlbumChange(album_name="Album A")
    membership_a = PhotoMembershipChange("hash-a", "Album A", "A")
    membership_b = PhotoMembershipChange("hash-b", "Album B", "B")
    original.photos_to_add = [add_a, add_b]
    original.photos_to_remove = [remove_a]
    original.albums_to_add = [album_a]
    original.album_membership_adds = [membership_a, membership_b]
    original.thumb_bytes_to_add = 999
    original.thumb_bytes_to_remove = 888

    selected = build_selected_photo_plan(
        original,
        (),
        selected_items_by_key={
            "photos_to_add": [add_b],
            "photos_to_remove": [],
            "albums_to_add": [album_a],
            "album_membership_adds": [membership_b],
        },
    )

    assert selected is not None
    assert selected.photos_to_add == [add_b]
    assert selected.photos_to_remove == []
    assert selected.albums_to_add == [album_a]
    assert selected.album_membership_adds == [membership_b]
    assert selected.thumb_bytes_to_add == 444
    assert selected.thumb_bytes_to_remove == 0

    add_b.display_name = "Changed"
    assert selected.photos_to_add == [PhotoSyncItem("hash-b", "B", size=222, estimated_size=444)]


def test_build_selected_photo_plan_returns_none_without_selected_changes() -> None:
    original = PhotoSyncPlan()
    original.photos_to_add = [PhotoSyncItem("hash-a", "A")]
    original.thumb_bytes_to_add = 111

    assert build_selected_photo_plan(original, set()) is None
