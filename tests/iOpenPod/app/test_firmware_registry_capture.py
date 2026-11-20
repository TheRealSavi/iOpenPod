"""Registry capture uses Storage and preserves device connection semantics."""

from pathlib import Path

import pytest
from tests.iOpenPod.app.test_firmware_mods import APPLE, CATALOG, GAME, ORIGINAL

from iOpenPod.app.firmware.capture import (
    REGISTRY_PATH,
    RegistryStatus,
    capture_registry,
)
from iOpenPod.app.firmware.planner import build_firmware, plan_firmware
from storage import AccessMode, SessionClosedError, SessionInvalidatedError, Storage
from storage.testing import VirtualStoragePlatform


def test_capture_missing_valid_corrupt_and_disconnected_registry(
    tmp_path: Path,
) -> None:
    root = tmp_path / "ipod"
    root.mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform)
    session = storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_ONLY
    )
    assert capture_registry(session).status is RegistryStatus.MISSING
    path = root / str(REGISTRY_PATH)
    path.parent.mkdir(parents=True)
    built = build_firmware(
        plan_firmware(APPLE, "7.26.0", CATALOG, (GAME.id,)), ORIGINAL
    )
    path.write_bytes(built.registry)
    observation = capture_registry(session)
    assert observation.status is RegistryStatus.AVAILABLE
    assert observation.registry is not None
    assert observation.registry.platform_version == "7.26.0"
    assert path.read_bytes() == built.registry
    path.write_bytes(b"bad registry")
    assert capture_registry(session).status is RegistryStatus.UNREADABLE
    session.close()
    with pytest.raises((SessionClosedError, SessionInvalidatedError)):
        capture_registry(session)
