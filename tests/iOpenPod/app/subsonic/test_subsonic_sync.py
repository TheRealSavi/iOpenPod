"""Tests for Subsonic playlist matching and library sync."""

from unittest.mock import MagicMock

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.subsonic.models import (
    SubsonicPlaylistMapping,
    SubsonicSong,
    SubsonicSyncMode,
)
from iOpenPod.app.subsonic.sync import (
    index_library_tracks,
    match_subsonic_entries,
    normalize_match_key,
    sync_subsonic_playlists,
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


def test_normalize_match_key() -> None:
    # Smart quotes & dashes transliteration
    k1 = normalize_match_key("Don’t Stop Believin’", "Journey")  # noqa: RUF001
    k2 = normalize_match_key("Don't Stop Believin'", "Journey")
    assert k1 == k2

    # Double smart quotes
    k3 = normalize_match_key("“Heroes”", "David Bowie")
    k4 = normalize_match_key('"Heroes"', "David Bowie")
    assert k3 == k4

    # En-dash vs hyphen
    k5 = normalize_match_key("Track 1 – Intro", "Artist")  # noqa: RUF001
    k6 = normalize_match_key("Track 1 - Intro", "Artist")
    assert k5 == k6

    # Case folding & extra whitespace
    k7 = normalize_match_key("  bohemian   rhapsody  ", "  QUEEN ")
    k8 = normalize_match_key("Bohemian Rhapsody", "Queen")
    assert k7 == k8


def test_index_library_tracks() -> None:
    t1 = _make_track(10, "Song One", "Artist A")
    t2 = _make_track(20, "Song Two", "Artist B")
    t3 = _make_track(30, "", "")

    index = index_library_tracks((t1, t2, t3))
    assert len(index) == 2
    assert index[normalize_match_key("Song One", "Artist A")] == 10
    assert index[normalize_match_key("Song Two", "Artist B")] == 20


def test_match_subsonic_entries() -> None:
    t1 = _make_track(10, "Song One", "Artist A")
    t2 = _make_track(20, "Song Two", "Artist B")
    index = index_library_tracks((t1, t2))

    entries = (
        SubsonicSong("s1", "Song One", "Artist A"),
        SubsonicSong("s2", "song two", "artist b"),
        SubsonicSong("s3", "Song Three", "Artist C"),
    )

    matched, unmatched = match_subsonic_entries(entries, index)
    assert matched == (10, 20)
    assert unmatched == 1


def test_sync_subsonic_playlists_create_new() -> None:
    workspace = LibraryWorkspace()
    t1 = _make_track(100, "Hotel California", "Eagles")
    t2 = _make_track(101, "Take It Easy", "Eagles")
    workspace.load(LibrarySnapshot(tracks=(t1, t2)))

    client = MagicMock()
    client.get_playlist.return_value = (
        SubsonicSong("s1", "Hotel California", "Eagles"),
        SubsonicSong("s2", "Take It Easy", "Eagles"),
    )

    mapping = SubsonicPlaylistMapping(
        subsonic_id="sub-1",
        subsonic_name="Eagles Best",
        target_ipod_id=None,
    )

    result = sync_subsonic_playlists(workspace, client, (mapping,))
    assert result.playlists_synced == 1
    assert result.tracks_matched == 2
    assert result.tracks_unmatched == 0
    assert len(result.errors) == 0

    playlists = workspace.playlists
    assert len(playlists) == 1
    pl = playlists[0]
    assert pl.name == "Eagles Best"
    assert tuple(e.track_id for e in pl.entries) == (100, 101)


def test_sync_subsonic_playlists_overwrite() -> None:
    workspace = LibraryWorkspace()
    t1 = _make_track(100, "Song A", "Artist")
    t2 = _make_track(200, "Song B", "Artist")
    t3 = _make_track(300, "Song C", "Artist")

    existing = Playlist(
        playlist_id=5,
        name="My List",
        kind=PlaylistKind.PLAYLIST,
        entries=playlist_entries((100,)),
        sort_order=PlaylistSortOrder.MANUAL,
    )
    workspace.load(LibrarySnapshot(tracks=(t1, t2, t3), playlists=(existing,)))

    client = MagicMock()
    client.get_playlist.return_value = (
        SubsonicSong("s2", "Song B", "Artist"),
        SubsonicSong("s3", "Song C", "Artist"),
    )

    mapping = SubsonicPlaylistMapping(
        subsonic_id="sub-1",
        subsonic_name="Sub List",
        target_ipod_id=5,
        mode=SubsonicSyncMode.OVERWRITE,
    )

    result = sync_subsonic_playlists(workspace, client, (mapping,))
    assert result.playlists_synced == 1
    assert result.tracks_matched == 2

    updated = workspace.playlist(5)
    assert updated is not None
    assert tuple(e.track_id for e in updated.entries) == (200, 300)


def test_sync_subsonic_playlists_merge_deduplicates() -> None:
    workspace = LibraryWorkspace()
    t1 = _make_track(100, "Song A", "Artist")
    t2 = _make_track(200, "Song B", "Artist")
    t3 = _make_track(300, "Song C", "Artist")

    existing = Playlist(
        playlist_id=7,
        name="Party",
        kind=PlaylistKind.PLAYLIST,
        entries=playlist_entries((100, 200)),
        sort_order=PlaylistSortOrder.MANUAL,
    )
    workspace.load(LibrarySnapshot(tracks=(t1, t2, t3), playlists=(existing,)))

    client = MagicMock()
    client.get_playlist.return_value = (
        SubsonicSong("s2", "Song B", "Artist"),
        SubsonicSong("s3", "Song C", "Artist"),
    )

    mapping = SubsonicPlaylistMapping(
        subsonic_id="sub-2",
        subsonic_name="Party",
        target_ipod_id=7,
        mode=SubsonicSyncMode.MERGE,
    )

    result = sync_subsonic_playlists(workspace, client, (mapping,))
    assert result.playlists_synced == 1
    assert result.tracks_matched == 2

    updated = workspace.playlist(7)
    assert updated is not None
    # 200 should not be duplicated; 300 should be appended
    assert tuple(e.track_id for e in updated.entries) == (100, 200, 300)
