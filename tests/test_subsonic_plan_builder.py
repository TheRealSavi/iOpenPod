from __future__ import annotations

from SubsonicManager.plan_builder import (
    _collect_playlists,
    _match_key,
    build_subsonic_sync_plan,
)


class _FakeClient:
    """Stub client returning canned catalog data."""

    def __init__(
        self,
        *,
        playlists_by_id: dict[str, dict] | None = None,
    ) -> None:
        self._playlists = playlists_by_id or {}

    def get_playlist(self, playlist_id: str) -> dict:
        return self._playlists.get(playlist_id, {})


def _song(sid, artist="A", title="T", **kw):
    base = {"id": sid, "artist": artist, "title": title, "suffix": "mp3"}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# _match_key (fuzzy de-dup)
# ---------------------------------------------------------------------------


def test_match_key_normalizes_curly_quotes() -> None:
    assert _match_key("I Don\u2019t Know Why", "Imagine Dragons") == _match_key(
        "I Don't Know Why", "Imagine Dragons"
    )


def test_match_key_normalizes_case_and_whitespace() -> None:
    assert _match_key("  Hello   World ", "The Artist") == _match_key(
        "hello world", "the artist"
    )


def test_match_key_strips_punctuation() -> None:
    assert _match_key("Song! (Remix)", "Artist") == _match_key(
        "Song Remix", "Artist"
    )


# ---------------------------------------------------------------------------
# collect playlists
# ---------------------------------------------------------------------------


def test_collect_playlists_returns_id_name_songs() -> None:
    client = _FakeClient(
        playlists_by_id={
            "p1": {"name": "Faves", "entry": [_song("e1"), _song("e2")]},
        }
    )
    result = _collect_playlists(client, ["p1"])
    assert len(result) == 1
    pid, name, songs = result[0]
    assert pid == "p1" and name == "Faves"
    assert [s["id"] for s in songs] == ["e1", "e2"]


def test_collect_playlists_ignores_blank_ids() -> None:
    client = _FakeClient(playlists_by_id={"p1": {"entry": [_song("e1")]}})
    assert len(_collect_playlists(client, ["", "  ", "p1"])) == 1


def test_collect_playlists_tolerates_fetch_failure() -> None:
    class BoomClient(_FakeClient):
        def get_playlist(self, pid):
            raise RuntimeError("boom")

    assert _collect_playlists(BoomClient(), ["p1"]) == []


# ---------------------------------------------------------------------------
# build_subsonic_sync_plan — playlist-only
# ---------------------------------------------------------------------------


def test_plan_no_playlists_when_none_selected() -> None:
    client = _FakeClient()
    plan = build_subsonic_sync_plan(client, ipod_tracks=[], cache_dir="/tmp")
    assert plan.to_add == []
    assert plan.playlists_to_add == []
    assert plan.playlists_to_edit == []


def test_plan_creates_playlist_with_matched_tracks() -> None:
    client = _FakeClient(
        playlists_by_id={"p1": {"name": "My Favorites", "entry": [_song("s1", "A", "One")]}}
    )
    plan = build_subsonic_sync_plan(
        client,
        ipod_tracks=[{"Title": "One", "Artist": "A", "db_track_id": 10}],
        cache_dir="/tmp",
        playlist_ids=["p1"],
    )
    assert plan.to_add == []  # no songs downloaded
    assert len(plan.playlists_to_add) == 1
    pl = plan.playlists_to_add[0]
    assert pl["Title"] == "My Favorites"
    assert pl["_isNew"] is True
    assert pl["_source"] == "subsonic"
    assert pl["items"] == [{"db_track_id": 10}]


def test_plan_skips_unmatched_tracks() -> None:
    client = _FakeClient(
        playlists_by_id={"p1": {"name": "PL", "entry": [_song("s1", "A", "One"),
                                                       _song("s2", "B", "Two")]}}
    )
    plan = build_subsonic_sync_plan(
        client,
        ipod_tracks=[{"Title": "One", "Artist": "A", "db_track_id": 1}],  # s2 not on iPod
        cache_dir="/tmp",
        playlist_ids=["p1"],
    )
    pl = plan.playlists_to_add[0]
    # Only s1 is matched; s2 dropped.
    assert pl["items"] == [{"db_track_id": 1}]


def test_plan_drops_playlist_with_no_matches() -> None:
    client = _FakeClient(
        playlists_by_id={"p1": {"name": "PL", "entry": [_song("s1", "X", "Y")]}}
    )
    plan = build_subsonic_sync_plan(
        client,
        ipod_tracks=[{"Title": "Other", "Artist": "Other", "db_track_id": 99}],
        cache_dir="/tmp",
        playlist_ids=["p1"],
    )
    assert plan.playlists_to_add == []


def test_plan_fuzzy_match_tolerates_curly_quotes() -> None:
    client = _FakeClient(
        playlists_by_id={"p1": {"name": "PL", "entry": [
            {"id": "s1", "title": "I Don\u2019t Know Why", "artist": "Imagine Dragons"}
        ]}}
    )
    plan = build_subsonic_sync_plan(
        client,
        ipod_tracks=[{"Title": "I Don't Know Why", "Artist": "Imagine Dragons",
                       "db_track_id": 77}],
        cache_dir="/tmp",
        playlist_ids=["p1"],
    )
    pl = plan.playlists_to_add[0]
    assert pl["items"] == [{"db_track_id": 77}]


