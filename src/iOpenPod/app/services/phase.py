"""Prepare Phase companions alongside the Library's recoverable Storage write."""

from __future__ import annotations

import json
import re
from contextlib import ExitStack, closing
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, cast

from iOpenPod.app.phase_activity import PhaseActivity, PhaseStage
from iOpenPod.app.phase_analysis import PhaseAnalysisService
from iOpenPod.app.phase_cache import (
    CACHE_LIMIT,
    VALIDATION_PATH,
    PhaseCacheEntry,
    decode_validation,
    encode_validation,
    fingerprint_identity,
    reuse_entry,
)
from iOpenPod.app.phase_inputs import prefetch_phase_inputs
from iOpenPod.app.phase_progress import PhaseProgress, PhaseProgressReporter
from iPodDB.games import (
    IncompletePhaseLibraryError,
    PhaseLibrary,
    PhaseTrack,
    build_phase_library,
    parse_game_manifest,
    parse_phase_library,
    phase_analysis_relative_path,
    read_phase_playlist_id,
)
from iPodDB.library import MediaType
from storage import (
    DevicePath,
    FileContent,
    FilePrecondition,
    HostPath,
    SessionInvalidatedError,
    TransactionWrite,
)
from storage.host_input import LocalHostFile

if TYPE_CHECKING:
    from collections.abc import Callable

    from iPodDB.library import LibrarySnapshot, Track
    from storage import FilesystemSession

_GAME = "iPod_Control/GameData_RW/1D000"
INDEX_PATH = DevicePath(f"{_GAME}/Phase Data/Phase Library")
MANIFEST_PATH = DevicePath("iPod_Control/Games_RO/1D000/Manifest.plist")
CACHE_PATH = DevicePath("iPod_Control/iOpenPod/phase-analysis-v1.json")


def _host_digest(
    observed: LocalHostFile, size: int, checkpoint: Callable[[], None]
) -> str:
    digest = sha256()
    with observed.open_read(checkpoint=checkpoint, max_bytes=size) as stream:
        while chunk := stream.read(1024 * 1024):
            checkpoint()
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class PhasePublication:
    files: tuple[FilePrecondition, ...] = ()
    writes: tuple[TransactionWrite, ...] = ()


def phase_playlist_changed(
    before: LibrarySnapshot,
    desired: LibrarySnapshot,
    media_writes: tuple[TransactionWrite, ...] = (),
) -> bool:
    """Gate automatic preparation on edits to the selection or its audio inputs."""
    previous = tuple(p for p in before.playlists if p.is_phase)
    selected = tuple(p for p in desired.playlists if p.is_phase)
    # Entry IDs are source-local occurrence identities, not Playlist edits.
    if tuple((replace(p, entries=()), p.track_ids) for p in previous) != tuple(
        (replace(p, entries=()), p.track_ids) for p in selected
    ):
        return True
    if not selected:
        return False
    members = set(selected[0].track_ids)

    def inputs(
        snapshot: LibrarySnapshot,
    ) -> tuple[tuple[int, int, str, int, tuple[MediaType, ...]], ...]:
        return tuple(
            sorted(
                (
                    t.track_id,
                    t.ipod.db_track_id if t.ipod else 0,
                    t.metadata.location,
                    t.length_ms,
                    t.media_types,
                )
                for t in snapshot.tracks
                if t.track_id in members
            )
        )

    if inputs(before) != inputs(desired):
        return True
    paths = {t.metadata.location for t in desired.tracks if t.track_id in members}
    return any(str(write.path) in paths for write in media_writes)


def _chart_identity(identity: str) -> str:
    """Ignore compute placement in both legacy and current Demucs provenance."""
    return re.sub(
        r"(demucs-[^:]+-torch-[^:+]+)(?:\+(?:cpu|cu\d+))?-(?:cpu|cuda|mps)-shifts0",
        r"\1-shifts0",
        identity,
    )


class _PhaseAnalysisSkippedError(Exception):
    """Stop optional work without cancelling the Library publication."""


