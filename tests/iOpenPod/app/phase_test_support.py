"""A chart-producing boundary double for Storage and application tests."""

from collections.abc import Callable

from iOpenPod.app.phase_analysis import PhaseAnalysisService
from iPodDB.games import PhaseChart, build_phase_analysis
from storage import DevicePath, FilesystemSession, HostPath


class StubPhaseAnalysis(PhaseAnalysisService):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[DevicePath | HostPath] = []

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
        self.calls.append(source)
        return build_phase_analysis(PhaseChart())
