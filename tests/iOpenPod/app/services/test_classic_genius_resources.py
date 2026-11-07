"""Classic Genius companions share Library capture, publication, and recovery."""

import sqlite3
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_device_coordinator import (
    _ipod_volume,  # pyright: ignore[reportPrivateUsage]
)
from tests.iPodDB.library.test_genius_writing import (
    authored,
    remove_second_track,
    update,
)
from tests.iPodDB.library.test_writing import library
from tests.iPodDB.SQLiteDB.sqlite_test_support import sqlite_value

from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.services import library_resources
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iPodDB.library import IPodLibrary, LibraryWritePlan, WriteTarget
from iPodDB.library.genius import parse_genius_database
from storage import AccessMode, FilesystemSession, Storage, StorageError
from storage.testing import VirtualStoragePlatform

_EXTRAS = library_resources.CLASSIC_GENIUS


@dataclass(frozen=True)
class _Device:
    root: Path
    storage: Storage
    active: ActiveIPod
    source: IPodLibrary


@contextmanager
def _device(tmp_path: Path, *, existing: bool = True) -> Generator[_Device]:
    root = _ipod_volume(tmp_path / "classic", model_number="MB029")
    output = authored() if existing else None
    source = IPodLibrary(output.itunes) if output else library()
    (root / str(library_resources.ITUNESDB)).write_bytes(source.serialize().itunes)
    if output is not None:
        assert output.genius is not None
        with sqlite3.connect(":memory:") as connection:
            connection.deserialize(output.genius)
            connection.execute("CREATE TABLE unrelated_extras(value TEXT)")
            connection.execute("INSERT INTO unrelated_extras VALUES ('retained')")
            connection.commit()
            (root / str(_EXTRAS)).write_bytes(connection.serialize())
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    coordinator = DeviceCoordinator(storage)
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id,
            reconcile_metadata=False,
        )
        yield _Device(root, storage, active, source)
    finally:
        coordinator.close()


def _capture(
    session: FilesystemSession,
    device: _Device,
    plan: LibraryWritePlan,
    temporary_files: ExitStack,
) -> library_resources.CapturedLibraryResources:
    return library_resources.capture(
        session,
        LibraryPreparationRequest(
            plan.draft.snapshot,
            device.active,
            1,
            1,
            replace_media=plan.draft.replace_media,
        ),
        plan,
        lambda: None,
        temporary_files=temporary_files,
        source_artwork_display_times=lambda _: (),
        source_artwork_paths=lambda _: (),
        volume_presentation_enabled=False,
    )


def _updated_plan(device: _Device) -> LibraryWritePlan:
    snapshot = device.source.snapshot
    desired = replace(
        snapshot,
        tracks=(replace(snapshot.tracks[0], title="Updated"), snapshot.tracks[1]),
    )
    intent = update()
    intent = replace(
        intent,
        data=replace(
            intent.data,
            configs=(replace(intent.data.configs[0], default_num_results=26),),
        ),
    )
    return device.source.analyze(
        device.source.begin_draft(desired, genius_update=intent)
    )


def test_classic_update_publishes_and_restores_both_artifacts(tmp_path: Path) -> None:
    with _device(tmp_path) as device, ExitStack() as temporary_files:
        original = {
            path: (device.root / str(path)).read_bytes()
            for path in (library_resources.ITUNESDB, _EXTRAS)
        }
        with device.storage.open_session(
            device.storage.discover().volumes[0], access=AccessMode.READ_WRITE
        ) as session:
            plan = _updated_plan(device)
            captured = _capture(session, device, plan, temporary_files)
            assert captured.resources.genius_source == original[_EXTRAS]
            result = device.source.prepare(plan, captured.resources)
            assert result.prepared is not None, result.issues
            prepared = result.prepared
            assert prepared.genius is not None
            assert (
                sqlite_value(prepared.genius, "SELECT value FROM unrelated_extras")
                == "retained"
            )
            transaction = library_resources.transaction(
                session,
                captured,
                prepared,
                original[library_resources.ITUNESDB],
                None,
                None,
            )
            assert transaction is not None
            assert {write.path for write in transaction.writes} == set(original)
            assert {
                change.path for change in library_resources.describe(transaction)
            } == {str(path) for path in original}
            committed = session.execute_transaction(transaction)
            assert session.read_snapshot(_EXTRAS).data == prepared.genius
            assert (
                session.read_snapshot(library_resources.ITUNESDB).data
                == prepared.itunes
            )
            session.restore_transaction(committed.recovery)
            for path, data in original.items():
                assert session.read_snapshot(path).data == data


