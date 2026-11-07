"""Incremental Phase preparation across saves and Filesystem Sessions."""

from collections.abc import Callable
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from tests.iOpenPod.app.phase_test_support import StubPhaseAnalysis
from tests.iOpenPod.app.services.test_phase_prefetch import device

from iOpenPod.app.phase_cache import VALIDATION_PATH
from iOpenPod.app.services.phase import (
    CACHE_PATH,
    INDEX_PATH,
    PhasePublication,
    prepare_phase,
)
from iPodDB.games import parse_phase_library
from iPodDB.library import LibrarySnapshot, Playlist, playlist_entries
from storage import (
    AccessMode,
    DevicePath,
    FileContent,
    FileFingerprint,
    FileSnapshot,
    FilesystemSession,
    HostPath,
    Storage,
    StorageTransaction,
    TransactionWrite,
)
from storage.testing import VirtualStoragePlatform


def commit(session: FilesystemSession, publication: PhasePublication) -> None:
    if not publication.writes:
        return
    changed = {write.path for write in publication.writes}
    session.execute_transaction(
        StorageTransaction(
            publication.writes,
            (),
            tuple(item for item in publication.files if item.path not in changed),
        )
    )


@pytest.mark.parametrize(
    "change", ["unrelated", "rename", "reorder", "remove", "reselect"]
)
def test_settled_cache_needs_no_audio_or_chart_reads_even_after_reconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    storage, original = device(tmp_path, 3)
    analyzer = StubPhaseAnalysis()
    volume = storage.discover().volumes[0]
    with storage.open_session(volume, access=AccessMode.READ_WRITE) as session:
        commit(
            session,
            prepare_phase(session, LibrarySnapshot(), original, analyzer=analyzer),
        )
        commit(session, prepare_phase(session, original, original, analyzer=analyzer))
    # A fresh Storage instance models application restart/reconnection: only
    # committed receipt files survive, not a remembered session or generation.
    reconnected = VirtualStoragePlatform()
    reconnected.add_volume(tmp_path)
    storage = Storage(reconnected)
    next_volume = storage.discover().volumes[0]
    assert next_volume.connection_generation != volume.connection_generation
    volume = next_volume
    desired = original
    if change == "unrelated":
        desired = replace(
            original, playlists=(*original.playlists, Playlist(102, "Other"))
        )
    elif change == "rename":
        desired = replace(
            original, tracks=tuple(replace(t, title="Renamed") for t in original.tracks)
        )
    else:
        playlist = original.playlists[0]
        if change == "reorder":
            playlist = replace(playlist, entries=playlist_entries((3, 1, 2)))
        elif change == "remove":
            playlist = replace(playlist, entries=playlist_entries((1, 3)))
        else:
            playlist = replace(playlist, playlist_id=202)
        desired = replace(original, playlists=(playlist,))
    original_read = FilesystemSession.read_snapshot
    original_hash = FilesystemSession.fingerprint
    allowed = {CACHE_PATH, VALIDATION_PATH, INDEX_PATH}

    def read(
        session: FilesystemSession, path: DevicePath, *, max_bytes: int | None = None
    ) -> FileSnapshot:
        assert (
            path in allowed
            or path.name == "Manifest.plist"
            or str(path).startswith(".iopenpod-recovery/")
        ), f"Unexpected Phase payload read: {path}"
        return original_read(session, path, max_bytes=max_bytes)

    def fingerprint(
        session: FilesystemSession,
        path: DevicePath,
        *,
        checkpoint: Callable[[], None] | None = None,
    ) -> FileFingerprint:
        assert (
            path in allowed
            or path.name == "Manifest.plist"
            or str(path).startswith(".iopenpod-recovery/")
        ), f"Unexpected Phase dependency hash: {path}"
        return original_hash(session, path, checkpoint=checkpoint)

    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("Unchanged Phase inputs started capture or analysis")

    monkeypatch.setattr(FilesystemSession, "read_snapshot", read)
    monkeypatch.setattr(FilesystemSession, "fingerprint", fingerprint)
    monkeypatch.setattr(FilesystemSession, "copy_to_host", unexpected)
    monkeypatch.setattr(StubPhaseAnalysis, "analyze", unexpected)
    events: list[object] = []
    with storage.open_session(volume, access=AccessMode.READ_WRITE) as session:
        result = prepare_phase(
            session,
            original,
            desired,
            analyzer=analyzer,
            analysis_progress=events.append,
        )
        assert not events
        if change in ("unrelated", "rename"):
            assert not result.writes
        else:
            index = next(
                write.source for write in result.writes if write.path == INDEX_PATH
            )
            assert isinstance(index, bytes)
            parsed = parse_phase_library(index)
            assert parsed.playlist_id == desired.playlists[0].playlist_id
            assert tuple(record.persistent_id for record in parsed.tracks) == tuple(
                0x8000000000000000 + track_id
                for track_id in desired.playlists[0].track_ids
            )
            commit(session, result)


