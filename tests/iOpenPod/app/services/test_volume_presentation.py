"""Desktop companion files follow saved names through recoverable Storage writes."""

import os
from configparser import ConfigParser
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from threading import Event, Thread

import pytest
from PIL import Image
from tests.iOpenPod.app.services.test_first_artwork_save import bare_device

from iOpenPod.app.library_write import LibraryPreparationRequest, WriteProgress
from iOpenPod.app.models.device import DeviceCandidateIssueCode
from iOpenPod.app.services import volume_presentation
from iOpenPod.app.services.device_coordinator import (
    DeviceAccessError,
    DeviceCoordinator,
    SyncRecoveryRequiredError,
)
from storage import (
    AccessMode,
    FilePreconditionError,
    Storage,
    StorageOperationError,
    StorageTransaction,
)
from storage.testing import VirtualStoragePlatform

_COMPANIONS = (
    "autorun.inf",
    ".xdg-volume-info",
    ".directory",
    ".VolumeIcon.icns",
    "iPod_Control/iOpenPod/volume-icon.png",
    "iPod_Control/iOpenPod/volume-icon.ico",
)


@pytest.mark.parametrize("host_identity_changed", [False, True])
def test_saved_rename_can_be_ejected_and_reconnected_without_recovery(
    tmp_path: Path, host_identity_changed: bool
) -> None:
    device = bare_device(tmp_path)
    coordinator = device.coordinator
    try:
        result = device.save(
            device.prepare(replace(device.active.library, device_name="HappyPod :)"))
        )
        assert result.active is not None, result.issues
        journal = device.root / result.recovery_path
        committed_journal = journal.read_bytes()
        coordinator.eject_active_ipod(result.active)
        reconnected = device.platform.reconnect(device.root)
        if host_identity_changed:
            device.platform.replace_identity(
                device.root,
                device_id=reconnected.physical_device.id.value,
                volume_id=reconnected.volume.id.value + ":new-host-volume-guid",
            )
        coordinator = DeviceCoordinator(device.storage)
        candidate = coordinator.discover_devices().candidates[0]
        selected = coordinator.select_device(candidate.id)
        assert selected.library.device_name == "HappyPod :)"
        assert journal.read_bytes() == committed_journal
        if host_identity_changed:
            assert coordinator.sync_cleanup_path == ""
    finally:
        coordinator.close()
        device.coordinator.close()


def test_disabled_selection_and_rename_preserve_custom_files_and_native_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = bare_device(tmp_path, volume_presentation_enabled=False)
    try:
        assert all(not (device.root / name).exists() for name in _COMPANIONS)
        custom: dict[str, bytes] = {}
        for name in _COMPANIONS:
            path = device.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            # Deliberately unsupported text and icon formats must not be read or
            # validated when the user manages their own presentation.
            custom[name] = b"\x80custom " + name.encode()
            path.write_bytes(custom[name])
        device.platform.set_volume_label(
            device.platform.inspect(device.root), "Custom drive"
        )

        def unexpected_native_update(*_args: object) -> None:
            pytest.fail("Disabled appearance must not call native metadata APIs")

        monkeypatch.setattr(
            device.platform, "set_volume_label", unexpected_native_update
        )
        monkeypatch.setattr(
            device.platform, "enable_volume_icon", unexpected_native_update
        )
        device.coordinator.select_device(device.active.candidate.id)
        assert not any(
            issue.code is DeviceCandidateIssueCode.VOLUME_PRESENTATION_INCOMPLETE
            for issue in device.active.candidate.issues
        )
        review = device.prepare(replace(device.active.library, device_name="Renamed"))
        assert review.result.prepared is not None, review.result.issues
        assert not set(_COMPANIONS) & {change.path for change in review.file_changes}
        custom[".directory"] = b"Edited by the user after review"
        (device.root / ".directory").write_bytes(custom[".directory"])
        result = device.save(review)
        assert result.active is not None, result.issues
        assert result.active.library.device_name == "Renamed"
        assert {
            name: (device.root / name).read_bytes() for name in _COMPANIONS
        } == custom
        assert device.platform.inspect(device.root).volume.label == "Custom drive"
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("during_preparation", [False, True])
def test_disabling_appearance_invalidates_pending_rename(
    tmp_path: Path, during_preparation: bool
) -> None:
    device = bare_device(tmp_path)
    try:
        original = {name: (device.root / name).read_bytes() for name in _COMPANIONS}
        label = device.platform.inspect(device.root).volume.label
        desired = replace(device.active.library, device_name="Renamed")

        def progress(event: WriteProgress) -> None:
            if during_preparation and event.phase == "resources.capture":
                device.coordinator.set_volume_presentation_enabled(False)

        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(desired, device.active, 1, 1), progress, Event()
        )
        assert review.result.prepared is not None, review.result.issues
        device.coordinator.set_volume_presentation_enabled(False)
        # Re-enabling must not revive the retired review either.
        device.coordinator.set_volume_presentation_enabled(True)
        device.coordinator.set_volume_presentation_enabled(False)
        rejected = device.save(review)
        assert rejected.active is None
        assert any(issue.code == "save.stale" for issue in rejected.issues)
        device.assert_original()
        saved = device.save(device.prepare(desired))
        assert saved.active is not None, saved.issues
        assert saved.active.library.device_name == "Renamed"
        assert {
            name: (device.root / name).read_bytes() for name in _COMPANIONS
        } == original
        assert device.platform.inspect(device.root).volume.label == label
    finally:
        device.coordinator.close()


