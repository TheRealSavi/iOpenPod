from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from iopenpod.application.runtime import DeviceManager
from iopenpod.device import bootstrap
from iopenpod.device.info import DeviceInfo, clear_current_device
from iopenpod.device.write_guard import DeviceWriteSafetyError


def _device(root: Path) -> DeviceInfo:
    return DeviceInfo(
        path=str(root),
        mount_name="NANO",
        model_number="MA005",
        model_family="iPod Nano",
        generation="1st Gen",
    )


def test_bootstrap_rejects_unrecognized_root_before_filesystem_inspection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    inspections: list[Path] = []
    monkeypatch.setattr(
        bootstrap,
        "inspect_device_write_readiness",
        lambda root, **_kwargs: inspections.append(root),
    )

    with pytest.raises(DeviceWriteSafetyError, match="verified iPod root"):
        bootstrap.ensure_device_itunes_database(tmp_path, _device(tmp_path))

    assert inspections == []
    assert list(tmp_path.iterdir()) == []


def test_bootstrap_refuses_unsafe_filesystem_before_creating_layout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control").mkdir()
    seed_calls: list[Path] = []

    def reject_readiness(*_args: object, **_kwargs: object) -> object:
        raise DeviceWriteSafetyError("the volume is mounted read-only")

    monkeypatch.setattr(bootstrap, "inspect_device_write_readiness", reject_readiness)
    monkeypatch.setattr(
        bootstrap,
        "_seed_ipod_layout",
        lambda root, **_kwargs: seed_calls.append(root),
    )

    with pytest.raises(DeviceWriteSafetyError, match="read-only"):
        bootstrap.ensure_device_itunes_database(tmp_path, _device(tmp_path))

    assert seed_calls == []
    assert not (tmp_path / "iPod_Control" / "iTunes").exists()


def test_bootstrap_revalidates_inside_guard_and_holds_it_through_flush(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control").mkdir()
    profile = SimpleNamespace(reported_volume_format="", case_sensitive=None)
    events: list[object] = []

    def inspect(*_args: object, **_kwargs: object) -> object:
        events.append("inspect")
        return profile

    class FakeGuard:
        def __init__(self, root: Path, *, volume_key: str) -> None:
            events.append(("guard_init", root, volume_key))

        def __enter__(self) -> FakeGuard:
            events.append("guard_enter")
            return self

        def __exit__(self, *_args: object) -> None:
            events.append("guard_exit")

        def assert_database_unchanged(self) -> None:
            events.append("database_unchanged")

        def refresh_database_generation(self) -> None:
            events.append("generation_refreshed")

    def revalidate(retained: object, **kwargs: object) -> object:
        events.append(("revalidate", retained, kwargs))
        return retained

    def seed(
        root: Path,
        *,
        uses_sqlite_db: bool,
        before_device_mutation,
    ) -> None:
        before_device_mutation()
        events.append(("seed", uses_sqlite_db))
        (root / "iPod_Control" / "iTunes").mkdir(parents=True)

    def write_itunesdb(root: str, *_args: object, **_kwargs: object) -> bool:
        events.append("write")
        before_device_mutation = cast(
            Callable[[], None],
            _kwargs["before_device_mutation"],
        )
        before_database_replace = cast(
            Callable[[], None],
            _kwargs["before_database_replace"],
        )
        before_device_mutation()
        before_database_replace()
        (Path(root) / "iPod_Control" / "iTunes" / "iTunesDB").write_bytes(b"mhbd")
        return True

    monkeypatch.setattr(bootstrap, "inspect_device_write_readiness", inspect)
    monkeypatch.setattr(bootstrap, "volume_lock_key", lambda _profile: "volume-key")
    monkeypatch.setattr(bootstrap, "DeviceWriteGuard", FakeGuard)
    monkeypatch.setattr(bootstrap, "revalidate_device_write_readiness", revalidate)
    monkeypatch.setattr(bootstrap, "_has_checksum_material", lambda *_args: True)
    monkeypatch.setattr(bootstrap, "_seed_ipod_layout", seed)
    monkeypatch.setattr("iopenpod.itunesdb_writer.write_itunesdb", write_itunesdb)
    monkeypatch.setattr(
        bootstrap,
        "flush_filesystem",
        lambda _root: events.append("flush") or (True, "ok"),
    )

    result = bootstrap.ensure_device_itunes_database(tmp_path, _device(tmp_path))

    assert result == str(tmp_path / "iPod_Control" / "iTunes" / "iTunesDB")
    assert events == [
        "inspect",
        ("guard_init", tmp_path, "volume-key"),
        "guard_enter",
        ("revalidate", profile, {"probe_case_sensitivity": True}),
        ("revalidate", profile, {"probe_case_sensitivity": False}),
        ("seed", False),
        "write",
        ("revalidate", profile, {"probe_case_sensitivity": False}),
        "database_unchanged",
        "generation_refreshed",
        ("revalidate", profile, {"probe_case_sensitivity": False}),
        "flush",
        "guard_exit",
    ]


def test_device_manager_propagates_bootstrap_failure_without_activation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    clear_current_device()
    manager = DeviceManager()
    device = _device(tmp_path)
    manager.discovered_ipod = device
    changes: list[str] = []
    manager.device_changed.connect(changes.append)

    def reject_bootstrap(*_args: object, **_kwargs: object) -> None:
        raise DeviceWriteSafetyError("filesystem safety failed")

    monkeypatch.setattr(
        "iopenpod.device.ensure_device_itunes_database",
        reject_bootstrap,
    )

    with pytest.raises(DeviceWriteSafetyError, match="filesystem safety failed"):
        manager.device_path = str(tmp_path)

    assert manager.device_path is None
    assert changes == []
