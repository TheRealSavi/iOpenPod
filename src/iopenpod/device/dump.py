"""Read-only diagnostic dump for connected iPods.

Usage:
    uv run python -m iopenpod.device.dump D:\
    uv run python -m iopenpod.device.dump --all
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

IDENTITY_FIELDS: tuple[str, ...] = (
    "serial",
    "firewire_guid",
    "model_number",
    "model_family",
    "generation",
    "capacity",
    "color",
    "firmware",
    "board",
    "family_id",
    "updater_family_id",
    "product_type",
    "usb_vid",
    "usb_pid",
    "usb_serial",
    "scsi_vendor",
    "scsi_product",
    "scsi_revision",
    "connected_bus",
    "reported_volume_format",
    "filesystem_type",
    "db_version",
    "shadow_db_version",
    "uses_sqlite_db",
    "supports_sparse_artwork",
    "max_tracks",
    "max_file_size_gb",
    "max_transfer_speed",
    "podcasts_supported",
    "voice_memos_supported",
)


def _device_dir(mount_path: str) -> Path:
    return Path(mount_path) / "iPod_Control" / "Device"


def _mount_name(mount_path: str) -> str:
    if sys.platform == "win32":
        drive, _tail = os.path.splitdrive(mount_path)
        if drive:
            return drive
        if mount_path and mount_path[0].isalpha():
            return f"{mount_path[0].upper()}:"
    return os.path.basename(os.path.normpath(mount_path)) or mount_path


def _normalise_mount_path(mount_path: str) -> str:
    if sys.platform == "win32":
        stripped = mount_path.strip().strip('"')
        if len(stripped) == 2 and stripped[0].isalpha() and stripped[1] == ":":
            return stripped + "\\"
        return stripped
    return mount_path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_safe(value: Any, *, include_raw: bool = False) -> Any:
    if isinstance(value, bytes):
        result: dict[str, Any] = {
            "bytes": len(value),
            "sha256": _sha256(value),
        }
        if include_raw:
            result["text"] = value.decode("utf-8", errors="replace")
        return result
    if isinstance(value, dict):
        return {
            str(k): _json_safe(v, include_raw=include_raw)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(v, include_raw=include_raw) for v in value]
    return value


def _normalise_for_compare(field: str, value: Any) -> str:
    if value in (None, ""):
        return ""
    if field == "firewire_guid":
        try:
            from .sysinfo import normalize_guid

            return normalize_guid(value)
        except Exception:
            pass
    if field == "usb_pid":
        try:
            return f"0x{int(value):04X}"
        except Exception:
            return str(value).strip().upper()
    return str(value).strip()


def _sysinfo_dump(mount_path: str) -> dict[str, Any]:
    path = _device_dir(mount_path) / "SysInfo"
    if not path.exists():
        return {"present": False}

    raw = path.read_text(errors="replace")
    from .sysinfo import identity_from_sysinfo, parse_sysinfo_text

    parsed = parse_sysinfo_text(raw)
    return {
        "present": True,
        "path": str(path),
        "sha256": _sha256(raw.encode("utf-8", errors="replace")),
        "fields": parsed,
        "identity": identity_from_sysinfo(parsed, "sysinfo"),
    }


def _sysinfo_extended_dump(
    mount_path: str,
    *,
    include_raw: bool,
) -> dict[str, Any]:
    path = _device_dir(mount_path) / "SysInfoExtended"
    if not path.exists():
        return {"present": False}

    raw = path.read_bytes()
    from .sysinfo import parse_sysinfo_extended

    parsed = parse_sysinfo_extended(raw, source="sysinfo_extended")
    result: dict[str, Any] = {
        "present": True,
        "path": str(path),
        "bytes": len(raw),
        "sha256": _sha256(raw),
        "used_regex_fallback": parsed.used_regex_fallback,
        "keys": sorted(parsed.plist.keys()),
        "identity": parsed.identity,
        "cover_art_formats": parsed.cover_art_formats,
        "photo_formats": parsed.photo_formats,
        "chapter_image_formats": parsed.chapter_image_formats,
    }
    if include_raw:
        result["raw"] = raw
        result["plist"] = parsed.plist
    return result


def _identity_from_live_vpd(vpd: dict[str, Any], source: str) -> dict[str, Any]:
    from .sysinfo import (
        ParsedSysInfoExtended,
        identity_from_sysinfo_extended,
        parse_sysinfo_extended,
    )

    raw = vpd.get("vpd_raw_xml")
    if raw:
        identity = parse_sysinfo_extended(raw, source=source, live=True).identity
    else:
        parsed = ParsedSysInfoExtended(plist=vpd, source=source, live=True)
        identity = identity_from_sysinfo_extended(parsed, source, live=True)
    sources = identity.setdefault("_sources", {})
    for field in (
        "usb_pid",
        "usb_vid",
        "usb_serial",
        "scsi_vendor",
        "scsi_product",
        "scsi_revision",
        "block_device",
    ):
        value = vpd.get(field)
        if value not in (None, "", b""):
            identity[field] = value
            sources[field] = source
    return identity


def _live_scsi_dump(
    mount_path: str,
    final_identity: dict[str, Any],
) -> dict[str, Any]:
    try:
        if sys.platform == "win32":
            from .vpd_windows import query_ipod_vpd_for_path

            result = query_ipod_vpd_for_path(
                mount_path,
                usb_pid=int(final_identity.get("usb_pid") or 0),
                serial_filter=str(final_identity.get("firewire_guid") or ""),
            )
        elif sys.platform == "linux":
            from .vpd_linux import query_ipod_vpd_for_path

            result = query_ipod_vpd_for_path(
                mount_path,
                usb_pid=int(final_identity.get("usb_pid") or 0),
                serial_filter=str(final_identity.get("firewire_guid") or ""),
            )
        elif sys.platform == "darwin":
            from .vpd_iokit import query_ipod_vpd

            result = query_ipod_vpd(
                usb_pid=int(final_identity.get("usb_pid") or 0),
                serial_filter=str(final_identity.get("firewire_guid") or ""),
            )
        else:
            return {"available": False, "reason": f"unsupported_{sys.platform}"}
        if not result:
            return {"available": True, "result": None, "error": "no_result"}
        source = str(result.get("_source") or {
            "win32": "windows_scsi",
            "linux": "linux_scsi",
            "darwin": "scsi_vpd",
        }.get(sys.platform, "scsi_vpd"))
        return {
            "available": True,
            "result": result,
            "identity": _identity_from_live_vpd(result, source),
            "standard_inquiry": {
                "vendor": result.get("scsi_vendor", ""),
                "product": result.get("scsi_product", ""),
                "revision": result.get("scsi_revision", ""),
            },
        }
    except Exception as exc:
        return {"available": True, "result": None, "error": repr(exc)}


def _live_windows_scsi_dump(
    mount_path: str,
    final_identity: dict[str, Any],
) -> dict[str, Any]:
    if sys.platform != "win32":
        return {"available": False, "reason": "not_windows"}
    return _live_scsi_dump(mount_path, final_identity)


def _live_usb_vendor_dump(
    final_identity: dict[str, Any],
) -> dict[str, Any]:
    try:
        from .usb_backend import backend_diagnostic
        from .vpd_usb_control import query_ipod_usb_sysinfo_extended

        result = query_ipod_usb_sysinfo_extended(
            usb_pid=int(final_identity.get("usb_pid") or 0),
            serial_filter=str(final_identity.get("firewire_guid") or ""),
        )
        if not result:
            return {
                "available": True,
                "result": None,
                "error": "no_result",
                "backend": backend_diagnostic(),
            }
        source = str(result.get("_source") or "usb_vendor")
        return {
            "available": True,
            "result": result,
            "identity": _identity_from_live_vpd(result, source),
            "backend": backend_diagnostic(),
        }
    except Exception as exc:
        return {"available": False, "result": None, "error": repr(exc)}


def _disk_size_gb(mount_path: str) -> float:
    try:
        import shutil

        return round(shutil.disk_usage(mount_path).total / 1e9, 1)
    except Exception:
        return 0.0


def _final_identity_snapshot(mount_path: str) -> dict[str, Any]:
    from .scanner import _probe_filesystem, _probe_hardware, _resolve_model

    mount_name = _mount_name(mount_path)
    hardware = _probe_hardware(mount_path, mount_name)
    filesystem = _probe_filesystem(mount_path)
    resolved = _resolve_model(hardware, filesystem, _disk_size_gb(mount_path))
    return {
        "hardware": hardware,
        "filesystem": filesystem,
        "resolved": resolved,
    }


def _append_identity_evidence(
    evidence: dict[str, list[dict[str, Any]]],
    source: str,
    identity: dict[str, Any] | None,
) -> None:
    if not identity:
        return
    sources = identity.get("_sources", {})
    for field in IDENTITY_FIELDS:
        value = identity.get(field)
        if value in (None, ""):
            continue
        evidence.setdefault(field, []).append({
            "source": sources.get(field, source),
            "value": value,
        })


def _append_plain_evidence(
    evidence: dict[str, list[dict[str, Any]]],
    source: str,
    data: dict[str, Any] | None,
) -> None:
    if not data:
        return
    sources = data.get("_sources", {})
    for field in IDENTITY_FIELDS:
        value = data.get(field)
        if value in (None, ""):
            continue
        evidence.setdefault(field, []).append({
            "source": sources.get(field, source),
            "value": value,
        })


def _rejected_conflicts(
    final_identity: dict[str, Any],
    evidence: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    rejected: list[dict[str, Any]] = []
    for field, entries in sorted(evidence.items()):
        final_value = final_identity.get(field)
        final_norm = _normalise_for_compare(field, final_value)
        if not final_norm:
            continue
        for entry in entries:
            value_norm = _normalise_for_compare(field, entry.get("value"))
            if value_norm and value_norm != final_norm:
                rejected.append({
                    "field": field,
                    "final_value": final_value,
                    "rejected_value": entry.get("value"),
                    "rejected_source": entry.get("source"),
                })
    return rejected


def dump_device_info(
    mount_path: str,
    *,
    include_raw: bool = False,
    probe_usb_vendor: bool = True,
) -> dict[str, Any]:
    """Build a read-only device diagnostic report."""
    mount_path = os.path.abspath(_normalise_mount_path(mount_path))
    snapshot = _final_identity_snapshot(mount_path)
    final_identity = snapshot["resolved"]

    sysinfo = _sysinfo_dump(mount_path)
    sysinfo_extended = _sysinfo_extended_dump(
        mount_path,
        include_raw=include_raw,
    )
    live_scsi = _live_scsi_dump(mount_path, final_identity)
    live_windows_scsi = (
        live_scsi
        if sys.platform == "win32"
        else {"available": False, "reason": "not_windows"}
    )
    live_usb_vendor = (
        _live_usb_vendor_dump(final_identity)
        if probe_usb_vendor
        else {"available": False, "reason": "disabled"}
    )

    evidence: dict[str, list[dict[str, Any]]] = {}
    _append_identity_evidence(evidence, "sysinfo", sysinfo.get("identity"))
    _append_identity_evidence(
        evidence,
        "sysinfo_extended",
        sysinfo_extended.get("identity"),
    )
    _append_plain_evidence(evidence, "hardware", snapshot.get("hardware"))
    _append_identity_evidence(
        evidence,
        "live_scsi",
        live_scsi.get("identity"),
    )
    _append_identity_evidence(
        evidence,
        "usb_vendor",
        live_usb_vendor.get("identity"),
    )

    usb_details = {
        key: snapshot["hardware"].get(key)
        for key in (
            "usb_vid",
            "usb_pid",
            "firewire_guid",
            "usbstor_instance_id",
            "usb_parent_instance_id",
            "usb_grandparent_instance_id",
        )
        if snapshot["hardware"].get(key) not in (None, "")
    }

    report = {
        "mount_path": mount_path,
        "mount_name": _mount_name(mount_path),
        "sysinfo": sysinfo,
        "disk_sysinfo_extended": sysinfo_extended,
        "live_scsi_vpd": live_scsi,
        "live_windows_scsi_vpd": live_windows_scsi,
        "live_usb_vendor": live_usb_vendor,
        "standard_inquiry": live_scsi.get("standard_inquiry", {}),
        "usb_details": usb_details,
        "final_resolved_identity": final_identity,
        "resolver_conflicts": final_identity.get("_conflicts", []),
        "all_identity_evidence": evidence,
        "rejected_conflicting_evidence": _rejected_conflicts(
            final_identity,
            evidence,
        ),
    }
    return _json_safe(report, include_raw=include_raw)


def _default_paths() -> list[str]:
    from .scanner import _find_ipod_volumes

    return [mount for mount, _display in _find_ipod_volumes()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dump read-only iPod identity evidence for debugging.",
    )
    parser.add_argument("paths", nargs="*", help="Mounted iPod path(s)")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Dump every mounted volume containing iPod_Control",
    )
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="Include raw SysInfoExtended text in the JSON output",
    )
    parser.add_argument(
        "--no-usb-vendor",
        action="store_true",
        help="Skip the USB vendor-control diagnostic probe",
    )
    args = parser.parse_args(argv)

    paths = list(args.paths)
    if args.all or not paths:
        paths.extend(path for path in _default_paths() if path not in paths)

    if not paths:
        print("No iPod volumes found.", file=sys.stderr)
        return 1

    reports = [
        dump_device_info(
            path,
            include_raw=args.include_raw,
            probe_usb_vendor=not args.no_usb_vendor,
        )
        for path in paths
    ]
    payload: Any = reports[0] if len(reports) == 1 else reports
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
