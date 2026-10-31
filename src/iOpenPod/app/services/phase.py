"""Prepare Phase companions alongside the Library's recoverable Storage write."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, cast

from iOpenPod.app.phase_analysis import PhaseAnalysisService
from iOpenPod.app.phase_audio import PHASE_ANALYSIS_VERSION
from iPodDB.games import (
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
    TransactionWrite,
)
from storage.host_input import LocalHostFile

if TYPE_CHECKING:
    from collections.abc import Callable

    from iPodDB.library import LibrarySnapshot
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


def capture_phase_selection(
    session: FilesystemSession,
) -> tuple[int | None, FilePrecondition]:
    if not session.exists(INDEX_PATH):
        return None, FilePrecondition(INDEX_PATH, None)
    snapshot = session.read_snapshot(INDEX_PATH, max_bytes=8 * 1024 * 1024)
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

    def read(path: DevicePath, limit: int) -> bytes | None:
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

    original = read(INDEX_PATH, 8 * 1024 * 1024)
    existing = (
        parse_phase_library(original) if original is not None else PhaseLibrary(0)
    )
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
    audio_analyzer = (analyzer or PhaseAnalysisService()).for_analysis()
    cached_bytes = read(CACHE_PATH, 8 * 1024 * 1024)
    cache: dict[str, str] = {}
    if cached_bytes is not None:
        decoded: object = json.loads(cached_bytes)
        if not isinstance(decoded, dict):
            raise ValueError("Invalid Phase analysis cache.")
        untyped = cast("dict[object, object]", decoded)
        if any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in untyped.items()
        ):
            raise ValueError("Invalid Phase analysis cache records.")
        cache = cast("dict[str, str]", decoded)
    updated_cache = dict(cache)
    incoming = {w.path: w for w in media_writes}
    tracks = {t.track_id: t for t in desired.tracks}
    retained = {t.persistent_id: t for t in existing.tracks}
    records: list[PhaseTrack] = []
    seen: set[int] = set()
    unique_ids = tuple(dict.fromkeys(playlist.track_ids))
    for completed, track_id in enumerate(unique_ids):
        checkpoint()
        track = tracks[track_id]
        # SDK include music bit, exclude the other media kinds. Keep ineligible
        # tracks in the user's ordinary Playlist, but do not invent charts for them.
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
        if pid in seen:
            continue
        seen.add(pid)
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

            audio_hash = _host_digest(observed, supplied.content.size, checkpoint)
            if audio_hash != supplied.content.sha256:
                raise ValueError("Prepared Phase audio changed before analysis.")
            audio_before = None
        else:
            source = audio_path
            audio_before = session.fingerprint(audio_path)
            files[audio_path] = FilePrecondition(audio_path, audio_before)
            audio_hash = audio_before.sha256
        key = f"{PHASE_ANALYSIS_VERSION}:{audio_hash}:{track.length_ms}"
        cached = cache.get(f"{pid:016X}")
        if analysis is not None and cached == f"{key}:{sha256(analysis).hexdigest()}":
            data = analysis
        else:
            data = audio_analyzer.analyze(
                source,
                input_suffix=PurePosixPath(track.metadata.location).suffix,
                length_ms=track.length_ms,
                session=session,
                checkpoint=checkpoint,
            )
            publish(path, data, analysis)
        if supplied is not None:
            assert observed is not None
            if _host_digest(observed, supplied.content.size, checkpoint) != audio_hash:
                raise ValueError("Prepared Phase audio changed during analysis.")
        elif session.fingerprint(audio_path) != audio_before:
            raise ValueError("Phase audio changed during analysis.")
        updated_cache[f"{pid:016X}"] = f"{key}:{sha256(data).hexdigest()}"
        records.append(PhaseTrack(pid, record.shard, len(data)))
    progress(len(unique_ids), len(unique_ids), "")
    # Keep metadata bounded to this playlist; unused chart files remain untouched.
    retained_ids = {f"{record.persistent_id:016X}" for record in records}
    updated_cache = {k: v for k, v in updated_cache.items() if k in retained_ids}
    cache_data = (json.dumps(updated_cache, sort_keys=True) + "\n").encode()
    if len(cache_data) > 8 * 1024 * 1024:
        raise ValueError("Phase analysis cache exceeds its supported size.")
    publish(CACHE_PATH, cache_data, cached_bytes)
    publish(
        INDEX_PATH,
        build_phase_library(PhaseLibrary(playlist.playlist_id, tuple(records))),
        original,
    )
    return PhasePublication(tuple(files.values()), tuple(writes))