@pytest.mark.parametrize("existing", [False, True])
def test_external_extras_change_rejects_publication(
    tmp_path: Path, existing: bool
) -> None:
    with (
        _device(tmp_path, existing=existing) as device,
        ExitStack() as temporary_files,
        device.storage.open_session(
            device.storage.discover().volumes[0], access=AccessMode.READ_WRITE
        ) as session,
    ):
        plan = _updated_plan(device)
        captured = _capture(session, device, plan, temporary_files)
        result = device.source.prepare(plan, captured.resources)
        assert result.prepared is not None, result.issues
        original = device.source.serialize().itunes
        transaction = library_resources.transaction(
            session, captured, result.prepared, original, None, None
        )
        assert transaction is not None
        (device.root / str(_EXTRAS)).write_bytes(b"external change")
        with pytest.raises(StorageError):
            session.execute_transaction(transaction)
        assert session.read_snapshot(library_resources.ITUNESDB).data == original
        assert session.read_snapshot(_EXTRAS).data == b"external change"


def test_missing_classic_companion_creation_and_rollback(tmp_path: Path) -> None:
    with (
        _device(tmp_path, existing=False) as device,
        ExitStack() as temporary_files,
        device.storage.open_session(
            device.storage.discover().volumes[0], access=AccessMode.READ_WRITE
        ) as session,
    ):
        plan = _updated_plan(device)
        captured = _capture(session, device, plan, temporary_files)
        assert captured.resources.genius_source is None
        assert (
            next(file for file in captured.files if file.path == _EXTRAS).fingerprint
            is None
        )
        result = device.source.prepare(plan, captured.resources)
        assert result.prepared is not None, result.issues
        original = device.source.serialize().itunes
        transaction = library_resources.transaction(
            session, captured, result.prepared, original, None, None
        )
        assert transaction is not None
        committed = session.execute_transaction(transaction)
        assert plan.draft.genius_update is not None
        assert (
            parse_genius_database(session.read_snapshot(_EXTRAS).data).data
            == plan.draft.genius_update.data
        )
        session.restore_transaction(committed.recovery)
        assert not session.exists(_EXTRAS)
        assert session.read_snapshot(library_resources.ITUNESDB).data == original


def test_identical_explicit_update_does_not_rewrite_companion(tmp_path: Path) -> None:
    with (
        _device(tmp_path) as device,
        ExitStack() as temporary_files,
        device.storage.open_session(device.storage.discover().volumes[0]) as session,
    ):
        plan = device.source.analyze(device.source.begin_draft(genius_update=update()))
        captured = _capture(session, device, plan, temporary_files)
        result = device.source.prepare(plan, captured.resources)
        assert result.prepared is not None, result.issues
        assert result.prepared.genius == captured.resources.genius_source
        transaction = library_resources.transaction(
            session,
            captured,
            result.prepared,
            device.source.serialize().itunes,
            None,
            None,
            allow_unchanged=True,
        )
        assert transaction is None


@pytest.mark.parametrize("replacement", [False, True])
def test_existing_genius_removal_or_replacement_captures_companion(
    tmp_path: Path, replacement: bool
) -> None:
    with _device(tmp_path) as device, ExitStack() as temporary_files:
        draft = (
            device.source.begin_draft(replace_media=(2,))
            if replacement
            else device.source.begin_draft(
                remove_second_track(device.source), delete_omissions=True
            )
        )
        plan = device.source.analyze(draft)
        with device.storage.open_session(
            device.storage.discover().volumes[0]
        ) as session:
            captured = _capture(session, device, plan, temporary_files)
            assert (
                captured.resources.genius_source == session.read_snapshot(_EXTRAS).data
            )


def test_ordinary_metadata_edit_does_not_depend_on_classic_extras(
    tmp_path: Path,
) -> None:
    with _device(tmp_path) as device, ExitStack() as temporary_files:
        plan = _updated_plan(device)
        plan = replace(plan, draft=replace(plan.draft, genius_update=None))
        with device.storage.open_session(
            device.storage.discover().volumes[0]
        ) as session:
            captured = _capture(session, device, plan, temporary_files)
            assert captured.resources.genius_source is None
            assert all(file.path != _EXTRAS for file in captured.files)


def test_sqlite_capture_does_not_capture_classic_root_extras(tmp_path: Path) -> None:
    with _device(tmp_path) as device, ExitStack() as temporary_files:
        plan = replace(_updated_plan(device), target=WriteTarget(sqlite_database=True))
        with device.storage.open_session(
            device.storage.discover().volumes[0]
        ) as session:
            captured = _capture(session, device, plan, temporary_files)
            assert captured.resources.genius_source is None
            assert all(file.path != _EXTRAS for file in captured.files)
            assert library_resources.sqlite_database_path("Extras.itdb") in {
                file.path for file in captured.files
            }


def test_uncaptured_companion_output_cannot_authorize_a_new_write(
    tmp_path: Path,
) -> None:
    with _device(tmp_path) as device, ExitStack() as temporary_files:
        plan = device.source.analyze(device.source.begin_draft())
        with device.storage.open_session(
            device.storage.discover().volumes[0]
        ) as session:
            captured = _capture(session, device, plan, temporary_files)
            with pytest.raises(ValueError, match="captured precondition"):
                library_resources.transaction(
                    session,
                    captured,
                    authored(),
                    device.source.serialize().itunes,
                    None,
                    None,
                )
