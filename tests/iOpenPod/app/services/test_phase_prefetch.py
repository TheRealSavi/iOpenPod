"""Overlap retained device input copies with ordered Phase analysis."""

import plistlib
import time
from collections.abc import Callable
from dataclasses import replace
from hashlib import sha256
from os import utime
from pathlib import Path
from threading import Event, get_ident

import pytest
from tests.iOpenPod.app.phase_test_support import StubPhaseAnalysis

from iOpenPod.app import phase_inputs
from iOpenPod.app.services.phase import INDEX_PATH, MANIFEST_PATH, prepare_phase
from iPodDB.games import (
    PhaseChart,
    PhaseTrack,
    PhaseTransient,
    build_phase_analysis,
    phase_analysis_relative_path,
)
from iPodDB.library import LibrarySnapshot, Playlist, Track, playlist_entries
from iPodDB.library.models import IPodTrackDetails, TrackMetadata
from storage import (
    AccessMode,
    CopyResult,
    DevicePath,
    FileContent,
    FileFingerprint,
    FilePreconditionError,
    FilesystemSession,
    HostPath,
    SessionInvalidatedError,
    Storage,
    StorageTransaction,
    TransactionWrite,
)
from storage.testing import VirtualStoragePlatform


def device(root: Path, count: int) -> tuple[Storage, LibrarySnapshot]:
    manifest = root / str(MANIFEST_PATH)
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(
        plistlib.dumps({"Name": "Phase", "Version": "1.0", "GUID": "phase"})
    )
    tracks = tuple(
        Track(
            index,
            str(index),
            "Artist",
            "Album",
            30_000,
            ipod=IPodTrackDetails(db_track_id=0x8000000000000000 + index),
            metadata=TrackMetadata(location=f"iPod_Control/Music/F00/{index}.m4a"),
        )
        for index in range(1, count + 1)
    )
    for track in tracks:
        path = root / track.metadata.location
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"compressed audio {track.track_id}".encode())
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    desired = LibrarySnapshot(
        tracks,
        (
            Playlist(
                101,
                "Phase",
                entries=playlist_entries(range(1, count + 1)),
                is_phase=True,
            ),
        ),
    )
    return Storage(platform), desired


class Captures:
    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        before: Callable[[DevicePath, Callable[[int], None] | None], None] = (
            lambda _source, _progress: None
        ),
        after: Callable[[DevicePath], None] = lambda _source: None,
    ) -> None:
        self.started: list[DevicePath] = []
        self.completed: list[DevicePath] = []
        self.paths: list[Path] = []
        self.peak_retained = 0
        original_copy = FilesystemSession.copy_to_host

        def copy_to_host(
            session: FilesystemSession,
            source: DevicePath,
            destination: HostPath,
            *,
            prepare_staged: Callable[[HostPath], None] | None = None,
            progress: Callable[[int], None] | None = None,
        ) -> CopyResult:
            self.started.append(source)
            self.paths.append(Path(destination))
            self.peak_retained = max(
                self.peak_retained, sum(path.exists() for path in self.paths) + 1
            )
            before(source, progress)
            result = original_copy(
                session,
                source,
                destination,
                prepare_staged=prepare_staged,
                progress=progress,
            )
            self.completed.append(source)
            after(source)
            return result

        monkeypatch.setattr(FilesystemSession, "copy_to_host", copy_to_host)

    def assert_cleaned(self) -> None:
        assert self.paths
        assert all(not path.parent.exists() for path in self.paths)


class ReadingAnalysis(StubPhaseAnalysis):
    def __init__(
        self,
        *,
        before: Callable[[int, Callable[[], None]], None] = (
            lambda _index, _checkpoint: None
        ),
    ) -> None:
        super().__init__()
        self.before = before
        self.payloads: list[bytes] = []
        self.outputs: list[bytes] = []
        self.closed: list[bool] = []

    def analyze(
        self,
        source: DevicePath | HostPath,
        *,
        input_suffix: str,
        length_ms: int,
        session: FilesystemSession,
        checkpoint: Callable[[], None],
    ) -> bytes:
        checkpoint()
        self.before(len(self.calls), checkpoint)
        assert isinstance(source, HostPath)
        self.calls.append(source)
        payload = Path(source).read_bytes()
        self.payloads.append(payload)
        track_id = int(payload.split()[-1])
        chart = build_phase_analysis(
            PhaseChart((PhaseTransient(track_id << 16, track_id, 1, 2),))
        )
        self.outputs.append(chart)
        return chart

    def close(self) -> None:
        self.closed.append(True)


