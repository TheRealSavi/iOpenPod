"""Qualified firmware settings over one captured, lossless source revision.

This workflow is separate from iTunesPrefs and from Library date interpretation.
Only explicit supported edits produce a Storage Transaction; optional malformed
clock metadata is retained and cannot prevent an unrelated preference change.
"""

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import replace

from device_registry import DeviceProfile, PreferencesSupport
from iOpenPod.app.display_text import exception_text, source_text
from iOpenPod.app.models.ipod_preferences import (
    IPodPreference,
    IPodPreferenceChoice,
    IPodPreferenceEdit,
    IPodPreferenceEditSpec,
    IPodPreferencesCatalog,
    IPodPreferenceSection,
    PreferenceFileStatus,
)
from iOpenPod.app.services.ipod_preferences import capture_ipod_preferences
from iOpenPod.app.services.preference_observations import (
    capture_inspection_file,
    merge_preference_rows,
    observation_rows,
)
from iPodDB.preferences import (
    NamedPreferencesDocument,
    NamedPreferencesProfile,
    PreferenceKey,
    PreferencesDocument,
    PreferencesProfile,
    available_named_preferences,
    available_preferences,
    inspect_named_binary_preferences,
    inspect_named_preferences,
    named_preference_value,
    parse_named_preferences,
    parse_preferences,
    preference_value,
    update_named_preferences,
    update_preferences,
    write_named_preferences,
    write_preferences,
)
from storage import (
    DevicePath,
    FileContent,
    FilePrecondition,
    FilesystemSession,
    StorageTransaction,
    TransactionWrite,
)

PREFERENCES_PATH = DevicePath("iPod_Control/Device/Preferences")
NAMED_PREFERENCES_PATH = DevicePath("iPod_Control/Device/iPodSettings.xml")
_NANO4_NAMED_PATH = DevicePath("iPod_Control/Device/iPodSettings")
_NAMED_TARGETS = frozenset(
    (
        "nano_5_1_0_2",
        "nano_6_1_2",
        "nano_7_1_0_4",
        "nano_updater_39_1_1_2",
    )
)


def preferences_source(catalog: IPodPreferencesCatalog) -> FilePrecondition:
    """Bind publication and even no-op freshness checks to the actual artifact."""
    if catalog.document is None or catalog.fingerprint is None:
        raise ValueError(
            source_text("Reload verified iPod preferences before editing.")
        )
    path = (
        NAMED_PREFERENCES_PATH
        if isinstance(catalog.document, NamedPreferencesDocument)
        else PREFERENCES_PATH
    )
    return FilePrecondition(path, catalog.fingerprint)


def read_preferences_catalog(
    session: FilesystemSession,
    profile: DeviceProfile,
    support: PreferencesSupport,
    *,
    firmware_versions: tuple[str, ...],
    updater_family_ids: tuple[int, ...],
    checkpoint: Callable[[], None],
) -> IPodPreferencesCatalog:
    """Capture display and editable fields from the same Storage snapshot."""
    checkpoint()
    captured = capture_ipod_preferences(
        session,
        profile,
        firmware_versions=firmware_versions,
        updater_family_ids=updater_family_ids,
    )
    checkpoint()
    if support.target is not None and support.target.value in _NAMED_TARGETS:
        # These firmwares' named UI store is distinct from binary Preferences
        # blob. A malformed optional clock blob cannot block this capture.
        return _read_named_catalog(
            session,
            captured.sections,
            support,
            NamedPreferencesProfile(support.target.value),
            checkpoint,
            captured.device_bytes,
        )
    sections = captured.sections
    document = None
    detail = ""
    if support.target is not None and captured.device_bytes is not None:
        try:
            document = parse_preferences(
                captured.device_bytes,
                profile=PreferencesProfile(support.target.value),
            )
        except ValueError as error:
            detail = source_text(
                "These preference bytes do not match the verified firmware format. They remain read-only. {detail}",
                detail=exception_text(error),
            )
    elif support.target is None:
        detail = source_text(
            "This model or firmware has not been verified for preference editing."
        )
    if document is not None:
        if document.reset_requested is True:
            detail = source_text(
                "These saved preferences request a reset on the iPod. Editing is disabled until the iPod has handled it."
            )
        editable = _editable_rows(document)
        sections = tuple(
            replace(
                section,
                status=PreferenceFileStatus.AVAILABLE,
                detail="",
                rows=merge_preference_rows(section.rows, editable),
            )
            if section.key == "device"
            else section
            for section in sections
        )
    if detail:
        sections = tuple(
            replace(section, detail=detail)
            if section.key == "device"
            and section.status is not PreferenceFileStatus.MISSING
            else section
            for section in sections
        )
    fingerprint = (
        captured.time_precondition.fingerprint
        if captured.time_precondition is not None
        else None
    )
    if support.target is not None and support.target.value == "nano_4_1_0_4":
        named = capture_inspection_file(
            session,
            key="named",
            title=source_text("Additional device settings"),
            path=_NANO4_NAMED_PATH,
            inspect=lambda data: inspect_named_preferences(
                data, profile=NamedPreferencesProfile("nano_4_1_0_4")
            ),
            checkpoint=checkpoint,
        )
        sections += (named.section,)
    checkpoint()
    return IPodPreferencesCatalog(sections, support, document, fingerprint)


