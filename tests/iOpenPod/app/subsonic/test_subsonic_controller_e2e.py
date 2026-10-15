"""End-to-end test verifying SubsonicController sync workflow against LibraryWorkspace."""

import time
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.subsonic.controller import SubsonicController
from iOpenPod.app.subsonic.models import (
    SubsonicPlaylistMapping,
    SubsonicSong,
    SubsonicSyncMode,
    SubsonicSyncResult,
)
from iPodDB.library import (
    LibrarySnapshot,
    Playlist,
    PlaylistKind,
    PlaylistSortOrder,
    Track,
    playlist_entries,
)


def _make_track(track_id: int, title: str, artist: str) -> Track:
    return Track(
        track_id=track_id,
        title=title,
        artist=artist,
        album="Test Album",
        length_ms=180000,
    )


def test_subsonic_controller_sync_e2e(monkeypatch: pytest.MonkeyPatch) -> None:
    _app = APPLICATION
    context = build_context()
    workspace = context.library_workspace

    # 1. Load an iPod library with 3 tracks and 1 existing playlist
    t1 = _make_track(1, "Billie Jean", "Michael Jackson")
    t2 = _make_track(2, "Beat It", "Michael Jackson")
    t3 = _make_track(3, "Thriller", "Michael Jackson")
    existing_pl = Playlist(
        playlist_id=10,
        name="Existing Playlist",
        kind=PlaylistKind.PLAYLIST,
        entries=playlist_entries((1,)),
        sort_order=PlaylistSortOrder.MANUAL,
    )
    workspace.load(
        LibrarySnapshot(
            tracks=(t1, t2, t3),
            playlists=(existing_pl,),
            device_name="Test iPod",
        )
    )

    # 2. Mock SubsonicClient
    mock_client = MagicMock()
    mock_client.get_playlists.return_value = ()
    # Subsonic playlist "sub-new" has Billie Jean and Thriller
    # Subsonic playlist "sub-merge" has Beat It
    def mock_get_playlist(pl_id: str) -> tuple[SubsonicSong, ...]:
        if pl_id == "sub-new":
            return (
                SubsonicSong("s1", "Billie Jean", "Michael Jackson"),
                SubsonicSong("s3", "Thriller", "Michael Jackson"),
            )
        if pl_id == "sub-merge":
            return (
                SubsonicSong("s2", "Beat It", "Michael Jackson"),
            )
        return ()

    mock_client.get_playlist.side_effect = mock_get_playlist
    monkeypatch.setattr(
        "iOpenPod.app.subsonic.controller.SubsonicClient",
        lambda *args, **kwargs: mock_client,
    )

    # 3. Create controller and test sync_playlists
    controller = SubsonicController(context.settings)
    finished_results = []
    controller.syncFinished.connect(lambda res: finished_results.append(res))

    mappings = (
        SubsonicPlaylistMapping(
            subsonic_id="sub-new",
            subsonic_name="MJ Hits",
            target_ipod_id=None,
        ),
        SubsonicPlaylistMapping(
            subsonic_id="sub-merge",
            subsonic_name="Existing Playlist",
            target_ipod_id=10,
            mode=SubsonicSyncMode.MERGE,
        ),
    )

    controller.sync_playlists(
        workspace,
        mappings,
        "https://music.example.com",
        "alice",
        "secret",
    )

    # Spin event loop to allow thread pool and queued signals to complete
    for _ in range(50):
        QCoreApplication.processEvents()
        if finished_results:
            break
        time.sleep(0.02)

    # 4. Verify results
    assert len(finished_results) == 1
    result: SubsonicSyncResult = finished_results[0]
    assert result.playlists_synced == 2
    assert result.tracks_matched == 3
    assert result.tracks_unmatched == 0
    assert len(result.errors) == 0

    # Verify workspace state
    # Workspace should now be dirty (staged changes ready to write to iPod!)
    assert workspace.dirty

    # Should have 2 playlists now: existing_pl (merged) and MJ Hits (new)
    playlists = workspace.playlists
    assert len(playlists) == 2

    pl_by_name = {p.name: p for p in playlists}
    assert "MJ Hits" in pl_by_name
    assert "Existing Playlist" in pl_by_name

    # MJ Hits should contain track 1 and 3
    mj_hits = pl_by_name["MJ Hits"]
    assert tuple(e.track_id for e in mj_hits.entries) == (1, 3)

    # Existing Playlist should contain track 1 (existing) and track 2 (merged)
    existing_updated = pl_by_name["Existing Playlist"]
    assert tuple(e.track_id for e in existing_updated.entries) == (1, 2)