def test_next_device_input_is_captured_while_current_track_is_analyzed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, desired = device(tmp_path, 2)
    analysis_started, next_capture_started = Event(), Event()
    callback_threads: list[int] = []
    captured_paths: list[Path] = []
    original_copy = FilesystemSession.copy_to_host

    def copy_to_host(
        session: FilesystemSession,
        source: DevicePath,
        destination: HostPath,
        *,
        prepare_staged: Callable[[HostPath], None] | None = None,
        progress: Callable[[int], None] | None = None,
    ) -> CopyResult:
        captured_paths.append(Path(destination))
        if source.name == "2.m4a":
            assert analysis_started.wait(3), "Copying ahead delayed the first analysis"
            next_capture_started.set()
        return original_copy(
            session,
            source,
            destination,
            prepare_staged=prepare_staged,
            progress=progress,
        )

    class BlockingAnalysis(StubPhaseAnalysis):
        def analyze(
            self,
            source: DevicePath | HostPath,
            *,
            input_suffix: str,
            length_ms: int,
            session: FilesystemSession,
            checkpoint: Callable[[], None],
        ) -> bytes:
            if not self.calls:
                analysis_started.set()
                assert next_capture_started.wait(3), (
                    "The next device input was not copied during current analysis"
                )
            return super().analyze(
                source,
                input_suffix=input_suffix,
                length_ms=length_ms,
                session=session,
                checkpoint=checkpoint,
            )

    monkeypatch.setattr(FilesystemSession, "copy_to_host", copy_to_host)
    analyzer = BlockingAnalysis()
    with storage.open_session(storage.discover().volumes[0]) as session:
        publication = prepare_phase(
            session,
            LibrarySnapshot(),
            desired,
            analyzer=analyzer,
            checkpoint=lambda: callback_threads.append(get_ident()),
            progress=lambda _done, _total, _title: callback_threads.append(get_ident()),
        )
    assert publication.writes and len(analyzer.calls) == 2
    assert all(isinstance(source, HostPath) for source in analyzer.calls)
    assert set(callback_threads) == {get_ident()}
    assert len(captured_paths) == 2 and all(
        not path.exists() for path in captured_paths
    )


def test_prefetch_preserves_fifo_payloads_and_publishes_exact_analyzer_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, desired = device(tmp_path, 3)
    desired = replace(
        desired,
        playlists=(
            replace(desired.playlists[0], entries=playlist_entries((3, 1, 3, 2))),
        ),
    )
    captures = Captures(monkeypatch)
    analyzer = ReadingAnalysis()
    with storage.open_session(storage.discover().volumes[0]) as session:
        publication = prepare_phase(
            session, LibrarySnapshot(), desired, analyzer=analyzer
        )
        for track_id, output in zip((3, 1, 2), analyzer.outputs, strict=True):
            record = PhaseTrack(0x8000000000000000 + track_id, 7, len(output))
            path = DevicePath(
                f"iPod_Control/GameData_RW/1D000/{phase_analysis_relative_path(record)}"
            )
            assert (
                next(write.source for write in publication.writes if write.path == path)
                == output
            )
            source = DevicePath(desired.tracks[track_id - 1].metadata.location)
            assert next(
                item.fingerprint for item in publication.files if item.path == source
            ) == session.fingerprint(source)
    assert analyzer.payloads == [
        b"compressed audio 3",
        b"compressed audio 1",
        b"compressed audio 2",
    ]
    assert [source.name for source in captures.started] == ["3.m4a", "1.m4a", "2.m4a"]
    assert analyzer.closed == [True]
    captures.assert_cleaned()
    assert not (tmp_path / str(INDEX_PATH)).exists()


