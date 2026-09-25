from pathlib import Path

from iopenpod.sync.integrity import check_integrity
from iopenpod.sync.ipod_track_paths import expected_ipod_track_file_path
from iopenpod.sync.mapping import MappingFile


def _make_music_file(ipod_root: Path, folder: str, filename: str) -> Path:
    path = ipod_root / "iPod_Control" / "Music" / folder / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"audio")
    return path


def test_resolve_location_returns_expected_missing_colon_path(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"

    resolved = expected_ipod_track_file_path(
        ipod_root,
        ":iPod_Control:Music:F00:GONE.mp3",
    )

    assert resolved == ipod_root / "iPod_Control" / "Music" / "F00" / "GONE.mp3"


def test_resolve_location_returns_expected_missing_windows_device_path(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"

    resolved = expected_ipod_track_file_path(
        ipod_root,
        r"X:\iPod_Control\Music\F01\GONE.m4a",
    )

    assert resolved == ipod_root / "iPod_Control" / "Music" / "F01" / "GONE.m4a"


def test_resolve_location_skips_external_windows_path_without_ipod_marker(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"

    resolved = expected_ipod_track_file_path(
        ipod_root,
        r"C:\Users\Someone\Music\Song.mp3",
    )

    assert resolved is None


def test_integrity_reports_missing_db_file_without_mutating_tracks(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    existing = _make_music_file(ipod_root, "F00", "LIVE.mp3")
    tracks = [
        {
            "db_track_id": 1,
            "Title": "Ghost",
            "Location": ":iPod_Control:Music:F00:GONE.mp3",
        },
        {
            "db_track_id": 2,
            "Title": "Live",
            "Location": ":iPod_Control:Music:F00:LIVE.mp3",
        },
    ]

    report = check_integrity(
        ipod_root,
        tracks,
        MappingFile(),
        delete_orphans=False,
    )

    assert report.missing_files == [
        {
            "db_track_id": 1,
            "Title": "Ghost",
            "Location": ":iPod_Control:Music:F00:GONE.mp3",
        }
    ]
    assert tracks == [
        {
            "db_track_id": 1,
            "Title": "Ghost",
            "Location": ":iPod_Control:Music:F00:GONE.mp3",
        },
        {
            "db_track_id": 2,
            "Title": "Live",
            "Location": ":iPod_Control:Music:F00:LIVE.mp3",
        }
    ]
    assert report.orphan_files == []
    assert existing.is_file()


def test_integrity_treats_directory_location_as_missing_without_removing_track(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    bogus_dir = ipod_root / "iPod_Control" / "Music" / "F00" / "DIR.mp3"
    bogus_dir.mkdir(parents=True)
    tracks = [
        {
            "db_track_id": 1,
            "Title": "Directory",
            "Location": ":iPod_Control:Music:F00:DIR.mp3",
        },
    ]

    report = check_integrity(
        ipod_root,
        tracks,
        MappingFile(),
        delete_orphans=False,
    )

    assert [track["Title"] for track in report.missing_files] == ["Directory"]
    assert len(tracks) == 1


def test_integrity_ignores_appledouble_sidecar_orphans(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    real = _make_music_file(ipod_root, "F00", "LIVE.m4a")
    sidecar = _make_music_file(ipod_root, "F00", "._LIVE.m4a")
    tracks = [
        {
            "db_track_id": 1,
            "Title": "Live",
            "Location": ":iPod_Control:Music:F00:LIVE.m4a",
        }
    ]

    report = check_integrity(
        ipod_root,
        tracks,
        MappingFile(),
        delete_orphans=True,
    )

    assert report.orphan_files == []
    assert report.errors == []
    assert real.is_file()
    assert sidecar.is_file()


def test_integrity_reports_orphan_without_deleting_it_even_when_legacy_flag_is_true(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    orphan = _make_music_file(ipod_root, "F00", "ORPHAN.mp3")

    report = check_integrity(
        ipod_root,
        [],
        MappingFile(),
        delete_orphans=True,
    )

    assert report.orphan_files == [orphan]
    assert orphan.read_bytes() == b"audio"


def test_integrity_reports_stale_mapping_without_mutating_mapping(
    tmp_path: Path,
) -> None:
    mapping = MappingFile()
    mapping.add_track(
        "fingerprint",
        db_track_id=9,
        source_format="flac",
        ipod_format="m4a",
        source_size=1,
        source_mtime=1.0,
        was_transcoded=True,
    )

    report = check_integrity(tmp_path / "ipod", [], mapping)

    assert report.stale_mappings == [("fingerprint", 9)]
    assert mapping.get_by_db_track_id(9) is not None
