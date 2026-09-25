"""Behavioral coverage for supported Smart Playlist matching and limit previews."""

from dataclasses import replace

import pytest

from iOpenPod.app.smart_playlist_preview import preview_smart_playlist
from iPodDB.library import (
    IPodTrackDetails,
    MediaType,
    Playlist,
    PlaylistKind,
    SmartField,
    SmartLimitSort,
    SmartLimitUnit,
    SmartLocation,
    SmartMatch,
    SmartMediaKind,
    SmartOperator,
    SmartPlaylist,
    SmartPlaylistLimit,
    SmartPlaylistReference,
    SmartRule,
    SmartRuleGroup,
    Track,
    TrackMetadata,
    UnsupportedSmartRule,
    playlist_entries,
)

_TRACKS = (
    Track(1, "Yesterday", "The Beatles", "Help!", 120_000, year=1965, rating=100),
    Track(
        2,
        "Across the Universe",
        "The Beatles",
        "Let It Be",
        210_000,
        year=1970,
        rating=80,
    ),
    Track(
        3, "Thunderstruck", "AC/DC", "The Razors Edge", 292_000, year=1990, rating=60
    ),
)


def _ids(smart: SmartPlaylist, tracks: tuple[Track, ...] = _TRACKS) -> tuple[int, ...]:
    return tuple(track.track_id for track in preview_smart_playlist(tracks, smart))


def test_all_and_any_rules_are_case_insensitive_and_numeric_ranges_are_inclusive() -> (
    None
):
    rules = (
        SmartRule(SmartField.ARTIST, SmartOperator.CONTAINS, "beatles"),
        SmartRule(SmartField.YEAR, SmartOperator.BETWEEN, 1970, 1990),
    )

    assert _ids(SmartPlaylist(rules=SmartRuleGroup(SmartMatch.ALL, rules))) == (2,)
    assert _ids(SmartPlaylist(rules=SmartRuleGroup(SmartMatch.ANY, rules))) == (1, 2, 3)


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    (
        (SmartOperator.IS, "YESTERDAY", (1,)),
        (SmartOperator.IS_NOT, "yesterday", (2, 3)),
        (SmartOperator.CONTAINS, "THE", (2,)),
        (SmartOperator.NOT_CONTAINS, "the", (1, 3)),
        (SmartOperator.BEGINS_WITH, "THUNDER", (3,)),
        (SmartOperator.ENDS_WITH, "verse", (2,)),
    ),
)
def test_supported_text_comparisons(
    operator: SmartOperator, value: str, expected: tuple[int, ...]
) -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(rules=(SmartRule(SmartField.TITLE, operator, value),))
    )
    assert _ids(smart) == expected


def test_checked_only_and_disabled_rules_apply_independently() -> None:
    tracks = tuple(
        replace(track, metadata=TrackMetadata(checked=track.track_id != 2))
        for track in _TRACKS
    )
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.RATING, SmartOperator.GREATER_THAN, 90),)
        ),
        checked_only=True,
    )

    assert _ids(smart, tracks) == (1,)
    assert _ids(replace(smart, match_rules=False), tracks) == (1, 3)


def test_count_limit_uses_requested_order_and_random_is_repeatable() -> None:
    limit = SmartPlaylistLimit(2, SmartLimitUnit.TRACKS, SmartLimitSort.TITLE)

    assert _ids(SmartPlaylist(limit=limit)) == (2, 3)
    assert _ids(SmartPlaylist(limit=replace(limit, descending=True))) == (1, 3)
    random_smart = SmartPlaylist(limit=replace(limit, sort=SmartLimitSort.RANDOM))
    assert _ids(random_smart) == _ids(random_smart)
    assert len(set(_ids(random_smart))) == 2
    assert _TRACKS[0].title == "Yesterday"


@pytest.mark.parametrize(
    ("unit", "value", "lengths", "sizes", "expected"),
    (
        (SmartLimitUnit.MINUTES, 3, (120_000, 90_000, 30_000), (0, 0, 0), (1, 3)),
        (SmartLimitUnit.HOURS, 1, (1_800_000, 2_000_000, 600_000), (0, 0, 0), (1, 3)),
        (SmartLimitUnit.MEGABYTES, 1, (0, 0, 0), (600_000, 600_000, 100_000), (1, 3)),
        (
            SmartLimitUnit.GIGABYTES,
            1,
            (0, 0, 0),
            (600_000_000, 600_000_000, 100_000_000),
            (1, 3),
        ),
    ),
)
def test_duration_and_size_limits_skip_tracks_that_would_exceed_the_budget(
    unit: SmartLimitUnit,
    value: int,
    lengths: tuple[int, ...],
    sizes: tuple[int, ...],
    expected: tuple[int, ...],
) -> None:
    tracks = tuple(
        replace(
            track,
            length_ms=length,
            size_bytes=size,
            metadata=TrackMetadata(date_added=index),
        )
        for index, (track, length, size) in enumerate(
            zip(_TRACKS, lengths, sizes, strict=True)
        )
    )
    smart = SmartPlaylist(
        limit=SmartPlaylistLimit(value, unit, SmartLimitSort.DATE_ADDED)
    )
    assert _ids(smart, tracks) == expected


