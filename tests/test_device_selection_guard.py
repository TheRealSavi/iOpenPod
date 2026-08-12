import sys
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QPixmap

from iopenpod.application.controllers import StartupDeviceRestoreController
from iopenpod.application.runtime import DeviceManager
from iopenpod.device import info as device_info
from iopenpod.device import scanner as device_scanner
from iopenpod.device.info import (
    DeviceInfo,
    UnidentifiedDeviceError,
    clear_current_device,
    get_current_device,
    has_safe_device_profile,
    set_current_device,
)
from iopenpod.gui import device_warnings
from iopenpod.gui.styles import paint_css
from iopenpod.gui.widgets import devicePicker
from iopenpod.gui.widgets.devicePicker import DeviceCard, DevicePickerDialog


class _FakeCard:
    def __init__(self, ipod: object) -> None:
        self.ipod = ipod
        self.selected = True

    def setSelected(self, selected: bool) -> None:
        self.selected = selected


class _FakeButton:
    def __init__(self) -> None:
        self.enabled = True
        self.text = ""

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def setText(self, text: str) -> None:
        self.text = text


class _FakeDeviceManager:
    def __init__(self) -> None:
        self.device_path: str | None = None
        self.discovered_ipod: object | None = None


def _unidentified_ipod() -> SimpleNamespace:
    return SimpleNamespace(
        path="E:\\",
        mount_name="E:",
        model_number="",
        model_family="iPod",
        generation="",
        color="",
    )


def test_active_device_store_rejects_ipod_without_model_number() -> None:
    clear_current_device()

    with pytest.raises(UnidentifiedDeviceError):
        set_current_device(DeviceInfo(path="E:\\", model_family="iPod"))

    assert get_current_device() is None


def test_safe_profile_rejects_uncatalogued_model_number() -> None:
    ipod = DeviceInfo(
        path="/Volumes/iPod",
        model_number="NOT-A-REAL-MODEL",
        model_family="iPod",
        generation="3rd Gen",
    )

    assert not has_safe_device_profile(ipod)


def test_safe_profile_rejects_exact_model_without_consumable_identity_fields() -> None:
    ipod = DeviceInfo(
        path="/Volumes/iPod",
        model_number="MA005",
        model_family="",
        generation="",
    )

    assert not has_safe_device_profile(ipod)


def _live_3g_ipod() -> DeviceInfo:
    ipod = DeviceInfo(
        path="/Volumes/iPod",
        mount_name="iPod",
        model_family="iPod",
        generation="3rd Gen",
        usb_pid=0x1201,
    )
    ipod._field_sources.update({
        "model_family": "usb_pid",
        "generation": "usb_pid",
        "usb_pid": "ioreg",
    })
    ipod._live_usb_pid = 0x1201
    return ipod


def test_safe_profile_rejects_exact_model_that_conflicts_with_live_pid() -> None:
    ipod = DeviceInfo(
        path="/Volumes/iPod",
        model_number="MA005",
        model_family="iPod Nano",
        generation="1st Gen",
        usb_pid=0x1201,
    )
    ipod._field_sources["usb_pid"] = "ioreg"
    ipod._live_usb_pid = 0x1201

    assert not has_safe_device_profile(ipod)


def test_safe_profile_rejects_stale_pid_that_conflicts_with_current_hardware() -> None:
    ipod = DeviceInfo(
        path="/Volumes/iPod",
        model_number="MC297",
        model_family="iPod Classic",
        generation="7th Gen",
        usb_pid=0x1261,
    )
    ipod._field_sources["usb_pid"] = "sysinfo"
    ipod._live_usb_pid = 0x1247

    assert not has_safe_device_profile(ipod)