def test_unrelated_playlist_save_does_not_read_phase_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, desired = device(tmp_path, 2)
    analyzer = ReadingAnalysis()
    with storage.open_session(storage.discover().volumes[0]) as session:
        publication = prepare_phase(
            session, LibrarySnapshot(), desired, analyzer=analyzer
        )
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        changed = {write.path for write in publication.writes}
        session.execute_transaction(
            StorageTransaction(
                publication.writes,
                (),
                tuple(item for item in publication.files if item.path not in changed),
            )
        )
        captures = Captures(monkeypatch)
        fingerprints: list[DevicePath] = []
        original_fingerprint = FilesystemSession.fingerprint

        def fingerprint(
            current: FilesystemSession,
            path: DevicePath,
            *,
            checkpoint: Callable[[], None] | None = None,
        ) -> FileFingerprint:
            fingerprints.append(path)
            return original_fingerprint(current, path, checkpoint=checkpoint)

        monkeypatch.setattr(FilesystemSession, "fingerprint", fingerprint)
        unrelated = replace(
            desired, playlists=(*desired.playlists, Playlist(102, "Unrelated"))
        )
        again = prepare_phase(session, desired, unrelated, analyzer=analyzer)
        assert len(analyzer.calls) == 2
        assert {
            "host_copies": len(captures.started),
            "audio_hashes": len(fingerprints),
        } == {"host_copies": 0, "audio_hashes": 0}
        for track in desired.tracks:
            path = DevicePath(track.metadata.location)
            assert all(item.path != path for item in again.files)


@pytest.mark.parametrize("change", ["audio", "chart", "missing_chart", "duration"])
def test_cached_playlist_reanalyzes_changed_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    storage, desired = device(tmp_path, 2)
    analyzer = StubPhaseAnalysis()
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        publication = prepare_phase(
            session, LibrarySnapshot(), desired, analyzer=analyzer
        )
        changed = {write.path for write in publication.writes}
        session.execute_transaction(
            StorageTransaction(
                publication.writes,
                (),
                tuple(item for item in publication.files if item.path not in changed),
            )
        )
        if change == "audio":
            path = tmp_path / desired.tracks[0].metadata.location
            original_stat = path.stat()
            payload = path.read_bytes()
            path.write_bytes(payload[:-1] + b"9")
            utime(
                path,
                ns=(
                    original_stat.st_atime_ns,
                    original_stat.st_mtime_ns + 2_000_000_000,
                ),
            )
        elif change in ("chart", "missing_chart"):
            path = tmp_path / str(publication.writes[0].path)
            if change == "missing_chart":
                path.unlink()
            else:
                payload = path.read_bytes()
                path.write_bytes(payload[:-1] + bytes([payload[-1] ^ 1]))
        else:
            desired = replace(
                desired,
                tracks=(
                    replace(desired.tracks[0], length_ms=31_000),
                    desired.tracks[1],
                ),
            )
        captures = Captures(monkeypatch)
        again = prepare_phase(session, desired, desired, analyzer=analyzer)
        assert len(analyzer.calls) == 3
        assert again.writes
        assert desired.tracks[1].metadata.location not in {
            str(path) for path in captures.started
        }
        assert len(captures.started) == (1 if change in ("audio", "duration") else 0)


def test_new_analysis_retains_content_checked_transaction_dependency(
    tmp_path: Path,
) -> None:
    storage, desired = device(tmp_path, 1)
    analyzer = StubPhaseAnalysis()
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        publication = prepare_phase(
            session, LibrarySnapshot(), desired, analyzer=analyzer
        )
        path = tmp_path / desired.tracks[0].metadata.location
        observed = path.stat()
        payload = path.read_bytes()
        path.write_bytes(payload[:-1] + b"9")
        utime(path, ns=(observed.st_atime_ns, observed.st_mtime_ns))
        write = TransactionWrite(
            DevicePath("saved-library"),
            b"new",
            FileContent(3, sha256(b"new").hexdigest()),
        )
        with pytest.raises(FilePreconditionError):
            session.execute_transaction(
                StorageTransaction((write,), (), publication.files)
            )
        assert not (tmp_path / "saved-library").exists()


def test_prefetch_retains_only_current_and_five_upcoming_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, desired = device(tmp_path, 8)
    six_captured, seventh_started = Event(), Event()

    def before_copy(
        source: DevicePath, _progress: Callable[[int], None] | None
    ) -> None:
        if source.name == "7.m4a":
            seventh_started.set()

    def after_copy(source: DevicePath) -> None:
        if source.name == "6.m4a":
            six_captured.set()

    def before_analysis(index: int, _checkpoint: Callable[[], None]) -> None:
        if index == 0:
            assert six_captured.wait(3), "Five upcoming inputs were not captured"
            assert not seventh_started.wait(0.05), (
                "Prefetch exceeded five upcoming inputs"
            )

    captures = Captures(monkeypatch, before=before_copy, after=after_copy)
    analyzer = ReadingAnalysis(before=before_analysis)
    with storage.open_session(storage.discover().volumes[0]) as session:
        prepare_phase(session, LibrarySnapshot(), desired, analyzer=analyzer)
    assert len(analyzer.calls) == 8
    assert captures.peak_retained == 6
    captures.assert_cleaned()


