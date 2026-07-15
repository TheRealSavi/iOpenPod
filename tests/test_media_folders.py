from iopenpod.infrastructure.media_folders import (
    media_folder_entries_to_settings,
    media_folder_paths,
)


def test_media_folder_entries_upgrade_legacy_strings() -> None:
    assert media_folder_entries_to_settings(["C:/Music"]) == [
        {
            "directory": "C:/Music",
            "recurse": True,
            "media_types": ["music", "video", "photo", "playlists"],
        }
    ]


def test_media_folder_entries_preserve_dict_options_and_aliases() -> None:
    entries = media_folder_entries_to_settings([
        {
            "directory": "C:/Media",
            "recurse": False,
            "media": ["audio", "photos", "audio"],
        }
    ])

    assert entries == [
        {
            "directory": "C:/Media",
            "recurse": False,
            "media_types": ["music", "photo"],
        }
    ]
    assert media_folder_paths(entries) == ["C:/Media"]


def test_media_folder_entries_preserve_playlist_media_type_aliases() -> None:
    entries = media_folder_entries_to_settings([
        {
            "directory": "C:/Media",
            "media": ["audio", "playlist_files", "playlists"],
        }
    ])

    assert entries[0]["media_types"] == ["music", "playlists"]
