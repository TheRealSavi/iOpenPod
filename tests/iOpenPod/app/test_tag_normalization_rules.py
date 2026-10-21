"""Normalization keeps each Track's credits and explicit sorting evidence."""

from dataclasses import replace

import pytest

from iOpenPod.app.tag_normalizer import TagProfile, normalize_tags
from iPodDB.library import (
    MediaType,
    Track,
    TrackFieldEdit,
    TrackMetadata,
    edit_track_metadata,
)


def _normalized(
    tracks: tuple[Track, ...], profile: TagProfile | None = None
) -> tuple[Track, ...]:
    suggestion = normalize_tags(tracks, profile or TagProfile())
    edits = {update.track_id: update.edits for update in suggestion.updates}
    return tuple(
        edit_track_metadata(track, edits.get(track.track_id, ())) for track in tracks
    )


@pytest.mark.parametrize("lead", ["Lead", "The Lead"])
@pytest.mark.parametrize("aware", [False, True])
def test_issue_223_keeps_each_collaboration_sort_artist(lead: str, aware: bool) -> None:
    tracks = tuple(
        Track(
            index,
            f"Track {index}",
            f"{lead}/{guest}",
            "Record",
            100,
            album_artist=lead,
            metadata=TrackMetadata(sort_artist=f"{lead}/{guest}"),
        )
        for index, guest in enumerate(("Guest A", "Guest B"), start=1)
    )

    profile = TagProfile(album_artist_aware=aware)
    resulting = _normalized(tracks, profile)

    assert [track.artist for track in resulting] == (
        [t.artist for t in tracks] if aware else [lead, lead]
    )
    expected_sorts = (
        ["Lead/Guest A, The", "Lead/Guest B, The"]
        if aware and lead == "The Lead"
        else [f"{lead}/Guest A", f"{lead}/Guest B"]
    )
    assert [track.metadata.sort_artist for track in resulting] == expected_sorts
    assert [track.title for track in resulting] == (
        [t.title for t in tracks]
        if aware
        else [
            "Track 1 (feat. Guest A)",
            "Track 2 (feat. Guest B)",
        ]
    )
    assert not normalize_tags(resulting, profile).updates


@pytest.mark.parametrize("artist", ["Lead Orchestra", "Leader", "Another Artist"])
def test_album_artist_does_not_replace_an_unrelated_credit(artist: str) -> None:
    track = Track(1, "Song", artist, "Record", 100, album_artist="Lead")

    result = _normalized((track,))[0]

    assert (result.artist, result.title) == (artist, "Song")


@pytest.mark.parametrize(
    "suffix",
    [
        " feat. Guest",
        " ft Guest",
        " featuring Guest",
        " (feat. Guest)",
        " [ft. Guest]",
        " with Guest",
        "/Guest",
        " & Guest",
        "; Guest",
        " + Guest",
    ],
)
def test_only_recognized_collaborations_move_to_the_title(suffix: str) -> None:
    track = Track(1, "Song", f"Lead{suffix}", "Record", 100, album_artist="Lead")

    result = _normalized((track,))[0]

    assert (result.artist, result.title) == ("Lead", "Song (feat. Guest)")
    assert not normalize_tags((result,)).updates


@pytest.mark.parametrize(
    "title", ["", "Song (feat. Someone Else)", "Song (feat. Guest A)"]
)
def test_credits_are_not_lost_when_the_title_cannot_represent_them(title: str) -> None:
    track = Track(1, title, "Lead feat. Guest B", "Record", 100, album_artist="Lead")

    result = _normalized((track,))[0]

    assert (result.artist, result.title) == (track.artist, title)


@pytest.mark.parametrize("guest", ["Guest", "Guest (Duo)", "Guest [US]"])
def test_matching_existing_feature_credit_is_not_duplicated(guest: str) -> None:
    track = Track(
        1,
        f"Song [featuring {guest}]",
        f"Lead (ft. {guest})",
        "Record",
        100,
        album_artist="Lead",
    )
    result = _normalized((track,))[0]
    assert (result.artist, result.title) == ("Lead", track.title)


@pytest.mark.parametrize("aware", [False, True])
def test_same_album_title_is_not_evidence_of_a_compilation(aware: bool) -> None:
    tracks = tuple(
        Track(i, "Song", artist, "Greatest Hits", 100)
        for i, artist in enumerate(("One", "Two"), start=1)
    )
    result = _normalized(tracks, TagProfile(album_artist_aware=aware))
    assert all(not t.metadata.compilation and not t.album_artist for t in result)
    assert [t.album for t in result] == ["Greatest Hits", "Greatest Hits"]


@pytest.mark.parametrize("aware", [False, True])
def test_compilation_marker_does_not_capture_a_same_name_album(aware: bool) -> None:
    tracks = (
        Track(1, "Song", "One", "Sampler", 100, album_artist="Various Artists"),
        Track(2, "Song", "Band", "Sampler", 100, album_artist="Band"),
    )
    result = _normalized(tracks, TagProfile(album_artist_aware=aware))
    assert result[0].metadata.compilation
    assert not result[1].metadata.compilation
    assert result[1].album_artist == "Band"


