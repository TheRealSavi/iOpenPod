from types import SimpleNamespace

from iopenpod.application.jobs import scan_for_ipod_devices


def test_scan_for_ipod_devices_uses_injected_scanner() -> None:
    devices = [SimpleNamespace(path="E:/")]

    assert scan_for_ipod_devices(lambda: devices) == devices


def test_scan_for_ipod_devices_normalizes_empty_results() -> None:
    assert scan_for_ipod_devices(lambda: None) == []
