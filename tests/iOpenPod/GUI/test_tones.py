"""Tone navigation, single-Track action and review before saving."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QTreeWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context
from tests.iOpenPod.GUI.extras_test_support import ExtrasTestController, find_widget

from device_registry import DEFAULT_DEVICE_REGISTRY
from iOpenPod.app.models.extras import AlarmSound, AlarmToneItem, ExtrasCatalog
from iOpenPod.app.tone_conversion import ToneArrangement
from iOpenPod.app.tone_conversion_controller import ToneConversionController
from iOpenPod.app.tone_preview import TonePreview
from iOpenPod.GUI.dialogs.tone_conversion import ToneConversionDialog
from iOpenPod.GUI.navigation import PageId, page_supported
from iOpenPod.GUI.pages.tones_page import TonesPage
from iOpenPod.GUI.widgets.track_actions import TrackActions, TrackSelection
from iPodDB.alarms import AlarmToneNote
from iPodDB.library import Track, TrackMetadata

NOTES = (AlarmToneNote(262, 500), AlarmToneNote(330, 500), AlarmToneNote(392, 500))
TRACK = Track(
    1,
    "Morning melody",
    "Artist",
    "Album",
    180000,
    metadata=TrackMetadata(location=":iPod_Control:Music:F00:song.mp3"),
)


class ToneTestController(ExtrasTestController):
    def __init__(self) -> None:
        super().__init__(
            ExtrasCatalog(
                tones=(AlarmToneItem("builtin:beep", "Beep", NOTES, builtin=True),),
                alarm_sounds=(
                    AlarmSound(AlarmSound.Kind.BEEP, "Beep", tone_name="Beep"),
                ),
                can_create_tone=True,
            )
        )
        self.created: list[tuple[str, tuple[AlarmToneNote, ...]]] = []

    def create_tone(self, name: str, notes: tuple[AlarmToneNote, ...]) -> bool:
        self.created.append((name, notes))
        self.working = True
        self.changed.emit()
        return True


class ConversionTestController(ToneConversionController):
    def __init__(self) -> None:
        QObject.__init__(self)
        self.arrangement = ToneArrangement(NOTES, 45.0, 46.5)
        self.message = ""
        self.error = ""
        self.working = False
        self.cancelled = False

    @property
    def busy(self) -> bool:
        return self.working

    def cancel(self) -> None:
        self.cancelled = True


def test_page_is_available_only_for_custom_tone_models() -> None:
    for model, expected in [
        ("MB565", True),
        ("MA978", True),
        ("MB598", True),
        ("MC027", True),
        ("MA004", False),
        ("MC525", False),
    ]:
        profile = next(
            p for p in DEFAULT_DEVICE_REGISTRY.profiles if p.model_number == model
        )
        assert page_supported(PageId.TONES, profile) is expected
    assert not page_supported(PageId.TONES, None)


def test_page_displays_saved_content_names_and_preview_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    played: list[tuple[AlarmToneNote, ...]] = []

    def play(_self: TonePreview, notes: tuple[AlarmToneNote, ...]) -> None:
        played.append(notes)

    monkeypatch.setattr(TonePreview, "play", play)
    controller = ToneTestController()
    controller.view = replace(
        controller.view,
        tones=(
            *controller.view.tones,
            AlarmToneItem("opaque.tone", "Morning melody", NOTES),
        ),
    )
    page = TonesPage(controller)
    try:
        page.show()
        APPLICATION.processEvents()
        assert page.findChild(QPushButton, "tonesRefresh") is None
        assert not any(
            "Make a short melody" in label.text() for label in page.findChildren(QLabel)
        )
        tree = find_widget(page, QTreeWidget, "tonesList")
        assert tree.topLevelItemCount() == 2
        custom = tree.topLevelItem(1)
        assert custom is not None and custom.text(0) == "Morning melody"
        tree.setCurrentItem(custom)
        assert find_widget(page, QPushButton, "tonePreview").isEnabled()
        tree.setFocus()
        QTest.keyClick(tree, Qt.Key.Key_Return)
        assert played == [NOTES]
        controller.view = ExtrasCatalog()
        controller.current = None
        controller.changed.emit()
        assert tree.topLevelItemCount() == 0
        assert not find_widget(page, QPushButton, "tonePreview").isEnabled()
    finally:
        page.close()


def test_conversion_review_validates_name_and_saves_only_explicitly() -> None:
    extras, conversion = ToneTestController(), ConversionTestController()
    dialog = ToneConversionDialog(TRACK, conversion, extras)
    try:
        dialog.show()
        APPLICATION.processEvents()
        save = find_widget(dialog, QPushButton, "toneSave")
        name = find_widget(dialog, QLineEdit, "toneName")
        status = find_widget(dialog, QLabel, "toneConversionStatus")
        assert not status.isVisible()
        assert not any(
            "A short melody" in label.text() for label in dialog.findChildren(QLabel)
        )
        assert save.isEnabled() and not extras.created
        name.setText("Beep")
        assert not save.isEnabled()
        name.setText("Morning")
        QTest.mouseClick(save, Qt.MouseButton.LeftButton)
        assert extras.created == [("Morning", NOTES)]
        assert not save.isEnabled()
        assert status.isVisible() and status.text() == "Saving tone…"
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert dialog.isVisible()
        extras.view = replace(
            extras.view,
            tones=(*extras.view.tones, AlarmToneItem("new.tone", "Morning", NOTES)),
        )
        extras.working = False
        extras.changed.emit()
        assert not dialog.isVisible()
    finally:
        dialog.close()


def test_cancel_and_device_change_never_publish_a_tone() -> None:
    extras, conversion = ToneTestController(), ConversionTestController()
    dialog = ToneConversionDialog(TRACK, conversion, extras)
    dialog.show()
    extras.current = None
    extras.changed.emit()
    assert not dialog.isVisible() and conversion.cancelled and not extras.created


def test_track_menu_offers_conversion_for_single_saved_music_track() -> None:
    context = build_context()
    extras = ToneTestController()
    assert extras.current is not None
    active = replace(
        extras.current, library=replace(extras.current.library, tracks=(TRACK,))
    )
    context.device_controller.finish_library_save(active)
    context.library_workspace.load(active.library)
    page = TonesPage(extras)
    actions = TrackActions(
        context.library_workspace,
        context.playback_controller,
        page,
        device_controller=context.device_controller,
    )
    selection = TrackSelection((TRACK,), context.library_workspace.edit_revision)
    try:
        menu = actions.build_menu(selection)
        action = next(
            action for action in menu.actions() if action.text() == "Convert to tone…"
        )
        assert action.isEnabled()
        emitted: list[object] = []
        actions.toneConversionRequested.connect(emitted.append)
        action.trigger()
        assert emitted == [TRACK]
        multiple = actions.build_menu(replace(selection, tracks=(TRACK, TRACK)))
        assert not next(
            action
            for action in multiple.actions()
            if action.text() == "Convert to tone…"
        ).isEnabled()
    finally:
        page.close()
        context.shutdown()