def test_explicit_compilation_preserves_a_named_album_artist() -> None:
    tracks = (
        Track(
            1,
            "Song A",
            "One",
            "Sampler",
            100,
            album_artist="Soundtrack",
            metadata=TrackMetadata(compilation=True),
        ),
        Track(2, "Song B", "Two", "Sampler", 100, album_artist="Soundtrack"),
    )
    result = _normalized(tracks)
    assert all(
        t.metadata.compilation and t.album_artist == "Soundtrack" for t in result
    )
    assert [t.artist for t in result] == ["One", "Two"]


def test_tracks_without_an_album_do_not_share_compilation_evidence() -> None:
    tracks = (
        Track(1, "Song A", "One", "", 100, metadata=TrackMetadata(compilation=True)),
        Track(2, "Song B", "One", "", 100),
    )
    result = _normalized(tracks)
    assert not result[1].metadata.compilation and not result[1].album_artist


@pytest.mark.parametrize("field", ["artist", "album_artist", "album", "composer"])
def test_conflicting_custom_sorts_are_preserved_without_voting(field: str) -> None:
    base = Track(
        1,
        "Song",
        "The Artist",
        "The Album",
        100,
        album_artist="The Artist",
        metadata=TrackMetadata(composer="The Composer"),
    )
    tracks = tuple(
        edit_track_metadata(
            replace(base, track_id=i),
            (TrackFieldEdit(f"metadata.sort_{field}", value),),
        )
        for i, value in enumerate(("Zulu", "Alpha", "Alpha", ""), start=1)
    )
    result = _normalized(tracks)
    assert [getattr(t.metadata, f"sort_{field}") for t in result[:3]] == [
        "Zulu",
        "Alpha",
        "Alpha",
    ]
    display = getattr(base.metadata if field == "composer" else base, field)
    assert getattr(result[3].metadata, f"sort_{field}") == f"{display[4:]}, The"
    assert not normalize_tags(result).updates


def test_unique_custom_sort_wins_over_generated_article_sort_for_missing_values() -> (
    None
):
    tracks = (
        Track(
            1,
            "Song A",
            "The Artist",
            "Record",
            100,
            metadata=TrackMetadata(sort_artist="Custom"),
        ),
        Track(2, "Song B", "The Artist", "Record", 100),
    )
    result = _normalized(tracks)
    assert [t.metadata.sort_artist for t in result] == ["Custom", "Custom"]


def test_feature_sort_does_not_spread_to_solo_or_missing_collaboration_sorts() -> None:
    tracks = (
        Track(
            1,
            "Song A",
            "Lead/Guest A",
            "Record",
            100,
            album_artist="Lead",
            metadata=TrackMetadata(sort_artist="Lead/Guest A"),
        ),
        Track(2, "Song B", "Lead/Guest B", "Record", 100, album_artist="Lead"),
        Track(3, "Song C", "Lead", "Record", 100, album_artist="Lead"),
    )
    result = _normalized(tracks)
    assert [t.metadata.sort_artist for t in result] == ["Lead/Guest A", "Lead", "Lead"]
    assert not normalize_tags(result).updates
    added = replace(tracks[2], track_id=4, title="New solo track")
    assert _normalized((*result, added))[-1].metadata.sort_artist == "Lead"


def test_album_sort_evidence_stays_with_its_album_artist() -> None:
    tracks = (
        Track(
            1,
            "Song A",
            "One",
            "Greatest Hits",
            100,
            album_artist="One",
            metadata=TrackMetadata(sort_album="One Collection"),
        ),
        Track(2, "Song B", "Two", "Greatest Hits", 100, album_artist="Two"),
    )
    result = _normalized(tracks, TagProfile(album_artist_aware=True))
    assert [t.metadata.sort_album for t in result] == [
        "One Collection",
        "Greatest Hits",
    ]


def test_case_variants_do_not_create_album_collisions_or_order_dependent_results() -> (
    None
):
    tracks = (
        Track(1, "Song A", "Artist", "Record", 100, album_artist="Artist"),
        Track(2, "Song B", "artist", "Record", 100, album_artist="artist"),
    )
    result = _normalized(tracks)
    assert [t.album for t in result] == ["Record", "Record"]
    assert _normalized(tracks[::-1])[::-1] == result


def test_missing_album_artist_does_not_invent_an_album_collision() -> None:
    tracks = (
        Track(1, "Song A", "Lead", "Record", 100, album_artist="Lead"),
        Track(2, "Song B", "Lead feat. Guest", "Record", 100),
    )
    assert [t.album for t in _normalized(tracks)] == ["Record", "Record"]


@pytest.mark.parametrize(
    "kind", [MediaType.PODCAST, MediaType.AUDIOBOOK, MediaType.TV_SHOW, MediaType.VIDEO]
)
def test_music_grouping_rules_do_not_rewrite_spoken_word_or_video(
    kind: MediaType,
) -> None:
    tracks = (
        Track(
            1,
            "Episode",
            "Host feat. Guest",
            "Series",
            100,
            album_artist="Host",
            media_types=(kind,),
        ),
        Track(2, "Other", "Other Artist", "Series", 100, album_artist="Other Artist"),
    )
    result = _normalized(tracks)
    assert (result[0].artist, result[0].title, result[0].album) == (
        tracks[0].artist,
        "Episode",
        "Series",
    )
    assert result[1].album == "Series"