def test_setting_change_does_not_block_on_an_executing_save(tmp_path: Path) -> None:
    device = bare_device(tmp_path)
    switched = Event()

    def disable() -> None:
        device.coordinator.set_volume_presentation_enabled(False)
        switched.set()

    setting_thread = Thread(target=disable)

    def progress(event: WriteProgress) -> None:
        if event.phase == "save.storage_transaction":
            setting_thread.start()
            assert switched.wait(2), "Changing settings blocked on device I/O"

    try:
        review = device.prepare(replace(device.active.library, device_name="Renamed"))
        saved = device.save(review, progress)
        assert saved.active is not None, saved.issues
        assert not device.coordinator.volume_presentation_enabled
        assert (
            _ini(device.root / "autorun.inf", "utf-16")["AutoRun"]["label"] == "Renamed"
        )
        assert device.platform.inspect(device.root).volume.label == "Renamed"
        saved_again = device.save(
            device.prepare(replace(device.active.library, device_name="Next name"))
        )
        assert saved_again.active is not None, saved_again.issues
        assert (
            _ini(device.root / "autorun.inf", "utf-16")["AutoRun"]["label"] == "Renamed"
        )
        assert device.platform.inspect(device.root).volume.label == "Renamed"
    finally:
        if setting_thread.ident is not None:
            setting_thread.join(5)
        device.coordinator.close()


def test_reenabling_appearance_provisions_on_next_selection(tmp_path: Path) -> None:
    device = bare_device(tmp_path, volume_presentation_enabled=False)
    try:
        device.coordinator.set_volume_presentation_enabled(True)
        assert all(not (device.root / name).exists() for name in _COMPANIONS)
        device.coordinator.select_device(device.active.candidate.id)
        assert all((device.root / name).is_file() for name in _COMPANIONS)
    finally:
        device.coordinator.close()


def test_disabled_read_only_selection_does_not_report_appearance_warning(
    tmp_path: Path,
) -> None:
    device = bare_device(tmp_path, volume_presentation_enabled=False)
    try:
        device.coordinator.close()
        device.platform.add_volume(device.root, writable=False)
        candidate = device.coordinator.discover_devices().candidates[0]
        active = device.coordinator.select_device(candidate.id)
        assert not any(
            issue.code is DeviceCandidateIssueCode.VOLUME_PRESENTATION_INCOMPLETE
            for issue in active.candidate.issues
        )
        assert all(not (device.root / name).exists() for name in _COMPANIONS)
    finally:
        device.coordinator.close()


def _ini(path: Path, encoding: str = "utf-8") -> ConfigParser:
    parser = ConfigParser(interpolation=None)
    parser.read_string(path.read_text(encoding=encoding))
    return parser


