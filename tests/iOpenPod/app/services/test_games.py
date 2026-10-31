"""Small authorization publication tests on virtual media, without firmware."""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import pytest

import iPodDB.ic_info
from device_registry import DeviceEvidence, DeviceIdentifier, EvidenceAuthority
from iOpenPod.app.services import games
from iOpenPod.app.services.device_coordinator import (
    DeviceCoordinationError,
    DeviceCoordinator,
)
from storage import (
    AccessMode,
    FilesystemSession,
    HardwareIdentifiers,
    Storage,
    StorageError,
)
from storage.testing import VirtualStoragePlatform

GUID = bytes.fromhex("0011223344556677")


@dataclass(frozen=True)
class Converted:
    data: bytes
    added_keys: int = 1
    replaced_keys: int = 0
    unchanged_keys: int = 0


@contextmanager
def volume(root: Path) -> Generator[FilesystemSession]:
    (root / "iPod_Control/iTunes").mkdir(parents=True)
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform, transaction_recovery_directory=root.parent / "recovery")
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        yield session


@pytest.mark.parametrize("existing", [None, b"old authorization"])
def test_prepare_captures_existing_file_and_commits_verified_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bytes | None
) -> None:
    captured: list[bytes | None] = []

    def convert(
        source: bytes,
        source_guid: bytes,
        destination_guid: bytes,
        family: int,
        previous: bytes | None,
    ) -> Converted:
        assert (
            source == b"bundled"
            and source_guid == GUID
            and destination_guid == GUID
            and family == 33
        )
        captured.append(previous)
        return Converted(b"merged", replaced_keys=int(previous is not None))

    monkeypatch.setattr(iPodDB.ic_info, "transfer_and_merge", convert, raising=False)
    root = tmp_path / "device"
    with volume(root) as session:
        target = root / str(games.AUTHORIZATION_PATH)
        if existing is not None:
            target.write_bytes(existing)
        plan = games.prepare(
            session,
            source=b"bundled",
            source_guid=GUID,
            destination_guid=GUID,
            family=33,
            dependencies=(),
        )
        assert captured == [existing]
        assert plan.transaction is not None and plan.transaction.host_recovery
        assert (target.read_bytes() if target.exists() else None) == existing
        result = session.execute_transaction(plan.transaction)
        assert result.flush.complete
        assert target.read_bytes() == b"merged"
        assert session.finalize_committed_transaction(
            result.recovery.journal_path
        ).complete


@pytest.mark.parametrize("changed_after_capture", [False, True])
def test_noop_skips_transaction_and_stale_existing_file_cannot_be_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_after_capture: bool
) -> None:
    def convert(*_args: object) -> Converted:
        return Converted(b"new" if changed_after_capture else b"original")

    monkeypatch.setattr(iPodDB.ic_info, "transfer_and_merge", convert, raising=False)
    root = tmp_path / "device"
    with volume(root) as session:
        target = root / str(games.AUTHORIZATION_PATH)
        target.write_bytes(b"original")
        plan = games.prepare(
            session,
            source=b"source",
            source_guid=GUID,
            destination_guid=GUID,
            family=33,
            dependencies=(),
        )
        if not changed_after_capture:
            assert plan.transaction is None and not plan.result.changed
        else:
            assert plan.transaction is not None
            target.write_bytes(b"external change")
            with pytest.raises(StorageError):
                session.execute_transaction(plan.transaction)
            assert target.read_bytes() == b"external change"


def test_invalid_existing_authorization_is_not_treated_as_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject(
        _source: bytes,
        _source_guid: bytes,
        _guid: bytes,
        _family: int,
        existing: bytes | None,
    ) -> Converted:
        assert existing == b""
        raise ValueError("Invalid authentication")

    monkeypatch.setattr(iPodDB.ic_info, "transfer_and_merge", reject, raising=False)
    root = tmp_path / "device"
    with volume(root) as session:
        target = root / str(games.AUTHORIZATION_PATH)
        target.write_bytes(b"")
        with pytest.raises(ValueError, match="Invalid authentication"):
            games.prepare(
                session,
                source=b"source",
                source_guid=GUID,
                destination_guid=GUID,
                family=33,
                dependencies=(),
            )
        assert target.read_bytes() == b""
        assert not session.host_transaction_journals()


