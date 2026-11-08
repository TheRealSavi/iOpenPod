"""Bounded, read-only preferences inspection through the selected session."""

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace

from device_registry import (
    DeviceEvidence,
    DeviceIdentifier,
    DeviceProfile,
    EvidenceAuthority,
    PreferencesSupport,
    resolve_preferences_support,
)
from iOpenPod.app.display_text import exception_text, source_text
from iOpenPod.app.models.ipod_preferences import (
    IPodPreference,
    IPodPreferenceSection,
    PreferenceFileStatus,
)
from iOpenPod.app.services.classic_calendar import resolve_classic_calendar
from iOpenPod.app.services.device_time import (
    resolve_device_time,
    resolve_named_device_time,
)
from iOpenPod.app.services.preference_observations import observation_rows
from iPodDB.device_time import DeviceTimeContext
from iPodDB.preferences import (
    CityTimezone,
    Classic201Preferences,
    ClassicClockPreferences,
    ClassicPreferences,
    DSTTableDocument,
    DSTTableProfile,
    FixedOffsetTimezone,
    FourthGenerationPreferences,
    ITunesPreferencesProfile,
    NamedClockEvidence,
    NamedPreferencesProfile,
    Nano3Preferences,
    PreferencesDocument,
    PreferencesLayout,
    PreferencesProfile,
    VideoPreferences,
    VolumeLimitPreferences,
    inspect_binary_preferences,
    matches_preferences_profile,
    parse_dst_table,
    parse_itunes_preferences,
    parse_preferences,
    read_named_clock_evidence,
)
from storage import DevicePath, FilePrecondition, FilesystemSession, StorageError

_PREFERENCES_LIMIT = 1024 * 1024


@dataclass(frozen=True, slots=True)
class CapturedIPodPreferences:
    sections: tuple[IPodPreferenceSection, ...]
    device_time: DeviceTimeContext
    # None means the observation could not be verified, not that the file is absent.
    time_precondition: FilePrecondition | None
    daylight_saving_rules: DSTTableDocument | None = None
    device_bytes: bytes | None = None


def read_ipod_preferences(
    session: FilesystemSession,
    profile: DeviceProfile,
    *,
    firmware_versions: tuple[str, ...] = (),
    updater_family_ids: tuple[int, ...] = (),
) -> tuple[IPodPreferenceSection, ...]:
    return capture_ipod_preferences(
        session,
        profile,
        firmware_versions=firmware_versions,
        updater_family_ids=updater_family_ids,
    ).sections


def capture_ipod_preferences(
    session: FilesystemSession,
    profile: DeviceProfile,
    *,
    firmware_versions: tuple[str, ...] = (),
    updater_family_ids: tuple[int, ...] = (),
) -> CapturedIPodPreferences:
    """Capture display and conversion evidence from the same verified bytes."""
    device, data, precondition = _read_section(
        session,
        "device",
        source_text("Device settings"),
        DevicePath("iPod_Control/Device/Preferences"),
        lambda data: _device_rows(data, profile, firmware_versions, updater_family_ids),
    )
    itunes, _, _ = _read_section(
        session,
        "itunes",
        source_text("iTunes settings"),
        DevicePath("iPod_Control/iTunes/iTunesPrefs"),
        lambda data: _itunes_rows(data, profile),
    )
    document = None
    if data is not None:
        with suppress(ValueError):
            document = _device_document(
                data, profile, firmware_versions, updater_family_ids
            )
    settings = document.settings if document is not None else None
    city_id = settings.city_id if isinstance(settings, ClassicPreferences) else None
    target = resolve_classic_calendar(profile, firmware_versions, updater_family_ids)
    dst_section, dst = _capture_dst(
        session,
        target.dst_profile if target is not None else DSTTableProfile.UNKNOWN,
        city_id,
    )
    sections: tuple[IPodPreferenceSection, ...] = (device, itunes)
    if dst_section.status is not PreferenceFileStatus.MISSING:
        sections += (dst_section,)
    context = resolve_device_time(document)
    support = _preferences_support(profile, firmware_versions, updater_family_ids)
    if support.target is not None and support.target.value in (
        "nano_5_1_0_2",
        "nano_6_1_2",
        "nano_7_1_0_4",
        "nano_updater_39_1_1_2",
    ):
        clock_section, context = _capture_named_clock(
            session, NamedPreferencesProfile(support.target.value)
        )
        sections += (clock_section,)
    return CapturedIPodPreferences(sections, context, precondition, dst, data)


