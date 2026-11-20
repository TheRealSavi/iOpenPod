"""Bounded installed-build records and a freestanding firmware registry source."""

import json
from dataclasses import dataclass
from typing import cast

from iOpenPod.app.firmware.models import (
    AppleFirmware,
    FirmwareBuildPlan,
    validate_digest,
    validate_id,
    validate_text,
)

MAX_REGISTRY_BYTES = 128 * 1024


@dataclass(frozen=True, slots=True)
class RegistryMod:
    id: str
    version: str
    name: str

    def __post_init__(self) -> None:
        validate_id(self.id)
        validate_text(self.version, maximum=32)
        validate_text(self.name)


@dataclass(frozen=True, slots=True)
class FirmwareRegistry:
    """Recorded build identity; possession of this file does not prove boot state."""

    apple: AppleFirmware
    platform_version: str
    build_id: str
    image_sha256: str
    requested: tuple[str, ...]
    mods: tuple[RegistryMod, ...]

    def __post_init__(self) -> None:
        validate_text(self.platform_version, maximum=32)
        validate_digest(self.build_id)
        validate_digest(self.image_sha256)
        ids = {mod.id for mod in self.mods}
        if len(self.mods) > 128 or len(ids) != len(self.mods):
            raise ValueError("Invalid Firmware Mod registry entries")
        if (
            len(set(self.requested)) != len(self.requested)
            or not set(self.requested) <= ids
        ):
            raise ValueError("Invalid requested Firmware Mods")


def registry_for_build(plan: FirmwareBuildPlan, image_sha256: str) -> FirmwareRegistry:
    return FirmwareRegistry(
        plan.apple,
        plan.platform_version,
        plan.build_id,
        image_sha256,
        plan.requested,
        tuple(RegistryMod(mod.id, mod.version, mod.name) for mod in plan.mods),
    )


def write_registry(registry: FirmwareRegistry) -> bytes:
    """Stable schema with no machine paths, device secrets or timestamps."""
    value = {
        "schema": 1,
        "apple": {
            "target": registry.apple.target_id,
            "version": registry.apple.version,
            "sha256": registry.apple.sha256,
            "bytes": registry.apple.size_bytes,
        },
        "platform_version": registry.platform_version,
        "build_id": registry.build_id,
        "image_sha256": registry.image_sha256,
        "requested": list(registry.requested),
        "mods": [
            {"id": mod.id, "version": mod.version, "name": mod.name}
            for mod in registry.mods
        ],
    }
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    ).encode()


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate Firmware Registry key")
        result[key] = value
    return result


def _mapping(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Unexpected Firmware Registry fields")
    # JSON object keys are strings; keep each value unknown until validated.
    result = cast("dict[str, object]", value)
    if set(result) != keys:
        raise ValueError("Unexpected Firmware Registry fields")
    return dict(result)


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Invalid Firmware Registry lists")
    return cast("list[object]", value)


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected Firmware Registry text")
    return value


def read_registry(data: bytes) -> FirmwareRegistry:
    if len(data) > MAX_REGISTRY_BYTES:
        raise ValueError("Firmware Registry exceeds the supported size")
    try:
        value: object = json.loads(data, object_pairs_hook=_object)
        root = _mapping(
            value,
            {
                "schema",
                "apple",
                "platform_version",
                "build_id",
                "image_sha256",
                "requested",
                "mods",
            },
        )
        if type(root["schema"]) is not int or root["schema"] != 1:
            raise ValueError("Unsupported Firmware Registry schema")
        apple = _mapping(root["apple"], {"target", "version", "sha256", "bytes"})
        size = apple["bytes"]
        if type(size) is not int:
            raise ValueError("Invalid Apple Firmware size")
        entries = _list(root["mods"])
        requested = _list(root["requested"])
        if len(entries) > 128:
            raise ValueError("Invalid Firmware Registry lists")
        mods: list[RegistryMod] = []
        for entry in entries:
            row = _mapping(entry, {"id", "version", "name"})
            mods.append(
                RegistryMod(
                    _string(row["id"]), _string(row["version"]), _string(row["name"])
                )
            )
        return FirmwareRegistry(
            AppleFirmware(
                _string(apple["target"]),
                _string(apple["version"]),
                _string(apple["sha256"]),
                size,
            ),
            _string(root["platform_version"]),
            _string(root["build_id"]),
            _string(root["image_sha256"]),
            tuple(_string(item) for item in requested),
            tuple(mods),
        )
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Invalid Firmware Registry encoding or nesting") from error


def registry_c_source(registry: FirmwareRegistry) -> str:
    """Emit read-only registry data for a native firmware menu to consume.

    Every UTF-8 byte is octal escaped: mod names cannot inject C tokens, and
    adjacent hex digits cannot change an escape. This emits data, not a menu hook.
    The final image hash remains a sidecar field to avoid a self-hashing image.
    """

    def literal(value: str) -> str:
        return '"' + "".join(f"\\{byte:03o}" for byte in value.encode("utf-8")) + '"'

    rows = [
        "/* Generated Firmware Mod Registry, schema 1. */",
        "struct iop_mod { const char *id, *version, *name; };",
        f"const char iop_platform_version[] = {literal(registry.platform_version)};",
        f"const char iop_apple_version[] = {literal(registry.apple.version)};",
        f"const char iop_build_id[] = {literal(registry.build_id)};",
        f"const unsigned int iop_mod_count = {len(registry.mods)}u;",
        "const struct iop_mod iop_mods[] = {",
        *(
            "    {"
            + ", ".join(literal(value) for value in (mod.id, mod.version, mod.name))
            + "},"
            for mod in registry.mods
        ),
        "    {0, 0, 0}",
        "};",
        "",
    ]
    return "\n".join(rows)