def test_host_analysis_allows_only_five_waiting_device_captures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, desired = device(tmp_path / "device", 8)
    incoming_path = tmp_path / "prepared.m4a"
    payload = b"incoming compressed audio 1"
    incoming_path.write_bytes(payload)
    incoming = TransactionWrite(
        DevicePath(desired.tracks[0].metadata.location),
        HostPath(incoming_path),
        FileContent(len(payload), sha256(payload).hexdigest()),
    )
    five_ready, sixth_started, six_ready, seventh_started = (
        Event(),
        Event(),
        Event(),
        Event(),
    )

    def before_copy(
        source: DevicePath, _progress: Callable[[int], None] | None
    ) -> None:
        if source.name == "7.m4a":
            sixth_started.set()
        elif source.name == "8.m4a":
            seventh_started.set()

    def after_copy(source: DevicePath) -> None:
        if source.name == "6.m4a":
            five_ready.set()
        elif source.name == "7.m4a":
            six_ready.set()

    def before_analysis(index: int, _checkpoint: Callable[[], None]) -> None:
        if index == 0:
            assert five_ready.wait(3)
            assert not sixth_started.wait(0.05), (
                "Host analysis allowed more than five waiting device captures"
            )
        elif index == 1:
            assert six_ready.wait(3)
            assert not seventh_started.wait(0.05), (
                "Device analysis exceeded its current capture plus five waiting"
            )

    captures = Captures(monkeypatch, before=before_copy, after=after_copy)
    analyzer = ReadingAnalysis(before=before_analysis)
    with storage.open_session(storage.discover().volumes[0]) as session:
        prepare_phase(
            session,
            LibrarySnapshot(),
            desired,
            analyzer=analyzer,
            media_writes=(incoming,),
        )
    assert analyzer.calls[0] == HostPath(incoming_path)
    assert len(analyzer.calls) == 8
    assert [source.name for source in captures.started] == [
        f"{index}.m4a" for index in range(2, 9)
    ]
    assert captures.peak_retained == 6
    captures.assert_cleaned()


@pytest.mark.parametrize("failure_kind", ["cancel", "analysis"])
def test_failure_stops_active_capture_and_removes_all_private_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_kind: str
) -> None:
    storage, desired = device(tmp_path, 8)
    next_copy_started, next_copy_stopped = Event(), Event()
    failure = (
        InterruptedError("cancelled Phase preparation")
        if failure_kind == "cancel"
        else ValueError("analysis failed")
    )
    callback_threads: list[int] = []

    def before_copy(source: DevicePath, progress: Callable[[int], None] | None) -> None:
        if source.name != "2.m4a":
            return
        next_copy_started.set()
        assert progress is not None
        deadline = time.monotonic() + 3
        try:
            while time.monotonic() < deadline:
                progress(0)
                time.sleep(0.005)
            pytest.fail("The in-flight capture did not stop after analysis failed")
        finally:
            next_copy_stopped.set()

    def checkpoint() -> None:
        callback_threads.append(get_ident())
        if failure_kind == "cancel" and next_copy_started.is_set():
            raise failure

    def before_analysis(_index: int, current_checkpoint: Callable[[], None]) -> None:
        assert next_copy_started.wait(3)
        if failure_kind == "cancel":
            current_checkpoint()
        raise failure

    captures = Captures(monkeypatch, before=before_copy)
    analyzer = ReadingAnalysis(before=before_analysis)
    with (
        storage.open_session(storage.discover().volumes[0]) as session,
        pytest.raises(type(failure)) as caught,
    ):
        prepare_phase(
            session,
            LibrarySnapshot(),
            desired,
            analyzer=analyzer,
            checkpoint=checkpoint,
        )
    assert caught.value is failure
    assert next_copy_stopped.is_set()
    assert len(captures.started) == 2
    assert set(callback_threads) == {get_ident()}
    assert analyzer.closed == [True]
    captures.assert_cleaned()
    assert not (tmp_path / str(INDEX_PATH)).exists()