def _capture_named_clock(
    session: FilesystemSession, profile: NamedPreferencesProfile
) -> tuple[IPodPreferenceSection, DeviceTimeContext]:
    """Capture optional Nano clock evidence before Library projection.

    The XML fingerprint verifies this read, but is deliberately not a Library
    publication precondition. The captured context stays with the Library source.
    World clocks, display format and the legacy binary blob cannot replace it.
    """
    evidence: NamedClockEvidence | None = None

    def project(data: bytes) -> tuple[IPodPreference, ...]:
        nonlocal evidence
        evidence = read_named_clock_evidence(data, profile=profile)
        raw = evidence.raw_value
        return (
            IPodPreference(
                "clock_city",
                source_text("Clock city"),
                evidence.city_label or source_text("Unknown"),
                raw_value=raw.decode("utf-8", errors="replace")[:512] if raw else "",
                detail=" ".join(evidence.issues),
            ),
            IPodPreference(
                "date_timezone",
                source_text("Timezone used for library dates"),
                evidence.iana_timezone or source_text("Unknown"),
            ),
        )

    section, _, _ = _read_section(
        session,
        "named_clock",
        source_text("Device clock settings"),
        DevicePath("iPod_Control/Device/iPodSettings.xml"),
        project,
    )
    context = (
        resolve_named_device_time(evidence)
        if evidence is not None
        else DeviceTimeContext(
            detail="The Nano named clock settings could not be captured. "
            + section.detail
        )
    )
    return replace(
        section,
        detail=context.detail,
        rows=tuple(
            replace(row, value=context.timezone_name or source_text("Unknown"))
            if row.key == "date_timezone"
            else row
            for row in section.rows
        ),
    ), context


def _capture_dst(
    session: FilesystemSession, profile: DSTTableProfile, city_id: int | None
) -> tuple[IPodPreferenceSection, DSTTableDocument | None]:
    document: DSTTableDocument | None = None

    def project(data: bytes) -> tuple[IPodPreference, ...]:
        nonlocal document
        document = parse_dst_table(data, profile=profile)
        if document.expected_rows is None:
            return ()
        rows: tuple[IPodPreference, ...] = (
            _row(
                "rule_count",
                "Complete saved rules",
                source_text(
                    "{count} / {total}",
                    count=str(len(document.rules)),
                    total=str(document.expected_rows),
                ),
            ),
        )
        if city_id is not None:
            matches = document.rules_for_city(city_id)
            rows += (
                _row("city_rule_count", "Rules for the saved city", str(len(matches))),
            )
        return rows

    section, _, _ = _read_section(
        session,
        "dst",
        source_text("Saved daylight saving rules"),
        DevicePath("iPod_Control/Device/dst"),
        project,
    )
    if document is not None and document.expected_rows is not None:
        section = replace(
            section,
            status=PreferenceFileStatus.AVAILABLE
            if document.complete
            else PreferenceFileStatus.UNKNOWN,
            detail=source_text(
                "These saved annual rules do not establish historical timezones. Library dates use the available city rules or a fixed-offset estimate."
            ),
        )
    return section, document


