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


def test_write_itunesdb_resolves_max_file_size_bytes_when_not_provided(
    monkeypatch, tmp_path
) -> None:
    # write_itunesdb should self-resolve the real filesystem per-file limit
    # (for ithmb chunking -- see write_artworkdb's max_file_size_bytes /
    # ITHMB_MAX_SIZE_BYTES docstrings) via the same
    # inspect_device_write_readiness() call _preflight_database_install()
    # already makes later, rather than silently falling back to
    # write_artworkdb's own arbitrary default, whenever a caller doesn't
    # already have a live FilesystemProfile to pass in.
    ipod_root = tmp_path / "ipod"
    (ipod_root / "iPod_Control" / "iTunes").mkdir(parents=True)

    captured = {}

    def fake_write_artworkdb(*_args, **kwargs):
        captured["max_file_size_bytes"] = kwargs.get("max_file_size_bytes")
        raise RuntimeError("stop here -- only the artwork call matters for this test")

    monkeypatch.setattr(
        "iopenpod.artworkdb_writer.artwork_writer.write_artworkdb",
        fake_write_artworkdb,
    )
    monkeypatch.setattr(
        mhbd_writer,
        "inspect_device_write_readiness",
        lambda _path: SimpleNamespace(max_file_size_bytes=123456, allocation_unit_size=1),
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

    with pytest.raises(RuntimeError, match="stop here"):
        mhbd_writer.write_itunesdb(
            str(ipod_root),
            tracks,
            pc_file_paths={1: "/music/one.mp3"},
        )

    assert captured["max_file_size_bytes"] == 123456


def test_write_itunesdb_prefers_explicit_max_file_size_bytes_argument(
    monkeypatch, tmp_path
) -> None:
    ipod_root = tmp_path / "ipod"
    (ipod_root / "iPod_Control" / "iTunes").mkdir(parents=True)

    captured = {}

    def fake_write_artworkdb(*_args, **kwargs):
        captured["max_file_size_bytes"] = kwargs.get("max_file_size_bytes")
        raise RuntimeError("stop here -- only the artwork call matters for this test")

    monkeypatch.setattr(
        "iopenpod.artworkdb_writer.artwork_writer.write_artworkdb",
        fake_write_artworkdb,
    )

    def _fail_inspect(_path):
        raise AssertionError("must not re-resolve when the caller already provided a value")

    monkeypatch.setattr(mhbd_writer, "inspect_device_write_readiness", _fail_inspect)
    monkeypatch.setattr(
        "iopenpod.device.itdb_write_filename",
        lambda _ipod_path: "iTunesDB",
    )
    monkeypatch.setattr(
        "iopenpod.device.resolve_itdb_path",
        lambda _ipod_path: None,
    )

    tracks = [TrackInfo(title="One", location=":iPod_Control:Music:F00:one.mp3")]

    with pytest.raises(RuntimeError, match="stop here"):
        mhbd_writer.write_itunesdb(
            str(ipod_root),
            tracks,
            pc_file_paths={1: "/music/one.mp3"},
            max_file_size_bytes=999,
        )

    assert captured["max_file_size_bytes"] == 999


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