def test_plan_multiple_playlists() -> None:
    client = _FakeClient(
        playlists_by_id={
            "p1": {"name": "Rock", "entry": [_song("r1")]},
            "p2": {"name": "Jazz", "entry": [_song("j1")]},
        }
    )
    plan = build_subsonic_sync_plan(
        client,
        ipod_tracks=[
            {"Title": "T", "Artist": "A", "db_track_id": 1},  # matches both _song defaults
        ],
        cache_dir="/tmp",
        playlist_ids=["p1", "p2"],
    )
    titles = sorted(pl["Title"] for pl in plan.playlists_to_add)
    assert titles == ["Jazz", "Rock"]


def test_plan_playlist_id_stable() -> None:
    client = _FakeClient(
        playlists_by_id={"p1": {"name": "PL", "entry": [_song("s1")]}}
    )
    plan_a = build_subsonic_sync_plan(
        client, ipod_tracks=[{"Title": "T", "Artist": "A", "db_track_id": 1}],
        cache_dir="/tmp", playlist_ids=["p1"],
    )
    plan_b = build_subsonic_sync_plan(
        client, ipod_tracks=[{"Title": "T", "Artist": "A", "db_track_id": 1}],
        cache_dir="/tmp", playlist_ids=["p1"],
    )
    assert plan_a.playlists_to_add[0]["playlist_id"] == plan_b.playlists_to_add[0]["playlist_id"]


# ---------------------------------------------------------------------------
# playlist mapping / merge
# ---------------------------------------------------------------------------


def _ipod_playlist(pid: int, name: str, member_ids: list[int]) -> dict:
    return {
        "playlist_id": pid,
        "Title": name,
        "items": [{"db_track_id": mid} for mid in member_ids],
    }


def test_plan_mapped_playlist_merges_into_existing() -> None:
    client = _FakeClient(
        playlists_by_id={"p1": {"name": "Subsonic PL", "entry": [_song("s1")]}}
    )
    ipod_pls = [_ipod_playlist(500, "Favorites", [10, 20])]
    plan = build_subsonic_sync_plan(
        client,
        ipod_tracks=[{"Title": "T", "Artist": "A", "db_track_id": 1}],
        cache_dir="/tmp",
        playlist_ids=["p1"],
        playlist_mappings={"p1": 500},
        ipod_playlists=ipod_pls,
    )
    # mapped -> merged (not new)
    assert plan.playlists_to_add == []
    assert len(plan.playlists_to_edit) == 1
    pl = plan.playlists_to_edit[0]
    assert pl["_isNew"] is False
    assert pl["playlist_id"] == 500
    assert pl["Title"] == "Favorites"
    # existing + new track, both resolved by db_track_id
    db_ids = sorted(it["db_track_id"] for it in pl["items"])
    assert db_ids == [1, 10, 20]
    assert pl["mhip_child_count"] == 3


def test_plan_mapping_target_missing_falls_back_to_create() -> None:
    client = _FakeClient(
        playlists_by_id={"p1": {"name": "PL", "entry": [_song("s1")]}}
    )
    plan = build_subsonic_sync_plan(
        client,
        ipod_tracks=[{"Title": "T", "Artist": "A", "db_track_id": 1}],
        cache_dir="/tmp",
        playlist_ids=["p1"],
        playlist_mappings={"p1": 9999},
        ipod_playlists=[],
    )
    assert len(plan.playlists_to_add) == 1
    assert plan.playlists_to_add[0]["_isNew"] is True
    assert plan.playlists_to_edit == []


def test_plan_partial_mapping() -> None:
    client = _FakeClient(
        playlists_by_id={
            "p1": {"name": "Mapped", "entry": [_song("s1")]},
            "p2": {"name": "New", "entry": [_song("s2")]},
        }
    )
    ipod_pls = [_ipod_playlist(100, "Existing", [5])]
    plan = build_subsonic_sync_plan(
        client,
        ipod_tracks=[{"Title": "T", "Artist": "A", "db_track_id": 1}],
        cache_dir="/tmp",
        playlist_ids=["p1", "p2"],
        playlist_mappings={"p1": 100},
        ipod_playlists=ipod_pls,
    )
    assert len(plan.playlists_to_edit) == 1
    assert plan.playlists_to_edit[0]["playlist_id"] == 100
    assert len(plan.playlists_to_add) == 1
    assert plan.playlists_to_add[0]["Title"] == "New"


def test_plan_overwrite_mapping_replaces_existing_members() -> None:
    """A negative mapping target means overwrite — existing iPod members replaced."""
    client = _FakeClient(
        playlists_by_id={"p1": {"name": "PL", "entry": [_song("s1")]}}
    )
    ipod_pls = [_ipod_playlist(500, "Favorites", [10, 20, 30])]
    plan = build_subsonic_sync_plan(
        client,
        ipod_tracks=[{"Title": "T", "Artist": "A", "db_track_id": 1}],
        cache_dir="/tmp",
        playlist_ids=["p1"],
        playlist_mappings={"p1": -500},
        ipod_playlists=ipod_pls,
    )
    assert len(plan.playlists_to_edit) == 1
    pl = plan.playlists_to_edit[0]
    assert pl["playlist_id"] == 500
    assert pl["_isNew"] is False
    # Only the new remote track — existing members 10,20,30 are gone.
    assert pl["items"] == [{"db_track_id": 1}]
