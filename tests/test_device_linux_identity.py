from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from iopenpod.device import linux_identity, scanner, vpd_linux


def test_parse_cached_vpd_page_80_returns_product_serial() -> None:
    payload = b"8P840FN62C7"
    page = bytes((0x00, 0x80)) + len(payload).to_bytes(2, "big") + payload

    assert linux_identity.parse_vpd_page_80(page) == "8P840FN62C7"


def test_findmnt_bind_mount_source_is_reduced_to_device(monkeypatch) -> None:
    completed = SimpleNamespace(
        returncode=0,
        stdout="/dev/sde1[iPod_Control/Music]\n",
    )
    monkeypatch.setattr(
        linux_identity.subprocess,
        "run",
        lambda *_args, **_kwargs: completed,
    )

    assert linux_identity.find_block_device("/mnt/ipod-music") == "/dev/sde1"


def test_non_ipod_sysfs_device_cannot_inject_cached_vpd_serial(
    monkeypatch,
) -> None:
    cached_calls: list[str] = []
    monkeypatch.setattr(
        linux_identity,
        "_is_ipod_scsi_device",
        lambda _disk: False,
    )
    monkeypatch.setattr(linux_identity.os.path, "exists", lambda _path: False)
    monkeypatch.setattr(
        linux_identity,
        "_cached_product_serial",
        lambda disk: cached_calls.append(disk) or "NOT-AN-IPOD",
    )

    assert linux_identity._identity_from_sysfs("sda") == {}
    assert cached_calls == []


def test_usb_identity_rejects_iphone_but_accepts_known_or_named_ipod() -> None:
    assert linux_identity._is_ipod_usb_identity(0x1261, "")
    assert linux_identity._is_ipod_usb_identity(None, "iPod")
    assert not linux_identity._is_ipod_usb_identity(0x12A8, "iPhone")


def test_probe_merges_partition_transport_with_whole_disk_product_serial(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        linux_identity,
        "find_block_device",
        lambda _mount: "/dev/sde1",
    )

    def fake_udev_identity(device: str) -> dict:
        if device == "/dev/sde1":
            return {
                "firewire_guid": "000A2700138A422D",
                "usb_pid": 0x1261,
                "_sources": {
                    "firewire_guid": "udev",
                    "usb_pid": "udev",
                },
            }
        assert device == "/dev/sde"
        return {
            "serial": "8P840FN62C7",
            "_sources": {"serial": "udev_scsi_id"},
        }

    monkeypatch.setattr(linux_identity, "_identity_from_udev", fake_udev_identity)
    monkeypatch.setattr(
        linux_identity,
        "_identity_from_sysfs",
        lambda _disk: {},
    )
    monkeypatch.setattr(
        linux_identity,
        "_identity_from_usb_bus",
        lambda _disk: {},
    )

    result = linux_identity.probe_linux_identity("/media/johng/IPOD")

    assert result["serial"] == "8P840FN62C7"
    assert result["firewire_guid"] == "000A2700138A422D"
    assert result["usb_pid"] == 0x1261
    assert result["_sources"] == {
        "serial": "udev_scsi_id",
        "firewire_guid": "udev",
        "usb_pid": "udev",
    }


def test_udev_product_serial_is_distinct_from_usb_transport_serial(
    monkeypatch,
) -> None:
    completed = SimpleNamespace(
        returncode=0,
        stdout=(
            "ID_VENDOR_ID=05ac\n"
            "ID_MODEL_ID=1261\n"
            "ID_SERIAL_SHORT=000A2700138A422D\n"
            "ID_IOPENPOD_PRODUCT_SERIAL=8P840FN62C7\n"
        ),
    )
    monkeypatch.setattr(
        linux_identity.subprocess,
        "run",
        lambda *_args, **_kwargs: completed,
    )

    result = linux_identity._identity_from_udev("/dev/sde")

    assert result["serial"] == "8P840FN62C7"
    assert result["firewire_guid"] == "000A2700138A422D"
    assert result["_sources"]["serial"] == "udev_scsi_id"
    assert result["_sources"]["firewire_guid"] == "udev"


def test_namespaced_udev_serial_does_not_require_propagated_usb_fields(
    monkeypatch,
) -> None:
    completed = SimpleNamespace(
        returncode=0,
        stdout="ID_IOPENPOD_PRODUCT_SERIAL=8P840FN62C7\n",
    )
    monkeypatch.setattr(
        linux_identity.subprocess,
        "run",
        lambda *_args, **_kwargs: completed,
    )

    result = linux_identity._identity_from_udev("/dev/sde")

    assert result == {
        "serial": "8P840FN62C7",
        "_sources": {"serial": "udev_scsi_id"},
    }


def test_linux_udev_rule_does_not_grant_raw_device_access() -> None:
    rule_path = (
        Path(__file__).parents[1] / "packaging" / "linux" / "61-iopenpod.rules"
    )
    rule = rule_path.read_text(encoding="utf-8")

    assert "ID_IOPENPOD_PRODUCT_SERIAL" in rule
    assert "--page=0x80" in rule
    assert 'ATTRS{vendor}=="Apple*"' in rule
    assert 'ATTRS{model}=="iPod*"' in rule
    assert 'SUBSYSTEMS=="usb"' not in rule
    assert "MODE=" not in rule
    assert "GROUP=" not in rule
    assert 'TAG+="uaccess"' not in rule


def test_raw_vpd_fallback_tries_whole_disk_before_partition(monkeypatch) -> None:
    monkeypatch.setattr(
        vpd_linux,
        "find_block_device",
        lambda _mount: "/dev/sde1",
    )

    assert vpd_linux._block_candidates("/media/johng/IPOD") == [
        "/dev/sde",
        "/dev/sde1",
    ]


def test_scanner_preserves_precise_linux_evidence_sources(monkeypatch) -> None:
    monkeypatch.setattr(scanner.sys, "platform", "linux")
    monkeypatch.setattr(
        scanner,
        "probe_linux_identity",
        lambda _mount: {
            "serial": "8P840FN62C7",
            "firewire_guid": "000A2700138A422D",
            "_sources": {
                "serial": "udev_scsi_id",
                "firewire_guid": "sysfs",
            },
        },
    )

    result = scanner._probe_hardware("/media/johng/IPOD", "IPOD")

    assert result["_sources"]["serial"] == "udev_scsi_id"
    assert result["_sources"]["firewire_guid"] == "sysfs"


def test_live_linux_product_serial_wins_over_stale_sysinfo() -> None:
    resolved = scanner._resolve_model(
        {
            "serial": "8P840FN62C7",
            "_sources": {"serial": "udev_scsi_id"},
        },
        {
            "serial": "C8T00000F0GD",
            "_sources": {"serial": "sysinfo"},
        },
        disk_size_gb=111.8,
    )

    assert resolved["serial"] == "8P840FN62C7"
    assert resolved["model_number"] == "MB565"
    assert resolved["_sources"]["serial"] == "udev_scsi_id"
    assert any(
        conflict["field"] == "serial"
        and conflict["rejected_value"] == "C8T00000F0GD"
        for conflict in resolved["_conflicts"]
    )
