"""Bounded, read-only preferences inspection through the selected session."""

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

from device_registry import DeviceProfile
from iOpenPod.app.display_text import exception_text, source_text
from iOpenPod.app.models.ipod_preferences import (
    IPodPreference,
    IPodPreferenceSection,
    PreferenceFileStatus,
)
from iOpenPod.app.services.device_time import resolve_device_time
from iPodDB.device_time import DeviceTimeContext
from iPodDB.preferences import (
    CityPreferences,
    CityTimezone,
    FixedOffsetTimezone,
    ITunesPreferencesProfile,
    Nano3Preferences,
    PreferencesDocument,
    PreferencesProfile,
    VolumeLimitPreferences,
    parse_itunes_preferences,
    parse_preferences,
)
from storage import DevicePath, FilePrecondition, FilesystemSession, StorageError

_PREFERENCES_LIMIT = 1024 * 1024


@dataclass(frozen=True, slots=True)
class CapturedIPodPreferences:
    sections: tuple[IPodPreferenceSection, ...]
    device_time: DeviceTimeContext
    # None means the observation could not be verified, not that the file is absent.
    time_precondition: FilePrecondition | None


def read_ipod_preferences(
    session: FilesystemSession,
    profile: DeviceProfile,
    *,
    firmware_versions: tuple[str, ...] = (),
) -> tuple[IPodPreferenceSection, ...]:
    return capture_ipod_preferences(
        session, profile, firmware_versions=firmware_versions
    ).sections


def capture_ipod_preferences(
    session: FilesystemSession,
    profile: DeviceProfile,
    *,
    firmware_versions: tuple[str, ...] = (),
) -> CapturedIPodPreferences:
    """Capture display and conversion evidence from the same verified bytes."""
    device, data, precondition = _read_section(
        session,
        "device",
        source_text("Device settings"),
        DevicePath("iPod_Control/Device/Preferences"),
        lambda data: _device_rows(data, profile, firmware_versions),
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
            document = _device_document(data, profile, firmware_versions)
    return CapturedIPodPreferences(
        (device, itunes), resolve_device_time(document), precondition
    )


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


def _device_document(
    data: bytes, profile: DeviceProfile, firmware_versions: tuple[str, ...]
) -> PreferencesDocument:
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
    data: bytes, profile: DeviceProfile, firmware_versions: tuple[str, ...]
) -> tuple[IPodPreference, ...]:
    document = _device_document(data, profile, firmware_versions)
    settings = document.settings
    if settings is None:
        return ()
    zone = document.timezone
    timezone: str = source_text("Unknown")
    if zone is None and not isinstance(settings, CityPreferences):
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
    return (
        _row("timezone", "Timezone", timezone),
        _row(
            "language",
            "Menu language",
            source_text("English")
            if settings.language_code == 0
            else _unknown(settings.language_code),
        ),
        _row("daylight_saving", "Daylight saving switch", daylight_saving),
        _row("volume_limit", "Volume limit", volume_limit),
    )


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