def test_noop_does_not_claim_success_after_an_external_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "device"
    with volume(root) as session:
        target = root / str(games.AUTHORIZATION_PATH)
        target.write_bytes(b"original")

        def convert(*_args: object) -> Converted:
            target.write_bytes(b"external change")
            return Converted(b"original")

        monkeypatch.setattr(
            iPodDB.ic_info, "transfer_and_merge", convert, raising=False
        )
        with pytest.raises(ValueError, match="changed during preparation"):
            games.prepare(
                session,
                source=b"source",
                source_guid=GUID,
                destination_guid=GUID,
                family=33,
                dependencies=(),
            )
        assert target.read_bytes() == b"external change"


def evidence(family: int, release: str) -> DeviceEvidence:
    return DeviceEvidence(
        updater_family_ids=(
            DeviceIdentifier(family, "test", EvidenceAuthority.CURRENT_HARDWARE),
        ),
        firmware_versions=(
            DeviceIdentifier(release, "test", EvidenceAuthority.CURRENT_HARDWARE),
        ),
    )


@pytest.mark.parametrize("family,release", [(33, "2.0.1"), (34, "1.0.2"), (13, "1.3")])
def test_supported_build_is_qualified(family: int, release: str) -> None:
    assert games.destination_family(evidence(family, release)) == family


@pytest.mark.parametrize(
    "value",
    [
        DeviceEvidence(),
        evidence(33, "2.0.2"),
        evidence(999, "1.0"),
        evidence(34, "34A20020"),
        evidence(33, "2.0.1").merged_with(evidence(34, "1.0.2")),
    ],
)
def test_unverified_or_conflicting_destination_fails_closed(
    value: DeviceEvidence,
) -> None:
    with pytest.raises(ValueError):
        games.destination_family(value)


def test_coordinator_uses_active_identity_and_storage_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "device"
    metadata = root / "iPod_Control/Device"
    metadata.mkdir(parents=True)
    (metadata / "SysInfo").write_text(
        "ModelNumStr: MB565\nUpdaterFamilyID: 33\nvisibleBuildID: 2.0.1\n"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root, identifiers=HardwareIdentifiers(transport_serial=GUID.hex())
    )
    coordinator = DeviceCoordinator(
        Storage(platform, transaction_recovery_directory=tmp_path / "recovery"),
        volume_presentation_enabled=False,
    )
    calls: list[tuple[bytes, int, bytes | None]] = []

    def convert(
        _source: bytes,
        _source_guid: bytes,
        guid: bytes,
        family: int,
        existing: bytes | None,
    ) -> Converted:
        calls.append((guid, family, existing))
        return Converted(b"new authorization")

    monkeypatch.setattr(iPodDB.ic_info, "transfer_and_merge", convert, raising=False)
    monkeypatch.setattr(games, "bundled_source", lambda: (b"source", GUID))
    try:
        candidate = coordinator.discover_devices().candidates[0]
        active = coordinator.select_device(candidate.id)
        assert not coordinator.games_unavailable_reason(active)
        result = coordinator.install_game_authorizations(active, Event())
        assert result.changed and result.added_keys == 1
        assert calls == [(GUID, 33, None)]
        assert (
            root / str(games.AUTHORIZATION_PATH)
        ).read_bytes() == b"new authorization"
    finally:
        coordinator.close()


@pytest.mark.parametrize("change", ["metadata", "disconnect", "cancel"])
def test_coordinator_stops_before_publication_when_preparation_loses_its_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    root = tmp_path / "device"
    metadata = root / "iPod_Control/Device"
    metadata.mkdir(parents=True)
    sysinfo = metadata / "SysInfo"
    sysinfo.write_text(
        "ModelNumStr: MB565\nUpdaterFamilyID: 33\nvisibleBuildID: 2.0.1\n"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root, identifiers=HardwareIdentifiers(transport_serial=GUID.hex())
    )
    coordinator = DeviceCoordinator(
        Storage(platform, transaction_recovery_directory=tmp_path / "recovery"),
        volume_presentation_enabled=False,
    )
    cancelled = Event()

    def convert(*_args: object) -> Converted:
        if change == "metadata":
            sysinfo.write_text("changed identity")
        elif change == "disconnect":
            platform.disconnect(root)
        else:
            cancelled.set()
        return Converted(b"new authorization")

    monkeypatch.setattr(iPodDB.ic_info, "transfer_and_merge", convert, raising=False)
    monkeypatch.setattr(games, "bundled_source", lambda: (b"source", GUID))
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        target = root / str(games.AUTHORIZATION_PATH)
        target.write_bytes(b"original authorization")
        with pytest.raises(
            (DeviceCoordinationError, StorageError),
            match=r"changed|disconnected|cancelled",
        ):
            coordinator.install_game_authorizations(active, cancelled)
        assert target.read_bytes() == b"original authorization"
    finally:
        coordinator.close()