def _read_section(
    session: FilesystemSession,
    key: str,
    title: str,
    path: DevicePath,
    project: Callable[[bytes], tuple[IPodPreference, ...]],
) -> tuple[IPodPreferenceSection, bytes | None, FilePrecondition | None]:
    precondition = None
    try:
        if not session.exists(path):
            return (
                IPodPreferenceSection(
                    key,
                    title,
                    PreferenceFileStatus.MISSING,
                    detail=source_text("This iPod has no file for these settings."),
                ),
                None,
                FilePrecondition(path),
            )
        snapshot = session.read_snapshot(path, max_bytes=_PREFERENCES_LIMIT)
        if session.fingerprint(path) != snapshot.fingerprint:
            return (
                IPodPreferenceSection(
                    key,
                    title,
                    PreferenceFileStatus.UNREADABLE,
                    detail=source_text(
                        "These settings changed while they were being read. Reload the iPod to try again."
                    ),
                ),
                None,
                None,
            )
        precondition = FilePrecondition(path, snapshot.fingerprint)
        rows = project(snapshot.data)
        if not rows:
            return (
                IPodPreferenceSection(
                    key,
                    title,
                    PreferenceFileStatus.UNKNOWN,
                    detail=source_text(
                        "This iPod uses a settings format that is not yet recognized."
                    ),
                ),
                snapshot.data,
                precondition,
            )
        return (
            IPodPreferenceSection(key, title, PreferenceFileStatus.AVAILABLE, rows),
            snapshot.data,
            precondition,
        )
    except StorageError as error:
        if not session.is_active:
            raise
        detail = exception_text(error)
    except ValueError as error:
        detail = exception_text(error)
    return (
        IPodPreferenceSection(
            key,
            title,
            PreferenceFileStatus.UNREADABLE,
            detail=source_text(
                "Could not read these settings: {detail}", detail=detail
            ),
        ),
        None,
        precondition,
    )


def _row(key: str, title: str, value: str) -> IPodPreference:
    return IPodPreference(key, source_text(title), value)


def _unknown(value: int) -> str:
    return source_text("Unknown (code {code})", code=str(value))


def _toggle(value: int) -> str:
    return {0: source_text("Off"), 1: source_text("On")}.get(value, _unknown(value))


def _preferences_support(
    profile: DeviceProfile,
    firmware_versions: tuple[str, ...],
    updater_family_ids: tuple[int, ...],
) -> PreferencesSupport:
    # These tuples have already been reduced to the strongest observations by
    # the caller. Preserve conflicts instead of picking a release or family.
    return resolve_preferences_support(
        profile,
        DeviceEvidence(
            firmware_versions=tuple(
                DeviceIdentifier(
                    value, "Selected firmware evidence", EvidenceAuthority.DERIVED
                )
                for value in firmware_versions
            ),
            updater_family_ids=tuple(
                DeviceIdentifier(
                    value, "Selected updater evidence", EvidenceAuthority.DERIVED
                )
                for value in updater_family_ids
            ),
        ),
    )


def _device_document(
    data: bytes,
    profile: DeviceProfile,
    firmware_versions: tuple[str, ...],
    updater_family_ids: tuple[int, ...],
) -> PreferencesDocument:
    target = resolve_classic_calendar(profile, firmware_versions, updater_family_ids)
    if target is not None:
        try:
            return parse_preferences(data, profile=target.preferences_profile)
        except ValueError:
            # A qualified target with unrecognized bytes must not fall back to a
            # narrower city field and alias an unknown u32 ID to a known u16 ID.
            return parse_preferences(data, layout=PreferencesLayout.UNKNOWN)
    support = _preferences_support(profile, firmware_versions, updater_family_ids)
    if support.target is not None:
        try:
            return parse_preferences(
                data, profile=PreferencesProfile(support.target.value)
            )
        except ValueError:
            return parse_preferences(data, layout=PreferencesLayout.UNKNOWN)
    # Missing or contradictory identity must not grant a weaker legacy clock
    # decoder to a recognized latest frame. In particular Nano 3's qualified
    # current frame has no verified city field, while the historical size-only
    # decoder would alias its bytes as one. Classic's legacy decoder would also
    # narrow the current u32 city to u16 after failed exact qualification.
    if (
        profile.family == "iPod Classic"
        or (profile.family, profile.generation) == ("iPod Nano", "3rd Gen")
    ) and any(
        matches_preferences_profile(data, candidate)
        for candidate in (
            PreferencesProfile.CLASSIC_6_1_1_2,
            PreferencesProfile.CLASSIC_120GB_2_0_1,
            PreferencesProfile.CLASSIC_UPDATER_35_2_0_4,
            PreferencesProfile.NANO_4_1_0_4,
            PreferencesProfile.CLASSIC_UPDATER_38_2_0_5,
        )
    ):
        return parse_preferences(data, layout=PreferencesLayout.UNKNOWN)
    if profile.family == "iPod Nano" and profile.generation in (
        "4th Gen",
        "5th Gen",
        "6th Gen",
        "7th Gen",
    ):
        # Equal extents do not establish Classic clock/city offsets. Touch
        # firmware also owns a separate named settings store. Unknown firmware
        # keeps its bytes and uses the normal nonblocking Library date fallback.
        return parse_preferences(data, layout=PreferencesLayout.UNKNOWN)
    document = parse_preferences(data)
    if document.settings is None:
        return document
    # Only assert extensions with both model evidence and a recognized extent.
    if (profile.family, profile.generation) == ("iPod Nano", "3rd Gen") and len(
        data
    ) == 2952:
        document = parse_preferences(data, profile=PreferencesProfile.NANO_3)
    elif (
        set(firmware_versions) == {"1.1.1"}
        and len(data) >= 2897
        and (
            profile.family == "iPod Nano"
            or (
                profile.family == "iPod"
                and profile.generation in ("5th Gen", "5.5th Gen")
            )
        )
    ):
        document = parse_preferences(
            data, profile=PreferencesProfile.VOLUME_LIMIT_1_1_1
        )
    return document


