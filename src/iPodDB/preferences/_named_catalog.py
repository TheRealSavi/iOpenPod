"""Qualified saved-field catalogs, not authoring permission or live state.

Extracted from the 2026-11-07 Nano firmware research; no lab runtime dependency.
The inventory excludes Countdown Timer registrations by user direction (ADR-0267);
it is not proof that indirect/factory registration discovery is complete. Bounds describe constructor
contracts, not complete UI or parser domains. Choices are independently recovered
UI labels and consumers; an absent choice must stay unresolved.

Sources: docs/research/preferences-nano567-complete-2026-11-07.md,
preferences-nano567-consumers-2026-11-07.md and preferences-nano34-consumers-
2026-11-07.md (Nano 4 registration 0814282c; extensionless store).

The city catalog is historical firmware data, not current IANA rules. City ID is
not row position. Packaged base offsets do not incorporate seasonal corrections
or a user-supplied iPodTZData.dat override. Nano 7 and refresh have independently
captured equal schema contracts, labels and packaged city data; sharing these
immutable data does not assert callback or hardware equivalence.
"""

from dataclasses import dataclass
from typing import Literal

from iPodDB.preferences.definitions import NamedPreferencesProfile


@dataclass(frozen=True, slots=True)
class NamedFieldSpec:
    key: str
    kind: Literal["boolean", "int32", "int64", "string"]
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class FirmwareCity:
    label: str
    nano5_base_minutes: int
    nano6_base_minutes: int
    nano7_base_minutes: int
    nano6_zone: str
    nano7_zone: str
    nano7_label: str | None = None


# Inventory SHA-256: 251526303ec283fffa6061a1d61dc688ed28ff977f7251b72631962cfa76c138
# Timezone receipt SHA-256: 8c21c6c30ac258598271630d9f327d8ee4485da0b215f7e9231f68f52a704477
# UI table receipt SHA-256: b6a0677df0d6702a235cd851a6e5427823dbca8076598f8897b5c2785a06c778
# Artifact basenames in the research lab: nano567-preferences-round2-20261107-
# final-inventory-v3/inventory.json, final-timezones-v2/results.json and
# final-tables/results.json. The app never reads those files at runtime.
# Updater 34 firmware SHA-256: dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49
# Updater 36 firmware SHA-256: d529680b7e7662876543d70b6941ddfac123d96c8ed1923432e4909909e896d8
# Updater 37 firmware SHA-256: 4a55fffbf58cfd04a393e9a40c0c1c42471dfb34d11847b676b85f02a8019999
# Updater 39 firmware SHA-256: ac4cf072d3c3f971b6acc03ed4f2ad1baa57d7bae20f89692bd6fb08d8a749e4

