"""Device Summary mod drafts remain separate from observed installed builds."""

from collections.abc import Iterator
from dataclasses import replace

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton
from tests.iOpenPod.GUI.test_device_summary_page import APPLICATION, summary_active_ipod

from device_registry import FirmwareTarget
from iOpenPod.app.firmware.capture import RegistryObservation, RegistryStatus
from iOpenPod.app.firmware.catalog import BASES, CATALOG, CORE_ID, PLATFORM_VERSION
from iOpenPod.app.firmware.planner import plan_firmware
from iOpenPod.app.firmware.registry import RegistryMod, registry_for_build
from iOpenPod.app.models.device import DeviceCandidateId
from iOpenPod.GUI.widgets.firmware_mods import FirmwareModsPanel


@pytest.fixture
def panel() -> Iterator[FirmwareModsPanel]:
    widget = FirmwareModsPanel()
    active = replace(
        summary_active_ipod(), firmware_target=FirmwareTarget.CLASSIC_120GB_2_0_1
    )
    widget.set_active_ipod(active)
    widget.show()
    APPLICATION.processEvents()
    try:
        yield widget
    finally:
        widget.close()


def choice(panel: FirmwareModsPanel, mod_id: str) -> QCheckBox:
    checkbox = panel.findChild(QCheckBox, "firmwareMod_org.iopenpod." + mod_id)
    assert checkbox is not None
    return checkbox


def test_selecting_game_includes_dependency_but_does_not_claim_installation(
    panel: FirmwareModsPanel,
) -> None:
    game = choice(panel, "parachute")
    homebrew = choice(panel, "homebrew")
    game.click()
    assert homebrew.isChecked() and not homebrew.isEnabled()
    plan = panel.build_plan
    assert plan is not None
    assert tuple(mod.id for mod in plan.mods) == (
        CORE_ID,
        "org.iopenpod.homebrew",
        "org.iopenpod.parachute",
    )
    label = panel.findChild(QLabel, "firmwarePlatformVersion")
    assert label is not None and label.text().endswith("Unavailable")
    game.click()
    assert not homebrew.isChecked() and homebrew.isEnabled()
    assert panel.build_plan is not None
    assert tuple(mod.id for mod in panel.build_plan.mods) == (CORE_ID,)


def test_drafts_survive_retranslation_but_not_device_changes(
    panel: FirmwareModsPanel,
) -> None:
    choice(panel, "dark-mode").click()
    before = panel.build_plan
    APPLICATION.sendEvent(panel, QEvent(QEvent.Type.LanguageChange))
    assert panel.build_plan == before
    active = replace(
        summary_active_ipod(), firmware_target=FirmwareTarget.CLASSIC_120GB_2_0_1
    )
    panel.set_active_ipod(active)
    assert panel.build_plan == before
    panel.set_active_ipod(
        replace(
            active, candidate=replace(active.candidate, id=DeviceCandidateId("another"))
        )
    )
    assert not choice(panel, "dark-mode").isChecked()
    panel.set_active_ipod(None)
    assert panel.build_plan is None and not panel.isVisible()


def test_busy_and_unknown_target_cannot_review_or_select(
    panel: FirmwareModsPanel,
) -> None:
    panel.set_busy(True)
    assert not choice(panel, "parachute").isEnabled()
    review = panel.findChild(QPushButton, "reviewFirmwareBuild")
    assert review is not None and not review.isEnabled()
    panel.set_busy(False)
    panel.set_active_ipod(summary_active_ipod())
    assert not review.isEnabled()
    assert panel.build_plan is None


def test_recorded_version_is_separate_and_unknown_installed_mod_can_be_explicitly_removed(
    panel: FirmwareModsPanel,
) -> None:
    base = BASES[FirmwareTarget.CLASSIC_120GB_2_0_1]
    plan = plan_firmware(base, PLATFORM_VERSION, CATALOG, (CORE_ID,))
    registry = registry_for_build(plan, "a" * 64)
    unknown = RegistryMod("org.external.test", "1.0.0", "External Mod")
    registry = replace(
        registry,
        platform_version="7.26.0",
        mods=(*registry.mods, unknown),
        requested=(*registry.requested, unknown.id),
    )
    active = replace(
        summary_active_ipod(),
        firmware_target=FirmwareTarget.CLASSIC_120GB_2_0_1,
        firmware_registry=RegistryObservation(RegistryStatus.AVAILABLE, registry),
    )
    panel.set_active_ipod(active)
    label = panel.findChild(QLabel, "firmwarePlatformVersion")
    assert label is not None and label.text().endswith("7.26.0")
    assert active.firmware_version == "2.0.1"
    assert panel.build_plan is None
    clear = panel.findChild(QPushButton, "clearFirmwareSelection")
    assert clear is not None and clear.isEnabled()
    clear.click()
    assert panel.build_plan is not None
    assert label.text().endswith("7.26.0")
    installed = panel.findChild(QLabel, "firmwareInstalledMods")
    assert installed is not None and "External Mod" in installed.text()
