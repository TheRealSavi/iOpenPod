from pathlib import Path

import pytest

from iopenpod.sync.mapping import MappingFile, MappingLoadError, MappingManager


def _mapping_path(ipod_root: Path) -> Path:
    return ipod_root / "iPod_Control" / "iTunes" / "iOpenPod.json"


def test_load_corrupt_mapping_does_not_rename_delete_or_write(tmp_path: Path) -> None:
    mapping_path = _mapping_path(tmp_path)
    mapping_path.parent.mkdir(parents=True)
    original = b"{not valid json"
    mapping_path.write_bytes(original)
    before_entries = tuple(sorted(path.name for path in mapping_path.parent.iterdir()))

    mapping = MappingManager(tmp_path).load()

    assert mapping.source_was_corrupt is True
    assert mapping.track_count == 0
    assert mapping_path.read_bytes() == original
    assert tuple(sorted(path.name for path in mapping_path.parent.iterdir())) == (
        before_entries
    )


def test_guarded_save_backs_up_corrupt_mapping_before_replacing_it(
    tmp_path: Path,
) -> None:
    mapping_path = _mapping_path(tmp_path)
    mapping_path.parent.mkdir(parents=True)
    original = b"{not valid json"
    mapping_path.write_bytes(original)
    predictable_temps = [
        mapping_path.with_suffix(".json.tmp"),
        mapping_path.with_suffix(".json.bak.tmp"),
    ]
    for predictable in predictable_temps:
        predictable.write_bytes(b"do-not-truncate")
    manager = MappingManager(tmp_path)
    mapping = manager.load()

    assert manager.save(mapping) is True

    assert mapping_path.with_suffix(".json.bak").read_bytes() == original
    assert MappingManager(tmp_path).load().source_was_corrupt is False
    assert mapping.source_was_corrupt is False
    assert all(path.read_bytes() == b"do-not-truncate" for path in predictable_temps)


def test_load_propagates_unreadable_mapping_instead_of_treating_it_as_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mapping_path = _mapping_path(tmp_path)
    mapping_path.parent.mkdir(parents=True)
    mapping_path.write_text("{}", encoding="utf-8")
    real_open = open

    def fail_mapping_open(path, *args, **kwargs):
        if Path(path) == mapping_path:
            raise OSError("device I/O error")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fail_mapping_open)

    with pytest.raises(MappingLoadError, match="device I/O error"):
        MappingManager(tmp_path).load()


def test_mapping_file_default_is_not_marked_corrupt() -> None:
    assert MappingFile().source_was_corrupt is False


def test_mapping_round_trips_rockbox_metadata_validation_markers() -> None:
    mapping = MappingFile()
    markers = {
        101: {
            "file_size": 4_096,
            "mtime_ns": 1_725_000_000_000_000_000,
            "metadata_signature": "abc123",
        },
    }
    artwork_state = {
        "exists": True,
        "file_size": 8_192,
        "mtime_ns": 1_725_000_000_100_000_000,
    }

    mapping.set_rockbox_metadata_validation(markers, artwork_state)
    loaded = MappingFile.from_dict(mapping.to_dict())

    assert loaded.rockbox_metadata_markers == markers
    assert loaded.rockbox_artwork_state == artwork_state