NANO5_FIELDS: tuple[NamedFieldSpec, ...] = (
    NamedFieldSpec("DateTime.TimeInTitle", "boolean", None, None, ()),
    NamedFieldSpec("DateTime.TimeZone", "int32", 0, 204, ()),
    NamedFieldSpec("DateTime.TwentyFourHourClock", "boolean", None, None, ()),
    NamedFieldSpec("General.BacklightTimer", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec("General.Brightness", "int32", 0, 100, ()),
    NamedFieldSpec(
        "General.Clicker", "string", None, None, (("off", "Off"), ("on", "On"))
    ),
    NamedFieldSpec("General.FontSize", "string", None, None, ()),
    NamedFieldSpec("General.GroupCompilations", "boolean", None, None, ()),
    NamedFieldSpec("General.Language", "string", None, None, ()),
    NamedFieldSpec(
        "General.MainMenu", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec(
        "General.MusicMenu", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec("General.PreviewPanel", "boolean", None, None, ()),
    NamedFieldSpec(
        "General.RadioRegion",
        "int32",
        -2147483648,
        2147483647,
        (
            ("1", "Americas"),
            ("11", "Asia"),
            ("4", "Australia"),
            ("2", "Europe"),
            ("3", "Japan"),
            ("10", "World Wide (TEST)"),
        ),
    ),
    NamedFieldSpec("General.Rotate", "boolean", None, None, ()),
    NamedFieldSpec("General.SortContacts", "string", None, None, ()),
    NamedFieldSpec("General.SpokenMenus", "int32", 0, 2, ()),
    NamedFieldSpec("NowPlaying.EnergySaver", "boolean", None, None, ()),
    NamedFieldSpec("Photos.Music", "int32", 0, 5, ()),
    NamedFieldSpec("Photos.Repeat", "boolean", None, None, ()),
    NamedFieldSpec("Photos.Shuffle", "boolean", None, None, ()),
    NamedFieldSpec(
        "Photos.TimePerSlide",
        "int32",
        0,
        5,
        (
            ("0", "Manual"),
            ("1", "2 Seconds"),
            ("2", "3 Seconds"),
            ("3", "5 Seconds"),
            ("4", "10 Seconds"),
            ("5", "20 Seconds"),
        ),
    ),
    NamedFieldSpec(
        "Photos.Transitions",
        "int32",
        0,
        9,
        (
            ("0", "None"),
            ("1", "Random"),
            ("2", "Dissolve"),
            ("3", "Slide"),
            ("4", "Push"),
            ("5", "Fade Through Black"),
            ("6", "Zoom"),
            ("7", "Ken Burns"),
            ("8", "Cube"),
            ("9", "Flip"),
        ),
    ),
    NamedFieldSpec(
        "Playback.AudiobookSpeed",
        "string",
        None,
        None,
        (("slow", "Slow"), ("normal", "Normal"), ("fast", "Fast")),
    ),
    NamedFieldSpec("Playback.Crossfade", "boolean", None, None, ()),
    NamedFieldSpec(
        "Playback.EQ",
        "int32",
        -2147483648,
        2147483647,
        (
            ("0", "Off"),
            ("100", "Acoustic"),
            ("101", "Bass Booster"),
            ("102", "Bass Reducer"),
            ("103", "Classical"),
            ("104", "Dance"),
            ("105", "Deep"),
            ("106", "Electronic"),
            ("107", "Flat"),
            ("108", "Hip Hop"),
            ("109", "Jazz"),
            ("110", "Latin"),
            ("111", "Loudness"),
            ("112", "Lounge"),
            ("113", "Piano"),
            ("114", "Pop"),
            ("115", "R&B"),
            ("116", "Rock"),
            ("117", "Small Speakers"),
            ("118", "Spoken Word"),
            ("119", "Treble Booster"),
            ("120", "Treble Reducer"),
            ("121", "Vocal Booster"),
        ),
    ),
    NamedFieldSpec("Playback.EnergySaver", "boolean", None, None, ()),
    NamedFieldSpec("Playback.MonoAudio", "boolean", None, None, ()),
    NamedFieldSpec(
        "Playback.Repeat",
        "string",
        None,
        None,
        (
            ("off", "Off"),
            ("one", "Repeat current item"),
            ("all", "Repeat current sequence"),
        ),
    ),
    NamedFieldSpec("Playback.Shake", "boolean", None, None, ()),
    NamedFieldSpec(
        "Playback.Shuffle",
        "string",
        None,
        None,
        (("off", "Off"), ("songs", "Shuffle songs"), ("albums", "Shuffle albums")),
    ),
    NamedFieldSpec("Playback.SoundCheck", "boolean", None, None, ()),
    NamedFieldSpec("Playback.VolumeLimit", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec("Settings.TransitionVersion", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec("Speakers.BacklightTimer", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec("Temp.BacklightTimer", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec("Trainer.DistanceUnits", "int32", 0, 1, ()),
    NamedFieldSpec("Trainer.Orientation", "int32", 0, 2, ()),
    NamedFieldSpec("Trainer.Pedometer", "int32", 0, 1, ()),
    NamedFieldSpec("Trainer.PedometerStepGoal", "int64", 0, 100000, ()),
    NamedFieldSpec(
        "Trainer.PowerPlaylist", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec(
        "Trainer.PowerSong", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec("Trainer.RemoteState", "int32", 0, 1, ()),
    NamedFieldSpec("Trainer.VoiceFeedback", "int32", 0, 2, ()),
    NamedFieldSpec(
        "Trainer.Weight", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec("Trainer.WeightCustomized", "boolean", None, None, ()),
    NamedFieldSpec("Video.TvAlternateAudio", "boolean", None, None, ()),
    NamedFieldSpec("Video.TvCaptions", "boolean", None, None, ()),
    NamedFieldSpec("Video.TvOut", "int32", 0, 2, ()),
    NamedFieldSpec("Video.TvScreenAspect", "int32", 0, 1, ()),
    NamedFieldSpec("Video.TvScreenFitToScreen", "boolean", None, None, ()),
    NamedFieldSpec("Video.TvSignal", "int32", 0, 1, ()),
    NamedFieldSpec("Video.TvSubtitles", "boolean", None, None, ()),
    NamedFieldSpec("Radio.LivePause", "boolean", None, None, ()),
)

NANO6_FIELDS: tuple[NamedFieldSpec, ...] = (
    NamedFieldSpec("Accessibility.Invert", "boolean", None, None, ()),
    NamedFieldSpec("Accessibility.MonoAudio", "boolean", None, None, ()),
    NamedFieldSpec("Accessibility.Speech", "int32", 0, 2, ()),
    NamedFieldSpec(
        "Accessibility.SpeechLocale",
        "string",
        None,
        None,
        (
            ("en-US", "en-US"),
            ("en-GB", "en-GB"),
            ("en-AU", "en-AU"),
            ("ja-JP", "ja-JP"),
            ("cs-CZ", "cs-CZ"),
            ("da-DK", "da-DK"),
            ("de-DE", "de-DE"),
            ("es-ES", "es-ES"),
            ("es-MX", "es-MX"),
            ("fr-FR", "fr-FR"),
            ("fr-CA", "fr-CA"),
            ("el-GR", "el-GR"),
            ("it-IT", "it-IT"),
            ("hu-HU", "hu-HU"),
            ("nl-NL", "nl-NL"),
            ("no-NO", "no-NO"),
            ("pt-PT", "pt-PT"),
            ("pt-BR", "pt-BR"),
            ("ru-RU", "ru-RU"),
            ("pl-PL", "pl-PL"),
            ("ro-RO", "ro-RO"),
            ("sk-SK", "sk-SK"),
            ("fi-FI", "fi-FI"),
            ("sv-SE", "sv-SE"),
            ("tr-TR", "tr-TR"),
            ("ko-KR", "ko-KR"),
            ("zh-CN", "zh-CN"),
            ("zh-HK", "zh-HK"),
            ("th-TH", "th-TH"),
        ),
    ),
    NamedFieldSpec("Accessibility.SpeechRate", "int32", 50, 400, ()),
    NamedFieldSpec("Accessibility.VoiceOverConfirm", "boolean", None, None, ()),
    NamedFieldSpec("Accessibility.VoiceOverSpeakHints", "boolean", None, None, ()),
    NamedFieldSpec("DateTime.ClockFace", "int32", 0, 17, ()),
    NamedFieldSpec("DateTime.TimeOnWake", "boolean", None, None, ()),
    NamedFieldSpec("DateTime.TimeZone", "int32", 0, 205, ()),
    NamedFieldSpec("DateTime.TwentyFourHourClock", "boolean", None, None, ()),
    NamedFieldSpec("DateTime.UserSet24HourSetting", "boolean", None, None, ()),
    NamedFieldSpec("General.BacklightTimer", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec("General.Brightness", "int32", 0, 100, ()),
    NamedFieldSpec(
        "General.Clicker", "string", None, None, (("off", "Off"), ("on", "On"))
    ),
    NamedFieldSpec("General.FontSize", "string", None, None, ()),
    NamedFieldSpec(
        "General.HomeScreen", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec(
        "General.Language",
        "string",
        None,
        None,
        (
            ("en-US", "English"),
            ("ja-JP", "日本語"),
            ("cs-CZ", "Čeština"),
            ("da-DK", "Dansk"),
            ("de-DE", "Deutsch"),
            ("es-ES", "Español"),
            ("fr-FR", "Français"),
            ("el-GR", "Ελληνικά"),
            ("hr-HR", "Hrvatski"),
            ("it-IT", "Italiano"),
            ("hu-HU", "Magyar"),
            ("nl-NL", "Nederlands"),
            ("no-NO", "Norsk"),
            ("pt-PT", "Português (Portugal)"),
            ("pt-BR", "Português (Brasil)"),
            ("ru-RU", "Русский"),
            ("pl-PL", "Polski"),
            ("ro-RO", "Română"),
            ("sk-SK", "Slovenčina"),
            ("fi-FI", "Suomi"),
            ("sv-SE", "Svenska"),
            ("tr-TR", "Türkçe"),
            ("ar-SA", "العربية"),
            ("ko-KR", "한글"),
            ("zh-CN", "简体中文"),
            ("zh-TW", "繁體中文"),
            ("zh-HK", "繁體中文（粵語）"),  # noqa: RUF001 -- exact firmware label
            ("he-IL", "עברית"),
            ("th-TH", "ภาษาไทย"),
        ),
    ),
    NamedFieldSpec(
        "General.MusicMenu", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec("General.PreviewPanel", "boolean", None, None, ()),
    NamedFieldSpec("General.RadioLivePause", "boolean", None, None, ()),
    NamedFieldSpec(
        "General.RadioRegion",
        "int32",
        -2147483648,
        2147483647,
        (
            ("1", "Americas"),
            ("11", "Asia"),
            ("4", "Australia"),
            ("2", "Europe"),
            ("3", "Japan"),
            ("10", "World Wide (TEST)"),
        ),
    ),
    NamedFieldSpec("General.RequirePasscodeLock", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec("General.Rotate", "boolean", None, None, ()),
    NamedFieldSpec("General.SBIconHint", "boolean", None, None, ()),
    NamedFieldSpec("General.SleepWakeButton", "int32", 0, 1, ()),
    NamedFieldSpec("General.SleepWakeButtonEnabled", "boolean", None, None, ()),
    NamedFieldSpec("General.SortContacts", "string", None, None, ()),
    NamedFieldSpec("General.SpringboardSmallIcons", "boolean", None, None, ()),
    NamedFieldSpec("General.UIRotation", "int32", 0, 3, ()),
    NamedFieldSpec("General.Wallpaper", "int32", 0, 12, ()),
    NamedFieldSpec("NowPlaying.EnergySaver", "boolean", None, None, ()),
    NamedFieldSpec("Photos.Music", "int32", 1, 5, ()),
    NamedFieldSpec("Photos.Repeat", "boolean", None, None, ()),
    NamedFieldSpec("Photos.Shuffle", "boolean", None, None, ()),
    NamedFieldSpec(
        "Photos.TimePerSlide",
        "int32",
        0,
        5,
        (
            ("1", "2 Seconds"),
            ("2", "3 Seconds"),
            ("3", "5 Seconds"),
            ("4", "10 Seconds"),
            ("5", "20 Seconds"),
        ),
    ),
    NamedFieldSpec(
        "Photos.Transitions",
        "int32",
        0,
        10,
        (
            # Nano6 original legacy label switch 0805fa88, separate from UI.
            ("0", "None"),
            ("1", "Random"),
            ("2", "Dissolve"),
            ("3", "Slide"),
            ("4", "Push"),
            ("5", "Fade Through Black"),
            ("6", "Zoom"),
            ("7", "Ken Burns"),
            ("8", "Cube"),
            ("9", "Page Flip"),
            ("10", "Origami"),
        ),
    ),
    NamedFieldSpec(
        "Playback.AudiobookSpeed",
        "string",
        None,
        None,
        (("slow", "Slow"), ("normal", "Normal"), ("fast", "Fast")),
    ),
    NamedFieldSpec("Playback.Compilations", "boolean", None, None, ()),
    NamedFieldSpec("Playback.Crossfade", "boolean", None, None, ()),
    NamedFieldSpec(
        "Playback.EQ",
        "int32",
        -2147483648,
        2147483647,
        (
            ("0", "Off"),
            ("100", "Acoustic"),
            ("101", "Bass Booster"),
            ("102", "Bass Reducer"),
            ("103", "Classical"),
            ("104", "Dance"),
            ("105", "Deep"),
            ("106", "Electronic"),
            ("107", "Flat"),
            ("108", "Hip Hop"),
            ("109", "Jazz"),
            ("110", "Latin"),
            ("111", "Loudness"),
            ("112", "Lounge"),
            ("113", "Piano"),
            ("114", "Pop"),
            ("115", "R&B"),
            ("116", "Rock"),
            ("117", "Small Speakers"),
            ("118", "Spoken Word"),
            ("119", "Treble Booster"),
            ("120", "Treble Reducer"),
            ("121", "Vocal Booster"),
        ),
    ),
    NamedFieldSpec("Playback.EnergySaver", "boolean", None, None, ()),
    NamedFieldSpec(
        "Playback.Repeat",
        "string",
        None,
        None,
        (
            ("off", "Off"),
            ("one", "Repeat current item"),
            ("all", "Repeat current sequence"),
        ),
    ),
    NamedFieldSpec("Playback.Shake", "boolean", None, None, ()),
    NamedFieldSpec(
        "Playback.Shuffle",
        "string",
        None,
        None,
        (("off", "Off"), ("songs", "Shuffle songs"), ("albums", "Shuffle albums")),
    ),
    NamedFieldSpec("Playback.SoundCheck", "boolean", None, None, ()),
    NamedFieldSpec("Playback.VolumeLimit", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec("Resume.IsSingleSong", "boolean", None, None, ()),
    NamedFieldSpec("Resume.IsValid", "boolean", None, None, ()),
    NamedFieldSpec(
        "Resume.Playlist", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec("Resume.Repeat", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec("Resume.Shuffle", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec(
        "Resume.Track", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec("Resume.TrackMS", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec("Settings.SoftwareVersion", "string", None, None, ()),
    NamedFieldSpec("Temp.BacklightTimer", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec(
        "Trainer.BodyLocation",
        "int32",
        0,
        3,
        (("0", "Waist"), ("1", "Chest"), ("2", "Pocket"), ("3", "Wrist")),
    ),
    NamedFieldSpec("Trainer.BodyLocationCustomized", "boolean", None, None, ()),
    NamedFieldSpec(
        "Trainer.DistanceUnits", "int32", 0, 1, (("1", "Miles"), ("0", "Kilometers"))
    ),
    NamedFieldSpec("Trainer.Gender", "int32", 0, 1, (("0", "Male"), ("1", "Female"))),
    NamedFieldSpec("Trainer.GenderCustomized", "boolean", None, None, ()),
    NamedFieldSpec("Trainer.HROWorkout_LastActivity", "int32", 1, 17, ()),
    NamedFieldSpec(
        "Trainer.Height", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec("Trainer.HeightCustomized", "boolean", None, None, ()),
    NamedFieldSpec(
        "Trainer.MeasurementSystem", "int32", 0, 1, (("1", "English"), ("0", "Metric"))
    ),
    NamedFieldSpec("Trainer.Orientation", "int32", 0, 2, ()),
    NamedFieldSpec("Trainer.Pedometer", "int32", 0, 1, ()),
    NamedFieldSpec("Trainer.PedometerActivty", "int32", 0, 4, ()),
    NamedFieldSpec("Trainer.PedometerStepGoal", "int64", 0, 100900, ()),
    NamedFieldSpec("Trainer.PedometerStepGoalSet", "boolean", None, None, ()),
    NamedFieldSpec("Trainer.PersonalSettingsCustomized", "boolean", None, None, ()),
    NamedFieldSpec(
        "Trainer.PowerPlaylist", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec(
        "Trainer.PowerSong", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec("Trainer.RemoteState", "boolean", None, None, ()),
    NamedFieldSpec("Trainer.TrainerSplashScreenShown", "boolean", None, None, ()),
    NamedFieldSpec(
        "Trainer.VoiceFeedback",
        "int32",
        0,
        2,
        (("1", "Female"), ("0", "Male"), ("2", "Off")),
    ),
    NamedFieldSpec(
        "Trainer.Weight", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec("Trainer.WeightCustomized", "boolean", None, None, ()),
    NamedFieldSpec("Trainer.WeightUnits", "int32", 0, 1, ()),
    NamedFieldSpec("Trainer.ZoneWorkout_Enabled", "boolean", None, None, ()),
    NamedFieldSpec("Trainer.ZoneWorkout_High", "int32", 15, 240, ()),
    NamedFieldSpec("Trainer.ZoneWorkout_Low", "int32", 15, 240, ()),
    NamedFieldSpec("Trainer.ZoneWorkout_ZoneSet", "boolean", None, None, ()),
    NamedFieldSpec("Video.TvOut", "int32", 0, 1, ()),
    NamedFieldSpec("Video.TvScreenAspect", "int32", 0, 1, ()),
    NamedFieldSpec("Video.TvScreenFitToScreen", "boolean", None, None, ()),
    NamedFieldSpec("Video.TvSignal", "int32", 0, 1, ()),
)

NANO7_FIELDS: tuple[NamedFieldSpec, ...] = (
    NamedFieldSpec("Accessibility.Invert", "boolean", None, None, ()),
    NamedFieldSpec("Accessibility.MonoAudio", "boolean", None, None, ()),
    NamedFieldSpec("Accessibility.Speech", "int32", 0, 2, ()),
    NamedFieldSpec(
        "Accessibility.SpeechLocale",
        "string",
        None,
        None,
        (
            ("en-US", "en-US"),
            ("en-GB", "en-GB"),
            ("en-AU", "en-AU"),
            ("ja-JP", "ja-JP"),
            ("cs-CZ", "cs-CZ"),
            ("da-DK", "da-DK"),
            ("de-DE", "de-DE"),
            ("es-ES", "es-ES"),
            ("es-MX", "es-MX"),
            ("fr-FR", "fr-FR"),
            ("fr-CA", "fr-CA"),
            ("el-GR", "el-GR"),
            ("it-IT", "it-IT"),
            ("hu-HU", "hu-HU"),
            ("nl-NL", "nl-NL"),
            ("no-NO", "no-NO"),
            ("pt-PT", "pt-PT"),
            ("pt-BR", "pt-BR"),
            ("ru-RU", "ru-RU"),
            ("pl-PL", "pl-PL"),
            ("ro-RO", "ro-RO"),
            ("sk-SK", "sk-SK"),
            ("fi-FI", "fi-FI"),
            ("sv-SE", "sv-SE"),
            ("tr-TR", "tr-TR"),
            ("ko-KR", "ko-KR"),
            ("zh-CN", "zh-CN"),
            ("zh-HK", "zh-HK"),
            ("th-TH", "th-TH"),
        ),
    ),
    NamedFieldSpec("Accessibility.SpeechRate", "int32", 50, 400, ()),
    NamedFieldSpec(
        "Accessibility.TripleClickHome",
        "int32",
        0,
        3,
        (("0", "Off"), ("1", "Toggle VoiceOver"), ("2", "Toggle Invert Colors")),
    ),
    NamedFieldSpec("Accessibility.VoiceOverConfirm", "boolean", None, None, ()),
    NamedFieldSpec("Accessibility.VoiceOverSpeakHints", "boolean", None, None, ()),
    NamedFieldSpec("Bluetooth.Enabled", "boolean", None, None, ()),
    NamedFieldSpec("DateTime.ClockFace", "int32", 0, 5, ()),
    NamedFieldSpec("DateTime.TimeOnWake", "boolean", None, None, ()),
    NamedFieldSpec("DateTime.TimeZone", "int32", 0, 205, ()),
    NamedFieldSpec("DateTime.TwentyFourHourClock", "boolean", None, None, ()),
    NamedFieldSpec("DateTime.UserSet24HourSetting", "boolean", None, None, ()),
    NamedFieldSpec("DateTime.WorldClock1TimeZone", "int32", 0, 205, ()),
    NamedFieldSpec("DateTime.WorldClock2TimeZone", "int32", 0, 205, ()),
    NamedFieldSpec("General.BacklightTimer", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec("General.Brightness", "int32", 0, 100, ()),
    NamedFieldSpec(
        "General.Clicker", "string", None, None, (("off", "Off"), ("on", "On"))
    ),
    NamedFieldSpec("General.FontSize", "string", None, None, ()),
    NamedFieldSpec(
        "General.HomeScreen", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec(
        "General.Language",
        "string",
        None,
        None,
        (
            ("en-US", "English (US)"),
            ("en-GB", "English (UK)"),
            ("ja-JP", "日本語"),
            ("cs-CZ", "Čeština"),
            ("da-DK", "Dansk"),
            ("de-DE", "Deutsch"),
            ("es-ES", "Español"),
            ("fr-FR", "Français"),
            ("el-GR", "Ελληνικά"),
            ("hr-HR", "Hrvatski"),
            ("it-IT", "Italiano"),
            ("hu-HU", "Magyar"),
            ("nl-NL", "Nederlands"),
            ("no-NO", "Norsk"),
            ("pt-PT", "Português (Portugal)"),
            ("pt-BR", "Português (Brasil)"),
            ("ru-RU", "Русский"),
            ("pl-PL", "Polski"),
            ("ro-RO", "Română"),
            ("sk-SK", "Slovenčina"),
            ("fi-FI", "Suomi"),
            ("sv-SE", "Svenska"),
            ("tr-TR", "Türkçe"),
            ("uk-UA", "Украї́нська"),
            ("ar-SA", "العربية"),
            ("ko-KR", "한글"),
            ("zh-CN", "简体中文"),
            ("zh-TW", "繁體中文"),
            ("zh-HK", "繁體中文（粵語）"),  # noqa: RUF001 -- exact firmware label
            ("he-IL", "עברית"),
            ("th-TH", "ภาษาไทย"),
            ("id-ID", "Bahasa Indonesia"),
            ("ms-MY", "Bahasa Melayu"),
            ("ca-ES", "Català"),
            ("vi-VN", "Tiếng Việt"),
        ),
    ),
    NamedFieldSpec(
        "General.MusicMenu", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec("General.PreviewPanel", "boolean", None, None, ()),
    NamedFieldSpec("General.RadioLivePause", "boolean", None, None, ()),
    NamedFieldSpec(
        "General.RadioRegion",
        "int32",
        -2147483648,
        2147483647,
        (
            ("1", "Americas"),
            ("11", "Asia"),
            ("4", "Australia"),
            ("2", "Europe"),
            ("3", "Japan"),
            ("10", "World Wide (TEST)"),
        ),
    ),
    NamedFieldSpec("General.RequirePasscodeLock", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec("General.Rotate", "boolean", None, None, ()),
    NamedFieldSpec("General.SleepWakeButton", "int32", 0, 1, ()),
    NamedFieldSpec("General.SleepWakeButtonEnabled", "boolean", None, None, ()),
    NamedFieldSpec("General.SortContacts", "string", None, None, ()),
    NamedFieldSpec("General.UIRotation", "int32", 0, 3, ()),
    NamedFieldSpec("General.Wallpaper", "int32", 0, 5, ()),
    NamedFieldSpec("NowPlaying.EnergySaver", "boolean", None, None, ()),
    NamedFieldSpec("Photos.Music", "int32", 1, 5, ()),
    NamedFieldSpec("Photos.Repeat", "boolean", None, None, ()),
    NamedFieldSpec("Photos.Shuffle", "boolean", None, None, ()),
    NamedFieldSpec(
        "Photos.TimePerSlide",
        "int32",
        0,
        5,
        (
            ("1", "2 Seconds"),
            ("2", "3 Seconds"),
            ("3", "5 Seconds"),
            ("4", "10 Seconds"),
            ("5", "20 Seconds"),
        ),
    ),
    NamedFieldSpec(
        "Photos.Transitions",
        "int32",
        2,
        10,
        (
            ("2", "Dissolve"),
            ("7", "Ken Burns"),
            ("9", "Page Flip"),
            ("4", "Push"),
            ("10", "Origami"),
        ),
    ),
    NamedFieldSpec("Playback.AirplaneMode", "boolean", None, None, ()),
    NamedFieldSpec(
        "Playback.AudiobookSpeed",
        "string",
        None,
        None,
        (("slow", "Slow"), ("normal", "Normal"), ("fast", "Fast")),
    ),
    NamedFieldSpec("Playback.Compilations", "boolean", None, None, ()),
    NamedFieldSpec("Playback.Crossfade", "boolean", None, None, ()),
    NamedFieldSpec(
        "Playback.EQ",
        "int32",
        -2147483648,
        2147483647,
        (
            ("0", "Off"),
            ("100", "Acoustic"),
            ("101", "Bass Booster"),
            ("102", "Bass Reducer"),
            ("103", "Classical"),
            ("104", "Dance"),
            ("105", "Deep"),
            ("106", "Electronic"),
            ("107", "Flat"),
            ("108", "Hip Hop"),
            ("109", "Jazz"),
            ("110", "Latin"),
            ("111", "Loudness"),
            ("112", "Lounge"),
            ("113", "Piano"),
            ("114", "Pop"),
            ("115", "R&B"),
            ("116", "Rock"),
            ("117", "Small Speakers"),
            ("118", "Spoken Word"),
            ("119", "Treble Booster"),
            ("120", "Treble Reducer"),
            ("121", "Vocal Booster"),
        ),
    ),
    NamedFieldSpec("Playback.EnergySaver", "boolean", None, None, ()),
    NamedFieldSpec("Playback.HeadsetEQ", "boolean", None, None, ()),
    NamedFieldSpec(
        "Playback.Repeat",
        "string",
        None,
        None,
        (
            ("off", "Off"),
            ("one", "Repeat current item"),
            ("all", "Repeat current sequence"),
        ),
    ),
    NamedFieldSpec("Playback.Shake", "boolean", None, None, ()),
    NamedFieldSpec(
        "Playback.Shuffle",
        "string",
        None,
        None,
        (("off", "Off"), ("songs", "Shuffle songs"), ("albums", "Shuffle albums")),
    ),
    NamedFieldSpec("Playback.SoundCheck", "boolean", None, None, ()),
    NamedFieldSpec("Playback.UseRecommendedVolumeRange", "boolean", None, None, ()),
    NamedFieldSpec("Playback.VolumeLimit", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec("Resume.IsSingleSong", "boolean", None, None, ()),
    NamedFieldSpec("Resume.IsValid", "boolean", None, None, ()),
    NamedFieldSpec(
        "Resume.Playlist", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec("Resume.Repeat", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec("Resume.Shuffle", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec(
        "Resume.Track", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec("Resume.TrackMS", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec("Settings.SoftwareVersion", "string", None, None, ()),
    NamedFieldSpec("Temp.BacklightTimer", "int32", -2147483648, 2147483647, ()),
    NamedFieldSpec(
        "Trainer.BodyLocation",
        "int32",
        0,
        3,
        (("0", "Waist"), ("1", "Chest"), ("2", "Pocket"), ("3", "Wrist")),
    ),
    NamedFieldSpec("Trainer.BodyLocationCustomized", "boolean", None, None, ()),
    NamedFieldSpec(
        "Trainer.DistanceUnits", "int32", 0, 1, (("1", "Miles"), ("0", "Kilometers"))
    ),
    NamedFieldSpec("Trainer.Gender", "int32", 0, 1, (("0", "Male"), ("1", "Female"))),
    NamedFieldSpec("Trainer.GenderCustomized", "boolean", None, None, ()),
    NamedFieldSpec("Trainer.HRMState", "boolean", None, None, ()),
    NamedFieldSpec("Trainer.HROWorkout_LastActivity", "int32", 1, 17, ()),
    NamedFieldSpec(
        "Trainer.Height", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec("Trainer.HeightCustomized", "boolean", None, None, ()),
    NamedFieldSpec(
        "Trainer.MeasurementSystem", "int32", 0, 1, (("1", "English"), ("0", "Metric"))
    ),
    NamedFieldSpec("Trainer.Orientation", "int32", 0, 2, ()),
    NamedFieldSpec("Trainer.Pedometer", "int32", 0, 1, ()),
    NamedFieldSpec("Trainer.PedometerActivty", "int32", 0, 4, ()),
    NamedFieldSpec("Trainer.PedometerStepGoal", "int64", 0, 100900, ()),
    NamedFieldSpec("Trainer.PedometerStepGoalSet", "boolean", None, None, ()),
    NamedFieldSpec("Trainer.PersonalSettingsCustomized", "boolean", None, None, ()),
    NamedFieldSpec(
        "Trainer.PowerPlaylist", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec(
        "Trainer.PowerSong", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec("Trainer.RemoteState", "boolean", None, None, ()),
    NamedFieldSpec("Trainer.Sensor", "boolean", None, None, ()),
    NamedFieldSpec(
        "Trainer.VoiceFeedback",
        "int32",
        0,
        2,
        (("1", "Female"), ("0", "Male"), ("2", "Off")),
    ),
    NamedFieldSpec(
        "Trainer.Weight", "int64", -9223372036854775808, 9223372036854775807, ()
    ),
    NamedFieldSpec("Trainer.WeightCustomized", "boolean", None, None, ()),
    NamedFieldSpec("Trainer.WeightUnits", "int32", 0, 1, ()),
    NamedFieldSpec("Trainer.ZoneWorkout_Enabled", "boolean", None, None, ()),
    NamedFieldSpec("Trainer.ZoneWorkout_High", "int32", 15, 240, ()),
    NamedFieldSpec("Trainer.ZoneWorkout_Low", "int32", 15, 240, ()),
    NamedFieldSpec("Trainer.ZoneWorkout_ZoneSet", "boolean", None, None, ()),
    NamedFieldSpec("Video.StartPlaying", "int32", 0, 1, ()),
    NamedFieldSpec("Video.TvAlternateAudio", "boolean", None, None, ()),
    NamedFieldSpec("Video.TvCaptions", "boolean", None, None, ()),
    NamedFieldSpec("Video.TvOut", "int32", 0, 1, ()),
    NamedFieldSpec("Video.TvPreferCCorSDH", "boolean", None, None, ()),
    NamedFieldSpec("Video.TvScreenAspect", "int32", 0, 1, ()),
    NamedFieldSpec("Video.TvScreenFitToScreen", "boolean", None, None, ()),
    NamedFieldSpec("Video.TvSignal", "int32", 0, 1, ()),
)

NANO4_FIELDS: tuple[NamedFieldSpec, ...] = (
    NamedFieldSpec("NowPlaying.EnergySaver", "boolean"),
    NamedFieldSpec("NowPlaying.Crossfade", "boolean"),
    NamedFieldSpec(
        "Settings.FontSize", "int32", 0, 1, (("0", "Standard"), ("1", "Large"))
    ),
    NamedFieldSpec("Settings.ShakeSetting", "boolean"),
    NamedFieldSpec("Settings.VoiceFeedback", "boolean"),
    NamedFieldSpec("Settings.PreviewPanel", "boolean"),
)

FIELDS_BY_PROFILE: dict[NamedPreferencesProfile, tuple[NamedFieldSpec, ...]] = {
    NamedPreferencesProfile.NANO_4_1_0_4: NANO4_FIELDS,
    NamedPreferencesProfile.NANO_5_1_0_2: NANO5_FIELDS,
    NamedPreferencesProfile.NANO_6_1_2: NANO6_FIELDS,
    NamedPreferencesProfile.NANO_7_1_0_4: NANO7_FIELDS,
    NamedPreferencesProfile.NANO_UPDATER_39_1_1_2: NANO7_FIELDS,
}

FIRMWARE_CITIES: dict[int, FirmwareCity] = {
    1: FirmwareCity(
        "California", -480, -480, -480, "America/Los_Angeles", "America/Los_Angeles"
    ),
    2: FirmwareCity("Chicago", -360, -360, -360, "America/Chicago", "America/Chicago"),
    3: FirmwareCity(
        "Honolulu", -600, -600, -600, "Pacific/Honolulu", "Pacific/Honolulu"
    ),
    4: FirmwareCity(
        "Anchorage", -540, -540, -540, "America/Anchorage", "America/Anchorage"
    ),
    5: FirmwareCity(
        "Cupertino", -480, -480, -480, "America/Los_Angeles", "America/Los_Angeles"
    ),
    6: FirmwareCity(
        "Los Angeles", -480, -480, -480, "America/Los_Angeles", "America/Los_Angeles"
    ),
    7: FirmwareCity(
        "Portland", -480, -480, -480, "America/Los_Angeles", "America/Los_Angeles"
    ),
    8: FirmwareCity(
        "San Diego", -480, -480, -480, "America/Los_Angeles", "America/Los_Angeles"
    ),
    9: FirmwareCity(
        "San Francisco", -480, -480, -480, "America/Los_Angeles", "America/Los_Angeles"
    ),
    10: FirmwareCity(
        "Seattle", -480, -480, -480, "America/Los_Angeles", "America/Los_Angeles"
    ),
    11: FirmwareCity(
        "Vancouver", -480, -480, -480, "America/Vancouver", "America/Vancouver"
    ),
    12: FirmwareCity(
        "Calgary", -420, -420, -420, "America/Edmonton", "America/Edmonton"
    ),
    13: FirmwareCity("Denver", -420, -420, -420, "America/Denver", "America/Denver"),
    14: FirmwareCity("Phoenix", -420, -420, -420, "America/Phoenix", "America/Phoenix"),
    15: FirmwareCity(
        "Salt Lake City", -420, -420, -420, "America/Denver", "America/Denver"
    ),
    16: FirmwareCity("Austin", -360, -360, -360, "America/Chicago", "America/Chicago"),
    17: FirmwareCity("Dallas", -360, -360, -360, "America/Chicago", "America/Chicago"),
    18: FirmwareCity(
        "Guatemala", -360, -360, -360, "America/Tegucigalpa", "America/Tegucigalpa"
    ),
    19: FirmwareCity("Managua", -360, -360, -360, "America/Managua", "America/Managua"),
    20: FirmwareCity("Memphis", -360, -360, -360, "America/Chicago", "America/Chicago"),
    21: FirmwareCity(
        "Mexico City", -360, -360, -360, "America/Mexico_City", "America/Mexico_City"
    ),
    22: FirmwareCity(
        "Minneapolis", -360, -360, -360, "America/Chicago", "America/Chicago"
    ),
    23: FirmwareCity("Regina", -360, -360, -360, "America/Regina", "America/Regina"),
    24: FirmwareCity(
        "San José", -360, -360, -360, "America/Costa_Rica", "America/Costa_Rica"
    ),
    25: FirmwareCity(
        "San Salvador", -360, -360, -360, "America/El_Salvador", "America/El_Salvador"
    ),
    26: FirmwareCity(
        "St. Louis", -360, -360, -360, "America/Chicago", "America/Chicago"
    ),
    27: FirmwareCity(
        "Tegucigalpa", -360, -360, -360, "America/Tegucigalpa", "America/Tegucigalpa"
    ),
    28: FirmwareCity(
        "Winnipeg", -360, -360, -360, "America/Winnipeg", "America/Winnipeg"
    ),
    29: FirmwareCity(
        "Atlanta", -300, -300, -300, "America/New_York", "America/New_York"
    ),
    30: FirmwareCity("Bogotá", -300, -300, -300, "America/Bogota", "America/Bogota"),
    31: FirmwareCity(
        "Boston", -300, -300, -300, "America/New_York", "America/New_York"
    ),
    32: FirmwareCity(
        "Columbus", -300, -300, -300, "America/New_York", "America/New_York"
    ),
    33: FirmwareCity(
        "Detroit", -300, -300, -300, "America/New_York", "America/New_York"
    ),
    34: FirmwareCity("Havana", -300, -300, -300, "America/Havana", "America/Havana"),
    35: FirmwareCity(
        "Indianapolis",
        -300,
        -300,
        -300,
        "America/Indiana/Indianapolis",
        "America/Indiana/Indianapolis",
    ),
    36: FirmwareCity(
        "Knoxville", -300, -300, -300, "America/New_York", "America/New_York"
    ),
    37: FirmwareCity("Lima", -300, -300, -300, "America/Lima", "America/Lima"),
    38: FirmwareCity(
        "Manchester", -300, -300, -300, "America/New_York", "America/New_York"
    ),
    39: FirmwareCity("Miami", -300, -300, -300, "America/New_York", "America/New_York"),
    40: FirmwareCity(
        "Montréal", -300, -300, -300, "America/Montreal", "America/Montreal"
    ),
    41: FirmwareCity(
        "New York", -300, -300, -300, "America/New_York", "America/New_York"
    ),
    42: FirmwareCity("Ottawa", -300, -300, -300, "America/Toronto", "America/Toronto"),
    43: FirmwareCity("Panama", -300, -300, -300, "America/Panama", "America/Panama"),
    44: FirmwareCity(
        "Philadelphia", -300, -300, -300, "America/New_York", "America/New_York"
    ),
    45: FirmwareCity(
        "Port-au-Prince",
        -300,
        -300,
        -300,
        "America/Port-au-Prince",
        "America/Port-au-Prince",
    ),
    46: FirmwareCity(
        "Quito", -300, -300, -300, "America/Guayaquil", "America/Guayaquil"
    ),
    47: FirmwareCity("Toronto", -300, -300, -300, "America/Toronto", "America/Toronto"),
    48: FirmwareCity(
        "Washington, D.C.", -300, -300, -300, "America/New_York", "America/New_York"
    ),
    49: FirmwareCity(
        "Asunción", -240, -240, -240, "America/Asuncion", "America/Asuncion"
    ),
    50: FirmwareCity("Caracas", -270, -270, -270, "America/Caracas", "America/Caracas"),
    51: FirmwareCity(
        "Georgetown", -240, -240, -240, "America/Guyana", "America/Guyana"
    ),
    52: FirmwareCity("Halifax", -240, -240, -240, "America/Halifax", "America/Halifax"),
    53: FirmwareCity("La Paz", -240, -240, -240, "America/La_Paz", "America/La_Paz"),
    54: FirmwareCity(
        "San Juan", -240, -240, -240, "America/Puerto_Rico", "America/Puerto_Rico"
    ),
    55: FirmwareCity(
        "Santiago", -240, -240, -240, "America/Santiago", "America/Santiago"
    ),
    56: FirmwareCity(
        "Santo Domingo",
        -240,
        -240,
        -240,
        "America/Santo_Domingo",
        "America/Santo_Domingo",
    ),
    57: FirmwareCity(
        "St. John's", -210, -210, -210, "America/St_Johns", "America/St_Johns"
    ),
    58: FirmwareCity(
        "Brasília", -180, -180, -180, "America/Sao_Paulo", "America/Sao_Paulo"
    ),
    59: FirmwareCity(
        "Buenos Aires",
        -180,
        -180,
        -180,
        "America/Argentina/Buenos_Aires",
        "America/Argentina/Buenos_Aires",
    ),
    60: FirmwareCity("Cayenne", -180, -180, -180, "America/Cayenne", "America/Cayenne"),
    61: FirmwareCity(
        "Montevideo", -180, -180, -180, "America/Montevideo", "America/Montevideo"
    ),
    62: FirmwareCity("Nuuk", -180, -180, -180, "America/Godthab", "America/Godthab"),
    63: FirmwareCity(
        "Paramaribo", -180, -180, -180, "America/Paramaribo", "America/Paramaribo"
    ),
    64: FirmwareCity("Recife", -180, -180, -180, "America/Recife", "America/Recife"),
    65: FirmwareCity(
        "Rio de Janeiro", -180, -180, -180, "America/Sao_Paulo", "America/Sao_Paulo"
    ),
    66: FirmwareCity(
        "São Paulo", -180, -180, -180, "America/Sao_Paulo", "America/Sao_Paulo"
    ),
    67: FirmwareCity(
        "Grytviken",
        -120,
        -120,
        -120,
        "Atlantic/South_Georgia",
        "Atlantic/South_Georgia",
    ),
    68: FirmwareCity(
        "Ponta Delgada", -60, -60, -60, "Atlantic/Azores", "Atlantic/Azores"
    ),
    69: FirmwareCity("Cork", 0, 0, 0, "Europe/Dublin", "Europe/Dublin"),
    70: FirmwareCity("Accra", 0, 0, 0, "Africa/Accra", "Africa/Accra"),
    71: FirmwareCity("Bamako", 0, 0, 0, "Africa/Bamako", "Africa/Bamako"),
    72: FirmwareCity("Cardiff", 0, 0, 0, "Europe/London", "Europe/London"),
    73: FirmwareCity("Conakry", 0, 0, 0, "Africa/Conakry", "Africa/Conakry"),
    74: FirmwareCity("Dakar", 0, 0, 0, "Africa/Dakar", "Africa/Dakar"),
    75: FirmwareCity("Dublin", 0, 0, 0, "Europe/Dublin", "Europe/Dublin"),
    76: FirmwareCity("Edinburgh", 0, 0, 0, "Europe/London", "Europe/London"),
    77: FirmwareCity("Freetown", 0, 0, 0, "Africa/Freetown", "Africa/Freetown"),
    78: FirmwareCity("Lisbon", 0, 0, 0, "Europe/Lisbon", "Europe/Lisbon"),
    79: FirmwareCity("London", 0, 0, 0, "Europe/London", "Europe/London"),
    80: FirmwareCity("Monrovia", 0, 0, 0, "Africa/Monrovia", "Africa/Monrovia"),
    81: FirmwareCity("Nouakchott", 0, 0, 0, "Africa/Nouakchott", "Africa/Nouakchott"),
    82: FirmwareCity(
        "Ouagadougou", 0, 0, 0, "Africa/Ouagadougou", "Africa/Ouagadougou"
    ),
    83: FirmwareCity("Reykjavík", 0, 0, 0, "Atlantic/Reykjavik", "Atlantic/Reykjavik"),
    84: FirmwareCity("Algiers", 60, 60, 60, "Africa/Algiers", "Africa/Algiers"),
    85: FirmwareCity("Amsterdam", 60, 60, 60, "Europe/Amsterdam", "Europe/Amsterdam"),
    86: FirmwareCity("Bangui", 60, 60, 60, "Africa/Bangui", "Africa/Bangui"),
    87: FirmwareCity("Belgrade", 60, 60, 60, "Europe/Belgrade", "Europe/Belgrade"),
    88: FirmwareCity("Berlin", 60, 60, 60, "Europe/Berlin", "Europe/Berlin"),
    89: FirmwareCity("Brussels", 60, 60, 60, "Europe/Brussels", "Europe/Brussels"),
    90: FirmwareCity("Budapest", 60, 60, 60, "Europe/Budapest", "Europe/Budapest"),
    91: FirmwareCity(
        "Copenhagen", 60, 60, 60, "Europe/Copenhagen", "Europe/Copenhagen"
    ),
    92: FirmwareCity("Douala", 60, 60, 60, "Africa/Douala", "Africa/Douala"),
    93: FirmwareCity("Geneva", 60, 60, 60, "Europe/Paris", "Europe/Paris"),
    94: FirmwareCity("Kinshasa", 60, 60, 60, "Africa/Kinshasa", "Africa/Kinshasa"),
    95: FirmwareCity("Lagos", 60, 60, 60, "Africa/Lagos", "Africa/Lagos"),
    96: FirmwareCity("Ljubljana", 60, 60, 60, "Europe/Belgrade", "Europe/Belgrade"),
    97: FirmwareCity("Luanda", 60, 60, 60, "Africa/Luanda", "Africa/Luanda"),
    98: FirmwareCity("Madrid", 60, 60, 60, "Europe/Madrid", "Europe/Madrid"),
    99: FirmwareCity("Munich", 60, 60, 60, "Europe/Berlin", "Europe/Berlin"),
    100: FirmwareCity("Ndjamena", 60, 60, 60, "Africa/Douala", "Africa/Douala"),
    101: FirmwareCity("Oslo", 60, 60, 60, "Europe/Warsaw", "Europe/Warsaw"),
    102: FirmwareCity("Paris", 60, 60, 60, "Europe/Paris", "Europe/Paris"),
    103: FirmwareCity("Prague", 60, 60, 60, "Europe/Prague", "Europe/Prague"),
    104: FirmwareCity("Rabat", 0, 0, 0, "Africa/Casablanca", "Africa/Casablanca"),
    105: FirmwareCity("Roma (Rome)", 60, 60, 60, "Europe/Rome", "Europe/Rome"),
    106: FirmwareCity("Stockholm", 60, 60, 60, "Europe/Stockholm", "Europe/Stockholm"),
    107: FirmwareCity("Tripoli", 120, 120, 60, "Africa/Tripoli", "Africa/Tripoli"),
    108: FirmwareCity("Tunis", 60, 60, 60, "Africa/Tunis", "Africa/Tunis"),
    109: FirmwareCity("Vienna", 60, 60, 60, "Europe/Vienna", "Europe/Vienna"),
    110: FirmwareCity("Warsaw", 60, 60, 60, "Europe/Warsaw", "Europe/Warsaw"),
    111: FirmwareCity("Zagreb", 60, 60, 60, "Europe/Belgrade", "Europe/Belgrade"),
    112: FirmwareCity("Zurich", 60, 60, 60, "Europe/Zurich", "Europe/Zurich"),
    113: FirmwareCity("Amman", 120, 120, 120, "Asia/Amman", "Asia/Amman"),
    114: FirmwareCity("Ankara", 120, 120, 120, "Europe/Istanbul", "Europe/Istanbul"),
    115: FirmwareCity("Beirut", 120, 120, 120, "Asia/Beirut", "Asia/Beirut"),
    116: FirmwareCity(
        "Bucharest", 120, 120, 120, "Europe/Bucharest", "Europe/Bucharest"
    ),
    117: FirmwareCity("Cairo", 120, 120, 120, "Africa/Cairo", "Africa/Cairo"),
    118: FirmwareCity("Cape Town", 120, 0, 0, "Africa/Bissau", "Africa/Bissau"),
    119: FirmwareCity("Harare", 120, 120, 120, "Africa/Harare", "Africa/Harare"),
    120: FirmwareCity("Helsinki", 120, 120, 120, "Europe/Helsinki", "Europe/Helsinki"),
    121: FirmwareCity("Istanbul", 120, 120, 120, "Europe/Istanbul", "Europe/Istanbul"),
    122: FirmwareCity("Jerusalem", 120, 120, 120, "Asia/Jerusalem", "Asia/Jerusalem"),
    123: FirmwareCity("Khartoum", 180, 180, 180, "Africa/Khartoum", "Africa/Khartoum"),
    124: FirmwareCity("Kiev", 120, 120, 120, "Europe/Kiev", "Europe/Kiev"),
    125: FirmwareCity("Lusaka", 120, 120, 120, "Africa/Lusaka", "Africa/Lusaka"),
    126: FirmwareCity("Maputo", 120, 120, 120, "Africa/Maputo", "Africa/Maputo"),
    127: FirmwareCity("Sofia", 120, 120, 120, "Europe/Sofia", "Europe/Sofia"),
    128: FirmwareCity(
        "Addis Ababa", 180, 180, 180, "Africa/Addis_Ababa", "Africa/Addis_Ababa"
    ),
    129: FirmwareCity(
        "Antananarivo", 180, 180, 180, "Indian/Antananarivo", "Indian/Antananarivo"
    ),
    130: FirmwareCity("Asmera", 180, 180, 180, "Africa/Asmara", "Africa/Asmara"),
    131: FirmwareCity("Baghdad", 180, 180, 180, "Asia/Baghdad", "Asia/Baghdad"),
    132: FirmwareCity("Damascus", 120, 120, 120, "Asia/Damascus", "Asia/Damascus"),
    133: FirmwareCity(
        "Dar es Salaam", 180, 180, 180, "Africa/Dar_es_Salaam", "Africa/Dar_es_Salaam"
    ),
    134: FirmwareCity("Djibouti", 180, 180, 180, "Africa/Djibouti", "Africa/Djibouti"),
    135: FirmwareCity("Doha", 180, 180, 180, "Asia/Qatar", "Asia/Qatar"),
    136: FirmwareCity("Kampala", 180, 180, 180, "Africa/Kampala", "Africa/Kampala"),
    137: FirmwareCity("Manama", 180, 180, 180, "Asia/Bahrain", "Asia/Bahrain"),
    138: FirmwareCity("Mecca", 180, 180, 180, "Asia/Riyadh", "Asia/Riyadh"),
    139: FirmwareCity(
        "Mogadishu", 180, 180, 180, "Africa/Mogadishu", "Africa/Mogadishu"
    ),
    140: FirmwareCity("Moscow", 180, 180, 240, "Europe/Moscow", "Europe/Moscow"),
    141: FirmwareCity("Nairobi", 180, 180, 180, "Africa/Nairobi", "Africa/Nairobi"),
    142: FirmwareCity("Riyadh", 180, 180, 180, "Asia/Riyadh", "Asia/Riyadh"),
    143: FirmwareCity("Sanaa", 180, 180, 180, "Asia/Aden", "Asia/Aden"),
    144: FirmwareCity(
        "St. Petersburg", 180, 180, 240, "Europe/Moscow", "Europe/Moscow"
    ),
    145: FirmwareCity(
        "Volgograd", 180, 180, 240, "Europe/Volgograd", "Europe/Volgograd"
    ),
    146: FirmwareCity("Abu Dhabi", 240, 240, 240, "Asia/Dubai", "Asia/Dubai"),
    147: FirmwareCity("Muscat", 240, 240, 240, "Asia/Muscat", "Asia/Muscat"),
    148: FirmwareCity(
        "Port Louis", 240, 240, 240, "Indian/Mauritius", "Indian/Mauritius"
    ),
    149: FirmwareCity("Victoria", 240, 240, 240, "Indian/Mahe", "Indian/Mahe"),
    150: FirmwareCity("Islamabad", 300, 300, 300, "Asia/Karachi", "Asia/Karachi"),
    151: FirmwareCity("Male", 300, 300, 300, "Indian/Maldives", "Indian/Maldives"),
    152: FirmwareCity("Tashkent", 300, 300, 300, "Asia/Tashkent", "Asia/Tashkent"),
    153: FirmwareCity(
        "Yekaterinburg", 300, 300, 360, "Asia/Yekaterinburg", "Asia/Yekaterinburg"
    ),
    154: FirmwareCity("Omsk", 360, 360, 420, "Asia/Omsk", "Asia/Omsk"),
    155: FirmwareCity("Dhaka", 360, 360, 360, "Asia/Dhaka", "Asia/Dhaka"),
    156: FirmwareCity(
        "Novosibirsk", 360, 360, 420, "Asia/Novosibirsk", "Asia/Novosibirsk"
    ),
    157: FirmwareCity("Beijing", 480, 480, 480, "Asia/Shanghai", "Asia/Shanghai"),
    158: FirmwareCity("Canton", 480, 480, 480, "Asia/Shanghai", "Asia/Shanghai"),
    159: FirmwareCity("Hong Kong", 480, 480, 480, "Asia/Hong_Kong", "Asia/Hong_Kong"),
    160: FirmwareCity(
        "Kuala Lumpur", 480, 480, 480, "Asia/Kuala_Lumpur", "Asia/Kuala_Lumpur"
    ),
    161: FirmwareCity("Manila", 480, 480, 480, "Asia/Manila", "Asia/Manila"),
    162: FirmwareCity("Perth", 480, 480, 480, "Australia/Perth", "Australia/Perth"),
    163: FirmwareCity("Shanghai", 480, 480, 480, "Asia/Shanghai", "Asia/Shanghai"),
    164: FirmwareCity("Singapore", 480, 480, 480, "Asia/Singapore", "Asia/Singapore"),
    165: FirmwareCity("Taipei", 480, 480, 480, "Asia/Taipei", "Asia/Taipei"),
    166: FirmwareCity("Tientsin", 480, 480, 480, "Asia/Shanghai", "Asia/Shanghai"),
    167: FirmwareCity(
        "Ulaanbaatar", 480, 480, 480, "Asia/Ulaanbaatar", "Asia/Ulaanbaatar"
    ),
    168: FirmwareCity("Darwin", 570, 570, 570, "Australia/Darwin", "Australia/Darwin"),
    169: FirmwareCity(
        "Adelaide", 570, 570, 570, "Australia/Adelaide", "Australia/Adelaide"
    ),
    170: FirmwareCity(
        "Brisbane", 600, 600, 600, "Australia/Brisbane", "Australia/Brisbane"
    ),
    171: FirmwareCity(
        "Canberra", 600, 600, 600, "Australia/Sydney", "Australia/Sydney"
    ),
    172: FirmwareCity("Guam", 600, 600, 600, "Pacific/Guam", "Pacific/Guam"),
    173: FirmwareCity("Hobart", 600, 600, 600, "Australia/Hobart", "Australia/Hobart"),
    174: FirmwareCity(
        "Melbourne", 600, 600, 600, "Australia/Melbourne", "Australia/Melbourne"
    ),
    175: FirmwareCity("Sydney", 600, 600, 600, "Australia/Sydney", "Australia/Sydney"),
    176: FirmwareCity(
        "Vladivostok", 600, 600, 660, "Asia/Vladivostok", "Asia/Vladivostok"
    ),
    177: FirmwareCity("Magadan", 660, 660, 720, "Asia/Magadan", "Asia/Magadan"),
    178: FirmwareCity("Nouméa", 660, 660, 660, "Pacific/Noumea", "Pacific/Noumea"),
    179: FirmwareCity("Anadyr", 720, 660, 720, "Asia/Anadyr", "Asia/Anadyr"),
    180: FirmwareCity(
        "Wellington", 720, 720, 720, "Pacific/Auckland", "Pacific/Auckland"
    ),
    181: FirmwareCity("Adak", -600, -600, -600, "America/Adak", "America/Adak"),
    182: FirmwareCity(
        "Pago Pago", -660, -660, -660, "Pacific/Pago_Pago", "Pacific/Pago_Pago"
    ),
    183: FirmwareCity("Tehran", 210, 210, 210, "Asia/Tehran", "Asia/Tehran"),
    184: FirmwareCity("Kabul", 270, 270, 270, "Asia/Kabul", "Asia/Kabul"),
    185: FirmwareCity(
        "Chennai (Madras)", 330, 330, 330, "Asia/Colombo", "Asia/Colombo"
    ),
    186: FirmwareCity("Colombo", 330, 330, 330, "Asia/Colombo", "Asia/Colombo"),
    187: FirmwareCity(
        "Kolkata (Calcutta)", 330, 330, 330, "Asia/Kolkata", "Asia/Kolkata"
    ),
    188: FirmwareCity("Mumbai (Bombay)", 330, 330, 330, "Asia/Kolkata", "Asia/Kolkata"),
    189: FirmwareCity("New Delhi", 330, 330, 330, "Asia/Kolkata", "Asia/Kolkata"),
    190: FirmwareCity(
        "Katmandu", 345, 345, 345, "Asia/Kathmandu", "Asia/Kathmandu", "Kathmandu"
    ),
    191: FirmwareCity("Osaka", 540, 540, 540, "Asia/Tokyo", "Asia/Tokyo"),
    192: FirmwareCity("Pyongyang", 540, 540, 540, "Asia/Pyongyang", "Asia/Pyongyang"),
    193: FirmwareCity("Seoul", 540, 540, 540, "Asia/Seoul", "Asia/Seoul"),
    194: FirmwareCity("Tokyo", 540, 540, 540, "Asia/Tokyo", "Asia/Tokyo"),
    195: FirmwareCity("Yakutsk", 540, 540, 600, "Asia/Yakutsk", "Asia/Yakutsk"),
    196: FirmwareCity("Athens", 120, 120, 120, "Europe/Athens", "Europe/Athens"),
    197: FirmwareCity("Rangoon", 390, 390, 390, "Asia/Rangoon", "Asia/Rangoon"),
    198: FirmwareCity(
        "Thanh Pho Ho Chi Minh",
        420,
        420,
        420,
        "Asia/Ho_Chi_Minh",
        "Asia/Ho_Chi_Minh",
        "Ho Chi Minh City",
    ),
    199: FirmwareCity(
        "Des Moines", -360, -360, -360, "America/Chicago", "America/Chicago"
    ),
    200: FirmwareCity("Bangkok", 420, 420, 420, "Asia/Bangkok", "Asia/Bangkok"),
    201: FirmwareCity("Hanoi", 420, 420, 420, "Asia/Ho_Chi_Minh", "Asia/Ho_Chi_Minh"),
    202: FirmwareCity("Jakarta", 420, 420, 420, "Asia/Jakarta", "Asia/Jakarta"),
    203: FirmwareCity(
        "Krasnoyarsk", 420, 420, 480, "Asia/Krasnoyarsk", "Asia/Krasnoyarsk"
    ),
    204: FirmwareCity("Kuwait", 180, 180, 180, "Asia/Kuwait", "Asia/Kuwait"),
    205: FirmwareCity(
        "Phnom Penh", 420, 420, 420, "Asia/Phnom_Penh", "Asia/Phnom_Penh"
    ),
}