def _eligible_tracks(
    desired: LibrarySnapshot, unique_ids: tuple[int, ...]
) -> tuple[tuple[int, Track], ...]:
    tracks = {track.track_id: track for track in desired.tracks}
    selected: list[tuple[int, Track]] = []
    seen: set[int] = set()
    for completed, track_id in enumerate(unique_ids):
        track = tracks[track_id]
        # Keep ineligible Tracks in the ordinary Playlist without inventing charts.
        if (
            track.media_types != (MediaType.AUDIO,)
            or not 30 <= track.length_ms // 1000 <= 1800
        ):
            continue
        pid = track.ipod.db_track_id if track.ipod is not None else 0
        if not pid:
            raise ValueError(
                "Phase needs final Track persistent IDs before publication."
            )
        if pid not in seen:
            seen.add(pid)
            selected.append((completed, track))
    return tuple(selected)


def _cached_audio_hash(cached: str | None, identity: str, length_ms: int) -> str | None:
    if cached is None:
        return None
    # Provider identities contain colons; the final three fields do not.
    fields = cached.rsplit(":", 3)
    if (
        len(fields) == 4
        and _chart_identity(fields[0]) == _chart_identity(identity)
        and fields[2] == str(length_ms)
    ):
        return fields[1]
    return None


def capture_phase_selection(
    session: FilesystemSession,
) -> tuple[int | None, FilePrecondition]:
    if not session.exists(INDEX_PATH):
        return None, FilePrecondition(INDEX_PATH, None)
    snapshot = session.read_snapshot(INDEX_PATH)
    try:
        playlist_id = read_phase_playlist_id(snapshot.data)
    except ValueError:
        playlist_id = None
    return playlist_id, FilePrecondition(INDEX_PATH, snapshot.fingerprint)


