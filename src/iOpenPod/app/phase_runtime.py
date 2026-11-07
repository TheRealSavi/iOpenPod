"""Use an explicitly installed Phase runtime without importing it into the app."""

from __future__ import annotations

import json
import logging
import re
import zipfile
from importlib.resources import files
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, cast

import numpy as np

from iOpenPod.app.core.settings.paths import default_backup_path
from iOpenPod.app.phase_activity import PhaseActivity, PhaseStage
from iOpenPod.app.phase_parts import HOP, RATE, PhasePart, PhasePartKind
from iOpenPod.app.phase_worker_session import PhaseWorkerSession
from storage.host_files import AtomicHostFile
from storage.host_installation import require_plain_path

if TYPE_CHECKING:
    from collections.abc import Callable


def runtime_directory() -> Path:
    return default_backup_path().parent / "PhaseAnalysis"


def worker_path() -> Path:
    return Path(str(files("iOpenPod").joinpath("assets/phase_runtime/worker.py")))


class ManagedPhaseSources:
    """One bounded child per preparation; the installed GUI runtime stays fixed."""

    def __init__(
        self, directory: Path, identity: str, *, _retain_worker: bool = False
    ) -> None:
        self.directory = directory
        self._identity = identity
        self._session: PhaseWorkerSession | None = None
        self._analysis_lock = Lock()
        self._retain_worker = _retain_worker
        self._supports_mix_overlap = False

    def for_analysis(self) -> ManagedPhaseSources:
        """Give each preparation its own lazy worker and evidence files."""
        return ManagedPhaseSources(self.directory, self._identity, _retain_worker=True)

    def close(self) -> None:
        """Release the model, interpreter and private files after preparation."""
        self._supports_mix_overlap = False
        session, self._session = self._session, None
        if session is not None:
            try:
                session.close()
            except OSError:
                logging.getLogger(__name__).exception(
                    "Could not remove the stopped Phase worker's private files"
                )

    @property
    def python(self) -> Path:
        windows = self.directory / "Scripts/python.exe"
        return windows if windows.is_file() else self.directory / "bin/python"

    @property
    def identity(self) -> str:
        return f"managed-v1:{self._identity}"

    @property
    def activity(self) -> PhaseActivity:
        return (
            self._session.activity
            if self._session is not None
            else PhaseActivity(PhaseStage.LOADING)
        )

    @property
    def supports_mix_overlap(self) -> bool:
        """Use only the last validated live response in this preparation."""
        return self._supports_mix_overlap

    @classmethod
    def installed(cls, root: Path | None = None) -> ManagedPhaseSources | None:
        root = root or runtime_directory()
        raw = AtomicHostFile(root / "current.json").read_bytes(max_bytes=4096)
        if raw is None:
            return None
        decoded: object = json.loads(raw)
        if not isinstance(decoded, dict):
            raise ValueError("Invalid Phase runtime receipt")
        data = cast("dict[str, object]", decoded)
        directory_name = data.get("directory")
        identity = data.get("identity")
        if (
            data.get("protocol") != 1
            or not isinstance(directory_name, str)
            or not re.fullmatch(r"runtime-[0-9a-f]{32}", directory_name)
            or not isinstance(identity, str)
            or not 0 < len(identity) <= 512
        ):
            raise ValueError("Invalid Phase runtime receipt")
        directory = root / directory_name
        require_plain_path(directory)
        source = cls(directory, identity)
        if not source.python.is_file():
            return None
        return source

    def analyze(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
        checkpoint: Callable[[], None],
    ) -> tuple[PhasePart, ...]:
        # Keep the output file owned through validation, not just the response.
        if not self._analysis_lock.acquire(blocking=False):
            raise RuntimeError("Phase source analysis is already in progress")
        try:
            return self._analyze(
                pcm, sample_rate=sample_rate, channels=channels, checkpoint=checkpoint
            )
        except BaseException:
            self.close()
            raise
        finally:
            if not self._retain_worker:
                self.close()
            self._analysis_lock.release()

    def _analyze(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
        checkpoint: Callable[[], None],
    ) -> tuple[PhasePart, ...]:
        checkpoint()
        if (
            type(sample_rate) is not int
            or sample_rate not in (RATE, 44_100)
            or type(channels) is not int
            or channels not in (1, 2)
        ):
            raise ValueError("Unsupported Phase separation PCM format")
        if (
            not pcm
            or len(pcm) % (4 * channels)
            or len(pcm) > 1801 * sample_rate * channels * 4
        ):
            raise ValueError("Invalid Phase separation PCM size")
        count = 1 + round(len(pcm) / (4 * channels) * RATE / sample_rate) // HOP
        if self._session is None:
            self._session = PhaseWorkerSession(
                self.python, worker_path(), self.directory.parent / "models"
            )
        target, identity = self._session.request(
            pcm, sample_rate=sample_rate, channels=channels, checkpoint=checkpoint
        )
        if not target.is_file() or target.stat().st_size > 256 * 1024 * 1024:
            raise ValueError("Invalid Phase worker output size")
        with zipfile.ZipFile(target) as entries:
            if (
                sum(item.file_size for item in entries.infolist())
                > 6 * 19 * count * 8 + 65536
            ):
                raise ValueError("Phase worker output exceeds the expected duration")
        parts: list[PhasePart] = []
        with np.load(target, allow_pickle=False) as archive:
            for kind in PhasePartKind:
                arrays = tuple(
                    archive[f"{kind.value}_{field}"]
                    for field in (
                        "bands",
                        "energy",
                        "chroma",
                        "magnitudes",
                    )
                )
                if arrays[1].shape != (count,):
                    raise ValueError("Phase worker returned the wrong duration")
                parts.append(PhasePart(kind, *arrays))
        checkpoint()
        self._identity = identity
        self._supports_mix_overlap = self._session.last_supports_mix_overlap
        return tuple(parts)
