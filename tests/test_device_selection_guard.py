import sys
from types import SimpleNamespace
from typing import Any, cast

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QPixmap

from iopenpod.application.controllers import StartupDeviceRestoreController
from iopenpod.application.runtime import DeviceManager
from iopenpod.device.info import (
    DeviceInfo,
    UnidentifiedDeviceError,
    clear_current_device,
    get_current_device,
    set_current_device,
)
from iopenpod.gui import device_warnings
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
    assert "Review Linux Setup" in button_labels
    assert "/etc/udev/rules.d/61-iopenpod.rules" in message.detailedText()
    assert "udevadm trigger" in message.detailedText()
    assert 'TAG+="uaccess"' not in message.detailedText()


def test_linux_setup_commands_are_visible_before_copying(qtbot) -> None:
    commands = "sudo install example\nsudo udevadm control --reload-rules\n"
    dialog = device_warnings.LinuxIdentitySetupReviewDialog(None, commands)
    qtbot.addWidget(dialog)

    assert dialog.commands.isReadOnly()
    assert dialog.commands.toPlainText() == commands
    assert dialog.commands.accessibleName() == "Linux iPod host setup commands"


def test_picker_automatically_offers_linux_setup_once_per_ipod(
    monkeypatch,
    qtbot,
    tmp_path,
) -> None:
    from iopenpod.device.virtual import create_virtual_ipod

    ipod = create_virtual_ipod(tmp_path, "MB565")
    ipod.model_number = ""
    ipod.serial = ""
    warnings: list[object] = []
    monkeypatch.setattr(devicePicker.sys, "platform", "linux")
    monkeypatch.setattr(
        devicePicker,
        "show_unidentified_ipod_warning",
        lambda _parent, device: warnings.append(device),
    )
    device_warnings._AUTOMATIC_WARNING_KEYS.clear()
    dialog = SimpleNamespace()

    DevicePickerDialog._offer_linux_identity_setup(
        cast(Any, dialog),
        [ipod],
    )
    DevicePickerDialog._offer_linux_identity_setup(
        cast(Any, dialog),
        [ipod],
    )

    assert warnings == [ipod]