def test_selection_provisions_model_icons_and_rename_commits_names(
    tmp_path: Path,
) -> None:
    device = bare_device(tmp_path)
    try:
        root = device.root
        for relative, format_name in (
            ("iPod_Control/iOpenPod/volume-icon.png", "PNG"),
            ("iPod_Control/iOpenPod/volume-icon.ico", "ICO"),
            (".VolumeIcon.icns", "ICNS"),
        ):
            with Image.open(BytesIO(root.joinpath(relative).read_bytes())) as icon:
                assert icon.format == format_name
                assert icon.width == icon.height
                assert icon.convert("RGBA").getchannel("A").getextrema()[0] == 0
        old_companion = (root / "autorun.inf").read_bytes()
        desired = replace(device.active.library, device_name="Zoë's iPod")
        review = device.prepare(desired)
        assert review.result.prepared is not None, review.result.issues
        assert (root / "autorun.inf").read_bytes() == old_companion
        assert {
            "autorun.inf",
            ".xdg-volume-info",
            ".directory",
            "iPod_Control/iTunes/iTunesDB",
        } <= {change.path for change in review.file_changes}
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert _ini(root / "autorun.inf", "utf-16")["AutoRun"]["label"] == "Zoë's iPod"
        assert _ini(root / ".xdg-volume-info")["Volume Info"]["Name"] == "Zoë's\\siPod"
        assert _ini(root / ".directory")["Desktop Entry"]["Icon"].startswith("./")
        assert device.platform.inspect(root).volume.label == "Zoë's iPod"
        with device.storage.open_session(
            device.storage.discover().volumes[0]
        ) as session:
            assert not volume_presentation.capture(
                session, desired.device_name, device.active.profile.product_image
            ).writes
    finally:
        device.coordinator.close()


def test_external_companion_edit_invalidates_review_before_database_publication(
    tmp_path: Path,
) -> None:
    device = bare_device(tmp_path)
    try:
        database = device.root / "iPod_Control/iTunes/iTunesDB"
        original = database.read_bytes()
        review = device.prepare(replace(device.active.library, device_name="New name"))
        assert review.result.prepared is not None, review.result.issues
        (device.root / ".directory").write_text(
            "[Desktop Entry]\nIcon=external\n", encoding="utf-8"
        )
        result = device.save(review)
        assert result.active is None
        assert database.read_bytes() == original
        assert _ini(device.root / ".directory")["Desktop Entry"]["Icon"] == "external"
    finally:
        device.coordinator.close()


def test_native_failure_does_not_undo_saved_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = bare_device(tmp_path)

    def refused(*_args: object) -> str:
        raise StorageOperationError("Native label permission denied")

    monkeypatch.setattr(device.platform, "set_volume_label", refused)
    try:
        result = device.save(
            device.prepare(replace(device.active.library, device_name="Saved"))
        )
        assert result.active is not None
        assert result.active.library.device_name == "Saved"
        assert (
            _ini(device.root / "autorun.inf", "utf-16")["AutoRun"]["label"] == "Saved"
        )
        assert any("permission denied" in issue.detail for issue in result.issues)
    finally:
        device.coordinator.close()


def test_companion_merge_preserves_other_settings_and_removes_stale_localized_names(
    tmp_path: Path,
) -> None:
    (tmp_path / "AUTORUN.INF").write_text(
        "; Keep me\n[AutoRun]\nlabel=Old\nicon=old.ico\n[Other]\nvalue=untouched\n",
        encoding="utf-8",
    )
    (tmp_path / ".directory").write_text(
        "[Desktop Entry]\nName=Old\nName[de]=Alt\nIcon=old\n[Dolphin]\nViewMode=2\n",
        encoding="utf-8",
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        captured = volume_presentation.capture(
            session, "名\\x\n[AutoRun]\nopen=bad", "iPodGeneric.png"
        )
        session.execute_transaction(StorageTransaction(captured.writes))
        assert not volume_presentation.capture(
            session, "名\\x\n[AutoRun]\nopen=bad", "iPodGeneric.png"
        ).writes
    autorun = _ini(tmp_path / "AUTORUN.INF", "utf-16")
    assert "open" not in autorun["AutoRun"]
    assert autorun["Other"]["value"] == "untouched"
    assert "; Keep me" in (tmp_path / "AUTORUN.INF").read_text(encoding="utf-16")
    kde = _ini(tmp_path / ".directory")
    assert "Name[de]" not in kde["Desktop Entry"]
    assert kde["Dolphin"]["ViewMode"] == "2"
    assert (
        _ini(tmp_path / ".xdg-volume-info")["Volume Info"]["IconFile"]
        == "iPod_Control/iOpenPod/volume-icon.png"
    )


def test_capture_rejects_directory_at_companion_path_without_mutation(
    tmp_path: Path,
) -> None:
    (tmp_path / "autorun.inf").mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    with (
        storage.open_session(storage.discover().volumes[0]) as session,
        pytest.raises(StorageOperationError),
    ):
        volume_presentation.capture(session, "Name", "iPodGeneric.png")
    assert not (tmp_path / ".VolumeIcon.icns").exists()


def test_missing_file_created_after_capture_blocks_transaction(tmp_path: Path) -> None:
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform)
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        capture = volume_presentation.capture(session, "Name", "iPodGeneric.png")
        (tmp_path / "autorun.inf").write_bytes(b"external")
        with pytest.raises(FilePreconditionError):
            session.validate_transaction(StorageTransaction(capture.writes))
    assert not (tmp_path / ".VolumeIcon.icns").exists()


