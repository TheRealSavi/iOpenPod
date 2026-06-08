from __future__ import annotations

from GUI.widgets.ipodTagNormalizer import (
    ipod_tag_profile,
    suggest_ipod_library_tag_fixes,
)


def test_ipod_tag_suggestion_moves_featured_artist_to_title() -> None:
    tracks = [
        {
            "db_track_id": 1,
            "Title": "Lead Single",
            "Artist": "Album Artist feat. Guest",
            "Album": "Record",
            "Album Artist": "Album Artist",
        },
        {
            "db_track_id": 2,
            "Title": "Deep Cut",
            "Artist": "Album Artist",
            "Album": "Record",
            "Album Artist": "Album Artist",
        },
    ]

    suggestion = suggest_ipod_library_tag_fixes(
        tracks,
        profile=ipod_tag_profile(family="iPod Classic", generation="3rd Gen"),
    )

    assert suggestion.changes_by_track[id(tracks[0])] == {
        "Artist": "Album Artist",
        "Title": "Lead Single (feat. Guest)",
        "Sort Artist": "Album Artist",
        "Sort Album Artist": "Album Artist",
        "Sort Album": "Record",
    }


def test_ipod_tag_suggestion_uses_album_artist_as_artist_for_grouping() -> None:
    tracks = [
        {
            "db_track_id": 1,
            "Title": "Song A",
            "Artist": "Artist feat. Guest",
            "Album": "Record",
            "Album Artist": "Artist",
        },
        {
            "db_track_id": 2,
            "Title": "Song B",
            "Artist": "Artist",
            "Album": "Record",
            "Album Artist": "Artist",
        },
    ]

    suggestion = suggest_ipod_library_tag_fixes(tracks)

    assert suggestion.changes_by_track[id(tracks[0])]["Artist"] == "Artist"


def test_ipod_tag_suggestion_keeps_artist_on_album_artist_aware_profiles() -> None:
    tracks = [
        {
            "db_track_id": 1,
            "Title": "Song A",
            "Artist": "Artist feat. Guest",
            "Album": "Record",
            "Album Artist": "Artist",
        }
    ]

    suggestion = suggest_ipod_library_tag_fixes(
        tracks,
        profile=ipod_tag_profile(
            family="iPod Nano",
            generation="7th Gen",
            uses_sqlite_db=True,
        ),
    )

    assert suggestion.changes_by_track[id(tracks[0])] == {
        "Sort Artist": "Artist feat. Guest",
        "Sort Album Artist": "Artist",
        "Sort Album": "Record",
    }


def test_ipod_tag_suggestion_disambiguates_same_album_titles_across_library() -> None:
    selected = {
        "db_track_id": 1,
        "Title": "Song A",
        "Artist": "One",
        "Album": "Greatest Hits",
        "Album Artist": "One",
    }
    other = {
        "db_track_id": 2,
        "Title": "Song B",
        "Artist": "Two",
        "Album": "Greatest Hits",
        "Album Artist": "Two",
    }

    suggestion = suggest_ipod_library_tag_fixes([selected, other])

    assert suggestion.changes_by_track[id(selected)]["Album"] == "Greatest Hits (One)"


def test_ipod_tag_suggestion_marks_true_compilation() -> None:
    tracks = [
        {"db_track_id": 1, "Title": "A", "Artist": "One", "Album": "Sampler"},
        {"db_track_id": 2, "Title": "B", "Artist": "Two", "Album": "Sampler"},
    ]

    suggestion = suggest_ipod_library_tag_fixes(tracks)

    assert suggestion.changes_by_track[id(tracks[0])] == {
        "Album Artist": "Various Artists",
        "compilation_flag": 1,
        "Sort Artist": "One",
        "Sort Album Artist": "Various Artists",
        "Sort Album": "Sampler",
    }
    assert suggestion.changes_by_track[id(tracks[1])] == {
        "Album Artist": "Various Artists",
        "compilation_flag": 1,
        "Sort Artist": "Two",
        "Sort Album Artist": "Various Artists",
        "Sort Album": "Sampler",
    }


def test_ipod_library_suggestion_populates_article_aware_sort_fields() -> None:
    tracks = [
        {
            "db_track_id": 1,
            "Title": "A",
            "Artist": "The Smashing Pumpkins",
            "Album": "The Album",
            "Composer": "The Composer",
            "Sort Artist": "The Smashing Pumpkins",
        },
        {
            "db_track_id": 2,
            "Title": "B",
            "Artist": "The Smashing Pumpkins",
            "Album": "The Album",
            "Composer": "The Composer",
        },
    ]

    suggestion = suggest_ipod_library_tag_fixes(tracks)

    assert suggestion.changes_by_track[id(tracks[0])] == {
        "Sort Artist": "Smashing Pumpkins, The",
        "Sort Album": "Album, The",
        "Sort Composer": "Composer, The",
    }
    assert suggestion.changes_by_track[id(tracks[1])] == {
        "Sort Artist": "Smashing Pumpkins, The",
        "Sort Album": "Album, The",
        "Sort Composer": "Composer, The",
    }


def test_ipod_library_suggestion_reuses_existing_custom_sort_for_same_artist() -> None:
    tracks = [
        {
            "db_track_id": 1,
            "Title": "A",
            "Artist": "Elvis Costello",
            "Album": "Record",
            "Sort Artist": "Costello, Elvis",
        },
        {
            "db_track_id": 2,
            "Title": "B",
            "Artist": "Elvis Costello",
            "Album": "Record",
        },
    ]

    suggestion = suggest_ipod_library_tag_fixes(tracks)

    assert "Sort Artist" not in suggestion.changes_by_track.get(id(tracks[0]), {})
    assert suggestion.changes_by_track[id(tracks[1])]["Sort Artist"] == "Costello, Elvis"


def test_library_suggestion_uses_library_sort_canonical() -> None:
    selected = {
        "db_track_id": 1,
        "Title": "A",
        "Artist": "Elvis Costello",
        "Album": "Record",
    }
    other = {
        "db_track_id": 2,
        "Title": "B",
        "Artist": "Elvis Costello",
        "Album": "Record",
        "Sort Artist": "Costello, Elvis",
    }

    suggestion = suggest_ipod_library_tag_fixes([selected, other])

    assert suggestion.changes_by_track[id(selected)]["Sort Artist"] == "Costello, Elvis"
