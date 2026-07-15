from pathlib import Path
from types import SimpleNamespace

from iopenpod.sync.existing_track_matcher import (
    best_ipod_track_match,
    candidate_ipod_fingerprint_match_db_track_id,
    existing_track_match_db_track_id,
    mapping_match_db_track_id,
    score_pc_to_ipod_track,
)


def _pc_track(**overrides):
    values = {
        "path": "/music/Song.mp3",
        "relative_path": "Song.mp3",
        "title": "Song",
        "artist": "Artist",
        "album": "Album",
        "track_number": 1,
        "disc_number": 1,
        "year": 2001,
        "duration_ms": 100_000,
        "bitrate": 256,
        "sample_rate": 44_100,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_mapping_match_ignores_stale_db_track_ids() -> None:
    mapping = SimpleNamespace(
        get_entries=lambda _fingerprint: [
            SimpleNamespace(db_track_id=101),
            SimpleNamespace(db_track_id=202),
        ],
    )

    assert mapping_match_db_track_id(mapping, "fp-song", {202}) == 202


def test_candidate_match_fingerprints_only_likely_metadata_candidates(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from iopenpod.sync import audio_fingerprint

    ipod_root = tmp_path / "ipod"
    likely_file = ipod_root / "iPod_Control" / "Music" / "F00" / "Song.mp3"
    unrelated_file = ipod_root / "iPod_Control" / "Music" / "F01" / "Other.mp3"
    likely_file.parent.mkdir(parents=True)
    unrelated_file.parent.mkdir(parents=True)
    likely_file.write_bytes(b"likely")
    unrelated_file.write_bytes(b"other")

    fingerprinted_paths: list[Path] = []

    def fake_fingerprint(path, *_args, **_kwargs):
        fingerprinted_paths.append(Path(path))
        fingerprint = "fp-song" if Path(path) == likely_file else "fp-other"
        return fingerprint, "computed"

    monkeypatch.setattr(
        audio_fingerprint,
        "get_or_compute_fingerprint_with_status",
        fake_fingerprint,
    )

    db_track_id = candidate_ipod_fingerprint_match_db_track_id(
        ipod_root,
        [
            {
                "db_track_id": 111,
                "Title": "Song",
                "Artist": "Artist",
                "Album": "Album",
                "Location": ":iPod_Control:Music:F00:Song.mp3",
                "track_number": 1,
                "disc_number": 1,
                "length": 100_200,
            },
            {
                "db_track_id": 222,
                "Title": "Unrelated",
                "Artist": "Someone Else",
                "Album": "Other Album",
                "Location": ":iPod_Control:Music:F01:Other.mp3",
                "track_number": 9,
                "disc_number": 1,
                "length": 100_000,
            },
        ],
        _pc_track(),
        tmp_path / "Song.mp3",
        "fp-song",
        fpcalc_path=None,
        fingerprint_cache={},
    )

    assert db_track_id == 111
    assert fingerprinted_paths == [likely_file]


def test_existing_track_match_uses_direct_ipod_source_path_even_with_weak_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from iopenpod.sync import audio_fingerprint

    ipod_root = tmp_path / "ipod"
    ipod_file = ipod_root / "iPod_Control" / "Music" / "F00" / "Song.mp3"
    ipod_file.parent.mkdir(parents=True)
    ipod_file.write_bytes(b"audio")
    mapping = SimpleNamespace(get_entries=lambda _fingerprint: [])

    monkeypatch.setattr(
        audio_fingerprint,
        "get_or_compute_fingerprint_with_status",
        lambda path, *_args, **_kwargs: (
            ("fp-song", "computed") if Path(path) == ipod_file else (None, "failed")
        ),
    )

    db_track_id = existing_track_match_db_track_id(
        ipod_root,
        [
            {
                "db_track_id": 333,
                "Title": "Device Metadata",
                "Artist": "Different",
                "Album": "Different",
                "Location": ":iPod_Control:Music:F00:Song.mp3",
                "track_number": 7,
                "disc_number": 1,
                "length": 95_000,
            }
        ],
        _pc_track(title="Playlist Name", artist="Playlist Artist", album="Playlist Album"),
        ipod_file,
        "fp-song",
        mapping=mapping,
        valid_db_track_ids={333},
        fpcalc_path=None,
        fingerprint_cache={},
    )

    assert db_track_id == 333


def test_best_match_uses_rich_metadata_score_with_deterministic_tie_break() -> None:
    pc_track = _pc_track()
    full_match = {
        "db_track_id": 20,
        "Title": "Song",
        "Artist": "Artist",
        "Album": "Album",
        "track_number": 1,
        "disc_number": 1,
        "year": 2001,
        "length": 100_250,
        "bitrate": 248,
        "sample_rate_1": 44_100,
    }
    title_only = {
        "db_track_id": 10,
        "Title": "Song",
        "Artist": "Other",
        "Album": "Other",
        "track_number": 2,
        "disc_number": 1,
        "length": 120_000,
    }

    assert score_pc_to_ipod_track(pc_track, full_match) > score_pc_to_ipod_track(
        pc_track,
        title_only,
    )
    assert best_ipod_track_match(
        [(10, title_only), (20, full_match)],
        pc_track,
    ) == 20
    assert best_ipod_track_match(
        [
            (30, {"Title": "Song"}),
            (20, {"Title": "Song"}),
        ],
        _pc_track(),
    ) == 20
