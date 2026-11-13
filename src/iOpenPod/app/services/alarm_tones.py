"""Capture qualified native tone names through the selected Storage session."""

from collections.abc import Callable
from dataclasses import dataclass

from device_registry import ExtrasSupport, FirmwareTarget
from iOpenPod.app.display_text import source_text
from iOpenPod.app.models.extras import AlarmSound
from iPodDB.alarms import MAX_ALARM_TONE_BYTES, parse_alarm_tone, saved_alarm_tone_name
from iPodDB.preferences import NamedPreferencesProfile, PreferencesProfile
from storage import (
    DeviceEntryKind,
    DevicePath,
    FilePrecondition,
    FilesystemSession,
    StorageError,
)

TONES_PATH = DevicePath("iPod_Control/Tones")


@dataclass(frozen=True, slots=True)
class CapturedAlarmTones:
    sounds: tuple[AlarmSound, ...] = ()
    dependencies: tuple[FilePrecondition, ...] = ()
    inventory: tuple[str, ...] | None = None
    issues: tuple[str, ...] = ()


def tone_inventory(session: FilesystemSession) -> tuple[str, ...]:
    return (
        tuple(
            sorted(
                str(entry.path)
                for entry in session.list_directory(TONES_PATH)
                if entry.kind is DeviceEntryKind.FILE
                and not entry.path.name.startswith(".")
                and entry.path.name != "Beep.tone"
            )
        )
        if session.exists(TONES_PATH)
        else ()
    )


def capture_alarm_tones(
    session: FilesystemSession, support: ExtrasSupport, checkpoint: Callable[[], None]
) -> CapturedAlarmTones:
    profiles = {
        FirmwareTarget.CLASSIC_6_1_1_2: PreferencesProfile.CLASSIC_6_1_1_2,
        FirmwareTarget.CLASSIC_120GB_2_0_1: PreferencesProfile.CLASSIC_120GB_2_0_1,
        FirmwareTarget.CLASSIC_UPDATER_35_2_0_4: PreferencesProfile.CLASSIC_UPDATER_35_2_0_4,
        FirmwareTarget.CLASSIC_UPDATER_38_2_0_5: PreferencesProfile.CLASSIC_UPDATER_38_2_0_5,
        FirmwareTarget.NANO_3_1_1_3: PreferencesProfile.NANO_3_1_1_3,
        FirmwareTarget.NANO_4_1_0_4: PreferencesProfile.NANO_4_1_0_4,
    }
    profile: PreferencesProfile | NamedPreferencesProfile | None = (
        profiles.get(support.alarm_firmware) if support.alarm_firmware else None
    )
    if support.alarm_firmware is FirmwareTarget.NANO_5_1_0_2:
        profile = NamedPreferencesProfile.NANO_5_1_0_2
    if profile is None:
        return CapturedAlarmTones()
    path = DevicePath(
        "iPod_Control/Device/iPodSettings.xml"
        if isinstance(profile, NamedPreferencesProfile)
        else "iPod_Control/Device/Preferences"
    )
    try:
        checkpoint()
        if not session.exists(path):
            return CapturedAlarmTones(
                issues=(
                    "The saved iPod language is unavailable; tone choices could not be verified.",
                )
            )
        source = session.read_snapshot(path, max_bytes=MAX_ALARM_TONE_BYTES)
        default_name = saved_alarm_tone_name(source.data, profile)
        if default_name is None:
            return CapturedAlarmTones(
                issues=(
                    "The saved iPod language could not be verified for alarm tones.",
                )
            )
        dependencies = [FilePrecondition(path, source.fingerprint)]
        beep = AlarmSound(
            AlarmSound.Kind.BEEP, source_text("Beep"), tone_name=default_name
        )
        names = tone_inventory(session)
        if len(names) > 19:
            return CapturedAlarmTones(
                (beep,),
                tuple(dependencies),
                issues=(
                    "Only Beep is available because the iPod's tone collection exceeds the supported inspection limit.",
                ),
            )
        custom: list[AlarmSound] = []
        seen = {default_name, "Beep"}
        ambiguous = False
        for name in names:
            checkpoint()
            captured = session.read_snapshot(
                DevicePath(name), max_bytes=MAX_ALARM_TONE_BYTES
            )
            dependencies.append(
                FilePrecondition(DevicePath(name), captured.fingerprint)
            )
            tone = parse_alarm_tone(captured.data, profile=profile)
            if not tone.selectable or tone.name is None:
                ambiguous = True
                continue
            if tone.name in seen:
                ambiguous = True
                continue
            seen.add(tone.name)
            custom.append(
                AlarmSound(AlarmSound.Kind.TONE, tone.name, tone_name=tone.name)
            )
        if ambiguous:
            return CapturedAlarmTones(
                (beep,),
                (dependencies[0],),
                issues=(
                    "Only Beep is available because some saved tone names are ambiguous or unreadable.",
                ),
            )
        return CapturedAlarmTones((beep, *custom), tuple(dependencies), names)
    except (StorageError, ValueError) as error:
        if not session.is_active:
            raise
        return CapturedAlarmTones(issues=(f"Alarm tones: {error}",))
