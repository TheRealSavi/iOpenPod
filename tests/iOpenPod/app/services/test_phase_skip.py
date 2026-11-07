"""Skipping Phase preserves verified work and normal write safety."""

import json
import plistlib
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.phase_test_support import StubPhaseAnalysis
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.services.test_phase_cache import commit
from tests.iOpenPod.app.services.test_phase_prefetch import device
from tests.iOpenPod.app.test_sync_execution import (
    _ipod,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_sync_genius import (
    _refresh_request,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    PreparationCancelledError,
    WriteProgress,
)
from iOpenPod.app.services.phase import (
    CACHE_PATH,
    INDEX_PATH,
    MANIFEST_PATH,
    prepare_phase,
)
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor
from iOpenPod.app.sync_plan import prepare_sync_plan
from iPodDB.games import parse_phase_library
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import LibrarySnapshot, Playlist, playlist_entries
from storage import (
    AccessMode,
    DevicePath,
    FilesystemSession,
    HostPath,
    SessionInvalidatedError,
)


@pytest.mark.parametrize("when", ["before", "during", "verification"])
def test_skip_keeps_only_verified_charts_and_resumes_on_next_phase_edit(
    tmp_path: Path,
    when: str,
) -> None:
    storage, desired = device(tmp_path, 4)
    skip = Event()

    class SkippingAnalysis(StubPhaseAnalysis):
        def analyze(
            self,
            source: DevicePath | HostPath,
            *,
            input_suffix: str,
            length_ms: int,
            session: FilesystemSession,
            checkpoint: Callable[[], None],
        ) -> bytes:
            data = super().analyze(
                source,
                input_suffix=input_suffix,
                length_ms=length_ms,
                session=session,
                checkpoint=checkpoint,
            )
            # Keep Track 1; interrupt Track 2. Track 4 is already cached.
            if len(self.calls) == 2:
                skip.set()
                if when == "during":
                    checkpoint()
            return data

    original = replace(
        desired,
        playlists=(replace(desired.playlists[0], entries=playlist_entries((4,))),),
    )
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        commit(
            session,
            prepare_phase(
                session, LibrarySnapshot(), original, analyzer=StubPhaseAnalysis()
            ),
        )
        analyzer = SkippingAnalysis()
        if when == "before":
            skip.set()
        result = prepare_phase(
            session, original, desired, analyzer=analyzer, skip_requested=skip.is_set
        )
        commit(session, result)
        index = parse_phase_library((tmp_path / str(INDEX_PATH)).read_bytes())
        expected = (4,) if when == "before" else (1, 4)
        assert (
            tuple(t.persistent_id - 0x8000000000000000 for t in index.tracks)
            == expected
        )
        cache = json.loads((tmp_path / str(CACHE_PATH)).read_bytes())
        assert set(cache) == {f"{0x8000000000000000 + i:016X}" for i in expected}
        # A fresh request evaluates the remaining Tracks and reuses completed work.
        resumed = StubPhaseAnalysis()
        commit(session, prepare_phase(session, desired, desired, analyzer=resumed))
        assert len(resumed.calls) == 4 - len(expected)
        assert (
            len(parse_phase_library((tmp_path / str(INDEX_PATH)).read_bytes()).tracks)
            == 4
        )


@pytest.mark.parametrize("disconnected", [False, True])
def test_skip_does_not_hide_cancellation_or_disconnection(
    tmp_path: Path, disconnected: bool
) -> None:
    storage, desired = device(tmp_path, 1)
    with storage.open_session(storage.discover().volumes[0]) as session:

        def checkpoint() -> None:
            if not disconnected:
                raise PreparationCancelledError

        def progress(_value: object) -> None:
            if disconnected:
                session.close()

        with pytest.raises(
            SessionInvalidatedError if disconnected else PreparationCancelledError
        ):
            prepare_phase(
                session,
                LibrarySnapshot(),
                desired,
                analyzer=StubPhaseAnalysis(),
                checkpoint=checkpoint,
                analysis_progress=progress,
                skip_requested=lambda: True,
            )
        assert not (tmp_path / str(INDEX_PATH)).exists()


def test_skip_continues_real_library_save_and_sync(tmp_path: Path) -> None:
    ipod = build_device(tmp_path)
    database = ipod.root / "iPod_Control/iTunes/iTunesDB"
    raw = parse_iTunesDB(database.read_bytes())
    for item in raw.find_chunks(MhitHeader):
        raw = raw.replace_chunk(
            item, replace(item.chunk, header=replace(item.chunk.header, length=30_000))
        )
    database.write_bytes(write_iTunesDB(raw))
    ipod.coordinator.select_device(ipod.active.candidate.id)
    manifest = ipod.root / str(MANIFEST_PATH)
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(
        plistlib.dumps({"Name": "Phase", "Version": "1", "GUID": "phase"})
    )
    try:
        original = ipod.active.library
        desired = replace(
            original,
            playlists=(
                *original.playlists,
                Playlist(
                    -1,
                    "Rhythm",
                    entries=playlist_entries(t.track_id for t in original.tracks),
                    is_phase=True,
                ),
            ),
        )
        request = LibraryPreparationRequest(desired, ipod.active, 1, 1)
        observed: list[str] = []

        def skip_save(value: WriteProgress) -> None:
            observed.append(value.phase)
            if value.phase == "resources.phase":
                request.phase_analysis_skip.set()

        review = ipod.coordinator.prepare_library(request, skip_save, Event())
        assert review.result.prepared is not None, review.result.issues
        saved = ipod.save(review)
        assert saved.active is not None, saved.issues
        assert "resources.phase" in observed
        selected = next(p for p in saved.active.library.playlists if p.is_phase)
        assert len(selected.track_ids) == len(original.tracks)
        assert (
            parse_phase_library((ipod.root / str(INDEX_PATH)).read_bytes()).tracks == ()
        )

        sync = _refresh_request(saved.active)
        assert not sync.phase_analysis_skip.is_set()
        media = _ipod(ipod)
        plan = prepare_sync_plan(sync.host, media, saved.active.library)
        sync = replace(
            sync,
            ipod=media,
            plan=replace(plan, items=plan.items[:1]),
            options=replace(sync.options, analyze_for_genius=False),
        )
        observed.clear()

        def skip_sync(value: WriteProgress) -> None:
            observed.append(value.phase)
            if value.phase == "resources.phase":
                sync.phase_analysis_skip.set()

        result = SyncExecutor(ipod.coordinator).execute(sync, skip_sync, Event())
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        assert "resources.phase" in observed
        assert len(result.active.library.tracks) == len(original.tracks) - 1
        assert (
            parse_phase_library((ipod.root / str(INDEX_PATH)).read_bytes()).tracks == ()
        )
        # An unrelated Sync must not resume the work that was just skipped.
        observed.clear()
        sync = _refresh_request(result.active)
        sync = replace(sync, options=replace(sync.options, analyze_for_genius=False))
        result = SyncExecutor(ipod.coordinator).execute(sync, skip_sync, Event())
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert "resources.phase" not in observed
    finally:
        ipod.coordinator.close()
