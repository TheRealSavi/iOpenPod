"""Mod compositions, failed preconditions, and registry interchange contracts."""

import hashlib
import json
from dataclasses import replace

import pytest

from iOpenPod.app.firmware.models import AppleFirmware, FirmwareMod, FirmwarePatch
from iOpenPod.app.firmware.planner import build_firmware, plan_firmware
from iOpenPod.app.firmware.registry import (
    MAX_REGISTRY_BYTES,
    read_registry,
    registry_c_source,
    write_registry,
)

ORIGINAL = b"Apple 2.0.5\0" + bytes(range(32))
APPLE = AppleFirmware(
    "test-classic", "2.0.5", hashlib.sha256(ORIGINAL).hexdigest(), len(ORIGINAL)
)
CORE = FirmwareMod(
    "org.test.platform",
    "7.26.0",
    "Platform",
    "Registry support.",
    (APPLE.target_id,),
    patches=(),
)
HOME = FirmwareMod(
    "org.test.homebrew",
    "1.0.0",
    "Homebrew",
    "Game loader.",
    (APPLE.target_id,),
    dependencies=(CORE.id,),
    hooks=("manifest-reader",),
    patches=(FirmwarePatch(12, bytes([0, 1]), bytes([10, 11])),),
)
GAME = FirmwareMod(
    "org.test.parachute",
    "1.0.1",
    "Parachute",
    "Corrected game.",
    (APPLE.target_id,),
    dependencies=(HOME.id,),
    patches=(FirmwarePatch(14, bytes([2, 3]), bytes([12, 13])),),
)
CATALOG = (CORE, HOME, GAME)


def test_composition_is_deterministic_and_unchecking_rebuilds_from_apple() -> None:
    plan = plan_firmware(APPLE, "7.26.0", CATALOG, [GAME.id])
    assert tuple(mod.id for mod in plan.mods) == (CORE.id, HOME.id, GAME.id)
    assert plan == plan_firmware(APPLE, "7.26.0", reversed(CATALOG), [GAME.id, GAME.id])
    built = build_firmware(plan, ORIGINAL)
    assert built.image == ORIGINAL[:12] + bytes([10, 11, 12, 13]) + ORIGINAL[16:]
    assert built.image[:12] == b"Apple 2.0.5\0"
    registry = read_registry(built.registry)
    assert registry.platform_version == "7.26.0"
    assert registry.apple.version == "2.0.5"
    assert registry.image_sha256 == hashlib.sha256(built.image).hexdigest()
    assert tuple(mod.id for mod in registry.mods) == (CORE.id, HOME.id, GAME.id)
    assert write_registry(registry) == built.registry
    assert build_firmware(plan, ORIGINAL) == built
    clean = build_firmware(plan_firmware(APPLE, "7.26.0", CATALOG, [CORE.id]), ORIGINAL)
    assert clean.image == ORIGINAL
    assert clean.plan.build_id != plan.build_id
    with pytest.raises(ValueError, match="pristine"):
        build_firmware(plan, built.image)


def test_build_identity_tracks_recipe_changes_with_unchanged_mod_version() -> None:
    plan = plan_firmware(APPLE, "7.26.0", CATALOG, [GAME.id])
    changed = replace(GAME, patches=(FirmwarePatch(14, bytes([2, 3]), b"XY"),))
    other = plan_firmware(APPLE, "7.26.0", (CORE, HOME, changed), [GAME.id])
    assert plan.build_id != other.build_id
    with pytest.raises(ValueError, match="pinned contents"):
        build_firmware(replace(plan, mods=other.mods), ORIGINAL)


