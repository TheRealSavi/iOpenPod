from dataclasses import fields

from iopenpod.application import sync_plan_merge
from iopenpod.application.sync_plan_merge import (
    merge_additional_photo_plan,
    merge_additional_sync_plan,
)
from iopenpod.sync.contracts import SyncAction, SyncItem, SyncPlan
from iopenpod.sync.integrity import IntegrityReport
from iopenpod.sync.mapping import MappingFile
from iopenpod.sync.photos import PhotoAlbumChange, PhotoSyncItem, PhotoSyncPlan


def _item(action: SyncAction, description: str) -> SyncItem:
    return SyncItem(action=action, description=description)


def test_merge_additional_sync_plan_preserves_import_context() -> None:
    existing_add = _item(SyncAction.ADD_TO_IPOD, "existing add")
    dropped_add = _item(SyncAction.ADD_TO_IPOD, "dropped add")
    existing_photo_plan = PhotoSyncPlan(
        albums_to_add=[PhotoAlbumChange("Existing Album")],
    )
    existing = SyncPlan(
        to_add=[existing_add],
        matched_pc_paths={1: "C:/Music/existing.mp3"},
        playlists_to_edit=[{"Title": "Existing"}],
        photo_plan=existing_photo_plan,
        total_pc_tracks=2,
        total_ipod_tracks=10,
        matched_tracks=1,
        removals_pre_checked=True,
    )
    existing.storage.bytes_to_add = 100
    dropped_photo_plan = PhotoSyncPlan(
        photos_to_add=[PhotoSyncItem("hash-a", "A")],
        thumb_bytes_to_add=300,
    )
    dropped = SyncPlan(
        to_add=[dropped_add],
        matched_pc_paths={2: "C:/Music/dropped.mp3"},
        playlists_to_add=[{"Title": "New"}],
        playlists_to_edit=[{"Title": "Dropped"}],
        playlists_to_remove=[{"Title": "Old"}],
        photo_plan=dropped_photo_plan,
        total_pc_tracks=1,
        total_ipod_tracks=9,
        matched_tracks=2,
        _mapping_requires_persistence=True,
    )
    dropped.storage.bytes_to_add = 200
    dropped.storage.bytes_to_remove = 50
    dropped.storage.bytes_to_update = 25

    merged = merge_additional_sync_plan(existing, dropped)

    assert merged is existing
    assert existing.to_add == [existing_add, dropped_add]
    assert existing.matched_pc_paths == {
        1: "C:/Music/existing.mp3",
        2: "C:/Music/dropped.mp3",
    }
    assert existing.playlists_to_add == [{"Title": "New"}]
    assert existing.playlists_to_edit == [
        {"Title": "Existing"},
        {"Title": "Dropped"},
    ]
    assert existing.playlists_to_remove == [{"Title": "Old"}]
    assert existing.storage.bytes_to_add == 300
    assert existing.storage.bytes_to_remove == 50
    assert existing.storage.bytes_to_update == 25
    assert existing.photo_plan is existing_photo_plan
    assert existing.photo_plan is not None
    assert existing.photo_plan.albums_to_add == [PhotoAlbumChange("Existing Album")]
    assert existing.photo_plan.photos_to_add == [PhotoSyncItem("hash-a", "A")]
    assert existing.photo_plan.thumb_bytes_to_add == 300
    assert existing.total_pc_tracks == 3
    assert existing.total_ipod_tracks == 10
    assert existing.matched_tracks == 3
    assert existing.removals_pre_checked is True
    assert existing._mapping_requires_persistence is True


def test_merge_additional_sync_plan_adopts_optional_context_when_missing() -> None:
    mapping = MappingFile()
    integrity_report = IntegrityReport()
    photo_plan = PhotoSyncPlan(photos_to_add=[PhotoSyncItem("hash-a", "A")])
    existing = SyncPlan()
    incoming = SyncPlan(
        mapping=mapping,
        integrity_report=integrity_report,
        photo_plan=photo_plan,
        removals_pre_checked=True,
    )

    merge_additional_sync_plan(existing, incoming)

    assert existing.mapping is mapping
    assert existing.integrity_report is integrity_report
    assert existing.photo_plan is photo_plan
    assert existing.removals_pre_checked is True


def test_merge_additional_photo_plan_combines_existing_and_incoming_changes() -> None:
    base = PhotoSyncPlan(
        albums_to_add=[PhotoAlbumChange("Existing Album")],
        photos_to_remove=[PhotoSyncItem("hash-old", "Old")],
        thumb_bytes_to_remove=100,
    )
    incoming = PhotoSyncPlan(
        albums_to_remove=[PhotoAlbumChange("Dropped Album")],
        photos_to_add=[PhotoSyncItem("hash-new", "New")],
        thumb_bytes_to_add=200,
    )

    merged = merge_additional_photo_plan(base, incoming)

    assert merged is base
    assert base.albums_to_add == [PhotoAlbumChange("Existing Album")]
    assert base.albums_to_remove == [PhotoAlbumChange("Dropped Album")]
    assert base.photos_to_add == [PhotoSyncItem("hash-new", "New")]
    assert base.photos_to_remove == [PhotoSyncItem("hash-old", "Old")]
    assert base.thumb_bytes_to_add == 200
    assert base.thumb_bytes_to_remove == 100


def test_merge_additional_sync_plan_has_policy_for_every_sync_plan_field() -> None:
    assert {field.name for field in fields(SyncPlan)} == (
        sync_plan_merge._SYNC_PLAN_MERGED_FIELDS
    )


def test_merge_additional_photo_plan_has_policy_for_every_photo_plan_field() -> None:
    assert {field.name for field in fields(PhotoSyncPlan)} == (
        sync_plan_merge._PHOTO_PLAN_MERGED_FIELDS
    )
