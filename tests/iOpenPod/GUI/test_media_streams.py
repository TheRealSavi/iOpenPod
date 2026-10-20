"""Stream choices remain responsive and separate from committed Sync intent."""

import time
from collections.abc import Callable
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import Qt, QTimer, QTranslator
from PySide6.QtTest import QSignalSpy, QTest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_media_stream_selection import (
    multiple_streams as multiple_streams,
)
from tests.iOpenPod.app.test_sync_stream_selection import host_library
from tests.iOpenPod.app.test_video_preparation import captioned_video as captioned_video
from tests.iOpenPod.app.test_video_preparation import ffmpeg as ffmpeg
from tests.iOpenPod.app.test_video_preparation import profile as profile
from tests.iOpenPod.app.test_video_preparation import video as video
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.GUI.test_sync_playlist_review import workspace as workspace

from device_registry import DeviceProfile
from iOpenPod.app.host_media_library import HostMediaFileKind, HostMediaSource
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
from iOpenPod.app.media import MediaInspector
from iOpenPod.app.media.models import MediaScanMetadata, StreamKind
from iOpenPod.app.media.stream_selection import MediaStreamSelection
from iOpenPod.app.media_stream_controller import MediaStreamController
from iOpenPod.app.media_stream_preferences import MediaStreamPreferences
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.models.track_table_model import TrackColumn, TrackRole
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
)
from iOpenPod.GUI.delegates.sync_track_delegate import SyncTrackDelegate
from iOpenPod.GUI.dialogs.media_streams import MediaStreamsDialog
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.sync_workspace import SyncWorkspace
from iOpenPod.GUI.widgets.media_stream_option import STREAM_OPTION_ROLE, StreamOption
from iOpenPod.GUI.widgets.track_table import TrackTable
from storage import AtomicHostFile, HostPath
from storage.host_input import LocalHostFile


def wait_for(predicate: Callable[[], bool]) -> None:
    until = time.monotonic() + 5
    while not predicate() and time.monotonic() < until:
        APPLICATION.processEvents()
        QTest.qWait(10)
    assert predicate()


def source(path: Path) -> HostMediaSource:
    facts = LocalHostFile.observe(HostPath(path))
    return HostMediaSource(
        facts.path, HostMediaFileKind.VIDEO, facts.size_bytes, facts.modified_ns
    )


def test_dialog_applies_nondefault_choices_and_can_restore_automatic(
    multiple_streams: Path,
    profile: DeviceProfile,
) -> None:
    dialog = MediaStreamsDialog(
        source(multiple_streams), "Multi-stream movie", profile, None
    )
    try:
        dialog.show()
        wait_for(dialog.automatic.isEnabled)
        assert dialog.video.count() == 2
        assert dialog.audio.count() == 3
        assert dialog.subtitles.count() == dialog.captions.count() == 1
        rows = (dialog.video, dialog.audio, dialog.subtitles, dialog.captions)
        for upper, lower in pairwise(rows):
            assert upper.geometry().bottom() < lower.geometry().top()
        assert dialog.subtitles.height() == dialog.subtitles.sizeHint().height()
        assert "spa" in dialog.audio.itemText(2)
        audio_option = dialog.audio.itemData(2, STREAM_OPTION_ROLE)
        assert isinstance(audio_option, StreamOption)
        assert "Spanish" in audio_option.details
        assert audio_option.number
        assert "\n" in dialog.audio.itemData(2, Qt.ItemDataRole.AccessibleTextRole)
        dialog.automatic.setChecked(False)
        dialog.video.setCurrentIndex(1)
        dialog.audio.setCurrentIndex(2)
        dialog.captions.item(0).setCheckState(Qt.CheckState.Unchecked)
        dialog.accept()
        choice = dialog.selection
        assert choice is not None
        assert choice.video is not None and choice.video.index == 1
        assert choice.audio is not None and choice.audio.index == 3
        assert len(choice.subtitles) == 1 and choice.captions == ()
        assert dialog.result() == dialog.DialogCode.Accepted
    finally:
        dialog.close()
    restored = MediaStreamsDialog(source(multiple_streams), "Movie", profile, choice)
    try:
        restored.show()
        wait_for(restored.automatic.isEnabled)
        assert restored.video.currentIndex() == 1
        assert restored.audio.currentIndex() == 2
        restored.automatic.setChecked(True)
        restored.accept()
        assert restored.selection is None
    finally:
        restored.close()