@pytest.mark.parametrize("changed_track", [1, 2])
def test_prefetched_device_audio_changes_are_detected_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_track: int
) -> None:
    storage, desired = device(tmp_path, 2)
    next_captured = Event()

    def after_copy(source: DevicePath) -> None:
        if source.name == "2.m4a":
            next_captured.set()

    def before_analysis(index: int, _checkpoint: Callable[[], None]) -> None:
        if index == 0:
            assert next_captured.wait(3)
            (
                tmp_path / desired.tracks[changed_track - 1].metadata.location
            ).write_bytes(b"externally changed audio")

    captures = Captures(monkeypatch, after=after_copy)
    analyzer = ReadingAnalysis(before=before_analysis)
    with (
        storage.open_session(storage.discover().volumes[0]) as session,
        pytest.raises(ValueError, match="Phase audio changed"),
    ):
        prepare_phase(session, LibrarySnapshot(), desired, analyzer=analyzer)
    assert analyzer.closed == [True]
    captures.assert_cleaned()
    assert not (tmp_path / str(INDEX_PATH)).exists()


def test_disconnect_discards_prefetched_inputs_and_stops_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, desired = device(tmp_path, 2)
    captures = Captures(monkeypatch)
    with storage.open_session(storage.discover().volumes[0]) as session:

        def disconnect(_index: int, _checkpoint: Callable[[], None]) -> None:
            session.invalidate("Device disconnected during analysis")

        analyzer = ReadingAnalysis(before=disconnect)
        with pytest.raises(SessionInvalidatedError):
            prepare_phase(session, LibrarySnapshot(), desired, analyzer=analyzer)
    assert analyzer.closed == [True]
    captures.assert_cleaned()
    assert not (tmp_path / str(INDEX_PATH)).exists()


def test_prepared_host_media_is_used_without_copying_missing_device_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "device"
    storage, desired = device(root, 2)
    incoming_path = tmp_path / "prepared.m4a"
    payload = b"incoming compressed audio 2"
    incoming_path.write_bytes(payload)
    device_path = DevicePath(desired.tracks[1].metadata.location)
    (root / str(device_path)).unlink()
    incoming = TransactionWrite(
        device_path,
        HostPath(incoming_path),
        FileContent(len(payload), sha256(payload).hexdigest()),
    )
    captures = Captures(monkeypatch)
    analyzer = ReadingAnalysis()
    with storage.open_session(storage.discover().volumes[0]) as session:
        publication = prepare_phase(
            session,
            LibrarySnapshot(),
            desired,
            analyzer=analyzer,
            media_writes=(incoming,),
        )
    assert publication.writes
    assert analyzer.payloads == [b"compressed audio 1", payload]
    assert analyzer.calls[1] == HostPath(incoming_path)
    assert [source.name for source in captures.started] == ["1.m4a"]
    assert incoming_path.read_bytes() == payload
    captures.assert_cleaned()


@pytest.mark.parametrize("kind", ["ineligible", "host"])
def test_preparation_without_eligible_device_inputs_needs_no_prefetch_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    storage, desired = device(tmp_path / "device", 2)
    incoming: list[TransactionWrite] = []
    if kind == "ineligible":
        desired = replace(
            desired,
            tracks=tuple(replace(track, length_ms=29_000) for track in desired.tracks),
        )
    else:
        for track in desired.tracks:
            path = tmp_path / f"prepared-{track.track_id}.m4a"
            payload = f"incoming audio {track.track_id}".encode()
            path.write_bytes(payload)
            incoming.append(
                TransactionWrite(
                    DevicePath(track.metadata.location),
                    HostPath(path),
                    FileContent(len(payload), sha256(payload).hexdigest()),
                )
            )

    def unexpected_resource(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Preparation without device inputs started prefetch resources")

    monkeypatch.setattr(phase_inputs, "staging_directory", unexpected_resource)
    monkeypatch.setattr(phase_inputs, "ThreadPoolExecutor", unexpected_resource)
    analyzer = ReadingAnalysis()
    with storage.open_session(storage.discover().volumes[0]) as session:
        publication = prepare_phase(
            session,
            LibrarySnapshot(),
            desired,
            analyzer=analyzer,
            media_writes=tuple(incoming),
        )
    assert publication.writes
    assert len(analyzer.calls) == (0 if kind == "ineligible" else 2)
    assert analyzer.closed == [True]
