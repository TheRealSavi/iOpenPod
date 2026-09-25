from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from iopenpod.device import linux_identity, linux_integration, scanner, vpd_linux
from iopenpod.device.virtual import create_virtual_ipod


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


def test_probe_accepts_only_mount_anchored_ipod_by_id_serial(
    monkeypatch,
    tmp_path: Path,
) -> None:
    mount = tmp_path / "ipod"
    create_virtual_ipod(mount, "MB565")
    by_id = tmp_path / "dev" / "disk" / "by-id"
    by_id.mkdir(parents=True)
    correct = by_id / "ipod-8P840FN62C7"
    wrong = by_id / "ipod-WRONGDEVICE"
    correct.touch()
    wrong.touch()

    monkeypatch.setattr(
        linux_identity,
        "find_block_device",
        lambda _mount: "/dev/sdb1",
    )
    monkeypatch.setattr(linux_identity, "_BY_ID_DIRECTORY", by_id)
    monkeypatch.setattr(
        linux_identity,
        "_identity_from_sysfs",
        lambda _disk: {},
    )
    monkeypatch.setattr(
        linux_identity,
        "_identity_from_udev",
        lambda _device: {},
    )
    monkeypatch.setattr(
        linux_identity,
        "_identity_from_usb_bus",
        lambda _disk: {},
    )
    realpath = linux_identity.os.path.realpath

    def fake_realpath(path) -> str:
        candidate = str(path)
        if candidate == str(correct):
            return "/dev/sdb"
        if candidate == str(wrong):
            return "/dev/sdc"
        if candidate in {"/dev/sdb", "/dev/sdb1"}:
            return candidate
        return realpath(path)

    monkeypatch.setattr(linux_identity.os.path, "realpath", fake_realpath)

    result = linux_identity.probe_linux_identity(str(mount))

    assert result["serial"] == "8P840FN62C7"
    assert result["_sources"]["serial"] == "udev_scsi_id"


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


def test_namespaced_serial_is_read_directly_from_host_udev_database(
    monkeypatch,
    tmp_path: Path,
) -> None:
    udev_data = tmp_path / "udev-data"
    udev_data.mkdir()
    (udev_data / "b8:16").write_text(
        "I:123456\n"
        "E:ID_IOPENPOD_RULE_VERSION=1\n"
        "E:ID_IOPENPOD_PRODUCT_SERIAL=8P840FN62C7\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(linux_identity, "_UDEV_DATA_DIRECTORY", udev_data)
    monkeypatch.setattr(
        linux_identity,
        "_udev_database_key",
        lambda _device: "b8:16",
    )
    monkeypatch.setattr(
        linux_identity.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError),
    )

    result = linux_identity._identity_from_udev("/dev/sdb")

    assert result == {
        "serial": "8P840FN62C7",
        "_sources": {"serial": "udev_scsi_id"},
    }


def test_flatpak_exposes_only_read_only_host_udev_data() -> None:
    manifest = (
        Path(__file__).parents[1]
        / "flatpak"
        / "io.github.therealsavi.iOpenPod.yml"
    ).read_text(encoding="utf-8")

    assert "--filesystem=/run/udev:ro" in manifest
    assert "--filesystem=/run/udev:rw" not in manifest


def test_linux_udev_rule_does_not_grant_raw_device_access() -> None:
    rule = linux_integration.udev_rule_text()

    assert "ID_IOPENPOD_PRODUCT_SERIAL" in rule
    assert 'ENV{ID_IOPENPOD_RULE_VERSION}="1"' in rule
    assert "--page=0x80" in rule
    assert 'ATTRS{vendor}=="Apple*"' in rule
    assert 'ATTRS{model}=="iPod*"' in rule
    assert 'SUBSYSTEMS=="usb"' not in rule
    assert "MODE=" not in rule
    assert "GROUP=" not in rule
    assert 'TAG+="uaccess"' not in rule


def test_missing_linux_serial_produces_portable_setup_instructions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    create_virtual_ipod(tmp_path, "MB565")
    monkeypatch.setattr(
        linux_integration,
        "_HOST_RULE_PATHS",
        (tmp_path / "missing.rules",),
    )

    result = linux_integration.describe_linux_identity_integration(
        str(tmp_path),
        platform="linux",
    )

    assert result.state is linux_integration.LinuxIntegrationState.SETUP_REQUIRED
    assert "/etc/udev/rules.d/61-iopenpod.rules" in result.setup_instructions
    assert "udevadm trigger" in result.setup_instructions
    assert "--sysname-match=\"$SYSNAME\"" in result.setup_instructions
    assert (
        "run_as_root install -o root -g root -m 0644"
        in result.setup_instructions
    )
    assert "run_as_root mv -fT" in result.setup_instructions
    assert "command -v sudo" in result.setup_instructions
    assert "command -v doas" in result.setup_instructions
    assert "sudo tee" not in result.setup_instructions
    assert f"sudo chmod 0644 {linux_integration.RULE_DESTINATION}" not in (
        result.setup_instructions
    )
    assert 'TAG+="uaccess"' not in result.setup_instructions


def test_linux_rule_state_respects_higher_priority_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    override = tmp_path / "etc" / linux_integration.RULE_FILENAME
    vendor = tmp_path / "usr" / linux_integration.RULE_FILENAME
    override.parent.mkdir()
    vendor.parent.mkdir()
    override.write_text("# disabled by administrator\n", encoding="utf-8")
    vendor.write_text(linux_integration.udev_rule_text(), encoding="utf-8")
    monkeypatch.setattr(
        linux_integration,
        "_HOST_RULE_PATHS",
        (override, vendor),
    )

    result = linux_integration.describe_linux_identity_integration(
        "/media/ipod",
        platform="linux",
    )

    assert result.state is linux_integration.LinuxIntegrationState.RULE_OUTDATED


def test_linux_setup_prompt_is_limited_to_unresolved_verified_ipods(
    tmp_path: Path,
) -> None:
    device = create_virtual_ipod(tmp_path, "MB565")
    device.model_number = ""
    device.serial = ""

    assert linux_integration.linux_identity_setup_needed(
        device,
        platform="linux",
    )

    device.model_number = "MB565"
    assert linux_integration.linux_identity_setup_needed(
        device,
        platform="linux",
    )
    device.serial = "8P840FN62C7"
    assert not linux_integration.linux_identity_setup_needed(
        device,
        platform="linux",
    )
    device.serial = ""
    assert not linux_integration.linux_identity_setup_needed(
        device,
        platform="win32",
    )


def test_linux_setup_prompt_accepts_verified_mount_without_transport_ids(
    tmp_path: Path,
) -> None:
    device = SimpleNamespace(
        path=str(tmp_path),
        model_number="",
        serial="",
        usb_pid=0,
        firewire_guid="",
    )

    assert linux_integration.linux_identity_setup_needed(
        device,
        platform="linux",
    )


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


def test_live_linux_product_serial_resolves_exact_model_without_caches() -> None:
    resolved = scanner._resolve_model(
        {
            "serial": "8P840FN62C7",
            "firewire_guid": "000A2700138A422D",
            "usb_pid": 0x1261,
            "_sources": {
                "serial": "udev_scsi_id",
                "firewire_guid": "sysfs",
                "usb_pid": "sysfs",
            },
        },
        {},
        disk_size_gb=127.7,
    )

    assert resolved["serial"] == "8P840FN62C7"
    assert resolved["model_number"] == "MB565"
    assert resolved["model_family"] == "iPod Classic"
    assert resolved["generation"] == "6.5th Gen"
    assert resolved["capacity"] == "120GB"
    assert resolved["color"] == "Black"


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