def test_linux_hardware_enrichment_marks_conflicting_pid_as_current(
    monkeypatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        device_scanner,
        "_probe_hardware_linux",
        lambda _path: {"usb_pid": 0x1201},
    )
    ipod = DeviceInfo(
        path="/media/ipod",
        model_number="MA005",
        model_family="iPod Nano",
        generation="1st Gen",
        usb_pid=0x1261,
    )
    ipod._field_sources["usb_pid"] = "sysinfo"

    device_info._enrich_from_hardware_probe(ipod)

    assert ipod._live_usb_pid == 0x1201
    assert not has_safe_device_profile(ipod)


def test_windows_hardware_enrichment_marks_recovery_pid_as_current(
    monkeypatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(device_scanner, "_setup_win32_prototypes", lambda: None)
    monkeypatch.setattr(
        device_scanner,
        "_identify_via_direct_ioctl",
        lambda _drive: {"usb_pid": 0x1247},
    )
    ipod = DeviceInfo(
        path="E:\\",
        model_number="MC297",
        model_family="iPod Classic",
        generation="7th Gen",
        usb_pid=0x1261,
    )
    ipod._field_sources["usb_pid"] = "sysinfo"

    device_info._enrich_from_hardware_probe(ipod)

    assert ipod._live_usb_pid == 0x1247
    assert not has_safe_device_profile(ipod)


def test_safe_profile_accepts_exact_color_model_for_shared_photo_pid() -> None:
    ipod = DeviceInfo(
        path="/Volumes/iPod",
        model_number="MA079",
        model_family="iPod",
        generation="4th Gen (color)",
        usb_pid=0x1204,
    )
    ipod._field_sources["usb_pid"] = "ioreg"
    ipod._live_usb_pid = 0x1204

    assert has_safe_device_profile(ipod)


def test_active_device_store_accepts_capability_equivalent_legacy_generation() -> None:
    """A storage-upgraded 3G has one safe sync profile despite unknown capacity."""

    clear_current_device()
    ipod = _live_3g_ipod()
    ipod.capacity = "120GB"
    ipod.color = "White"

    assert has_safe_device_profile(ipod)
    set_current_device(ipod)

    assert get_current_device() is ipod
    clear_current_device()


def test_safe_profile_rejects_live_pid_without_concrete_generation() -> None:
    """Writers still need a concrete family/generation profile to consume."""

    ipod = DeviceInfo(
        path="/Volumes/iPod",
        model_family="iPod",
        generation="",
        usb_pid=0x1202,
    )
    ipod._field_sources.update({
        "model_family": "usb_pid",
        "usb_pid": "ioreg",
    })
    ipod._live_usb_pid = 0x1202

    assert not has_safe_device_profile(ipod)


def test_safe_profile_rejects_coarse_live_pid_when_candidates_differ() -> None:
    """The shared 5G/5.5G PID cannot choose the write profile safely."""

    ipod = DeviceInfo(
        path="/Volumes/iPod",
        model_family="iPod",
        generation="",
        usb_pid=0x1209,
    )
    ipod._field_sources.update({
        "model_family": "usb_pid",
        "usb_pid": "ioreg",
    })
    ipod._live_usb_pid = 0x1209

    assert not has_safe_device_profile(ipod)


def test_safe_profile_rejects_recovery_pid_even_with_exact_model() -> None:
    ipod = DeviceInfo(
        path="/Volumes/iPod",
        model_number="MC297",
        model_family="iPod Classic",
        generation="7th Gen",
        usb_pid=0x1247,
    )
    ipod._field_sources["usb_pid"] = "ioreg"
    ipod._live_usb_pid = 0x1247

    assert not has_safe_device_profile(ipod)


def test_active_device_store_rejects_generation_with_variant_specific_profile() -> None:
    clear_current_device()
    ipod = DeviceInfo(
        path="/Volumes/iPod",
        model_family="iPod",
        generation="5th Gen",
    )

    assert not has_safe_device_profile(ipod)
    with pytest.raises(UnidentifiedDeviceError):
        set_current_device(ipod)

    assert get_current_device() is None


def test_safe_profile_rejects_3g_identity_without_live_pid_provenance() -> None:
    ipod = DeviceInfo(
        path="/Volumes/iPod",
        model_family="iPod",
        generation="3rd Gen",
        usb_pid=0x1201,
    )
    ipod._field_sources.update({
        "model_family": "usb_pid",
        "generation": "usb_pid",
        "usb_pid": "sysinfo",
    })

    assert not has_safe_device_profile(ipod)


def test_safe_profile_rejects_persisted_ioreg_source_without_current_observation() -> None:
    ipod = DeviceInfo(
        path="/Volumes/iPod",
        model_family="iPod",
        generation="3rd Gen",
        usb_pid=0x1201,
    )
    # Authority files persist field provenance, but cannot prove this PID was
    # observed from the device during the current scan.
    ipod._field_sources.update({
        "model_family": "usb_pid",
        "generation": "usb_pid",
        "usb_pid": "ioreg",
    })

    assert not has_safe_device_profile(ipod)


def test_safe_profile_rejects_3g_identity_with_conflicting_pid() -> None:
    ipod = DeviceInfo(
        path="/Volumes/iPod",
        model_family="iPod",
        generation="3rd Gen",
        usb_pid=0x1202,
    )
    ipod._field_sources.update({
        "model_family": "usb_pid",
        "generation": "usb_pid",
        "usb_pid": "ioreg",
    })
    ipod._live_usb_pid = 0x1202

    assert not has_safe_device_profile(ipod)


def test_device_manager_rejects_unidentified_ipod_before_activation(qtbot) -> None:
    clear_current_device()
    manager = DeviceManager()
    ipod = _unidentified_ipod()

    with pytest.raises(UnidentifiedDeviceError):
        manager.discovered_ipod = cast(Any, ipod)

    assert manager.discovered_ipod is None
    assert manager.device_path is None
    assert get_current_device() is None


def test_device_manager_rejects_path_without_identified_ipod(qtbot) -> None:
    manager = DeviceManager()

    with pytest.raises(UnidentifiedDeviceError):
        manager.device_path = "E:\\"

    assert manager.device_path is None


def test_device_manager_initializes_missing_database_for_identified_device(qtbot, tmp_path) -> None:
    """Selecting an identified iPod repairs an absent iTunes database layout."""

    clear_current_device()
    (tmp_path / "iPod_Control").mkdir()
    (tmp_path / "iPodInfo.json").write_text("{}", encoding="utf-8")
    manager = DeviceManager()
    ipod = DeviceInfo(
        path=str(tmp_path),
        mount_name="NANO",
        model_number="MA005",
        model_family="iPod Nano",
        generation="1st Gen",
    )

    manager.discovered_ipod = ipod
    manager.device_path = str(tmp_path)

    database = tmp_path / "iPod_Control" / "iTunes" / "iTunesDB"
    assert database.read_bytes()[:4] == b"mhbd"


def test_device_manager_leaves_hashed_device_uninitialized_without_guid(qtbot, tmp_path) -> None:
    """A selected device must not receive an iTunesDB it cannot validate."""

    clear_current_device()
    (tmp_path / "iPod_Control").mkdir()
    (tmp_path / "iPodInfo.json").write_text("{}", encoding="utf-8")
    manager = DeviceManager()
    ipod = DeviceInfo(
        path=str(tmp_path),
        mount_name="CLASSIC",
        model_number="MC297",
        model_family="iPod Classic",
        generation="7th Gen",
    )

    manager.discovered_ipod = ipod
    manager.device_path = str(tmp_path)

    assert not (tmp_path / "iPod_Control" / "iTunes" / "iTunesDB").exists()


def test_device_manager_uses_selected_device_database_format(qtbot, tmp_path) -> None:
    clear_current_device()
    (tmp_path / "iPod_Control").mkdir()
    (tmp_path / "iPodInfo.json").write_text("{}", encoding="utf-8")
    manager = DeviceManager()
    ipod = DeviceInfo(
        path=str(tmp_path),
        mount_name="NANO",
        model_number="MC060",
        model_family="iPod Nano",
        generation="5th Gen",
        hash_info_iv=b"i" * 16,
        hash_info_rndpart=b"r" * 12,
    )

    manager.discovered_ipod = ipod
    manager.device_path = str(tmp_path)

    database = tmp_path / "iPod_Control" / "iTunes" / "iTunesCDB"
    assert database.read_bytes()[:4] == b"mhbd"
    assert not (database.parent / "iTunesDB").exists()


def test_picker_warns_and_does_not_select_unidentified_ipod(monkeypatch) -> None:
    ipod = _unidentified_ipod()
    card = _FakeCard(ipod)
    select_button = _FakeButton()
    warnings: list[object] = []
    monkeypatch.setattr(
        devicePicker,
        "show_unidentified_ipod_warning",
        lambda _parent, rejected: warnings.append(rejected),
    )
    dialog = SimpleNamespace(
        selected_path="D:\\",
        selected_ipod=object(),
        _cards=[card],
        _select_btn=select_button,
    )

    DevicePickerDialog._on_card_clicked(cast(Any, dialog), ipod)

    assert dialog.selected_path == ""
    assert dialog.selected_ipod is None
    assert card.selected is False
    assert select_button.enabled is False
    assert select_button.text == "Select"
    assert warnings == [ipod]


def test_picker_selects_live_pid_with_uniform_write_profile() -> None:
    ipod = _live_3g_ipod()
    card = _FakeCard(ipod)
    select_button = _FakeButton()
    dialog = SimpleNamespace(
        selected_path="",
        selected_ipod=None,
        _cards=[card],
        _select_btn=select_button,
    )

    DevicePickerDialog._on_card_clicked(cast(Any, dialog), ipod)

    assert dialog.selected_path == "/Volumes/iPod"
    assert dialog.selected_ipod is ipod
    assert card.selected is True
    assert select_button.enabled is True
    assert select_button.text == "Select (iPod)"


def test_device_card_can_be_deleted_by_its_click_handler(monkeypatch, qtbot) -> None:
    """A nested dialog may process a scan refresh before the click returns."""
    monkeypatch.setattr(devicePicker, "get_ipod_image", lambda *_args: QPixmap())
    ipod = SimpleNamespace(
        model_family="iPod",
        generation="Classic",
        color="",
        ipod_name="",
        display_name="iPod Classic",
    )
    card = DeviceCard(ipod)
    card.setSelected(True)
    assert paint_css("device.picker.selected_fill") in card.styleSheet()
    assert paint_css("device.picker.selected_border") in card.styleSheet()

    def delete_card(_ipod: object) -> None:
        card.setParent(None)
        card.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    card.clicked.connect(delete_card)
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    card.mousePressEvent(event)


def test_device_card_can_be_deleted_by_its_double_click_handler(monkeypatch, qtbot) -> None:
    monkeypatch.setattr(devicePicker, "get_ipod_image", lambda *_args: QPixmap())
    ipod = SimpleNamespace(
        model_family="iPod",
        generation="Classic",
        color="",
        ipod_name="",
        display_name="iPod Classic",
    )
    card = DeviceCard(ipod)

    def delete_card(_ipod: object) -> None:
        card.setParent(None)
        card.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    card.clicked.connect(delete_card)
    event = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        QPointF(10, 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    card.mouseDoubleClickEvent(event)


def test_fast_resume_rejects_unidentified_ipod_and_requests_warning(qtbot) -> None:
    manager = _FakeDeviceManager()
    controller = StartupDeviceRestoreController(cast(Any, manager), "E:\\")
    rejected: list[tuple[str, object]] = []
    controller.identification_rejected.connect(
        lambda path, ipod: rejected.append((path, ipod))
    )
    ipod = _unidentified_ipod()

    controller._on_found("E:\\", ipod)

    assert manager.device_path is None
    assert manager.discovered_ipod is None
    assert rejected == [("E:\\", ipod)]


def test_fast_resume_accepts_live_pid_with_uniform_write_profile(qtbot) -> None:
    manager = _FakeDeviceManager()
    controller = StartupDeviceRestoreController(cast(Any, manager), "/Volumes/iPod")
    rejected: list[tuple[str, object]] = []
    controller.identification_rejected.connect(
        lambda path, ipod: rejected.append((path, ipod))
    )
    ipod = _live_3g_ipod()

    controller._on_found("/Volumes/iPod", ipod)

    assert manager.discovered_ipod is ipod
    assert manager.device_path == "/Volumes/iPod"
    assert rejected == []


def test_linux_unidentified_warning_offers_safe_host_setup(
    monkeypatch,
    qtbot,
) -> None:
    shown_messages = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        device_warnings.QMessageBox,
        "exec",
        lambda message: shown_messages.append(message) or 0,
    )
    ipod = SimpleNamespace(
        path="/media/johng/IPOD",
        mount_name="IPOD",
        model_number="",
        firewire_guid="000A2700138A422D",
        usb_pid=0x1261,
    )

    device_warnings.show_unidentified_ipod_warning(None, ipod)

    assert len(shown_messages) == 1
    message = shown_messages[0]
    button_labels = {button.text() for button in message.buttons()}
    assert button_labels == {"View Setup Commands", "Report Issue", "Close"}
    assert message.detailedText() == ""


def test_linux_setup_commands_are_visible_before_copying(qtbot) -> None:
    commands = "sudo install example\nsudo udevadm control --reload-rules\n"
    dialog = device_warnings.LinuxIdentitySetupReviewDialog(None, commands)
    qtbot.addWidget(dialog)

    assert dialog.commands.isReadOnly()
    assert dialog.commands.toPlainText() == commands
    assert dialog.commands.accessibleName() == "Linux iPod host setup commands"
    assert "close this window to scan" in dialog._next_step_label.text().lower()
    assert {button.text() for button in dialog._buttons.buttons()} == {
        "Copy Commands",
        "Done",
    }


def test_linux_setup_refreshes_device_picker_when_review_is_closed(
    qtbot,
) -> None:
    commands = "sudo install example\n"
    refreshes: list[None] = []
    dialog = device_warnings.LinuxIdentitySetupReviewDialog(
        None,
        commands,
        after_close=lambda: refreshes.append(None),
    )
    qtbot.addWidget(dialog)

    dialog.reject()

    assert refreshes == [None]


def test_picker_automatically_offers_linux_setup_once_per_ipod(
    monkeypatch,
    qtbot,
    tmp_path,
) -> None:
    from iopenpod.device.virtual import create_virtual_ipod

    ipod = create_virtual_ipod(tmp_path, "MB565")
    ipod.model_number = ""
    ipod.serial = ""
    warnings: list[tuple[object, Callable[[], None]]] = []
    monkeypatch.setattr(devicePicker.sys, "platform", "linux")
    monkeypatch.setattr(
        devicePicker,
        "show_unidentified_ipod_warning",
        lambda _parent, device, **kwargs: warnings.append((device, kwargs["after_close"])),
    )
    device_warnings._AUTOMATIC_WARNING_KEYS.clear()
    rescans: list[None] = []
    dialog = SimpleNamespace(_start_scan=lambda: rescans.append(None))

    DevicePickerDialog._offer_linux_identity_setup(
        cast(Any, dialog),
        [ipod],
    )
    DevicePickerDialog._offer_linux_identity_setup(
        cast(Any, dialog),
        [ipod],
    )

    assert len(warnings) == 1
    warned_ipod, after_close = warnings[0]
    assert warned_ipod is ipod
    after_close()
    assert rescans == [None]
