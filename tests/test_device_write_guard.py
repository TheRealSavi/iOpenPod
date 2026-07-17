from __future__ import annotations

from pathlib import Path

import pytest

from iopenpod.device import write_guard
from iopenpod.device.write_guard import (
    DeviceBusyError,
    DeviceWriteGuard,
    DeviceWriteSafetyError,
    ExternalDatabaseChangeError,
    capture_database_generation,
)


def test_guard_refuses_symlink_lock_file_without_touching_target(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    ipod_root.mkdir()
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    guard = DeviceWriteGuard(
        ipod_root,
        volume_key="volume-123",
        track_database_generation=False,
        lock_dir=lock_dir,
    )
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"must-not-change")
    try:
        guard.lock_path.symlink_to(victim)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(DeviceWriteSafetyError, match="lock"):
        with guard:
            pass

    assert victim.read_bytes() == b"must-not-change"


def test_guard_can_lock_volume_without_reading_database(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    ipod_root.mkdir()
    monkeypatch.setattr(
        write_guard,
        "capture_database_generation",
        lambda _path: pytest.fail("database generation should not be read"),
    )

    with DeviceWriteGuard(
        ipod_root,
        volume_key="volume-123",
        track_database_generation=False,
        lock_dir=tmp_path / "locks",
    ):
        pass


def _database(ipod_root: Path, contents: bytes = b"mhbd-original") -> Path:
    path = ipod_root / "iPod_Control" / "iTunes" / "iTunesDB"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    return path


def test_only_one_writer_can_hold_a_device_guard(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    ipod_root.mkdir()
    lock_dir = tmp_path / "locks"

    with DeviceWriteGuard(ipod_root, volume_key="volume-123", lock_dir=lock_dir):
        with pytest.raises(DeviceBusyError, match="already writing"):
            with DeviceWriteGuard(
                ipod_root,
                volume_key="volume-123",
                lock_dir=lock_dir,
            ):
                pass

    # The guard must be available again after the first writer exits.
    with DeviceWriteGuard(ipod_root, volume_key="volume-123", lock_dir=lock_dir):
        pass


def test_mount_aliases_share_one_underlying_volume_lock(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    lock_dir = tmp_path / "locks"

    with DeviceWriteGuard(
        first_root,
        volume_key="linux|8:33|/dev/sdb1|77",
        track_database_generation=False,
        lock_dir=lock_dir,
    ):
        with pytest.raises(DeviceBusyError, match="already writing"):
            with DeviceWriteGuard(
                second_root,
                volume_key="linux|8:33|/dev/sdb1|91",
                track_database_generation=False,
                lock_dir=lock_dir,
            ):
                pass


def test_guard_detects_external_database_content_change(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    database = _database(ipod_root)

    with DeviceWriteGuard(ipod_root, lock_dir=tmp_path / "locks") as guard:
        database.write_bytes(b"mhbd-external-change")

        with pytest.raises(
            ExternalDatabaseChangeError,
            match="changed after this write session started",
        ):
            guard.assert_database_unchanged()


def test_guard_detects_database_created_after_session_started(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    ipod_root.mkdir()

    with DeviceWriteGuard(ipod_root, lock_dir=tmp_path / "locks") as guard:
        _database(ipod_root)

        with pytest.raises(ExternalDatabaseChangeError):
            guard.assert_database_unchanged()


def test_guard_can_refresh_generation_after_its_own_commit(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    database = _database(ipod_root)

    with DeviceWriteGuard(ipod_root, lock_dir=tmp_path / "locks") as guard:
        database.write_bytes(b"mhbd-iopenpod-commit")
        guard.refresh_database_generation()

        guard.assert_database_unchanged()


def test_guard_rejects_cache_generation_that_was_already_replaced(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    database = _database(ipod_root)
    cached_generation = capture_database_generation(ipod_root)
    database.write_bytes(b"mhbd-written-by-another-app")

    with pytest.raises(
        ExternalDatabaseChangeError,
        match="changed since the iPod library was loaded",
    ):
        with DeviceWriteGuard(
            ipod_root,
            expected_database_generation=cached_generation,
            lock_dir=tmp_path / "locks",
        ):
            pass
