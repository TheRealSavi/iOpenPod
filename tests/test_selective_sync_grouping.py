from types import SimpleNamespace

from GUI.widgets.selectiveSyncBrowser import SelectiveSyncBrowser
from SyncEngine.pc_library import PCTrack


def _track(
    title: str,
    relative_path: str,
    *,
    artist: str = "Unknown Artist",
    album: str = "Unknown Album",
    album_artist: str | None = None,
    is_video: bool = False,
    video_kind: str = "",
) -> PCTrack:
    extension = "." + relative_path.rsplit(".", 1)[-1].lower()
    return PCTrack(
        path=f"/music/{relative_path}",
        relative_path=relative_path,
        filename=relative_path.rsplit("/", 1)[-1],
        extension=extension,
        mtime=0,
        size=1,
        title=title,
        artist=artist,
        album=album,
        album_artist=album_artist,
        genre=None,
        year=None,
        track_number=None,
        track_total=None,
        disc_number=None,
        disc_total=None,
        duration_ms=1000,
        bitrate=None,
        sample_rate=None,
        rating=None,
        is_video=is_video,
        video_kind=video_kind,
    )


def _browser_with_tracks(tracks: list[PCTrack]) -> SelectiveSyncBrowser:
    browser = SelectiveSyncBrowser.__new__(SelectiveSyncBrowser)
    browser._all_tracks = tracks
    browser._playlist_discovery = None
    browser._groups = {}
    browser._buckets = {}
    browser._selected_playlists = {}
    def _art_candidates(track_list: list) -> list[str]:
        return []

    browser._art_candidates = _art_candidates
    return browser


def test_selective_sync_groups_unknown_albums_by_source_folder():
    browser = _browser_with_tracks(
        [
            _track("Song 1", "Album A/01 Song 1.mp3"),
            _track("Song 2", "Album A/02 Song 2.mp3"),
            _track("Song 3", "Album B/01 Song 3.mp3"),
        ]
    )

    browser._build_groups()

    albums = browser._groups["Albums"]
    assert set(albums) == {"Album A", "Album B"}
    assert albums["Album A"]["artist"] == "Unknown Artist 1"
    assert albums["Album B"]["artist"] == "Unknown Artist 2"
    assert [t.title for t in albums["Album A"]["tracks"]] == ["Song 1", "Song 2"]
    assert [t.title for t in albums["Album B"]["tracks"]] == ["Song 3"]


def test_selective_sync_unknown_artist_view_uses_parent_folder_artist():
    browser = _browser_with_tracks(
        [
            _track("Song 1", "Artist A/Album/Disc 1/01 Song 1.mp3"),
            _track("Song 2", "Artist A/Album/Disc 2/01 Song 2.mp3"),
            _track("Song 3", "Artist B/Other Album/01 Song 3.mp3"),
        ]
    )

    browser._build_groups()

    artists = browser._groups["Artists"]
    assert set(artists) == {"Artist A", "Artist B"}
    assert [t.title for t in artists["Artist A"]["tracks"]] == ["Song 1", "Song 2"]
    assert [t.title for t in artists["Artist B"]["tracks"]] == ["Song 3"]


def test_selective_sync_album_groups_use_shared_album_identity_rules():
    browser = _browser_with_tracks(
        [
            _track(
                "Song 1",
                "Compilation/01 Song 1.mp3",
                artist="Artist",
                album="Compilation",
                album_artist="Various Artists",
            ),
            _track(
                "Song 2",
                "Compilation/02 Song 2.mp3",
                artist="Artist",
                album="Compilation",
                album_artist=None,
            ),
        ]
    )

    albums = browser._build_music_albums(browser._all_tracks)
    assert set(albums) == {"Compilation"}
    assert albums["Compilation"]["artist"] == "Various Artists"
    assert [t.title for t in albums["Compilation"]["tracks"]] == ["Song 1", "Song 2"]


