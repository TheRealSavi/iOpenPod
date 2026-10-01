"""Make timezone fallbacks and unprojectable retained dates observable."""

from __future__ import annotations

from typing import TYPE_CHECKING

from iPodDB.device_time import DeviceTimeSource, mac_to_unix
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library._field_policy import DATE_FIELDS
from iPodDB.library.writing import IssueSeverity, WriteIssue
from iPodDB.PhotosDB.shared.chunk_defs.mhii import MhiiHeader

if TYPE_CHECKING:
    from iPodDB.device_time import DeviceTimeContext
    from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
    from iPodDB.PhotosDB.shared.chunk_defs.mhfd import MhfdHeader as PhotosMhfdHeader
    from iPodDB.shared.chunk import DatabaseDocument


def time_warnings(
    document: DatabaseDocument[MhbdHeader],
    photos: DatabaseDocument[PhotosMhfdHeader] | None,
    context: DeviceTimeContext,
) -> tuple[WriteIssue, ...]:
    issues: list[WriteIssue] = []

    def warn(code: str, text: str, artifact: str = "iTunesDB") -> None:
        issues.append(
            WriteIssue(code, text, IssueSeverity.WARNING, "source", artifact=artifact)
        )

    if context.source is DeviceTimeSource.UNRESOLVED:
        warn(
            "source.timezone_unresolved",
            "The iPod timezone is unknown. Local dates are unavailable; unchanged date bytes will be retained.",
        )
    elif context.source is DeviceTimeSource.DATABASE_HEADER and context.detail:
        warn(
            "source.timezone_fallback",
            "Preferences do not resolve the iPod timezone. Dates use the database's fixed offset; historical DST cannot be reconstructed.",
        )
    if context.detail and context.source is DeviceTimeSource.PREFERENCES_CITY:
        warn("source.timezone_policy", context.detail)
    unavailable = 0
    for item in document.find_chunks(MhitHeader):
        for name, native in (
            *DATE_FIELDS.items(),
            ("date_added_to_itunes", "date_added_to_itunes"),
        ):
            try:
                value = getattr(item.chunk.header, native)
                decoded = mac_to_unix(
                    value,
                    context,
                    utc=name in ("release_date", "date_added_to_itunes"),
                )
                unavailable += int(value != 0 and decoded == 0)
            except ValueError:
                unavailable += 1
    if unavailable:
        warn(
            "source.unavailable_dates",
            "Some retained Track dates cannot be represented uniquely with the known timezone and missing-date marker. They are unavailable in the Library; unrelated edits preserve their native bytes.",
        )
    unavailable = 0
    if photos is not None:
        for photo in photos.find_chunks(MhiiHeader):
            for value in (
                photo.chunk.header.original_date,
                photo.chunk.header.exif_taken_date,
            ):
                try:
                    decoded = mac_to_unix(value, context)
                    unavailable += int(value != 0 and decoded == 0)
                except ValueError:
                    unavailable += 1
    if unavailable:
        warn(
            "source.unavailable_dates",
            "Some retained Photo dates cannot be represented uniquely with the known timezone and missing-date marker. They are unavailable in the Library; unrelated edits preserve their native bytes.",
            "PhotosDB",
        )
    return tuple(issues)
