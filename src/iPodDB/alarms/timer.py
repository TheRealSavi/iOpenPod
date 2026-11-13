"""Saved countdown state and lossless presets for qualified touch Nano firmware.

This describes captured preferences, not a running timer or a command channel.
The duration preset and the persisted civil deadline are independent values.
See docs/research/timer-controls-touch-2026-11-13.md for native evidence.
"""

from dataclasses import dataclass

from whenever import PlainDateTime

from iPodDB.preferences._named_catalog import FIELDS_BY_PROFILE, NANO6_TIMER_FIELDS
from iPodDB.preferences._named_xml import parse_named_xml, unsigned_decimal
from iPodDB.preferences.definitions import NamedPreferencesProfile
from iPodDB.shared.errors import iPodDBWriteError


@dataclass(frozen=True, slots=True)
class CountdownTimerSnapshot:
    """Saved observations only; missing or unknown values never imply defaults."""

    saved_hours: int | None = None
    saved_minutes: int | None = None
    deadline: PlainDateTime | None = None
    raw_deadline: str | None = None
    sleep_ipod: bool | None = None
    sound_index: int | None = None
    issues: tuple[str, ...] = ()
    can_edit_duration: bool = False
    can_edit_sleep: bool = False
    can_edit_sound: bool = False


@dataclass(frozen=True, slots=True)
class CountdownTimerChanges:
    """Explicit saved preset edits; None leaves that setting unchanged.

    Choosing a sound also clears SleepiPod, as the native sound selector does.
    Choosing Sleep iPod retains the last saved sound. Neither changes DateTime.
    """

    saved_hours: int | None = None
    saved_minutes: int | None = None
    sleep_ipod: bool | None = None
    sound_index: int | None = None


@dataclass(frozen=True, slots=True)
class CountdownTimerFiles:
    """Independent captured sources after a pure preset edit, without I/O."""

    settings: bytes | None
    timer_settings: bytes | None


# Each index is independently bound to its native sound file and display
# resource in all three exact images. See timer-controls-touch-2026-11-13.md.
COUNTDOWN_TIMER_SOUNDS = (
    "Marimba",
    "Alarm",
    "Ascending",
    "Bark",
    "Bell Tower",
    "Blues",
    "Boing",
    "Crickets",
    "Digital",
    "Doorbell",
    "Duck",
    "Harp",
    "Motorcycle",
    "Old Car Horn",
    "Old Phone",
    "Piano Riff",
    "Pinball",
    "Robot",
    "Sci-Fi",
    "Sonar",
    "Strum",
    "Timba",
    "Time Passing",
    "Trill",
    "Xylophone",
)


@dataclass(frozen=True, slots=True)
class _Scalar:
    text: str
    start: int
    end: int
    editable: bool


_PROFILES = (
    NamedPreferencesProfile.NANO_6_1_2,
    NamedPreferencesProfile.NANO_7_1_0_4,
    NamedPreferencesProfile.NANO_UPDATER_39_1_1_2,
)


def _fields(source: bytes | None) -> tuple[dict[str, _Scalar], tuple[str, ...]]:
    if source is None:
        return {}, ()
    root, issues = parse_named_xml(source)
    if root is None:
        return {}, issues
    sections = [section for section in root.children if section.name == "Timer"]
    if not sections:
        return {}, ()
    if len(sections) != 1 or sections[0].attributes:
        return {}, ("Timer settings have an ambiguous section.",)
    result: dict[str, _Scalar] = {}
    problems: list[str] = []
    for name in ("Hours", "Minutes", "DateTime", "SleepiPod", "SoundIndex"):
        nodes = [node for node in sections[0].children if node.name == name]
        if not nodes:
            continue
        if len(nodes) != 1 or (
            nodes[0].attributes or nodes[0].children or nodes[0].complex
        ):
            problems.append(f"Timer.{name} is ambiguous or is not a plain scalar.")
            continue
        # Keep source spelling rather than normalizing entity-encoded numbers.
        node = nodes[0]
        result[name] = _Scalar(
            source[node.start : node.end].decode("utf-8"),
            node.start,
            node.end,
            not node.self_closing and node.end >= node.start,
        )
    return result, tuple(problems)