def test_selective_sync_movie_only_folders_do_not_create_music_albums():
    browser = _browser_with_tracks(
        [
            _track(
                "Movie",
                "Movies/Movie.mov",
                is_video=True,
                video_kind="movie",
            ),
            _track("Song", "Music Album/01 Song.mp3"),
        ]
    )

    browser._build_groups()

    assert set(browser._groups["Albums"]) == {"Music Album"}
    assert [track.title for track in browser._buckets["movie"]] == ["Movie"]


def test_selective_sync_grid_item_actions_resolve_and_toggle_tracks():
    tracks = [
        _track("Song 1", "Album A/01 Song 1.mp3"),
        _track("Song 2", "Album A/02 Song 2.mp3"),
        _track("Song 3", "Album B/01 Song 3.mp3"),
    ]
    browser = _browser_with_tracks(tracks)
    browser._current_mode = "Albums"
    browser._selected_tracks = {track.path: True for track in tracks}

    footer_updates: list[bool] = []
    browser._update_footer = lambda: footer_updates.append(True)
    browser._build_groups()

    resolved = browser._tracks_for_grid_items([
        {"title": "Album A"},
        {"title": "Album B"},
    ])
    assert [track.title for track in resolved] == ["Song 1", "Song 2", "Song 3"]

    browser._set_grid_tracks_checked(resolved[:2], False)

    assert browser._selected_tracks[tracks[0].path] is False
    assert browser._selected_tracks[tracks[1].path] is False
    assert browser._selected_tracks[tracks[2].path] is True
    assert footer_updates == [True]


def test_selective_sync_builds_playlist_groups_from_discovered_files():
    tracks = [
        _track("Song 1", "Album A/01 Song 1.mp3"),
        _track("Song 2", "Album A/02 Song 2.mp3"),
    ]
    browser = _browser_with_tracks(tracks)
    browser._playlist_discovery = SimpleNamespace(
        playlists=(
            SimpleNamespace(
                title="Road Trip",
                source_path="/music/playlists/road-trip.m3u8",
                items=(
                    {"source_path": tracks[1].path},
                    {"source_path": tracks[0].path},
                ),
                total_entries=3,
                skipped_entries=1,
            ),
        )
    )

    browser._build_groups()

    playlists = browser._groups["Playlists"]
    assert set(playlists) == {"Road Trip"}
    assert [track.title for track in playlists["Road Trip"]["tracks"]] == [
        "Song 2",
        "Song 1",
    ]
    assert playlists["Road Trip"]["track_count"] == 2
    assert playlists["Road Trip"]["skipped_count"] == 1
    assert "1 skipped" in playlists["Road Trip"]["subtitle"]


def test_selective_sync_grid_item_actions_resolve_playlist_tracks():
    tracks = [
        _track("Song 1", "Album A/01 Song 1.mp3"),
        _track("Song 2", "Album A/02 Song 2.mp3"),
    ]
    browser = _browser_with_tracks(tracks)
    browser._current_mode = "Playlists"
    browser._selected_tracks = {track.path: True for track in tracks}
    browser._selected_playlists = {"/music/playlists/road-trip.m3u8": True}
    browser._update_footer = lambda: None
    browser._playlist_discovery = SimpleNamespace(
        playlists=(
            SimpleNamespace(
                title="Road Trip",
                source_path="/music/playlists/road-trip.m3u8",
                items=({"source_path": tracks[1].path},),
                total_entries=1,
                skipped_entries=0,
            ),
        )
    )
    browser._build_groups()

    resolved = browser._tracks_for_grid_items([{"title": "Road Trip"}])
    browser._set_grid_playlists_checked([{"title": "Road Trip"}], False)
    browser._set_grid_tracks_checked(resolved, False)

    assert [track.title for track in resolved] == ["Song 2"]
    assert browser._selected_playlists["/music/playlists/road-trip.m3u8"] is False
    assert browser._selected_tracks[tracks[0].path] is True
    assert browser._selected_tracks[tracks[1].path] is False