def _read_named_catalog(
    session: FilesystemSession,
    sections: tuple[IPodPreferenceSection, ...],
    support: PreferencesSupport,
    profile: NamedPreferencesProfile,
    checkpoint: Callable[[], None],
    binary_source: bytes | None,
) -> IPodPreferencesCatalog:
    captured = capture_inspection_file(
        session,
        key="device",
        title=source_text("Device settings"),
        path=NAMED_PREFERENCES_PATH,
        inspect=lambda data: inspect_named_preferences(data, profile=profile),
        checkpoint=checkpoint,
    )
    document = (
        parse_named_preferences(captured.source, profile=profile)
        if captured.source is not None
        else None
    )
    primary = captured.section
    if document is not None:
        primary = replace(
            primary, rows=merge_preference_rows(primary.rows, _editable_rows(document))
        )
    sections = (
        primary,
        *(s for s in sections if s.key not in ("device", "named_clock")),
    )
    if binary_source is not None:
        inspection = inspect_named_binary_preferences(binary_source, profile=profile)
        sections += (
            IPodPreferenceSection(
                "legacy_device",
                source_text("Legacy device settings"),
                PreferenceFileStatus.AVAILABLE
                if inspection.observations
                else PreferenceFileStatus.UNKNOWN,
                observation_rows(inspection),
                "\n".join(inspection.issues),
            ),
        )
    checkpoint()
    return IPodPreferencesCatalog(sections, support, document, captured.fingerprint)


def prepare_preferences_change(
    catalog: IPodPreferencesCatalog,
    changes: tuple[IPodPreferenceEdit, ...],
    *,
    dependencies: tuple[FilePrecondition, ...] = (),
    checkpoint: Callable[[], None],
) -> StorageTransaction | None:
    """Validate typed intent and retain every byte outside the changed fields."""
    checkpoint()
    document = catalog.document
    support = catalog.support
    if (
        document is None
        or catalog.fingerprint is None
        or support is None
        or support.target is None
        or document.profile.value != support.target.value
    ):
        raise ValueError(
            source_text("Reload verified iPod preferences before editing.")
        )
    permitted = {
        row.key
        for section in catalog.sections
        if section.key == "device"
        for row in section.rows
        if row.edit is not None
    }
    edits: dict[PreferenceKey, int] = {}
    for change in changes:
        if change.section_key != "device" or change.key not in permitted:
            raise ValueError(
                source_text("This preference is not available for editing.")
            )
        key = PreferenceKey(change.key)
        if key in edits:
            raise ValueError(
                source_text("A preference cannot be changed twice in one save.")
            )
        edits[key] = change.value
    data = (
        write_named_preferences(update_named_preferences(document, edits))
        if isinstance(document, NamedPreferencesDocument)
        else write_preferences(update_preferences(document, edits))
    )
    if data == document.source_bytes:
        return None
    checkpoint()
    return StorageTransaction(
        writes=(
            TransactionWrite(
                preferences_source(catalog).path,
                data,
                FileContent(len(data), hashlib.sha256(data).hexdigest()),
                expected=catalog.fingerprint,
            ),
        ),
        dependencies=dependencies,
    )


