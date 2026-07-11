from __future__ import annotations

from types import SimpleNamespace

from iopenpod.sync.path_identity import stable_path_key
from iopenpod.sync.track_identity import (
    SyncTrackIdentityState,
    build_fingerprint_identity_plan,
)


def test_track_identity_state_records_claims_and_matched_sources(tmp_path) -> None:
    source = tmp_path / "song.mp3"
    source.write_bytes(b"audio")

    state = SyncTrackIdentityState()
    state.claim("101")
    state.record_matched_source(str(source), "101")

    assert state.is_claimed(101)
    assert state.source_path_to_db_track_id == {stable_path_key(source): 101}


def test_track_identity_state_aliases_duplicate_sources_for_playlist_resolution(
    tmp_path,
) -> None:
    representative = tmp_path / "chosen.mp3"
    duplicate = tmp_path / "duplicate.mp3"
    representative.write_bytes(b"same")
    duplicate.write_bytes(b"same")

    state = SyncTrackIdentityState()
    state.record_matched_source(str(representative), 101)
    state.record_duplicate_group_aliases(
        [
            SimpleNamespace(path=str(representative)),
            SimpleNamespace(path=str(duplicate)),
        ]
    )

    playlist_index = state.build_playlist_index(
        pending_add_source_paths=(),
        valid_source_paths=(str(representative),),
    )
    resolved = playlist_index.resolve_playlist_source(str(duplicate))

    assert resolved is not None
    assert resolved.source_path == stable_path_key(representative)
    assert resolved.db_track_id == 101


def test_fingerprint_identity_plan_groups_by_fingerprint_and_album() -> None:
    original = SimpleNamespace(
        artist="Artist",
        album="Album",
        title="Song",
    )
    duplicate = SimpleNamespace(
        artist="Artist",
        album="Album",
        title="Song",
    )
    variant = SimpleNamespace(
        artist="Artist",
        album="Greatest Hits",
        title="Song",
    )

    plan = build_fingerprint_identity_plan({"fp": [original, duplicate, variant]})

    assert set(plan.groups) == {
        ("fp", "album"),
        ("fp", "greatest hits"),
    }
    assert plan.groups[("fp", "album")] == (original, duplicate)
    assert plan.duplicates == {"Artist|Album|Song": (original, duplicate)}


def test_fingerprint_identity_plan_sorts_album_matches_first() -> None:
    album_track = SimpleNamespace(album="Album")
    variant_track = SimpleNamespace(album="Greatest Hits")
    plan = build_fingerprint_identity_plan(
        {
            "fp": [variant_track, album_track],
        }
    )

    class FakeMapping:
        def get_entries(self, fingerprint):
            return [SimpleNamespace(db_track_id=101)]

    sorted_groups = plan.sorted_groups_for_matching(
        mapping=FakeMapping(),
        ipod_by_db_track_id={101: {"Album": "Album"}},
    )

    assert [key for key, _tracks in sorted_groups] == [
        ("fp", "album"),
        ("fp", "greatest hits"),
    ]
