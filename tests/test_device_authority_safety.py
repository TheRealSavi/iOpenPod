from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from iopenpod.device import authority
from iopenpod.device.info import DeviceInfo


class _RecordingSession:
    def __init__(self) -> None:
        self.writes: list[tuple[Path, bytes, Path]] = []

    def write_text_atomic(
        self,
        relative_path,
        text,
        *,
        allowed_subtree,
        encoding="utf-8",
    ):
        path = Path(relative_path)
        self.writes.append((path, text.encode(encoding), Path(allowed_subtree)))
        return path

    def write_bytes_atomic(self, relative_path, data, *, allowed_subtree):
        path = Path(relative_path)
        self.writes.append((path, bytes(data), Path(allowed_subtree)))
        return path


def test_update_sysinfo_uses_scan_identity_and_guarded_metadata_session(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control" / "Device").mkdir(parents=True)
    session = _RecordingSession()
    captured: dict[str, str] = {}

    @contextmanager
    def fake_guard(path, **kwargs):
        captured["path"] = str(path)
        captured.update(kwargs)
        yield session

    monkeypatch.setattr(authority, "guarded_device_metadata_session", fake_guard)
    info = DeviceInfo(
        path=str(tmp_path),
        model_number="MA005",
        reported_volume_format="FAT32",
        volume_identity_key="scan-volume",
    )
    info._field_sources["model_number"] = "device_tree"

    authority.update_sysinfo(info)

    assert captured["expected_volume_identity_key"] == "scan-volume"
    assert captured["reported_volume_format"] == "FAT32"
    written_names = {path.name for path, _data, _subtree in session.writes}
    assert written_names == {"SysInfo", authority.AUTHORITY_FILENAME}
    assert all(
        subtree == Path("iPod_Control") / "Device"
        for _path, _data, subtree in session.writes
    )


def test_live_sysinfo_cache_uses_atomic_guarded_writes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "iPod_Control" / "Device").mkdir(parents=True)
    session = _RecordingSession()

    @contextmanager
    def fake_guard(_path, **_kwargs):
        yield session

    monkeypatch.setattr(authority, "guarded_device_metadata_session", fake_guard)

    assert authority.cache_sysinfo_extended(
        str(tmp_path),
        b"<plist><dict></dict></plist>",
        expected_volume_identity_key="scan-volume",
    )

    written_names = [path.name for path, _data, _subtree in session.writes]
    assert written_names == ["SysInfoExtended", authority.AUTHORITY_FILENAME]