def test_unsupported_subtitle_is_visible_but_cannot_be_selected(
    multiple_streams: Path,
    profile: DeviceProfile,
) -> None:
    metadata = MediaInspector().scan_metadata(
        HostPath(multiple_streams), checkpoint=lambda: None
    )
    metadata = replace(
        metadata,
        streams=tuple(
            replace(stream, codec="hdmv_pgs_subtitle", codec_tag="")
            if stream.kind is StreamKind.SUBTITLE
            else stream
            for stream in metadata.streams
        ),
    )

    class Inspector(MediaInspector):
        def scan_metadata(
            self, source: HostPath, *, checkpoint: Callable[[], None]
        ) -> MediaScanMetadata:
            checkpoint()
            return metadata

    dialog = MediaStreamsDialog(
        source(multiple_streams), "Movie", profile, None, inspector=Inspector()
    )
    try:
        wait_for(dialog.automatic.isEnabled)
        dialog.automatic.setChecked(False)
        item = dialog.subtitles.item(0)
        assert "unavailable" in item.text()
        assert not item.flags() & Qt.ItemFlag.ItemIsEnabled
        option = item.data(STREAM_OPTION_ROLE)
        assert isinstance(option, StreamOption)
        assert "Unavailable on this iPod" in option.status
        assert item.toolTip() == ""
        dialog.reject()
        assert dialog.selection is None
    finally:
        dialog.close()


def test_legacy_text_subtitles_are_available_and_selected_when_choosing_streams(
    multiple_streams: Path,
    profile: DeviceProfile,
) -> None:
    metadata = MediaInspector().scan_metadata(
        HostPath(multiple_streams), checkpoint=lambda: None
    )
    template = next(s for s in metadata.streams if s.kind is StreamKind.SUBTITLE)
    codecs = ("sami", "subviewer", "subviewer1", "microdvd", "mpl2", "text")
    subtitles = tuple(
        replace(
            template,
            index=100 + index,
            codec=codec,
            codec_tag="",
            width=None,
            height=None,
            default=False,
            dispositions=(),
        )
        for index, codec in enumerate(codecs)
    )
    metadata = replace(
        metadata,
        streams=tuple(s for s in metadata.streams if s.kind is not StreamKind.SUBTITLE)
        + subtitles,
    )

    class Inspector(MediaInspector):
        def scan_metadata(
            self, source: HostPath, *, checkpoint: Callable[[], None]
        ) -> MediaScanMetadata:
            checkpoint()
            return metadata

    dialog = MediaStreamsDialog(
        source(multiple_streams), "Movie", profile, None, inspector=Inspector()
    )
    try:
        wait_for(dialog.automatic.isEnabled)
        dialog.automatic.setChecked(False)
        assert dialog.subtitles.count() == len(codecs)
        for index, codec in enumerate(codecs):
            item = dialog.subtitles.item(index)
            assert codec in item.text()
            assert "unavailable" not in item.text()
            assert item.flags() & Qt.ItemFlag.ItemIsEnabled
            assert item.checkState() is Qt.CheckState.Checked
        dialog.accept()
        assert dialog.result() == dialog.DialogCode.Accepted
        assert dialog.selection is not None
        assert dialog.selection.subtitles == subtitles
    finally:
        dialog.close()


def test_language_change_preserves_pending_stream_choices(
    multiple_streams: Path,
    profile: DeviceProfile,
) -> None:
    dialog = MediaStreamsDialog(source(multiple_streams), "Movie", profile, None)
    translator = QTranslator()
    catalog = (
        Path(__file__).resolve().parents[3]
        / "src/iOpenPod/GUI/presentation/i18n/translations/iopenpod_de.qm"
    )
    try:
        dialog.show()
        wait_for(dialog.automatic.isEnabled)
        dialog.automatic.setChecked(False)
        dialog.audio.setCurrentIndex(2)
        dialog.captions.item(0).setCheckState(Qt.CheckState.Unchecked)
        assert translator.load(str(catalog))
        APPLICATION.installTranslator(translator)
        APPLICATION.processEvents()
        assert dialog.windowTitle() == "Streams auswählen"
        assert dialog.automatic.text() == "Streams automatisch auswählen"
        assert dialog.audio.currentIndex() == 2
        assert dialog.captions.item(0).checkState() is Qt.CheckState.Unchecked
    finally:
        APPLICATION.removeTranslator(translator)
        APPLICATION.processEvents()
        dialog.close()


def test_changed_source_is_rejected_before_inspection(video: Path) -> None:
    original = source(video)
    video.write_bytes(b"changed")
    controller = MediaStreamController()
    failures = QSignalSpy(controller.failed)
    ready = QSignalSpy(controller.inspected)
    assert controller.start(original)
    wait_for(lambda: not controller.busy)
    assert failures.count() == 1 and ready.count() == 0
    assert "changed after scanning" in str(failures.at(0)[0])


def test_cancelling_inspection_reaps_work_and_ignores_result(video: Path) -> None:
    started = Event()

    class Inspector(MediaInspector):
        def scan_metadata(
            self, source: HostPath, *, checkpoint: Callable[[], None]
        ) -> MediaScanMetadata:
            started.set()
            while True:
                checkpoint()
                time.sleep(0.01)

    controller = MediaStreamController(inspector=Inspector())
    ready = QSignalSpy(controller.inspected)
    failures = QSignalSpy(controller.failed)
    assert controller.start(source(video))
    wait_for(started.is_set)
    controller.cancel()
    wait_for(lambda: not controller.busy)
    assert ready.count() == failures.count() == 0