_TITLES = {
    "shuffle_mode": source_text("Shuffle"),
    "repeat_mode": source_text("Repeat"),
    "eq_preset": source_text("Equalizer"),
    "sound_check": source_text("Sound Check"),
    "backlight_timeout": source_text("Backlight timer"),
    "brightness": source_text("Brightness"),
    "clicker": source_text("Clicker"),
    "alternate_audio": source_text("Alternate Audio"),
    "audiobook_speed": source_text("Audiobook speed"),
    "contact_sort": source_text("Sort contacts by"),
    "contact_display": source_text("Contact name order"),
    "photo_duration": source_text("Time per slide"),
    "photo_repeat": source_text("Repeat slideshow"),
    "photo_shuffle": source_text("Shuffle photos"),
    "photo_transition": source_text("Slideshow transition"),
    "tv_out": source_text("TV Out"),
    "tv_signal": source_text("TV signal"),
    "tv_screen": source_text("TV screen"),
    "fit_to_screen_disabled": source_text("Fit to screen"),
    "widescreen": source_text("Widescreen"),
    "voice_memo_quality": source_text("Voice memo quality"),
    "nike_spoken_feedback": source_text("Nike spoken feedback"),
    "nike_remote_commands_disabled": source_text("Nike remote commands"),
}

_TOGGLE = {0: source_text("Off"), 1: source_text("On")}
_CHOICES = {
    "shuffle_mode": {
        0: source_text("Off"),
        1: source_text("Songs"),
        2: source_text("Albums"),
    },
    "repeat_mode": {
        0: source_text("Off"),
        1: source_text("All"),
        2: source_text("One"),
    },
    "clicker": {0: source_text("Off"), 3: source_text("On")},
    "sound_check": _TOGGLE,
    "alternate_audio": _TOGGLE,
    "photo_repeat": _TOGGLE,
    "photo_shuffle": _TOGGLE,
    "widescreen": _TOGGLE,
    "audiobook_speed": {
        -1: source_text("Slower"),
        0: source_text("Normal"),
        1: source_text("Faster"),
    },
    "tv_out": {0: source_text("Off"), 1: source_text("On"), 2: source_text("Ask")},
    "tv_signal": {0: source_text("NTSC"), 1: source_text("PAL")},
    "tv_screen": {0: source_text("Standard"), 1: source_text("Widescreen")},
    "fit_to_screen_disabled": {0: source_text("On"), 1: source_text("Off")},
    "nike_remote_commands_disabled": {0: source_text("On"), 1: source_text("Off")},
    "nike_spoken_feedback": {
        0: source_text("Female"),
        1: source_text("Male"),
        2: source_text("Off"),
    },
    "voice_memo_quality": {0: source_text("Low"), 1: source_text("High")},
    "eq_preset": {
        0: source_text("Off"),
        100: source_text("Acoustic"),
        101: source_text("Bass Booster"),
        102: source_text("Bass Reducer"),
        103: source_text("Classical"),
        104: source_text("Dance"),
        105: source_text("Deep"),
        106: source_text("Electronic"),
        107: source_text("Flat"),
        108: source_text("Hip Hop"),
        109: source_text("Jazz"),
        110: source_text("Latin"),
        111: source_text("Loudness"),
        112: source_text("Lounge"),
        113: source_text("Piano"),
        114: source_text("Pop"),
        115: source_text("R & B"),
        116: source_text("Rock"),
        117: source_text("Small Speakers"),
        118: source_text("Spoken Word"),
        119: source_text("Treble Booster"),
        120: source_text("Treble Reducer"),
        121: source_text("Vocal Booster"),
    },
}