@pytest.mark.parametrize(
    "smart",
    (
        SmartPlaylist(editable=False),
        SmartPlaylist(rules=SmartRuleGroup(rules=(UnsupportedSmartRule(),))),
        SmartPlaylist(
            rules=SmartRuleGroup(
                rules=(SmartRule(SmartField.YEAR, SmartOperator.IS, "2000"),)
            )
        ),
        SmartPlaylist(
            rules=SmartRuleGroup(
                rules=(SmartRule(SmartField.TITLE, SmartOperator.LESS_THAN, "Song"),)
            )
        ),
        SmartPlaylist(
            rules=SmartRuleGroup(
                rules=(SmartRule(SmartField.YEAR, SmartOperator.BETWEEN, 2000, 1990),)
            )
        ),
        SmartPlaylist(
            rules=SmartRuleGroup(
                rules=(SmartRule(SmartField.RATING, SmartOperator.IS, 101),)
            )
        ),
        SmartPlaylist(
            limit=SmartPlaylistLimit(0, SmartLimitUnit.TRACKS, SmartLimitSort.TITLE)
        ),
    ),
)
def test_invalid_or_unsupported_rules_never_silently_return_all_tracks(
    smart: SmartPlaylist,
) -> None:
    with pytest.raises(ValueError):
        preview_smart_playlist(_TRACKS, smart)


def test_nested_groups_and_empty_group_truth_values() -> None:
    nested = SmartRuleGroup(
        SmartMatch.ANY,
        (
            SmartRule(SmartField.ARTIST, SmartOperator.CONTAINS, "Beatles"),
            SmartRule(SmartField.YEAR, SmartOperator.IS, 1990),
        ),
    )
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(nested, SmartRule(SmartField.RATING, SmartOperator.GREATER_THAN, 60))
        )
    )
    assert _ids(smart) == (1, 2)
    # An empty root disables rule filtering in the Original/libgpod update flow;
    # nested groups retain the ordinary boolean identity.
    assert _ids(SmartPlaylist(rules=SmartRuleGroup(SmartMatch.ANY))) == (1, 2, 3)
    assert (
        _ids(
            SmartPlaylist(rules=SmartRuleGroup(rules=(SmartRuleGroup(SmartMatch.ANY),)))
        )
        == ()
    )
    assert _ids(SmartPlaylist(rules=SmartRuleGroup(rules=(SmartRuleGroup(),)))) == (
        1,
        2,
        3,
    )


def test_relative_dates_are_evaluated_once_at_the_supplied_instant() -> None:
    tracks = (
        replace(_TRACKS[0], metadata=TrackMetadata(last_played=100)),
        replace(_TRACKS[1], metadata=TrackMetadata(last_played=101)),
        _TRACKS[2],
    )
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.LAST_PLAYED, SmartOperator.IN_LAST, 100),)
        )
    )
    assert tuple(
        t.track_id for t in preview_smart_playlist(tracks, smart, now=200)
    ) == (2,)
    inverse = replace(
        smart,
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.LAST_PLAYED, SmartOperator.NOT_IN_LAST, 100),)
        ),
    )
    assert tuple(
        t.track_id for t in preview_smart_playlist(tracks, inverse, now=200)
    ) == (1, 3)


def test_boolean_and_extended_metadata_conditions() -> None:
    track = replace(
        _TRACKS[0], metadata=TrackMetadata(compilation=True, composer="Bach", bpm=120)
    )
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(
                SmartRule(SmartField.COMPILATION, SmartOperator.IS_TRUE, 0),
                SmartRule(SmartField.COMPOSER, SmartOperator.IS, "BACH"),
                SmartRule(SmartField.BPM, SmartOperator.BETWEEN, 119, 121),
            )
        )
    )
    assert _ids(smart, (track,)) == (1,)


def test_playlist_rules_use_saved_membership_including_folder_descendants() -> None:
    folder = Playlist(20, "Folder", PlaylistKind.FOLDER)
    child = Playlist(
        10,
        "Road trip",
        parent_id=20,
        entries=playlist_entries((1, 3)),
    )
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(
                SmartRule(
                    SmartField.PLAYLIST,
                    SmartOperator.IS,
                    SmartPlaylistReference(20),
                ),
            )
        )
    )

    assert tuple(
        track.track_id
        for track in preview_smart_playlist(_TRACKS, smart, playlists=(folder, child))
    ) == (1, 3)
    inverse = replace(
        smart,
        rules=SmartRuleGroup(
            rules=(
                SmartRule(
                    SmartField.PLAYLIST,
                    SmartOperator.IS_NOT,
                    SmartPlaylistReference(10),
                ),
            )
        ),
    )
    assert tuple(
        track.track_id
        for track in preview_smart_playlist(_TRACKS, inverse, playlists=(folder, child))
    ) == (2,)


def test_missing_playlist_rule_reference_is_an_error() -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(
                SmartRule(
                    SmartField.PLAYLIST,
                    SmartOperator.IS,
                    SmartPlaylistReference(999),
                ),
            )
        )
    )
    with pytest.raises(ValueError, match="missing Playlist 999"):
        preview_smart_playlist(_TRACKS, smart)


def test_purchased_media_kind_and_location_choices_are_evaluated() -> None:
    tracks = (
        replace(_TRACKS[0], ipod=IPodTrackDetails(purchased_aac_flag=1)),
        replace(_TRACKS[1], media_types=(MediaType.MUSIC_VIDEO,)),
        replace(_TRACKS[2], media_types=(MediaType.PODCAST,)),
    )
    rules = SmartRuleGroup(
        SmartMatch.ANY,
        (
            SmartRule(SmartField.PURCHASED, SmartOperator.IS_TRUE, 0),
            SmartRule(
                SmartField.MEDIA_KIND,
                SmartOperator.IS,
                SmartMediaKind.MUSIC_VIDEO,
            ),
        ),
    )
    assert _ids(SmartPlaylist(rules=rules), tracks) == (1, 2)
    assert _ids(
        SmartPlaylist(
            rules=SmartRuleGroup(
                rules=(
                    SmartRule(
                        SmartField.LOCATION,
                        SmartOperator.IS,
                        SmartLocation.LOCAL,
                    ),
                )
            )
        ),
        tracks,
    ) == (1, 2, 3)
