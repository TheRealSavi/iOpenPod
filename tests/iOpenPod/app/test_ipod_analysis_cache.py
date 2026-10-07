import hashlib
import json
from pathlib import Path

import pytest

from iOpenPod.app import ipod_analysis_cache as cache_module
from iOpenPod.app.ipod_analysis_cache import IPodAnalysisCache, IPodAnalysisRecord
from storage import AtomicHostFile, DevicePath, StorageOperationError


def _record(identity: int, fingerprint: str = "1,2,3") -> IPodAnalysisRecord:
    return IPodAnalysisRecord(
        "database",
        identity,
        DevicePath(f"iPod_Control/Music/{identity}.mp3"),
        99,
        123,
        fingerprint,
    )


def test_analysis_cache_bounds_decoded_memory_by_evicting_old_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache_module, "_MAX_DECODED_ACOUSTIC_BYTES", 10)
    file = AtomicHostFile(tmp_path / "cache.json")
    cache = IPodAnalysisCache(file, "a" * 64)
    for number in range(1, 4):
        cache.remember(_record(number))
    cache.save(force=True)
    loaded = IPodAnalysisCache(file, "a" * 64)
    loaded.load()
    assert loaded.get("database", 1, _record(1).path) is None
    assert loaded.get("database", 2, _record(2).path) == _record(2)
    assert loaded.get("database", 3, _record(3).path) == _record(3)


def test_analysis_cache_bounds_encoded_size_without_losing_newest_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache_module, "_MAX_BYTES", 1024)
    file = AtomicHostFile(tmp_path / "cache.json")
    cache = IPodAnalysisCache(file, "b" * 64)
    for number in range(1, 20):
        cache.remember(_record(number))
    cache.save(force=True)
    assert file.path.stat().st_size <= 1024
    loaded = IPodAnalysisCache(file, "b" * 64)
    loaded.load()
    assert loaded.get("database", 1, _record(1).path) is None
    assert loaded.get("database", 19, _record(19).path) == _record(19)


def test_analysis_cache_checkpoints_and_does_not_rewrite_unchanged_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr(
        "iOpenPod.app.ipod_analysis_cache.time.monotonic", lambda: clock[0]
    )
    file = AtomicHostFile(tmp_path / "cache.json")
    cache = IPodAnalysisCache(file, "c" * 64)
    cache.remember(_record(1))
    cache.save()
    assert not file.exists()
    clock[0] = 31.0
    cache.save()
    before = file.revision()
    assert before is not None
    cache.remember(_record(1))
    clock[0] = 62.0
    cache.save()
    assert file.revision() == before
    reloaded = IPodAnalysisCache(file, "c" * 64)
    reloaded.load()
    assert reloaded.get("database", 1, _record(1).path) == _record(1)


@pytest.mark.parametrize(
    "mutation",
    ["identity", "checksum", "duplicate", "empty", "decoded_budget", "oversized"],
)
def test_analysis_cache_rejects_invalid_or_unbounded_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    file = AtomicHostFile(tmp_path / "cache.json")
    cache = IPodAnalysisCache(file, "d" * 64)
    cache.remember(_record(1))
    cache.save(force=True)
    payload = file.read_bytes()
    assert payload is not None
    document = json.loads(payload)
    if mutation == "identity":
        document["identity"] = "e" * 64
    elif mutation == "checksum":
        document["sha256"] = "e" * 64
    elif mutation == "duplicate":
        document["records"] *= 2
    elif mutation == "empty":
        document["records"][0][-1] = ""
    elif mutation == "decoded_budget":
        monkeypatch.setattr(cache_module, "_MAX_DECODED_ACOUSTIC_BYTES", 4)
    else:
        monkeypatch.setattr(cache_module, "_MAX_BYTES", 5)
    if mutation in {"duplicate", "empty"}:
        document["sha256"] = hashlib.sha256(
            json.dumps(
                document["records"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
    file.replace_bytes(json.dumps(document).encode())
    with pytest.raises((ValueError, StorageOperationError)):
        IPodAnalysisCache(file, "d" * 64).load()


def test_analysis_cache_stores_long_fingerprint_losslessly_in_compact_form(
    tmp_path: Path,
) -> None:
    file = AtomicHostFile(tmp_path / "cache.json")
    raw = ",".join(str(4_000_000_000 + number) for number in range(1000))
    cache = IPodAnalysisCache(file, "a" * 64)
    cache.remember(_record(1, raw))
    cache.save(force=True)
    payload = file.read_bytes()
    assert payload is not None
    assert len(payload) < len(raw) // 2
    loaded = IPodAnalysisCache(file, "a" * 64)
    loaded.load()
    assert loaded.get("database", 1, _record(1).path) == _record(1, raw)


def test_analysis_cache_rejects_excessive_json_nesting_as_invalid_data(
    tmp_path: Path,
) -> None:
    file = AtomicHostFile(tmp_path / "cache.json")
    file.replace_bytes(b"[" * 10_000 + b"0" + b"]" * 10_000)
    with pytest.raises(ValueError, match="nested too deeply"):
        IPodAnalysisCache(file, "a" * 64).load()
