from __future__ import annotations

from iopenpod.itunesdb_shared.playlist_lifecycle import playlist_edit_payload


def test_playlist_edit_payload_preserves_origin_flags_and_items() -> None:
    original = {
        "playlist_id": 0x1234,
        "_mhsd_dataset_type": 2,
        "_mhsd_result_key": "mhlp",
        "_source": "regular",
        "podcast_flag": 0,
        "mhsd5_type": 0,
        "items": [{"track_id": 7}],
        "playlist_settings": {"opaque": True},
        "playlist_property_plist": {
            "raw_body": b"old",
            "plist": {"description": "before", "unknown": 55},
        },
    }

    edited = playlist_edit_payload(
        original,
        {
            "Title": "Renamed",
            "_isNew": False,
            "playlist_description": "after",
            "Album": "after",
        },
    )

    assert edited["Title"] == "Renamed"
    assert edited["_mhsd_dataset_type"] == 2
    assert edited["_mhsd_result_key"] == "mhlp"
    assert edited["_source"] == "regular"
    assert edited["items"] == [{"track_id": 7}]
    assert edited["playlist_settings"] == {"opaque": True}
    assert edited["playlist_description"] == "after"
    assert edited["Album"] == "after"


def test_playlist_edit_payload_canonicalizes_folder_kind_and_parent_fields() -> None:
    payload = playlist_edit_payload(
        None,
        {
            "Title": "New Folder Child",
            "is_folder": True,
            "parent_folder_playlist_id": 0x1234,
        },
    )

    assert payload["playlist_kind_flags"] == 0x0100
    assert payload["podcast_flag"] == 0x0100
    assert payload["is_folder"] is True
    assert payload["is_podcast"] is False
    assert payload["parent_folder_playlist_id"] == 0x1234
    assert payload["unk0x30_playlist_ref"] == 0x1234
