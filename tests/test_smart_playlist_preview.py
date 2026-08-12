from __future__ import annotations

import copy

from iopenpod.application.smart_playlist_preview import (
    SmartPlaylistPreviewRequest,
    compute_smart_playlist_preview,
)
from iopenpod.itunesdb_writer.mhod_spl_writer import (
    SmartPlaylistPrefs,
    SmartPlaylistRules,
)
from iopenpod.sync.spl_evaluator import spl_update


class _ReadOnlyPreviewSource:
    def __init__(self) -> None:
        self.tracks = [
            {"track_id": 1, "Title": "Yesterday", "Artist": "The Beatles"},
            {"track_id": 2, "Title": "Across the Universe", "Artist": "The Beatles"},
            {"track_id": 3, "Title": "Thunderstruck", "Artist": "AC/DC"},
        ]
        self.playlists = [{"playlist_id": 10, "items": [{"track_id": 1}, {"track_id": 3}]}]
        self.reads: list[str] = []
        self.write_attempts = 0

    def get_tracks(self) -> list[dict]:
        self.reads.append("tracks")
        return list(self.tracks)

    def get_playlists(self) -> list[dict]:
        self.reads.append("playlists")
        return list(self.playlists)

    def get_data(self) -> dict:
        self.reads.append("data")
        return {}

    def save_user_playlist(self, _playlist: dict) -> None:
        self.write_attempts += 1
        raise AssertionError("a live preview must never persist")


def test_preview_computes_and_sorts_without_mutating_or_persisting() -> None:
    source = _ReadOnlyPreviewSource()
    original_tracks = copy.deepcopy(source.tracks)
    original_playlists = copy.deepcopy(source.playlists)
    request = SmartPlaylistPreviewRequest(
        generation=7,
        preferences={"check_rules": True, "check_limits": False},
        rules={
            "conjunction": "AND",
            "rules": [
                {
                    "field_id": 0x04,
                    "action_id": 0x01000002,
                    "string_value": "beatles",
                }
            ],
        },
        sort_order=3,
    )

    result = compute_smart_playlist_preview(request, source, lambda: False)

    assert result.generation == 7
    assert [track["track_id"] for track in result.tracks] == [2, 1]
    assert source.reads == ["tracks", "playlists", "data"]
    assert source.write_attempts == 0
    assert source.tracks == original_tracks
    assert source.playlists == original_playlists


def test_preview_playlist_membership_rules_use_read_only_cached_membership() -> None:
    source = _ReadOnlyPreviewSource()
    request = SmartPlaylistPreviewRequest(
        generation=3,
        preferences={"check_rules": True},
        rules={
            "conjunction": "AND",
            "rules": [
                {
                    "field_id": 0x28,
                    "action_id": 0x00000001,
                    "from_value": 10,
                }
            ],
        },
    )

    result = compute_smart_playlist_preview(request, source, lambda: False)

    assert [track["track_id"] for track in result.tracks] == [1, 3]
    assert source.write_attempts == 0


def test_preview_cancellation_avoids_even_read_only_cache_work() -> None:
    source = _ReadOnlyPreviewSource()

    result = compute_smart_playlist_preview(
        SmartPlaylistPreviewRequest(1, {}, {}),
        source,
        lambda: True,
    )

    assert result.tracks == []
    assert source.reads == []


def test_evaluator_cooperatively_stops_a_large_scan() -> None:
    tracks = [{"track_id": track_id} for track_id in range(1000)]
    cancellation_checks = 0

    def is_cancelled() -> bool:
        nonlocal cancellation_checks
        cancellation_checks += 1
        return cancellation_checks >= 2

    result = spl_update(
        SmartPlaylistPrefs(check_rules=False),
        SmartPlaylistRules(),
        tracks,
        is_cancelled=is_cancelled,
    )

    assert result == []
    assert cancellation_checks == 2