@pytest.mark.parametrize("track_id", (100, (1 << 62) + 100, (1 << 63) - 1))
@pytest.mark.parametrize("activation", ("mouse", "keyboard"))
def test_workspace_stages_dialog_choices_in_review(
    workspace: SyncWorkspace,
    tmp_path: Path,
    video: Path,
    track_id: int,
    activation: str,
) -> None:
    device = build_device(tmp_path)
    timer = QTimer()
    until = time.monotonic() + 5

    def choose() -> None:
        dialog = APPLICATION.activeModalWidget()
        if isinstance(dialog, MediaStreamsDialog):
            if dialog.automatic.isEnabled():
                dialog.automatic.setChecked(False)
                dialog.audio.setCurrentIndex(0)
                dialog.accept()
            elif time.monotonic() > until:
                dialog.reject()

    try:
        host = host_library(video)
        host = replace(
            host,
            snapshot=replace(
                host.snapshot,
                tracks=(replace(host.snapshot.tracks[0], track_id=track_id),),
            ),
        )
        item = SyncPlanItem(
            SyncPlanAction.ADD,
            SyncPlanMediaKind.TRACK,
            SyncPlanBasis.HOST_ONLY,
            "Movie",
            host_path=str(video),
        )
        workspace.load_comparison(
            host,
            SyncPlan((item,)),
            device.active,
            IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False),
        )
        workspace.selection.set_tracks_checked((track_id,), True)
        timer.timeout.connect(choose)
        timer.start(10)
        assert workspace.browser is not None
        page = workspace.browser.page_widgets[PageId.TRACKS]
        table = page.findChild(TrackTable)
        assert table is not None
        page.show()
        APPLICATION.processEvents()
        index = table.model().index(0, TrackColumn.SYNC_SELECTION)
        assert index.data(TrackRole.TRACK_ID) == track_id
        if activation == "mouse":
            QTest.mouseClick(
                table.viewport(),
                Qt.MouseButton.LeftButton,
                pos=SyncTrackDelegate.button_rect(table.visualRect(index)).center(),
            )
        else:
            table.setCurrentIndex(index)
            QTest.keyClick(table, Qt.Key.Key_Return)
        choice = workspace.selection.stream_selection(track_id)
        assert choice is not None and choice.video is not None and choice.audio is None
        assert index.data(TrackRole.STREAM_MANUAL) is True
        workspace.show_review()
        assert workspace.plan is not None
        assert workspace.plan.items[0].stream_selection == choice
        workspace.clear()
        workspace.load_comparison(
            host,
            SyncPlan((item,)),
            device.active,
            IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False),
        )
        assert workspace.selection.stream_selection(track_id) == choice
    finally:
        timer.stop()
        device.coordinator.close()


def test_stale_saved_choice_can_be_corrected(
    video: Path, profile: DeviceProfile
) -> None:
    metadata = MediaInspector().scan_metadata(HostPath(video), checkpoint=lambda: None)
    stale = MediaStreamSelection(replace(metadata.video_streams[0], index=99), None)
    dialog = MediaStreamsDialog(source(video), "Movie", profile, stale)
    try:
        dialog.show()
        wait_for(dialog.automatic.isEnabled)
        assert not dialog.automatic.isChecked()
        assert dialog.video.currentData() == metadata.video_streams[0]
        dialog.accept()
        assert dialog.result() == dialog.DialogCode.Accepted
        assert (
            dialog.selection is not None
            and dialog.selection.video == metadata.video_streams[0]
        )
    finally:
        dialog.close()


def test_failed_save_keeps_dialog_open_for_retry(
    video: Path, profile: DeviceProfile
) -> None:
    attempts = 0

    def save(_selection: MediaStreamSelection | None) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("Disk full")

    dialog = MediaStreamsDialog(
        source(video), "Movie", profile, None, save_selection=save
    )
    try:
        dialog.show()
        wait_for(dialog.automatic.isEnabled)
        dialog.automatic.setChecked(False)
        dialog.accept()
        assert dialog.isVisible() and dialog.result() != dialog.DialogCode.Accepted
        dialog.accept()
        assert dialog.result() == dialog.DialogCode.Accepted and attempts == 2
    finally:
        dialog.close()


def test_unreadable_preferences_prevent_workspace_execution(
    workspace: SyncWorkspace, tmp_path: Path, video: Path
) -> None:
    file = AtomicHostFile(tmp_path / "choices.json")
    file.replace_bytes(b"bad preferences")
    workspace.selection = SyncSelection(
        workspace, stream_preferences=MediaStreamPreferences(file)
    )
    device = build_device(tmp_path)
    try:
        workspace.load_comparison(
            host_library(video),
            SyncPlan(()),
            device.active,
            IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False),
        )
        requested = QSignalSpy(workspace.executeRequested)
        workspace._request_execution()  # pyright: ignore[reportPrivateUsage]
        assert requested.count() == 0 and workspace.selection.preference_error
    finally:
        device.coordinator.close()
