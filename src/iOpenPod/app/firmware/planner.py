"""Resolve mod selections and compose checked images from pristine inputs."""

import hashlib
import json
from collections.abc import Iterable
from itertools import pairwise

from iOpenPod.app.firmware.models import (
    AppleFirmware,
    FirmwareBuild,
    FirmwareBuildPlan,
    FirmwareMod,
    validate_text,
)


def plan_firmware(
    apple: AppleFirmware,
    platform_version: str,
    catalog: Iterable[FirmwareMod],
    selected: Iterable[str],
) -> FirmwareBuildPlan:
    """Pin a deterministic dependency closure or explain why it cannot compose."""
    validate_text(platform_version, maximum=32)
    entries = tuple(catalog)
    by_id = {mod.id: mod for mod in entries}
    if len(by_id) != len(entries) or len(entries) > 128:
        raise ValueError("The Firmware Mod catalog must have at most 128 unique IDs")
    requested = tuple(sorted(set(selected)))
    visiting: set[str] = set()
    visited: set[str] = set()
    resolved: list[FirmwareMod] = []

    def visit(mod_id: str) -> None:
        if mod_id in visiting:
            raise ValueError(f"Firmware Mod dependency cycle: {mod_id}")
        if mod_id in visited:
            return
        mod = by_id.get(mod_id)
        if mod is None:
            raise ValueError(f"Unknown Firmware Mod: {mod_id}")
        if apple.target_id not in mod.targets:
            raise ValueError(f"{mod.name} does not support this Apple Firmware target")
        visiting.add(mod_id)
        for dependency in sorted(mod.dependencies):
            visit(dependency)
        visiting.remove(mod_id)
        visited.add(mod_id)
        resolved.append(mod)

    for mod_id in requested:
        visit(mod_id)
    hooks: dict[str, str] = {}
    spans: list[tuple[int, int, str]] = []
    for mod in resolved:
        for conflict in mod.conflicts:
            if conflict in visited:
                raise ValueError(f"{mod.name} conflicts with {by_id[conflict].name}")
        for hook in mod.hooks:
            if hook in hooks:
                raise ValueError(
                    f"Shared hook conflict: {mod.id} and {hooks[hook]} ({hook})"
                )
            hooks[hook] = mod.id
        for patch in mod.patches or ():
            end = patch.offset + len(patch.expected)
            if end > apple.size_bytes:
                raise ValueError(f"{mod.name} patches beyond the Apple Firmware image")
            spans.append((patch.offset, end, mod.id))
    spans.sort()
    for previous, following in pairwise(spans):
        if previous[1] > following[0]:
            raise ValueError(
                f"Overlapping firmware patches: {previous[2]} and {following[2]}"
            )
    identity = {
        "schema": 1,
        "apple": [apple.target_id, apple.version, apple.sha256, apple.size_bytes],
        "platform_version": platform_version,
        "requested": requested,
        "mods": [
            {
                "id": mod.id,
                "version": mod.version,
                "name": mod.name,
                "description": mod.description,
                "targets": sorted(mod.targets),
                "dependencies": sorted(mod.dependencies),
                "conflicts": sorted(mod.conflicts),
                "hooks": sorted(mod.hooks),
                "patches": None
                if mod.patches is None
                else [
                    [patch.offset, patch.expected.hex(), patch.replacement.hex()]
                    for patch in sorted(mod.patches, key=lambda patch: patch.offset)
                ],
            }
            for mod in resolved
        ],
    }
    build_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return FirmwareBuildPlan(
        apple, platform_version, requested, tuple(resolved), build_id
    )


def build_firmware(plan: FirmwareBuildPlan, original: bytes) -> FirmwareBuild:
    """Verify all inputs before applying any patch; no filesystem side effects."""
    from iOpenPod.app.firmware.registry import registry_for_build, write_registry

    checked = plan_firmware(
        plan.apple, plan.platform_version, plan.mods, plan.requested
    )
    if checked != plan:
        raise ValueError("Firmware Build Plan does not match its pinned contents")
    if plan.missing_recipes:
        raise ValueError(
            "Qualified build recipes are unavailable: "
            + ", ".join(plan.missing_recipes)
        )
    if (
        len(original) != plan.apple.size_bytes
        or hashlib.sha256(original).hexdigest() != plan.apple.sha256
    ):
        raise ValueError("The build requires the exact pristine Apple Firmware image")
    for mod in plan.mods:
        for patch in mod.patches or ():
            if (
                original[patch.offset : patch.offset + len(patch.expected)]
                != patch.expected
            ):
                raise ValueError(f"Expected original bytes do not match for {mod.id}")
    image = bytearray(original)
    for mod in plan.mods:
        for patch in mod.patches or ():
            image[patch.offset : patch.offset + len(patch.expected)] = patch.replacement
    result = bytes(image)
    registry = registry_for_build(plan, hashlib.sha256(result).hexdigest())
    return FirmwareBuild(plan, result, write_registry(registry))