def test_recovery_restores_companion_bytes_and_database(tmp_path: Path) -> None:
    device = bare_device(tmp_path)
    original = (device.root / "autorun.inf").read_bytes()
    try:
        result = device.save(
            device.prepare(replace(device.active.library, device_name="New name"))
        )
        assert result.active is not None
        device.restore(result.recovery_path)
        assert (device.root / "autorun.inf").read_bytes() == original
    finally:
        device.coordinator.close()


def test_selection_is_idempotent_and_cleans_its_completed_journal(
    tmp_path: Path,
) -> None:
    device = bare_device(tmp_path)
    try:
        root = device.root
        assert not tuple(root.glob(".iopenpod-recovery/*/transaction.json"))
        before = {
            path: path.stat().st_mtime_ns
            for path in root.rglob("*")
            if path.is_file() and "Device" not in path.relative_to(root).parts
        }
        candidate_id = device.active.candidate.id
        device.coordinator.discover_devices()
        device.coordinator.select_device(candidate_id)
        assert {
            path: path.stat().st_mtime_ns
            for path in root.rglob("*")
            if path.is_file() and "Device" not in path.relative_to(root).parts
        } == before
    finally:
        device.coordinator.close()


def test_read_only_selection_reports_presentation_without_touching_files(
    tmp_path: Path,
) -> None:
    device = bare_device(tmp_path)
    try:
        device.coordinator.close()
        before = {
            path: path.read_bytes() for path in device.root.rglob("*") if path.is_file()
        }
        device.platform.add_volume(device.root, writable=False)
        candidate = device.coordinator.discover_devices().candidates[0]
        active = device.coordinator.select_device(candidate.id)
        assert any(
            issue.code is DeviceCandidateIssueCode.VOLUME_PRESENTATION_INCOMPLETE
            for issue in active.candidate.issues
        )
        assert {
            path: path.read_bytes() for path in device.root.rglob("*") if path.is_file()
        } == before
    finally:
        device.coordinator.close()


def test_disconnect_during_native_presentation_never_publishes_an_active_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = bare_device(tmp_path)
    candidate_id = device.active.candidate.id

    def disconnect(*_args: object) -> None:
        device.platform.disconnect(device.root)

    monkeypatch.setattr(device.platform, "enable_volume_icon", disconnect)
    try:
        with pytest.raises(DeviceAccessError):
            device.coordinator.select_device(candidate_id)
        assert device.coordinator.active_ipod is None
    finally:
        device.coordinator.close()


def test_interrupted_presentation_requires_recovery_before_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = bare_device(tmp_path)
    candidate_id = device.active.candidate.id
    for name in ("autorun.inf", ".xdg-volume-info", ".directory"):
        (device.root / name).unlink()
    original_replace = os.replace

    def fail_replace(source: str | Path, destination: str | Path) -> None:
        if Path(destination) == device.root / ".directory":
            raise OSError("Simulated interruption during companion publication")
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_replace)
    try:
        with pytest.raises(SyncRecoveryRequiredError) as raised:
            device.coordinator.select_device(candidate_id)
        assert raised.value.recovery_path
        assert device.coordinator.active_ipod is None
        assert (device.root / raised.value.recovery_path).is_file()
        device.assert_original()
    finally:
        device.coordinator.close()
