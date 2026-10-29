"""Play count merge rules, song matching, and durable state."""

import json
from pathlib import Path

import pytest

from iOpenPod.app.jellyfin.device_state import (
    DevicePlayCounts,
    decode_play_counts,
    encode_play_counts,
)
from iOpenPod.app.jellyfin.matching import MatchOutcome, TrackIndex
from iOpenPod.app.jellyfin.models import JellyfinError, JellyfinTrack
from iOpenPod.app.jellyfin.state import (
    PairState,
    PlayCountState,
    PlayCountStore,
    merged_count,
)
from iPodDB.library import Track, TrackMetadata
from storage import AtomicHostFile


def remote(
    item_id: str = "a" * 32,
    title: str = "Song",
    *,
    album: str = "Album",
    artists: tuple[str, ...] = ("Artist",),
    number: int = 1,
    length_ms: int = 180_000,
) -> JellyfinTrack:
    return JellyfinTrack(item_id, title, album, artists, "", number, 1, length_ms, 0)


def local(
    title: str = "Song",
    *,
    artist: str = "Artist",
    album: str = "Album",
    number: int = 1,
    length_ms: int = 181_000,
) -> Track:
    return Track(
        1,
        title,
        artist,
        album,
        length_ms,
        track_number=number,
        metadata=TrackMetadata(disc_number=1),
    )


def test_first_pairing_takes_the_larger_count() -> None:
    assert merged_count(None, 3, 8) == 8
    assert merged_count(None, 9, 2) == 9


def test_plays_on_both_sides_since_last_sync_are_added() -> None:
    previous = PairState("a" * 32, 10, 10, 10)
    assert merged_count(previous, 13, 11) == 14
    assert merged_count(previous, 10, 10) == 10


def test_a_jellyfin_count_that_was_never_sent_still_counts_once() -> None:
    # The iPod holds the merged 12, but Jellyfin was last seen at 9.
    previous = PairState("a" * 32, 12, 12, 9)
    assert merged_count(previous, 12, 9) == 12
    assert merged_count(previous, 12, 10) == 13


def test_decreases_are_not_propagated() -> None:
    previous = PairState("a" * 32, 10, 10, 10)
    assert merged_count(previous, 10, 0) == 10
    assert merged_count(previous, 4, 12) == 12


def test_an_unconfirmed_ipod_save_falls_back_to_the_larger_count() -> None:
    previous = PairState("a" * 32, 10, 5, 5, pending=True)
    assert merged_count(previous, 12, 7) == 12


def test_match_by_title_album_artist_number_and_length() -> None:
    index = TrackIndex((remote(), remote("b" * 32, "Other")))
    found = index.match(local(title=" song ", album="ALBUM"))
    assert found.outcome is MatchOutcome.MATCHED
    assert found.remote is not None and found.remote.item_id == "a" * 32


@pytest.mark.parametrize(
    "track",
    [
        local(artist="Someone Else"),
        local(number=2),
        local(length_ms=190_000),
        local(album="Live"),
        local(title=""),
    ],
)
def test_conflicting_metadata_is_unmatched(track: Track) -> None:
    assert TrackIndex((remote(),)).match(track).outcome is MatchOutcome.UNMATCHED


def test_featured_artists_match_jellyfins_split_artists() -> None:
    index = TrackIndex((remote(artists=("Artist", "Guest")),))
    track = local(artist="Artist feat. Guest")
    assert index.match(track).outcome is MatchOutcome.MATCHED


def test_several_candidates_are_ambiguous_not_guessed() -> None:
    index = TrackIndex((remote(), remote("b" * 32)))
    assert index.match(local()).outcome is MatchOutcome.AMBIGUOUS


def test_a_remembered_item_wins_over_metadata() -> None:
    index = TrackIndex((remote(), remote("b" * 32)))
    found = index.match(local(title="Renamed"), "b" * 32)
    assert found.remote is not None and found.remote.item_id == "b" * 32


def test_state_round_trips(tmp_path: Path) -> None:
    store = PlayCountStore(AtomicHostFile(tmp_path / "state.json"))
    assert store.load() == PlayCountState()
    state = PlayCountState({"key": PairState("a" * 32, 5, 5, 3, pending=True)})
    store.save(state)
    assert store.load() == state


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        json.dumps({"version": 2, "pairs": {}}).encode(),
        json.dumps(
            {
                "version": 1,
                "pairs": {
                    "key": {
                        "item_id": "a",
                        "agreed": 1,
                        "ipod_seen": 5,
                        "jellyfin_seen": 0,
                        "pending": False,
                    }
                },
            }
        ).encode(),
    ],
)
def test_unreadable_state_is_reported_and_preserved(
    tmp_path: Path, content: bytes
) -> None:
    path = tmp_path / "state.json"
    path.write_bytes(content)
    with pytest.raises(JellyfinError, match="unreadable"):
        PlayCountStore(AtomicHostFile(path)).load()
    assert path.read_bytes() == content


def test_ipod_memory_round_trips_compactly_and_deterministically() -> None:
    state = DevicePlayCounts(
        {
            "server:user": {
                101: PairState("a" * 32, 8, 8, 6),
                7: PairState("b" * 32, 1, 1, 1),
            }
        }
    )
    data = encode_play_counts(state)
    assert decode_play_counts(data) == state
    assert data == encode_play_counts(decode_play_counts(data))
    assert b" " not in data


@pytest.mark.parametrize(
    "document",
    [
        {"version": 2, "accounts": {}},
        {"version": 1, "accounts": {"a": {"x": {}}}},
        {"version": 1, "accounts": {"a": {"0": {}}}},
        {
            "version": 1,
            "accounts": {
                "a": {"5": {"item": "i", "agreed": 1, "ipod": 2, "jellyfin": 0}}
            },
        },
        {
            "version": 1,
            "accounts": {
                "a": {"5": {"item": "", "agreed": 1, "ipod": 1, "jellyfin": 1}}
            },
        },
    ],
)
def test_invalid_ipod_memory_is_refused(document: object) -> None:
    with pytest.raises(JellyfinError, match="unreadable"):
        decode_play_counts(json.dumps(document).encode())
