from __future__ import annotations

from iopenpod.application.jobs import _is_regular_import_target_playlist
from iopenpod.application.runtime import _is_regular_playlist_mirror_candidate
from iopenpod.gui.widgets.trackContextMenu import _is_editable_regular_playlist
from iopenpod.sync.quick_writes import (
    _is_regular_playlist_mirror_candidate as quick_write_mirror_candidate,
)
from iopenpod.sync.sync_executor import (
    _is_regular_playlist_mirror_candidate as sync_mirror_candidate,
)


def test_playlist_folder_is_not_a_direct_track_membership_target() -> None:
    folder = {
        "playlist_id": 100,
        "Title": "Folder",
        "playlist_kind_flags": 0x0100,
        "podcast_flag": 0x0100,
        "is_folder": True,
        "_source": "regular",
    }

    assert _is_regular_import_target_playlist(folder) is False
    assert _is_editable_regular_playlist(folder) is False
    assert _is_regular_playlist_mirror_candidate(folder) is True
    assert quick_write_mirror_candidate(folder) is True
    assert sync_mirror_candidate(folder) is True


def test_unknown_kind_bits_do_not_turn_regular_playlist_into_podcast() -> None:
    playlist = {
        "playlist_id": 100,
        "Title": "Future Flags",
        "playlist_kind_flags": 0x0200,
        "podcast_flag": 0x0200,
        "_source": "regular",
    }

    assert _is_regular_import_target_playlist(playlist) is True
    assert _is_editable_regular_playlist(playlist) is True
    assert _is_regular_playlist_mirror_candidate(playlist) is True
    assert quick_write_mirror_candidate(playlist) is True
    assert sync_mirror_candidate(playlist) is True


def test_podcast_low_bit_is_honored_when_other_kind_bits_are_present() -> None:
    playlist = {
        "playlist_id": 100,
        "Title": "Podcast Flags",
        "playlist_kind_flags": 0x0201,
        "podcast_flag": 0x0201,
        "_source": "regular",
    }

    assert _is_regular_import_target_playlist(playlist) is False
    assert _is_editable_regular_playlist(playlist) is False
    assert _is_regular_playlist_mirror_candidate(playlist) is False
    assert quick_write_mirror_candidate(playlist) is False
    assert sync_mirror_candidate(playlist) is False
