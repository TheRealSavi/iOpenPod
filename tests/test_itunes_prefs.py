from __future__ import annotations

import struct
from pathlib import Path

import pytest

from iopenpod.itunesdb_writer.mhbd_writer import write_mhbd
from iopenpod.sync.itunes_prefs import protect_from_itunes


def _itunes_dir(ipod_root: Path) -> Path:
    itunes_dir = ipod_root / "iPod_Control" / "iTunes"
    itunes_dir.mkdir(parents=True)
    (ipod_root / "iPodInfo.json").write_text("{}", encoding="utf-8")
    return itunes_dir


def test_protect_from_itunes_preserves_existing_library_link_id(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    itunes_dir = _itunes_dir(ipod_root)
    original_id = bytes.fromhex("1122334455667788")

    prefs = bytearray(1232)
    prefs[:4] = b"frpd"
    prefs[12:20] = original_id
    (itunes_dir / "iTunesPrefs").write_bytes(prefs)

    updated = protect_from_itunes(ipod_root, track_count=1, total_music_bytes=10, total_music_seconds=1)

    assert updated.library_link_id == original_id
    assert (itunes_dir / "iTunesPrefs").read_bytes()[12:20] == original_id


def test_protect_from_itunes_falls_back_to_existing_db_library_id(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    itunes_dir = _itunes_dir(ipod_root)
    original_id = bytes.fromhex("8877665544332211")

    db_bytes = bytearray(write_mhbd([], db_id=0x1234))
    db_bytes[0x48:0x50] = original_id
    db_path = itunes_dir / "iTunesDB"
    db_path.write_bytes(db_bytes)

    monkeypatch.setattr("iopenpod.device.resolve_itdb_path", lambda _ipod_path: str(db_path))

    updated = protect_from_itunes(ipod_root, track_count=1, total_music_bytes=10, total_music_seconds=1)

    assert updated.library_link_id == original_id
    assert (itunes_dir / "iTunesPrefs").read_bytes()[12:20] == original_id


def test_write_mhbd_preserves_reference_library_persistent_id() -> None:
    original_id = 0x8877665544332211

    data = write_mhbd(
        [],
        db_id=0x1234,
        reference_info={"db_persistent_id": original_id},
    )

    assert struct.unpack("<Q", data[0x48:0x50])[0] == original_id


def test_protect_from_itunes_ignores_predictable_temp_symlink(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    itunes_dir = _itunes_dir(ipod_root)
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside-safe")
    predictable = itunes_dir / "iTunesPrefs.tmp"
    try:
        predictable.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    protect_from_itunes(
        ipod_root,
        track_count=1,
        total_music_bytes=10,
        total_music_seconds=1,
    )

    assert outside.read_bytes() == b"outside-safe"
    assert predictable.is_symlink()
    assert (itunes_dir / "iTunesPrefs").read_bytes()[:4] == b"frpd"
    assert (itunes_dir / "iTunesPrefs.plist").is_file()


def test_protect_from_itunes_does_not_truncate_stale_predictable_temp(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    itunes_dir = _itunes_dir(ipod_root)
    predictable = itunes_dir / "iTunesPrefs.tmp"
    predictable.write_bytes(b"stale-file-owned-by-someone-else")

    protect_from_itunes(ipod_root)

    assert predictable.read_bytes() == b"stale-file-owned-by-someone-else"