def parse_countdown_timer(
    settings: bytes | None,
    *,
    profile: NamedPreferencesProfile,
    timer_settings: bytes | None = None,
) -> CountdownTimerSnapshot:
    """Read exact-profile timer stores without guessing live state or a timezone.

    ``settings`` is iPodSettings.xml. Nano 6 alone reads the deadline and end
    behavior from ``timer_settings`` (iPodTimerSettings.xml, also rooted at
    iPodSettings). Nano 7 ignores that separate input entirely.
    """
    if type(profile) is not NamedPreferencesProfile or profile not in _PROFILES:
        return CountdownTimerSnapshot(
            issues=("This firmware profile has no qualified countdown timer.",)
        )
    ordinary, issues = _fields(settings)
    if profile is NamedPreferencesProfile.NANO_6_1_2:
        running, timer_issues = _fields(timer_settings)
        issues += timer_issues
    else:
        running = ordinary
    specs = {
        field.key: field for field in (*FIELDS_BY_PROFILE[profile], *NANO6_TIMER_FIELDS)
    }
    problems = list(issues)

    def number(fields: dict[str, _Scalar], name: str) -> int | None:
        field = fields.get(name)
        if field is None:
            return None
        spec = specs[f"Timer.{name}"]
        value = unsigned_decimal(field.text, 32, boolean=spec.kind == "boolean")
        if value is None or (
            (spec.kind == "boolean" and value not in (0, 1))
            or (spec.minimum is not None and value < spec.minimum)
            or (spec.maximum is not None and value > spec.maximum)
        ):
            problems.append(f"Timer.{name} has an unrecognized saved value.")
            return None
        return value

    deadline_field = running.get("DateTime")
    raw_deadline = None if deadline_field is None else deadline_field.text
    deadline = None
    if raw_deadline:
        try:
            if not (
                len(raw_deadline) == 14
                and raw_deadline.isascii()
                and raw_deadline.isdecimal()
            ):
                raise ValueError("unrecognized deadline spelling")
            deadline = PlainDateTime(
                int(raw_deadline[:4]),
                int(raw_deadline[4:6]),
                int(raw_deadline[6:8]),
                int(raw_deadline[8:10]),
                int(raw_deadline[10:12]),
                int(raw_deadline[12:14]),
            )
        except (ValueError, OverflowError):
            problems.append("Timer.DateTime has an unrecognized civil deadline.")
    hours = number(ordinary, "Hours")
    minutes = number(ordinary, "Minutes")
    sleep = number(running, "SleepiPod")
    sound = number(running, "SoundIndex")

    def editable(fields: dict[str, _Scalar], *names: str) -> bool:
        return all(name in fields and fields[name].editable for name in names)

    return CountdownTimerSnapshot(
        saved_hours=hours,
        saved_minutes=minutes,
        deadline=deadline,
        raw_deadline=raw_deadline,
        sleep_ipod=None if sleep is None else bool(sleep),
        sound_index=sound,
        issues=tuple(problems),
        can_edit_duration=editable(ordinary, "Hours", "Minutes"),
        can_edit_sleep=editable(running, "SleepiPod"),
        can_edit_sound=editable(running, "SoundIndex", "SleepiPod"),
    )


def patch_countdown_timer(
    settings: bytes | None,
    *,
    profile: NamedPreferencesProfile,
    changes: CountdownTimerChanges,
    timer_settings: bytes | None = None,
) -> CountdownTimerFiles:
    """Patch proven existing preset scalars, preserving deadlines and other bytes.

    The caller qualifies identity and publishes the returned changed files using
    their captured source preconditions. No document or absent field is created.
    Firmware adoption is separate from successful file publication.
    """
    if type(profile) is not NamedPreferencesProfile or profile not in _PROFILES:
        raise iPodDBWriteError("This firmware has no qualified timer preset writer.")
    if type(changes) is not CountdownTimerChanges:
        raise iPodDBWriteError("Timer preset edits require typed changes.")
    specs = {
        field.key: field for field in (*FIELDS_BY_PROFILE[profile], *NANO6_TIMER_FIELDS)
    }
    updates: dict[str, int] = {}
    for name, value in (
        ("Hours", changes.saved_hours),
        ("Minutes", changes.saved_minutes),
        ("SoundIndex", changes.sound_index),
    ):
        if value is None:
            continue
        spec = specs[f"Timer.{name}"]
        if (
            type(value) is not int
            or spec.minimum is None
            or spec.maximum is None
            or not spec.minimum <= value <= spec.maximum
        ):
            raise iPodDBWriteError(f"Timer.{name} is outside its qualified domain.")
        updates[name] = value
    if changes.sleep_ipod is not None:
        if type(changes.sleep_ipod) is not bool:
            raise iPodDBWriteError("Timer.SleepiPod requires a boolean choice.")
        updates["SleepiPod"] = int(changes.sleep_ipod)
    if changes.sound_index is not None:
        if changes.sleep_ipod is True:
            raise iPodDBWriteError("Choose either a timer sound or Sleep iPod.")
        updates["SleepiPod"] = 0

    def patch(source: bytes | None, names: tuple[str, ...]) -> bytes | None:
        selected = {name: value for name, value in updates.items() if name in names}
        if not selected:
            return source
        if source is None:
            raise iPodDBWriteError("The timer preset source has not been captured.")
        fields, _issues = _fields(source)
        spans: list[tuple[int, int, bytes]] = []
        for name, value in selected.items():
            field = fields.get(name)
            if field is None or not field.editable:
                raise iPodDBWriteError(f"Timer.{name} has no unique writable scalar.")
            if unsigned_decimal(field.text, 32, boolean=name == "SleepiPod") == value:
                continue
            spans.append((field.start, field.end, str(value).encode("ascii")))
        for start, end, replacement in sorted(spans, reverse=True):
            source = source[:start] + replacement + source[end:]
        return source

    if profile is NamedPreferencesProfile.NANO_6_1_2:
        return CountdownTimerFiles(
            patch(settings, ("Hours", "Minutes")),
            patch(timer_settings, ("SleepiPod", "SoundIndex")),
        )
    return CountdownTimerFiles(
        patch(settings, ("Hours", "Minutes", "SleepiPod", "SoundIndex")),
        timer_settings,
    )
