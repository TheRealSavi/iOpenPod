"""Compose exact Registry identities with independently qualified Calendar codecs."""

from device_registry import ExtrasSupport, FirmwareTarget
from iPodDB.calendar import CalendarProfile

_PROFILES = {
    FirmwareTarget.MINI_1_1_4_1: CalendarProfile.MINI_1_1_4_1,
    FirmwareTarget.MINI_2_1_4_1: CalendarProfile.MINI_2_1_4_1,
    FirmwareTarget.NANO_1_1_3_1: CalendarProfile.NANO_1_1_3_1,
    FirmwareTarget.NANO_3_1_1_3: CalendarProfile.NANO_3_1_1_3,
    FirmwareTarget.NANO_4_1_0_4: CalendarProfile.NANO_4_1_0_4,
    FirmwareTarget.NANO_5_1_0_2: CalendarProfile.NANO_5_1_0_2,
    FirmwareTarget.VIDEO_1_3: CalendarProfile.VIDEO_1_3,
    FirmwareTarget.CLASSIC_6_1_1_2: CalendarProfile.CLASSIC_6_1_1_2,
    FirmwareTarget.CLASSIC_120GB_2_0_1: CalendarProfile.CLASSIC_120GB_2_0_1,
    FirmwareTarget.CLASSIC_UPDATER_35_2_0_4: CalendarProfile.CLASSIC_UPDATER_35_2_0_4,
    FirmwareTarget.CLASSIC_UPDATER_38_2_0_5: CalendarProfile.CLASSIC_UPDATER_38_2_0_5,
}


def calendar_profile(support: ExtrasSupport | None) -> CalendarProfile:
    if support is None or support.calendar_firmware is None:
        return CalendarProfile.UNKNOWN
    return _PROFILES.get(support.calendar_firmware, CalendarProfile.UNKNOWN)
