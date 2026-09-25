from __future__ import annotations

from pathlib import Path

import pytest

from iopenpod.device import ChecksumType
from iopenpod.sqlitedb_writer import cbk_writer, sqlite_writer


def test_hash72_cbk_without_hashinfo_stops_before_creating_output(
    tmp_path: Path,
) -> None:
    locations = tmp_path / "Locations.itdb"
    locations.write_bytes(b"sqlite-data")
    output = tmp_path / "Locations.itdb.cbk"

    with pytest.raises(ValueError, match="HashInfo is required"):
        cbk_writer.write_locations_cbk(
            str(output),
            str(locations),
            ChecksumType.HASH72,
        )

    assert not output.exists()


def test_unknown_checksum_cbk_stops_before_creating_output(tmp_path: Path) -> None:
    locations = tmp_path / "Locations.itdb"
    locations.write_bytes(b"sqlite-data")
    output = tmp_path / "Locations.itdb.cbk"

    with pytest.raises(ValueError, match="UNKNOWN"):
        cbk_writer.write_locations_cbk(
            str(output),
            str(locations),
            ChecksumType.UNKNOWN,
        )

    assert not output.exists()


def test_install_database_file_flushes_sibling_before_atomic_replace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "generated" / "Library.itdb"
    source.parent.mkdir()
    source.write_bytes(b"new database")
    target = tmp_path / "device" / "Library.itdb"
    target.parent.mkdir()
    target.write_bytes(b"good database")

    original_flush = sqlite_writer.flush_written_file
    original_replace = sqlite_writer.durable_replace
    events: list[tuple[str, Path | None]] = []

    def checked_flush(file) -> None:
        events.append(("flush", None))
        original_flush(file)

    def checked_replace(temp_path: str, target_path: str) -> None:
        temp = Path(temp_path)
        events.append(("replace", temp))
        assert temp.parent == target.parent
        assert temp != target
        assert target.read_bytes() == b"good database"
        original_replace(temp_path, target_path)

    monkeypatch.setattr(sqlite_writer, "flush_written_file", checked_flush)
    monkeypatch.setattr(sqlite_writer, "durable_replace", checked_replace)

    sqlite_writer._install_database_file(
        str(source),
        str(target),
        before_device_mutation=lambda: None,
    )

    assert [name for name, _path in events] == ["flush", "replace"]
    assert target.read_bytes() == b"new database"
    assert events[1][1] is not None
    assert not events[1][1].exists()


def test_install_database_file_preserves_target_and_removes_temp_on_flush_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "generated.itdb"
    source.write_bytes(b"new database")
    target = tmp_path / "Library.itdb"
    target.write_bytes(b"good database")

    monkeypatch.setattr(
        sqlite_writer,
        "flush_written_file",
        lambda _file: (_ for _ in ()).throw(OSError("flush failed")),
    )

    with pytest.raises(OSError, match="flush failed"):
        sqlite_writer._install_database_file(
            str(source),
            str(target),
            before_device_mutation=lambda: None,
        )

    assert target.read_bytes() == b"good database"
    assert list(tmp_path.glob(".Library.itdb.*.tmp")) == []
