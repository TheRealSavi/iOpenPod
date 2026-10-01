"""Scrobbling runs before a real Sync transaction, including removal-only Sync."""

from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_scrobbling import (
    ACCOUNTS,
    NOW,
    ClientStub,
    MemoryCredentials,
    track,
)
from tests.iOpenPod.app.test_sync_execution import (
    _ipod,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.scrobbling.queue import QueueState, ScrobbleQueue, capture
from iOpenPod.app.scrobbling.service import ScrobbleService
from iOpenPod.app.sync_execution import (
    SyncExecutionRequest,
    SyncExecutionStatus,
    SyncExecutor,
    SyncOptions,
)
from iOpenPod.app.sync_plan import prepare_sync_plan
from iPodDB.library import IssueSeverity, LibrarySnapshot
from storage import AtomicHostFile


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("outcome", ["offline", "accepted", "filtered", "adjusted"])
def test_sync_submits_before_removal_and_keeps_failed_listens(
    tmp_path: Path, enabled: bool, outcome: str
) -> None:
    device = build_device(tmp_path)
    try:
        active = device.active
        volume = device.coordinator.active_volume_id
        assert volume is not None
        queue = ScrobbleQueue(AtomicHostFile(tmp_path / "scrobbles.json"))
        state = QueueState()
        song = track(last_played=NOW - 30 * 86400) if outcome == "adjusted" else track()
        capture(state, volume.value, LibrarySnapshot((song,)), ACCOUNTS[:1], NOW)
        queue.save(state)
        client = ClientStub()
        client.error = outcome == "offline"
        client.partial = outcome == "filtered"

        def check_before_publication() -> None:
            assert device.active is active
            assert (
                device.root / "iPod_Control/iTunes/iTunesDB"
            ).read_bytes() == device.original["iPod_Control/iTunes/iTunesDB"]

        client.after_submit = check_before_publication
        scrobbler = ScrobbleService(
            device.coordinator,
            queue,
            MemoryCredentials(),
            clients=lambda _: client,
            clock=lambda: NOW,
        )
        host = HostMediaLibrary(LibrarySnapshot(), (), (), HostMediaCacheStats())
        ipod = _ipod(device)
        request = SyncExecutionRequest(
            prepare_sync_plan(host, ipod, active.library),
            host,
            ipod,
            active,
            1,
            1,
            options=SyncOptions(scrobble=enabled),
            reconcile_playlists=False,
            scrobble_accounts=ACCOUNTS[:1],
        )
        phases: list[str] = []
        result = SyncExecutor(device.coordinator, scrobbler=scrobbler).execute(
            request, lambda event: phases.append(event.phase), Event()
        )
        assert result.status in (
            SyncExecutionStatus.SUCCESS,
            SyncExecutionStatus.PARTIAL,
        )
        assert result.active is not None and not result.active.library.tracks
        assert len(client.calls) == int(enabled)
        expected_pending = (
            2 if outcome == "offline" or not enabled else int(client.partial)
        )
        assert len(queue.load().pending) == expected_pending
        if enabled:
            assert phases.index("sync.scrobble") < phases.index(
                "save.storage.publishing"
            )
        if enabled and outcome == "offline":
            assert any(issue.code == "sync.scrobble_pending" for issue in result.issues)
        if enabled and outcome == "filtered":
            issue = next(
                issue
                for issue in result.issues
                if issue.code == "sync.scrobble_pending"
            )
            assert "1 accepted, 1 pending" in issue.message
            assert "Timestamp too old (code 3): 1 listen" in issue.detail
            assert 'Artist: "Artist"; Title: "Song"; Album: "Album"' in issue.detail
            assert "estimated playback start (UTC)" in issue.detail
            assert "supplied no further explanation" in issue.detail
        if enabled and outcome == "adjusted":
            notice = next(
                issue
                for issue in result.issues
                if issue.code == "sync.scrobble_dates_adjusted"
            )
            assert notice.severity is IssueSeverity.INFO
            assert "2 dates adjusted" in notice.message
            assert "Original estimated playback start (UTC)" in notice.detail
            assert "Last.fm submission start (UTC)" in notice.detail
            assert not any(
                issue.code == "sync.scrobble_pending" for issue in result.issues
            )
            assert [listen.timestamp for listen in client.calls[0]] == [NOW - 1, NOW]
    finally:
        device.coordinator.close()


def test_sync_stops_before_mutation_when_outbox_cannot_be_loaded(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        path = tmp_path / "scrobbles.json"
        path.write_text("invalid")
        queue = ScrobbleQueue(AtomicHostFile(path))
        client = ClientStub()
        scrobbler = ScrobbleService(
            device.coordinator, queue, MemoryCredentials(), clients=lambda _: client
        )
        host = HostMediaLibrary(LibrarySnapshot(), (), (), HostMediaCacheStats())
        ipod = _ipod(device)
        request = SyncExecutionRequest(
            prepare_sync_plan(host, ipod, device.active.library),
            host,
            ipod,
            device.active,
            1,
            1,
            scrobble_accounts=ACCOUNTS,
        )
        result = SyncExecutor(device.coordinator, scrobbler=scrobbler).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.FAILED
        assert result.issues[0].code == "sync.scrobble_capture_failed"
        assert not client.calls
        device.assert_original()
        # Turning off this optional step leaves ordinary Sync usable.
        disabled = replace(request, options=SyncOptions(scrobble=False))
        result = SyncExecutor(device.coordinator, scrobbler=scrobbler).execute(
            disabled, lambda _: None, Event()
        )
        assert result.status in (
            SyncExecutionStatus.SUCCESS,
            SyncExecutionStatus.PARTIAL,
        )
    finally:
        device.coordinator.close()