def _profile_choices(
    document: PreferencesDocument | NamedPreferencesDocument, key: str
) -> Mapping[int, str] | None:
    """Translate evidenced values without assuming shared offsets share units."""
    if not isinstance(document, PreferencesDocument):
        return _CHOICES.get(key)
    mini = document.profile in (
        PreferencesProfile.MINI_1_1_4_1,
        PreferencesProfile.MINI_2_1_4_1,
    )
    legacy_photo = document.profile in (
        PreferencesProfile.NANO_1_1_3_1,
        PreferencesProfile.VIDEO_1_3,
    )
    if key == "backlight_timeout":
        if mini:
            return {
                0: source_text("Off"),
                2: source_text("2 seconds"),
                3: source_text("5 seconds"),
                4: source_text("10 seconds"),
                5: source_text("20 seconds"),
                6: source_text("Always on"),
            }
        if legacy_photo:
            return {
                0: source_text("Off"),
                2: source_text("2 seconds"),
                3: source_text("5 seconds"),
                4: source_text("10 seconds"),
                5: source_text("15 seconds"),
                6: source_text("20 seconds"),
                8: source_text("Always on"),
            }
        return {
            0: source_text("Off"),
            1: source_text("2 seconds"),
            2: source_text("5 seconds"),
            3: source_text("10 seconds"),
            4: source_text("20 seconds"),
            5: source_text("30 seconds"),
            6: source_text("Always on"),
        }
    if key in ("contact_sort", "contact_display"):
        if document.profile in (
            PreferencesProfile.NANO_3_1_1_3,
            PreferencesProfile.NANO_4_1_0_4,
        ):
            return {0: source_text("First"), 1: source_text("Last")}
        return {0: source_text("First Last"), 1: source_text("Last, First")}
    if key == "photo_duration":
        seconds = {
            0: source_text("Manual"),
            2: source_text("2 seconds"),
            3: source_text("3 seconds"),
            5: source_text("5 seconds"),
            10: source_text("10 seconds"),
            20: source_text("20 seconds"),
        }
        return dict(enumerate(seconds.values())) if legacy_photo else seconds
    if key == "photo_transition":
        if document.profile is PreferencesProfile.NANO_4_1_0_4:
            return {
                -1: source_text("Random"),
                25: source_text("None"),
                26: source_text("Dissolve"),
                27: source_text("Slide"),
                6: source_text("Push"),
                5: source_text("Fade Through Black"),
                21: source_text("Zoom"),
            }
        if legacy_photo:
            return {
                -1: source_text("Random"),
                0: source_text("Off"),
                1: source_text("Wipe across"),
                2: source_text("Wipe down"),
                3: source_text("Wipe from center"),
                6: source_text("Push across"),
                8: source_text("Push down"),
                9: source_text("Cube across"),
                10: source_text("Cube down"),
                11: source_text("Page flip"),
                12: source_text("Radial"),
                13: source_text("Swirl"),
                14: source_text("Dissolve"),
            }
        return {
            -1: source_text("Random"),
            0: source_text("None"),
            14: source_text("Cross Fade"),
            5: source_text("Fade To Black"),
            24: source_text("Zoom Out"),
            1: source_text("Wipe Across"),
            3: source_text("Wipe Center"),
        }
    return _CHOICES.get(key)


def _editable_rows(
    document: PreferencesDocument | NamedPreferencesDocument,
) -> tuple[IPodPreference, ...]:
    rows: list[IPodPreference] = []
    fields = (
        available_named_preferences(document)
        if isinstance(document, NamedPreferencesDocument)
        else available_preferences(document)
    )
    for field in fields:
        key = field.key.value
        labels = _profile_choices(document, key)
        if (
            isinstance(document, PreferencesDocument)
            and key == "clicker"
            and document.profile
            in (
                PreferencesProfile.MINI_1_1_4_1,
                PreferencesProfile.MINI_2_1_4_1,
                PreferencesProfile.NANO_1_1_3_1,
                PreferencesProfile.NANO_3_1_1_3,
                PreferencesProfile.NANO_4_1_0_4,
            )
        ):
            labels = {
                0: source_text("Off"),
                1: source_text("Speaker"),
                2: source_text("Headphones"),
                3: source_text("Both"),
            }
        elif (
            isinstance(document, PreferencesDocument)
            and key == "clicker"
            and document.profile is PreferencesProfile.VIDEO_1_3
        ):
            # Video's resource-labelled setter reverses the Mini route bits.
            # Do not infer these labels from shared offsets or bit positions.
            labels = {
                0: source_text("Off"),
                1: source_text("Headphones"),
                2: source_text("Speaker"),
                3: source_text("On"),
            }
        title = _TITLES.get(key)
        value = (
            named_preference_value(document, field.key)
            if isinstance(document, NamedPreferencesDocument)
            else preference_value(document, field.key)
        )
        if title is None or value is None:
            continue
        if (
            key == "brightness"
            and field.minimum is not None
            and field.maximum is not None
        ):
            rows.append(
                IPodPreference(
                    key,
                    title,
                    str(value),
                    IPodPreferenceEditSpec(
                        value, minimum=field.minimum, maximum=field.maximum
                    ),
                )
            )
            continue
        if labels is None:
            continue
        # A native domain without understood labels remains outside the editor.
        if any(option not in labels for option in field.allowed_values):
            continue
        choices = tuple(
            IPodPreferenceChoice(option, labels[option])
            for option in field.allowed_values
        )
        rows.append(
            IPodPreference(
                key,
                title,
                labels.get(
                    value, source_text("Unknown (code {code})", code=str(value))
                ),
                IPodPreferenceEditSpec(value, choices),
            )
        )
    return tuple(rows)