def _device_rows(
    data: bytes,
    profile: DeviceProfile,
    firmware_versions: tuple[str, ...],
    updater_family_ids: tuple[int, ...],
) -> tuple[IPodPreference, ...]:
    document = _device_document(data, profile, firmware_versions, updater_family_ids)
    settings = document.settings
    if settings is None:
        return ()
    zone = document.timezone
    timezone: str = source_text("Unknown")
    if (
        zone is None
        and not document.has_video13_framing
        and isinstance(settings, (FourthGenerationPreferences, VideoPreferences))
    ):
        timezone = _unknown(settings.timezone_code)
    if isinstance(zone, CityTimezone):
        timezone = zone.timezone_name or source_text(
            "Unknown (city {city})", city=str(zone.city_id)
        )
    elif isinstance(zone, FixedOffsetTimezone):
        minutes = abs(zone.offset_seconds) // 60
        sign = "+" if zone.offset_seconds >= 0 else "-"
        timezone = source_text(
            "UTC{offset}", offset=f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"
        )
    extension = document.extended_settings
    unavailable = source_text("Not decoded for this model or firmware")
    daylight_saving: str = unavailable
    volume_limit: str = unavailable
    if isinstance(extension, Nano3Preferences):
        daylight_saving = {0: source_text("Off"), 60: source_text("On")}.get(
            extension.daylight_saving_minutes,
            _unknown(extension.daylight_saving_minutes),
        )
    if isinstance(extension, VolumeLimitPreferences):
        volume_limit = (
            source_text("{value} / 64", value=str(extension.volume_limit))
            if 0 <= extension.volume_limit <= 64
            else _unknown(extension.volume_limit)
        )
    classic = isinstance(extension, ClassicClockPreferences)
    if isinstance(extension, ClassicClockPreferences):
        if extension.retained_dst_state == 0:
            daylight_saving = source_text("Off (raw 0)")
        elif extension.retained_dst_state in (1, 60):
            daylight_saving = source_text(
                "On (raw {value})", value=str(extension.retained_dst_state)
            )
        else:
            daylight_saving = _unknown(extension.retained_dst_state)
    rows: tuple[IPodPreference, ...] = (
        _row("timezone", "Library timezone" if classic else "Timezone", timezone),
        _row(
            "language",
            "Menu language",
            source_text("English")
            if settings.language_code == 0
            else _unknown(settings.language_code),
        ),
        _row(
            "daylight_saving",
            "Saved daylight saving state" if classic else "Daylight saving switch",
            daylight_saving,
        ),
        _row("volume_limit", "Volume limit", volume_limit),
    )
    if isinstance(settings, Classic201Preferences):
        rows += (
            _row(
                "alternate_audio", "Alternate Audio", _toggle(settings.alternate_audio)
            ),
        )
    if isinstance(extension, ClassicClockPreferences):
        rows += (
            _row(
                "clock_bias_days",
                "Saved clock correction (days)",
                str(extension.clock_bias_days),
            ),
            _row(
                "clock_bias_seconds",
                "Saved clock correction (raw seconds word)",
                str(extension.clock_bias_seconds),
            ),
        )
    inspection = inspect_binary_preferences(document)
    observed = observation_rows(inspection)
    observed_keys = {item.key for item in observed}
    rows = observed + tuple(item for item in rows if item.key not in observed_keys)
    if inspection.issues:
        rows += (
            IPodPreference(
                "inspection_notes",
                source_text("Interpretation notes"),
                "\n".join(inspection.issues),
            ),
        )
    return rows


