"""Reviewed Sync regenerates missing cover pixels without global cover deferral."""

import hashlib
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from PIL import Image
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_sync_execution import (
    _AvailableTools,  # pyright: ignore[reportPrivateUsage]
    _Executor,  # pyright: ignore[reportPrivateUsage]
    _host,  # pyright: ignore[reportPrivateUsage]
    _ipod,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.host_media_library import HostArtworkKind, HostMediaArtworkSource
from iOpenPod.app.library_sync_helper import SyncDetails
from iOpenPod.app.library_write import PreparationCancelledError
from iOpenPod.app.sync_execution import SyncExecutionRequest, SyncExecutionStatus
from iOpenPod.app.sync_plan import SyncPlan, SyncPlanAction, prepare_sync_plan
from storage import (
    DevicePath,
    FileFingerprint,
    FilesystemSession,
    HostPath,
    StorageOperationError,
)
from storage.content_workspace import ContentWorkspace, StagedContent
from storage.host_input import LocalHostFile


@pytest.mark.parametrize(
    "damage", ["missing", "truncated", "unreadable", "cancelled", "disconnect"]
)
def test_sync_regenerates_all_supplied_covers_to_fresh_verified_shards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    device = build_device(tmp_path)
    try:
        original = device.active.library
        thumbnail = next((device.root / "iPod_Control/Artwork").glob("*.ithmb"))
        if damage == "missing":
            thumbnail.unlink()
        elif damage == "truncated":
            thumbnail.write_bytes(b"damaged")
        else:
            native_capture = ContentWorkspace.capture_device_snapshot

            def capture(
                self: ContentWorkspace, session: FilesystemSession, path: DevicePath
            ) -> tuple[bytes | StagedContent, FileFingerprint]:
                if path.name == thumbnail.name:
                    if damage == "cancelled":
                        raise PreparationCancelledError
                    if damage == "disconnect":
                        device.platform.disconnect(device.root)
                        session.stat(path)
                        pytest.fail("Disconnected session remained usable")
                    raise StorageOperationError("Thumbnail is unreadable")
                return native_capture(self, session, path)

            monkeypatch.setattr(ContentWorkspace, "capture_device_snapshot", capture)
        retained = thumbnail.read_bytes() if thumbnail.exists() else None
        host = _host(tmp_path, "First replacement", "Second replacement")
        cover_path = tmp_path / "cover.png"
        Image.new("RGB", (64, 64), "blue").save(cover_path)
        observed = LocalHostFile.observe(HostPath(cover_path))
        host = replace(
            host,
            snapshot=replace(
                host.snapshot,
                tracks=tuple(
                    replace(track, artwork_id=123) for track in host.snapshot.tracks
                ),
            ),
            artwork_sources=(
                HostMediaArtworkSource(
                    123,
                    HostArtworkKind.FOLDER,
                    observed.path,
                    observed.size_bytes,
                    observed.modified_ns,
                    hashlib.sha256(cover_path.read_bytes()).hexdigest(),
                ),
            ),
        )
        ipod = _ipod(device)
        ipod = replace(
            ipod,
            tracks=tuple(
                replace(
                    track,
                    sync=SyncDetails(
                        "2026-01-01T00:00:00+00:00",
                        str(source.path),
                        source.size_bytes - 1,
                        source.modified_ns - 1,
                        "m4a",
                        "aac",
                        False,
                    ),
                )
                for track, source in zip(ipod.tracks, host.sources, strict=True)
            ),
        )
        comparison = prepare_sync_plan(host, ipod, original)
        plan = SyncPlan(
            tuple(
                item
                for item in comparison.items
                if item.action is SyncPlanAction.UPDATE
            )
        )
        assert len(plan.items) == 2
        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            SyncExecutionRequest(plan, host, ipod, device.active, 1, 1),
            lambda _: None,
            Event(),
        )
        if damage in {"cancelled", "disconnect"}:
            assert result.status is (
                SyncExecutionStatus.CANCELLED
                if damage == "cancelled"
                else SyncExecutionStatus.FAILED
            )
            device.assert_original()
            return
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        assert not any(issue.code == "sync.artwork_deferred" for issue in result.issues)
        assert {track.artwork_id for track in result.active.library.tracks}.isdisjoint(
            {track.artwork_id for track in original.tracks}
        )
        assert (device.root / "iPod_Control/Artwork/F1055_2.ithmb").is_file()
        if retained is None:
            assert not thumbnail.exists()
        else:
            assert thumbnail.read_bytes() == retained
    finally:
        device.coordinator.close()
