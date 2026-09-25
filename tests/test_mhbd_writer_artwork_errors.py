from __future__ import annotations

from types import SimpleNamespace

import pytest

from iopenpod.device import DeviceCapabilities
from iopenpod.device.storage_safety import FileSizeLimitError
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


def test_size_rejection_retains_the_unwritten_database_for_inspection(
    monkeypatch,
    tmp_path,
) -> None:
    ipod_root = tmp_path / "ipod"
    (ipod_root / "iPod_Control" / "iTunes").mkdir(parents=True)
    monkeypatch.setattr(
        mhbd_writer,
        "inspect_device_write_readiness",
        lambda _path: SimpleNamespace(
            max_file_size_bytes=None,
            allocation_unit_size=1,
        ),
    )

    with pytest.raises(FileSizeLimitError) as error:
        mhbd_writer.write_itunesdb(
            str(ipod_root),
            [
                TrackInfo(
                    title="One",
                    location=":iPod_Control:Music:F00:one.mp3",
                    lyrics="long lyric " * 100,
                )
            ],
            backup=False,
            capabilities=DeviceCapabilities(max_database_bytes=1),
        )

    assert error.value.proposed_database_bytes.startswith(b"mhbd")
    assert error.value.proposed_database_filename == "iTunesDB"
