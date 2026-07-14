from types import SimpleNamespace
from typing import Any, cast

import pytest

from iopenpod.application.controllers import StartupDeviceRestoreController
from iopenpod.application.runtime import DeviceManager
from iopenpod.device.info import (
    DeviceInfo,
    UnidentifiedDeviceError,
    clear_current_device,
    get_current_device,
    set_current_device,
)
from iopenpod.gui.widgets import devicePicker
from iopenpod.gui.widgets.devicePicker import DevicePickerDialog


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
