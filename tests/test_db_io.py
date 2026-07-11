from __future__ import annotations

import pytest

from iopenpod.sync import _db_io


def test_write_database_raises_original_writer_error_when_requested(
    monkeypatch,
    tmp_path,
) -> None:
    from iopenpod import itunesdb_writer

    class WriterError(RuntimeError):
        pass

    def fake_write_itunesdb(*_args, **_kwargs):
        raise WriterError("Artwork image exceeds Pillow safety limit. Offending image: /music/Album/cover.tif")

    monkeypatch.setattr(itunesdb_writer, "write_itunesdb", fake_write_itunesdb)

    with pytest.raises(WriterError, match="Offending image: /music/Album/cover.tif"):
        _db_io.write_database(tmp_path, [], raise_on_error=True)
