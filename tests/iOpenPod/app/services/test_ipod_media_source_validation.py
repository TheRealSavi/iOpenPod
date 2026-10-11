"""A scan must not return results after its selected Library disappears."""

from collections.abc import Callable
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_device_coordinator import (
    _ipod_volume,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.library_sync_helper import (
    IPodMediaScanner,
    IPodMediaScanProgress,
    IPodMediaScanStage,
)
from iOpenPod.app.services.device_coordinator import (
    DeviceChangedError,
    DeviceCoordinator,
)
from iPodDB.iTunesDB.cdb import compress_iTunesCDB
from storage import DevicePathNotFoundError, HostPath, Storage
from storage.testing import VirtualStoragePlatform


class _Fingerprinter:
    def __init__(self) -> None:
        self.calls = 0

    def fingerprint(self, source: HostPath, *, checkpoint: Callable[[], None]) -> str:
        checkpoint()
        assert Path(source.path).read_bytes() == b"audio payload"
        self.calls += 1
        return "1,2,3"


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("database_name", ["iTunesDB", "iTunesCDB"])
@pytest.mark.parametrize("remove_during_scan", [False, True])
def test_missing_selected_database_reports_library_change_without_writing(
    tmp_path: Path, database_name: str, remove_during_scan: bool
) -> None:
    root = _ipod_volume(
        tmp_path / "ipod",
        model_number="MC027" if database_name == "iTunesCDB" else "MB565",
        database_name=database_name,
    )
    database = root / "iPod_Control" / "iTunes" / database_name
    if database_name == "iTunesCDB":
        database.write_bytes(compress_iTunesCDB(database.read_bytes()))
    platform = VirtualStoragePlatform()
    platform.add_volume(root, label="Test iPod")
    fingerprinter = _Fingerprinter()
    coordinator = DeviceCoordinator(
        Storage(platform),
        ipod_media_scanner=IPodMediaScanner(
            fingerprinter, temporary_directory=tmp_path
        ),
    )
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        original = _files(root)
        stages: list[IPodMediaScanStage] = []
        if not remove_during_scan:
            database.unlink()

        def progress(update: IPodMediaScanProgress) -> None:
            stages.append(update.stage)
            if remove_during_scan and update.stage is IPodMediaScanStage.TRACKS:
                database.unlink()

        with pytest.raises(
            DeviceChangedError, match="Library is no longer present"
        ) as caught:
            coordinator.scan_ipod_media(active, progress, Event())

        assert "Device Picker" in str(caught.value)
        assert isinstance(caught.value.__cause__, DevicePathNotFoundError)
        assert fingerprinter.calls == int(remove_during_scan)
        assert (IPodMediaScanStage.TRACKS in stages) is remove_during_scan
        original.pop(database.relative_to(root).as_posix())
        assert _files(root) == original
    finally:
        coordinator.close()
