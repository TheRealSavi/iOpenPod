"""Capture qualified native tone names through the selected Storage session."""

from collections.abc import Callable
from dataclasses import dataclass

from device_registry import ExtrasSupport, FirmwareTarget
from iOpenPod.app.display_text import source_text
from iOpenPod.app.models.extras import AlarmSound, AlarmToneItem
from iPodDB.alarms import (
    MAX_ALARM_TONE_BYTES,
    MAX_CUSTOM_ALARM_TONES,
    AlarmToneNote,
    parse_alarm_tone,
    saved_alarm_tone_name,
)
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
    items: tuple[AlarmToneItem, ...] = ()

    @property
    def can_create(self) -> bool:
        return (
            self.inventory is not None
            and len(self.inventory) < MAX_CUSTOM_ALARM_TONES
            and not self.issues
        )


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
        language_dependencies: tuple[FilePrecondition, ...] = ()
        language_issues: tuple[str, ...] = ()
        default_name = None
        if not session.exists(path):
            language_issues = (
                "The saved iPod language is unavailable; tone choices could not be verified.",
            )
        else:
            source = session.read_snapshot(path, max_bytes=MAX_ALARM_TONE_BYTES)
            default_name = saved_alarm_tone_name(source.data, profile)
            language_dependencies = (FilePrecondition(path, source.fingerprint),)
            if default_name is None:
                language_issues = (
                    "The saved iPod language could not be verified for alarm tones.",
                )
        dependencies = list(language_dependencies)
        beep = AlarmSound(
            AlarmSound.Kind.BEEP, source_text("Beep"), tone_name=default_name
        )
        names = tone_inventory(session)
        custom: list[AlarmSound] = []
        items = [AlarmToneItem("builtin:beep", source_text("Beep"), builtin=True)]
        beep_path = DevicePath("iPod_Control/Tones/Beep.tone")
        if session.exists(beep_path):
            captured_beep = session.read_snapshot(
                beep_path, max_bytes=MAX_ALARM_TONE_BYTES
            )
            parsed_beep = parse_alarm_tone(captured_beep.data, profile=profile)
            if parsed_beep.valid:
                items[0] = AlarmToneItem(
                    "builtin:beep", source_text("Beep"), parsed_beep.notes, builtin=True
                )
        else:
            items[0] = AlarmToneItem(
                "builtin:beep",
                source_text("Beep"),
                (AlarmToneNote(540, 200), AlarmToneNote(676, 400)) * 4,
                builtin=True,
            )
        seen = {default_name, "Beep"}
        ambiguous = False
        # Show individual damaged/overflow entries without qualifying a writer.
        # The UI inspection cap bounds hostile collections separately from the
        # native 19-custom-tone capacity.
        for name in names[:256]:
            checkpoint()
            captured = session.read_snapshot(
                DevicePath(name), max_bytes=MAX_ALARM_TONE_BYTES
            )
            dependencies.append(
                FilePrecondition(DevicePath(name), captured.fingerprint)
            )
            tone = parse_alarm_tone(captured.data, profile=profile)
            items.append(
                AlarmToneItem(
                    name,
                    tone.name or DevicePath(name).name,
                    tone.notes if tone.valid else (),
                    issue=" ".join(tone.issues),
                )
            )
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
        if language_issues:
            return CapturedAlarmTones(issues=language_issues, items=tuple(items))
        if len(names) > MAX_CUSTOM_ALARM_TONES:
            return CapturedAlarmTones(
                (beep,),
                language_dependencies,
                issues=(
                    "Only Beep is available because the iPod's tone collection exceeds the supported inspection limit.",
                ),
                items=tuple(items),
            )
        if ambiguous:
            return CapturedAlarmTones(
                (beep,),
                language_dependencies,
                issues=(
                    "Only Beep is available because some saved tone names are ambiguous or unreadable.",
                ),
                items=tuple(items),
            )
        return CapturedAlarmTones(
            (beep, *custom), tuple(dependencies), names, items=tuple(items)
        )
    except (StorageError, ValueError) as error:
        if not session.is_active:
            raise
        return CapturedAlarmTones(issues=(f"Alarm tones: {error}",))
