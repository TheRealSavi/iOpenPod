from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from iopenpod.sync.contracts import SyncPlan
from iopenpod.sync.fingerprint_diff_engine import FingerprintDiffEngine


def _engine(tmp_path, *, supports_photo: bool = True) -> FingerprintDiffEngine:
    engine = cast(FingerprintDiffEngine, FingerprintDiffEngine.__new__(FingerprintDiffEngine))
    engine.supports_photo = supports_photo
    engine.ipod_path = tmp_path / "iPod"
    cast(Any, engine).pc_library = SimpleNamespace(root_entries=["root"], root_path=tmp_path)
    engine.photo_sync_settings = {"fit_photo_thumbnails": True}
    return engine


def test_plan_photos_scans_and_adds_storage_deltas(monkeypatch, tmp_path) -> None:
    import iopenpod.sync.fingerprint_diff_engine as diff_module

    progress_events: list[tuple[str, int, int, str]] = []
    plan = SyncPlan()
    fake_photo_plan = SimpleNamespace(
        thumb_bytes_to_add=111,
        thumb_bytes_to_remove=22,
    )

    monkeypatch.setattr(diff_module, "read_photo_db", lambda _ipod_path: "device")

    def fake_scan_pc_photos(root_entries, *, progress_callback, max_workers, is_cancelled):
        assert root_entries == ["root"]
        assert max_workers >= 1
        progress_callback(1, 1, "photo.jpg")
        return "pc"

    monkeypatch.setattr(diff_module, "scan_pc_photos", fake_scan_pc_photos)

    def fake_build_photo_sync_plan(pc_photos, device_photos, photo_edits, **kwargs):
        assert pc_photos == "pc"
        assert device_photos == "device"
        assert kwargs["sync_settings"] == {"fit_photo_thumbnails": True}
        return fake_photo_plan

    monkeypatch.setattr(diff_module, "build_photo_sync_plan", fake_build_photo_sync_plan)

    cancelled = _engine(tmp_path)._plan_photos(
        plan,
        allowed_paths=None,
        photo_edits=None,
        sync_workers=2,
        progress_callback=lambda *event: progress_events.append(event),
        is_cancelled=lambda: False,
    )

    assert cancelled is False
    assert plan.photo_plan is fake_photo_plan
    assert plan.storage.bytes_to_add == 111
    assert plan.storage.bytes_to_remove == 22
    assert progress_events == [
        ("scan_photos", 0, 0, "Scanning photos..."),
        ("scan_photos", 1, 1, "photo.jpg"),
    ]


def test_plan_photos_reports_cancelled_scan(monkeypatch, tmp_path) -> None:
    import iopenpod.sync.fingerprint_diff_engine as diff_module

    plan = SyncPlan()
    monkeypatch.setattr(diff_module, "read_photo_db", lambda _ipod_path: "device")
    monkeypatch.setattr(
        diff_module,
        "scan_pc_photos",
        lambda *args, **kwargs: "pc",
    )

    cancelled = _engine(tmp_path)._plan_photos(
        plan,
        allowed_paths=None,
        photo_edits=None,
        sync_workers=2,
        progress_callback=None,
        is_cancelled=lambda: True,
    )

    assert cancelled is True
    assert plan.photo_plan is None
