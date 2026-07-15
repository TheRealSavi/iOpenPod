from __future__ import annotations

import pytest

from iopenpod.itunesdb_writer import mhbd_writer
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo


def test_write_itunesdb_surfaces_artwork_write_errors(monkeypatch, tmp_path) -> None:
    ipod_root = tmp_path / "ipod"
    (ipod_root / "iPod_Control" / "iTunes").mkdir(parents=True)

    def fake_write_artworkdb(*_args, **_kwargs):
        raise RuntimeError("palette artwork could not be converted")

    monkeypatch.setattr(
        "iopenpod.artworkdb_writer.artwork_writer.write_artworkdb",
        fake_write_artworkdb,
    )
    monkeypatch.setattr(
        "iopenpod.device.itdb_write_filename",
        lambda _ipod_path: "iTunesDB",
    )
    monkeypatch.setattr(
        "iopenpod.device.resolve_itdb_path",
        lambda _ipod_path: None,
    )

    tracks = [TrackInfo(title="One", location=":iPod_Control:Music:F00:one.mp3")]

    with pytest.raises(RuntimeError, match="palette artwork could not be converted"):
        mhbd_writer.write_itunesdb(
            str(ipod_root),
            tracks,
            pc_file_paths={1: "/music/one.mp3"},
        )