def _itunes_rows(data: bytes, profile: DeviceProfile) -> tuple[IPodPreference, ...]:
    document = parse_itunes_preferences(
        data,
        profile=ITunesPreferencesProfile.SHUFFLE
        if profile.family == "iPod Shuffle"
        else ITunesPreferencesProfile.STANDARD,
    )
    settings = document.settings
    mode = {0: source_text("Manual"), 1: source_text("Automatic")}
    music_selection = {
        1: source_text("Entire library"),
        2: source_text("Selected playlists"),
    }
    podcast_selection = {
        1: source_text("All podcasts"),
        2: source_text("Selected podcasts"),
    }
    rows: tuple[IPodPreference, ...] = (
        _row(
            "setup_completed",
            "iTunes setup completed",
            _toggle(settings.setup_completed),
        ),
        _row(
            "open_itunes",
            "Open iTunes on connection",
            _toggle(settings.open_itunes_on_attach),
        ),
        _row(
            "music_sync_mode",
            "Music sync",
            mode.get(settings.music_sync_mode, _unknown(settings.music_sync_mode)),
        ),
        _row(
            "music_sync_selection",
            "Music selection",
            music_selection.get(
                settings.music_sync_selection, _unknown(settings.music_sync_selection)
            ),
        ),
        _row("disk_use", "Disk use", _toggle(settings.disk_use_enabled)),
        _row(
            "checked_only",
            "Sync checked tracks only",
            _toggle(settings.sync_checked_only),
        ),
        _row("artwork", "Show artwork", _toggle(settings.show_artwork)),
        _row("photos", "Sync photos", _toggle(settings.sync_photos)),
        _row(
            "original_photos",
            "Include original photos",
            _toggle(settings.include_original_photos),
        ),
        _row(
            "transcode",
            "Convert to 128 kbps AAC",
            _toggle(settings.transcode_to_128kbps_aac),
        ),
        _row(
            "source_list",
            "Keep in iTunes source list",
            _toggle(settings.keep_in_source_list),
        ),
        _row(
            "podcast_sync_mode",
            "Podcast sync",
            mode.get(settings.podcast_sync_mode, _unknown(settings.podcast_sync_mode)),
        ),
        _row(
            "podcast_sync_selection",
            "Podcast selection",
            podcast_selection.get(
                settings.podcast_sync_selection,
                _unknown(settings.podcast_sync_selection),
            ),
        ),
        _row("sound_check", "Sound Check", _toggle(settings.sound_check_enabled)),
        _row(
            "library_link",
            "Linked library identifier",
            settings.library_link_id.hex().upper(),
        ),
        _row(
            "secondary_library_link",
            "Secondary library identifier",
            settings.secondary_library_link_id.hex().upper(),
        ),
        _row(
            "shuffle_music_capacity",
            "Shuffle music capacity",
            source_text(
                "{value} (units unknown)",
                value=str(settings.shuffle_music_capacity_raw),
            ),
        ),
        _row(
            "shuffle_file_capacity",
            "Shuffle file capacity",
            source_text(
                "{value} (units unknown)", value=str(settings.shuffle_file_capacity_raw)
            ),
        ),
    )
    if document.voice_over is not None:
        rows += (
            _row(
                "voice_over",
                "VoiceOver",
                source_text("On")
                if document.voice_over.enabled
                else source_text("Off"),
            ),
        )
    return rows
