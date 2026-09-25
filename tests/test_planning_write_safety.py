import json
from pathlib import Path
from types import SimpleNamespace

from iopenpod.sync.audio_fingerprint import FingerprintCache
from iopenpod.sync.fingerprint_diff_engine import FingerprintDiffEngine
from iopenpod.sync.mapping import MappingFile
from iopenpod.sync.pc_library import PCLibrary


def _device_snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
        for path in sorted(root.rglob("*"))
    }


def test_compute_diff_reports_cleanup_without_writing_renaming_or_deleting(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    pc_root = tmp_path / "pc"
    pc_root.mkdir()
    orphan = ipod_root / "iPod_Control" / "Music" / "F00" / "ORPHAN.mp3"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"orphan audio")

    mapping = MappingFile()
    mapping.add_track(
        "stale-fingerprint",
        db_track_id=42,
        source_format="flac",
        ipod_format="m4a",
        source_size=100,
        source_mtime=1.0,
        was_transcoded=True,
    )
    mapping_path = ipod_root / "iPod_Control" / "iTunes" / "iOpenPod.json"
    mapping_path.parent.mkdir(parents=True)
    mapping_path.write_text(json.dumps(mapping.to_dict()), encoding="utf-8")
    before = _device_snapshot(ipod_root)

    monkeypatch.setattr(
        "iopenpod.sync.fingerprint_diff_engine.is_fpcalc_available",
        lambda _path="": True,
    )
    monkeypatch.setattr(
        FingerprintCache,
        "get_instance",
        classmethod(lambda _cls: SimpleNamespace(save=lambda: None)),
    )

    plan = FingerprintDiffEngine(
        PCLibrary(pc_root),
        ipod_root,
        supports_photo=False,
    ).compute_diff([], write_fingerprints=False, existing_playlists=[])

    assert _device_snapshot(ipod_root) == before
    assert orphan.is_file()
    assert mapping_path.is_file()
    assert not mapping_path.with_suffix(".json.bak").exists()
    assert plan.integrity_report is not None
    assert plan.integrity_report.orphan_files == [orphan]
    assert plan.integrity_report.stale_mappings == [("stale-fingerprint", 42)]
    assert plan._mapping_requires_persistence is True
    assert plan.has_changes is True
