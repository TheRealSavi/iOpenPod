"""Worker cancellation keeps its read reservation until actual completion."""

from collections.abc import Callable
from dataclasses import replace
from threading import Event, get_ident
from time import monotonic, sleep

import pytest
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context
from tests.iOpenPod.GUI.extras_test_support import make_active_ipod
from tests.iOpenPod.GUI.test_tones import NOTES, TRACK

from iOpenPod.app.playback.backend import PlaybackSourceProvider
from iOpenPod.app.tone_conversion import ToneArrangement
from iPodDB.library import Track
from storage.media_processing import MediaToolFinder


def test_cancelled_work_never_delivers_a_stale_arrangement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = build_context()
    initial = make_active_ipod()
    active = replace(initial, library=replace(initial.library, tracks=(TRACK,)))
    context.device_controller.finish_library_save(active)
    started, release = Event(), Event()
    threads: list[int] = []

    def convert(
        track: Track,
        provider: PlaybackSourceProvider,
        *,
        checkpoint: Callable[[], None],
        report: Callable[[str], None],
        find_tool: MediaToolFinder | None = None,
    ) -> ToneArrangement:
        assert track is TRACK
        threads.append(get_ident())
        started.set()
        assert release.wait(5)
        checkpoint()
        return ToneArrangement(NOTES, 30, 31.5)

    monkeypatch.setattr(
        "iOpenPod.app.tone_conversion_controller.convert_track_to_tone", convert
    )
    controller = context.tone_conversion_controller
    try:
        assert controller.start(TRACK)
        assert started.wait(5)
        assert threads != [get_ident()]
        assert not context.device_controller.device_writes_allowed
        controller.cancel()
        assert controller.busy and not context.device_controller.device_writes_allowed
        assert not controller.start(TRACK)
        release.set()
        deadline = monotonic() + 5
        while controller.busy and monotonic() < deadline:
            APPLICATION.processEvents()
            sleep(0.005)
        APPLICATION.processEvents()
        assert not controller.busy and controller.arrangement is None
        assert context.device_controller.device_writes_allowed
    finally:
        release.set()
        context.shutdown()