def prepare_phase(
    session: FilesystemSession,
    before: LibrarySnapshot,
    desired: LibrarySnapshot,
    *,
    checkpoint: Callable[[], None] = lambda: None,
    analyzer: PhaseAnalysisService | None = None,
    media_writes: tuple[TransactionWrite, ...] = (),
    progress: Callable[[int, int, str], None] = lambda _done, _total, _title: None,
    analysis_progress: Callable[[PhaseProgress], None] = lambda _value: None,
    skip_requested: Callable[[], bool] = lambda: False,
) -> PhasePublication:
    """Use final persistent IDs and verified audio; prepare charts without writes.

    Charts for removed tracks remain on disk. Deselection
    writes an empty index so the game's name fallback cannot use stale records.
    """
    selected = tuple(p for p in desired.playlists if p.is_phase)
    if len(selected) > 1:
        raise ValueError("Only one Playlist can be selected for Phase.")
    if not selected and not any(p.is_phase for p in before.playlists):
        return PhasePublication()
    files: dict[DevicePath, FilePrecondition] = {}
    writes: list[TransactionWrite] = []

    def read(path: DevicePath, limit: int | None) -> bytes | None:
        checkpoint()
        if not session.exists(path):
            files[path] = FilePrecondition(path, None)
            return None
        snapshot = session.read_snapshot(path, max_bytes=limit)
        files[path] = FilePrecondition(path, snapshot.fingerprint)
        return snapshot.data

    def publish(path: DevicePath, data: bytes, previous: bytes | None) -> None:
        if data != previous:
            expected = files[path].fingerprint
            writes.append(
                TransactionWrite(
                    path,
                    data,
                    FileContent(len(data), sha256(data).hexdigest()),
                    expected,
                )
            )

    original = read(INDEX_PATH, None)
    try:
        existing = (
            parse_phase_library(original) if original is not None else PhaseLibrary(0)
        )
    except IncompletePhaseLibraryError:
        # Rebuild short indexes at commit, retaining the original fingerprint and
        # bytes for Storage's conflict checks and recoverable replacement.
        existing = PhaseLibrary(0)
    if not selected:
        publish(INDEX_PATH, build_phase_library(PhaseLibrary(0)), original)
        return PhasePublication(tuple(files.values()), tuple(writes))
    manifest = read(MANIFEST_PATH, 1024 * 1024)
    if manifest is None:
        raise ValueError(
            "Phase is no longer installed. Clear the Phase Playlist setting."
        )
    parse_game_manifest(manifest)
    playlist = selected[0]
    with (
        closing((analyzer or PhaseAnalysisService()).for_analysis()) as audio_analyzer,
        ExitStack() as input_lifetime,
    ):
        cached_bytes = read(CACHE_PATH, 8 * 1024 * 1024)
        cache: dict[str, str] = {}
        if cached_bytes is not None:
            decoded: object = json.loads(cached_bytes)
            if not isinstance(decoded, dict):
                raise ValueError("Invalid Phase analysis cache.")
            untyped = cast("dict[object, object]", decoded)
            if any(
                not isinstance(k, str) or not isinstance(v, str)
                for k, v in untyped.items()
            ):
                raise ValueError("Invalid Phase analysis cache records.")
            cache = cast("dict[str, str]", decoded)
        updated_cache = dict(cache)
        validation_bytes = read(VALIDATION_PATH, CACHE_LIMIT)
        validation = decode_validation(validation_bytes)
        updated_validation: dict[str, PhaseCacheEntry] = {}
        incoming = {w.path: w for w in media_writes}
        retained = {t.persistent_id: t for t in existing.tracks}
        unique_ids = tuple(dict.fromkeys(playlist.track_ids))
        eligible = _eligible_tracks(desired, unique_ids)
        identity = audio_analyzer.identity if eligible else ""
        reuse_hashes: dict[DevicePath, str] = {}
        reused: dict[int, PhaseTrack] = {}
        for _, track in eligible:
            checkpoint()
            assert track.ipod is not None
            pid = track.ipod.db_track_id
            pid_key = f"{pid:016X}"
            audio_path = DevicePath(track.metadata.location)
            cached = cache.get(pid_key)
            cached_hash = _cached_audio_hash(cached, identity, track.length_ms)
            if cached_hash is not None:
                reuse_hashes[audio_path] = cached_hash
            entry = validation.get(pid_key)
            record = retained.get(pid)
            if (
                cached_hash is None
                or entry is None
                or record is None
                or audio_path in incoming
                or entry.provenance != cached
                or entry.audio_path != str(audio_path)
                or entry.audio is None
            ):
                continue
            path = DevicePath(f"{_GAME}/{phase_analysis_relative_path(record)}")
            refreshed = reuse_entry(
                session,
                entry,
                audio_path=audio_path,
                chart_path=path,
                chart_size=record.analysis_size,
            )
            if refreshed is not None:
                reused[pid] = record
                updated_validation[pid_key] = refreshed
        pending = tuple(
            (completed, track)
            for completed, track in eligible
            if track.ipod is not None and track.ipod.db_track_id not in reused
        )
        records = dict(reused)
        reporter = PhaseProgressReporter(
            tuple(track.length_ms for _, track in pending), analysis_progress
        )
        current_title = ""
        activity = PhaseActivity(PhaseStage.CAPTURING)
        analyzing = False

        def report_checkpoint() -> None:
            checkpoint()
            if not session.is_active:
                raise SessionInvalidatedError(
                    "The Filesystem Session ended during Phase analysis"
                )
            reporter.emit(
                current_title, audio_analyzer.activity if analyzing else activity
            )
            if skip_requested():
                raise _PhaseAnalysisSkippedError

        if pending:
            reporter.emit(current_title, activity)
        try:
            if pending:
                report_checkpoint()
            inputs = input_lifetime.enter_context(
                prefetch_phase_inputs(
                    session,
                    tuple(
                        DevicePath(track.metadata.location)
                        for _, track in pending
                        if DevicePath(track.metadata.location) not in incoming
                    ),
                    checkpoint=report_checkpoint,
                    reuse_hashes=reuse_hashes,
                )
            )
            for completed, track in eligible:
                assert track.ipod is not None
                if track.ipod.db_track_id in reused:
                    continue
                current_title = track.title
                activity = PhaseActivity(PhaseStage.CAPTURING)
                inputs.checkpoint()
                pid = track.ipod.db_track_id
                progress(completed, len(unique_ids), track.title)
                record = retained.get(pid, PhaseTrack(pid, 7, 1))
                path = DevicePath(f"{_GAME}/{phase_analysis_relative_path(record)}")
                analysis = read(path, 16 * 1024 * 1024)
                if analysis is not None:
                    if len(analysis) < 90 or analysis[:4] != b"pha\x02":
                        raise ValueError(f"Unrecognized Phase analysis file: {path}")
                    if pid in retained and len(analysis) != record.analysis_size:
                        raise ValueError(
                            f"Phase analysis size disagrees with its index: {path}"
                        )
                cached = cache.get(f"{pid:016X}")
                reusable_hash = _cached_audio_hash(
                    cached, audio_analyzer.identity, track.length_ms
                )
                if (
                    analysis is None
                    or cached is None
                    or cached.rsplit(":", 1)[-1] != sha256(analysis).hexdigest()
                ):
                    reusable_hash = None
                with ExitStack() as capture:
                    audio_path = DevicePath(track.metadata.location)
                    source: HostPath | DevicePath
                    observed: LocalHostFile | None = None
                    supplied = incoming.get(audio_path)
                    if supplied is not None:
                        if isinstance(supplied.source, bytes):
                            raise ValueError(
                                "Phase analysis requires a prepared audio file source."
                            )
                        source = supplied.source
                        observed = LocalHostFile.observe(source)

                        audio_hash = _host_digest(
                            observed, supplied.content.size, inputs.checkpoint
                        )
                        if audio_hash != supplied.content.sha256:
                            raise ValueError(
                                "Prepared Phase audio changed before analysis."
                            )
                    else:
                        prepared = capture.enter_context(
                            inputs.capture(audio_path, reuse_sha256=reusable_hash)
                        )
                        source = prepared.source
                        audio_before = prepared.fingerprint
                        files[audio_path] = FilePrecondition(audio_path, audio_before)
                        audio_hash = audio_before.sha256
                    key = f"{audio_analyzer.identity}:{audio_hash}:{track.length_ms}"
                    if (
                        analysis is not None
                        and cached is not None
                        and reusable_hash == audio_hash
                    ):
                        activity = PhaseActivity(PhaseStage.REUSING)
                        inputs.checkpoint()
                        data = analysis
                        key = cached.rsplit(":", 1)[0]
                    else:
                        analyzing = True
                        try:
                            data = audio_analyzer.analyze(
                                source,
                                input_suffix=PurePosixPath(
                                    track.metadata.location
                                ).suffix,
                                length_ms=track.length_ms,
                                session=session,
                                checkpoint=inputs.checkpoint,
                            )
                        finally:
                            analyzing = False
                        # A failed accelerator or optional provider can change the analyzer.
                        # Record the identity that produced these bytes, never the candidate.
                        key = (
                            f"{audio_analyzer.identity}:{audio_hash}:{track.length_ms}"
                        )
                    activity = PhaseActivity(PhaseStage.VERIFYING)
                    inputs.checkpoint()
                    if supplied is not None:
                        assert observed is not None
                        if (
                            _host_digest(
                                observed, supplied.content.size, inputs.checkpoint
                            )
                            != audio_hash
                        ):
                            raise ValueError(
                                "Prepared Phase audio changed during analysis."
                            )
                # Capture exit verifies the source. Only fully verified results may
                # survive a Skip request observed during the next Track.
                publish(path, data, analysis)
                updated_cache[f"{pid:016X}"] = f"{key}:{sha256(data).hexdigest()}"
                updated_validation[f"{pid:016X}"] = PhaseCacheEntry(
                    updated_cache[f"{pid:016X}"],
                    str(audio_path),
                    fingerprint_identity(files[audio_path].fingerprint)
                    if supplied is None
                    else None,
                    str(path),
                    fingerprint_identity(files[path].fingerprint)
                    if data == analysis
                    else None,
                )
                records[pid] = PhaseTrack(pid, record.shard, len(data))
                reporter.complete_track()
        except _PhaseAnalysisSkippedError:
            input_lifetime.close()
            checkpoint()
            if not session.is_active:
                raise SessionInvalidatedError(
                    "The Filesystem Session ended during Phase analysis"
                ) from None
        progress(len(unique_ids), len(unique_ids), "")
        if pending:
            reporter.emit("", PhaseActivity(PhaseStage.FINALIZING))
        # Keep metadata bounded to this playlist; unused chart files remain untouched.
        retained_ids = {f"{pid:016X}" for pid in records}
        updated_cache = {k: v for k, v in updated_cache.items() if k in retained_ids}
        cache_data = (json.dumps(updated_cache, sort_keys=True) + "\n").encode()
        if len(cache_data) > 8 * 1024 * 1024:
            raise ValueError("Phase analysis cache exceeds its supported size.")
        publish(CACHE_PATH, cache_data, cached_bytes)
        publish(
            VALIDATION_PATH, encode_validation(updated_validation), validation_bytes
        )
        publish(
            INDEX_PATH,
            build_phase_library(
                PhaseLibrary(
                    playlist.playlist_id,
                    tuple(
                        records[track.ipod.db_track_id]
                        for _, track in eligible
                        if track.ipod is not None and track.ipod.db_track_id in records
                    ),
                )
            ),
            original,
        )
        return PhasePublication(tuple(files.values()), tuple(writes))
