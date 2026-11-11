"""Calendar-owned timezone definitions and native event binding order."""

import re

from iPodDB.calendar.models import CalendarComponent, CalendarZone

_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
UTC_ZONE = CalendarZone("Z", 0)


def zone_key(name: str) -> str:
    return name.translate(_ASCII_LOWER)


def writable_zone_name(name: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9_+./-]{1,128}", name) is not None


def adopt_zone(zones: dict[str, CalendarZone | None], zone: CalendarZone) -> None:
    key = zone_key(zone.name)
    zones[key] = None if key in zones else zone


def calendar_zone_names(
    component: CalendarComponent, *, before_offset: int | None = None
) -> tuple[str, ...]:
    """Find unique named zones available at an event's position in the file."""
    zones: dict[str, CalendarZone | None] = {"z": UTC_ZONE}
    for child in component.children:
        if before_offset is not None and child.start_offset >= before_offset:
            break
        if child.name == "VTIMEZONE" and (zone := read_zone(child)) is not None:
            adopt_zone(zones, zone)
    return tuple(
        zone.name
        for key, zone in zones.items()
        if key != "z"
        and zone is not None
        and zone.standard_offset is not None
        and writable_zone_name(zone.name)
    )


def read_zone(component: CalendarComponent) -> CalendarZone | None:
    names = [prop.value for prop in component.properties if prop.name == "TZID"]
    if len(names) != 1 or not names[0]:
        return None

    def offset(kind: str) -> int | None:
        observances = [child for child in component.children if child.name == kind]
        if len(observances) != 1:
            return None
        values = [
            prop.value
            for prop in observances[0].properties
            if prop.name == "TZOFFSETTO" and not prop.parameters
        ]
        if len(values) != 1 or not re.fullmatch(r"[+-][0-9]{4}", values[0]):
            return None
        value = values[0]
        hours, minutes = int(value[1:3]), int(value[3:5])
        if hours > 23 or minutes > 59:
            return None
        return (hours * 3600 + minutes * 60) * (-1 if value[0] == "-" else 1)

    return CalendarZone(names[0], offset("STANDARD"), offset("DAYLIGHT"))


def event_zone(
    component: CalendarComponent, zones: dict[str, CalendarZone | None]
) -> CalendarZone | None:
    assigned = None
    for prop in component.properties:
        if prop.name not in {"DTSTART", "DTEND"}:
            continue
        tzids = prop.parameter_values("TZID")
        if len(tzids) == 1:
            name = tzids[0]
        elif not tzids and re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", prop.value):
            name = "Z"
        else:
            continue
        key = zone_key(name)
        if key in zones:
            assigned = zones[key]
    return assigned