@pytest.mark.parametrize(
    "receipt", [None, b"invalid", b'{"version":99}', b'{"version":1,"tracks":[]}']
)
def test_old_or_damaged_receipts_are_rebuilt_without_reanalyzing_audio(
    tmp_path: Path,
    receipt: bytes | None,
) -> None:
    storage, desired = device(tmp_path, 2)
    analyzer = StubPhaseAnalysis()
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        commit(
            session,
            prepare_phase(session, LibrarySnapshot(), desired, analyzer=analyzer),
        )
        path = tmp_path / str(VALIDATION_PATH)
        if receipt is None:
            path.unlink()
        else:
            path.write_bytes(receipt)
        rebuilt = prepare_phase(session, desired, desired, analyzer=analyzer)
        assert len(analyzer.calls) == 2
        assert {write.path for write in rebuilt.writes} == {VALIDATION_PATH}
        commit(session, rebuilt)
        assert not prepare_phase(session, desired, desired, analyzer=analyzer).writes


def test_incoming_replacement_bypasses_matching_cached_device_metadata(
    tmp_path: Path,
) -> None:
    storage, desired = device(tmp_path / "device", 2)
    analyzer = StubPhaseAnalysis()
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        commit(
            session,
            prepare_phase(session, LibrarySnapshot(), desired, analyzer=analyzer),
        )
        commit(session, prepare_phase(session, desired, desired, analyzer=analyzer))
        source = tmp_path / "replacement.m4a"
        payload = b"replacement audio"
        source.write_bytes(payload)
        incoming = TransactionWrite(
            DevicePath(desired.tracks[0].metadata.location),
            HostPath(source),
            FileContent(len(payload), sha256(payload).hexdigest()),
            session.fingerprint(DevicePath(desired.tracks[0].metadata.location)),
        )
        result = prepare_phase(
            session, desired, desired, analyzer=analyzer, media_writes=(incoming,)
        )
        assert len(analyzer.calls) == 3
        assert analyzer.calls[-1] == HostPath(source)
        assert result.writes


def test_adding_phase_member_analyzes_only_the_new_track(tmp_path: Path) -> None:
    storage, desired = device(tmp_path, 4)
    original = replace(
        desired,
        playlists=(replace(desired.playlists[0], entries=playlist_entries((1, 2, 3))),),
    )
    analyzer = StubPhaseAnalysis()
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        commit(
            session,
            prepare_phase(session, LibrarySnapshot(), original, analyzer=analyzer),
        )
        commit(session, prepare_phase(session, original, original, analyzer=analyzer))
        result = prepare_phase(session, original, desired, analyzer=analyzer)
        assert len(analyzer.calls) == 4
        media_dependencies = {
            str(item.path)
            for item in result.files
            if str(item.path).startswith("iPod_Control/Music/")
        }
        assert media_dependencies == {desired.tracks[3].metadata.location}
        commit(session, result)


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("backend", ["cuda", "mps"])
@pytest.mark.parametrize("receipts", [False, True])
def test_backend_change_reuses_published_charts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    managed: bool,
    backend: str,
    receipts: bool,
) -> None:
    storage, desired = device(tmp_path, 2)
    producer = "librosa-phase-7:" + ("managed-v1:" if managed else "")
    producer += "demucs-4.0.1-5c90dfd2-torch-2.14.0+cpu-cpu-shifts0:stereo"
    monkeypatch.setattr(StubPhaseAnalysis, "identity", property(lambda self: producer))
    analyzer = StubPhaseAnalysis()
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        commit(
            session,
            prepare_phase(session, LibrarySnapshot(), desired, analyzer=analyzer),
        )
        if not receipts:
            (tmp_path / str(VALIDATION_PATH)).unlink()
        original_provenance = (tmp_path / str(CACHE_PATH)).read_bytes()
        producer = producer.replace("+cpu-cpu", f"+cu130-{backend}")
        result = prepare_phase(session, desired, desired, analyzer=analyzer)
        assert len(analyzer.calls) == 2, "Changing compute backend regenerated charts"
        assert {write.path for write in result.writes} <= {VALIDATION_PATH}
        commit(session, result)
        assert (tmp_path / str(CACHE_PATH)).read_bytes() == original_provenance