@pytest.mark.parametrize(
    ("catalog", "selected", "message"),
    [
        ((CORE, CORE), (CORE.id,), "unique IDs"),
        (CATALOG, ("unknown",), "Unknown"),
        ((CORE, GAME), (GAME.id,), "Unknown"),
        ((replace(CORE, targets=("elsewhere",)),), (CORE.id,), "does not support"),
        ((replace(CORE, dependencies=(HOME.id,)), HOME), (HOME.id,), "cycle"),
        ((CORE, HOME, replace(GAME, conflicts=(HOME.id,))), (GAME.id,), "conflicts"),
        ((CORE, HOME, replace(GAME, hooks=HOME.hooks)), (GAME.id,), "Shared hook"),
        ((CORE, HOME, replace(GAME, patches=HOME.patches)), (GAME.id,), "Overlapping"),
        (
            (replace(CORE, patches=(FirmwarePatch(999, b"x", b"y"),)),),
            (CORE.id,),
            "beyond",
        ),
    ],
)
def test_invalid_compositions_are_rejected(
    catalog: tuple[FirmwareMod, ...], selected: tuple[str, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        plan_firmware(APPLE, "7.26.0", catalog, selected)


def test_preimage_and_missing_recipe_fail_before_returning_an_image() -> None:
    changed = replace(GAME, patches=(FirmwarePatch(14, b"XX", b"YY"),))
    with pytest.raises(ValueError, match="original bytes"):
        build_firmware(
            plan_firmware(APPLE, "7.26.0", (CORE, HOME, changed), [GAME.id]), ORIGINAL
        )
    missing = replace(CORE, patches=None)
    plan = plan_firmware(APPLE, "7.26.0", (missing,), [missing.id])
    assert plan.missing_recipes == (CORE.id,)
    with pytest.raises(ValueError, match="unavailable"):
        build_firmware(plan, ORIGINAL)
    with pytest.raises(ValueError, match="pristine"):
        build_firmware(
            plan_firmware(APPLE, "7.26.0", (CORE,), [CORE.id]), ORIGINAL[:-1]
        )


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b"[]",
        b"null",
        b'{"schema":1,"schema":1}',
        b"[" * 2000,
        b"\xff",
        bytes(MAX_REGISTRY_BYTES + 1),
    ],
    ids=[
        "empty-object",
        "array",
        "null",
        "duplicate-key",
        "nested",
        "encoding",
        "oversize",
    ],
)
def test_registry_rejects_malformed_unbounded_and_ambiguous_records(
    payload: bytes,
) -> None:
    with pytest.raises(ValueError):
        read_registry(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", True),
        ("schema", 2),
        ("build_id", "short"),
        ("requested", ["unknown"]),
        ("mods", [{"id": "../../bad"}]),
    ],
)
def test_registry_rejects_invalid_field_shapes(field: str, value: object) -> None:
    built = build_firmware(plan_firmware(APPLE, "7.26.0", CATALOG, [GAME.id]), ORIGINAL)
    record = json.loads(built.registry)
    record[field] = value
    with pytest.raises(ValueError):
        read_registry(json.dumps(record).encode())


def test_native_registry_source_escapes_mod_names_and_avoids_self_hashing() -> None:
    mod = replace(CORE, name='A "quote" and café \\ name')
    built = build_firmware(plan_firmware(APPLE, "7.26.0", (mod,), [mod.id]), ORIGINAL)
    source = registry_c_source(read_registry(built.registry))
    assert "const unsigned int iop_mod_count = 1u;" in source
    assert "const char iop_platform_version[]" in source
    assert "const char iop_apple_version[]" in source
    assert "café" not in source
    assert "\\303\\251" in source
    assert "image_sha256" not in source


def test_production_catalog_cannot_emit_a_fake_bootable_build() -> None:
    from iOpenPod.app.firmware.catalog import BASES, CATALOG, CORE_ID, PLATFORM_VERSION

    for base in BASES.values():
        plan = plan_firmware(base, PLATFORM_VERSION, CATALOG, (CORE_ID,))
        assert plan.missing_recipes
        with pytest.raises(ValueError, match="unavailable"):
            build_firmware(plan, b"")
