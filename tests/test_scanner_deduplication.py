from iopenpod.device import scanner
from iopenpod.device.info import DeviceInfo


def _device(path: str, *, guid: str = "", serial: str = "") -> DeviceInfo:
    return DeviceInfo(
        path=path,
        mount_name=path.rsplit("/", 1)[-1],
        firewire_guid=guid,
        serial=serial,
    )


def test_scan_for_ipods_collapses_duplicate_mount_aliases(monkeypatch) -> None:
    devices = {
        "/media/tester/IPOD": _device(
            "/media/tester/IPOD",
            guid="0123456789abcdef",
            serial="SERIAL00001",
        ),
        "/run/media/tester/IPOD": _device(
            "/run/media/tester/IPOD",
            guid="0123456789ABCDEF",
            serial="SERIAL00001",
        ),
    }

    monkeypatch.setattr(
        scanner,
        "_find_ipod_volumes",
        lambda: [
            ("/media/tester/IPOD", "IPOD"),
            ("/run/media/tester/IPOD", "IPOD"),
        ],
    )
    monkeypatch.setattr(
        scanner,
        "_identify_ipod_mount",
        lambda mount_path, _display_name: devices[mount_path],
    )
    monkeypatch.setattr(scanner, "_clear_macos_usb_cache", lambda: None)

    assert scanner.scan_for_ipods() == [devices["/media/tester/IPOD"]]


def test_scan_for_ipods_keeps_distinct_devices(monkeypatch) -> None:
    first = _device("/run/media/tester/IPOD1", guid="0123456789ABCDEF")
    second = _device("/run/media/tester/IPOD2", guid="FEDCBA9876543210")

    monkeypatch.setattr(
        scanner,
        "_find_ipod_volumes",
        lambda: [
            (first.path, "IPOD1"),
            (second.path, "IPOD2"),
        ],
    )
    monkeypatch.setattr(
        scanner,
        "_identify_ipod_mount",
        lambda mount_path, _display_name: first if mount_path == first.path else second,
    )
    monkeypatch.setattr(scanner, "_clear_macos_usb_cache", lambda: None)

    assert scanner.scan_for_ipods() == [first, second]
