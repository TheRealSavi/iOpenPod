from GUI.widgets.selectiveSyncBrowser import SelectiveSyncBrowser
from SyncEngine.pc_library import PCTrack


def _track(
    title: str,
    relative_path: str,
    *,
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
        artist="Unknown Artist",
        album="Unknown Album",
        album_artist=None,
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
    browser._groups = {}
    browser._buckets = {}
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
