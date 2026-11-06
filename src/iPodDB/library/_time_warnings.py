"""Report best-effort date interpretation without blocking Library workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from iPodDB.device_time import DeviceTimeSource, interpret_mac
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

    def warn(
        code: str, text: str, artifact: str = "iTunesDB", *, detail: str = ""
    ) -> None:
        issues.append(
            WriteIssue(
                code,
                text,
                IssueSeverity.WARNING,
                "source",
                artifact=artifact,
                detail=detail,
            )
        )

    if context.source is DeviceTimeSource.UNRESOLVED:
        warn(
            "source.timezone_unresolved",
            "The iPod timezone is unknown. Dates are interpreted as UTC; unchanged native date bytes are retained.",
            detail=context.detail,
        )
    elif context.source is DeviceTimeSource.DATABASE_HEADER and context.detail:
        warn(
            "source.timezone_fallback",
            "Preferences do not resolve the iPod timezone. Dates use the database's fixed offset; historical DST cannot be reconstructed.",
            detail=context.detail,
        )
    if context.detail and context.source is DeviceTimeSource.PREFERENCES_CITY:
        warn("source.timezone_policy", context.detail)
    approximations: set[str] = set()
    for item in document.find_chunks(MhitHeader):
        for name, native in (
            *DATE_FIELDS.items(),
            ("date_added_to_itunes", "date_added_to_itunes"),
        ):
            value = getattr(item.chunk.header, native)
            interpreted = interpret_mac(
                value, context, utc=name in ("release_date", "date_added_to_itunes")
            )
            if interpreted.detail:
                approximations.add(interpreted.detail)
            if value != 0 and interpreted.value == 0:
                approximations.add(
                    "An epoch date shares the Library's missing-date display marker; its native value is retained."
                )
    if approximations:
        warn(
            "source.approximate_dates",
            "Some Track dates use best-effort interpretation; unrelated edits preserve their native bytes.",
            detail=" ".join(sorted(approximations)),
        )
    approximations = set()
    if photos is not None:
        for photo in photos.find_chunks(MhiiHeader):
            for value in (
                photo.chunk.header.original_date,
                photo.chunk.header.exif_taken_date,
            ):
                interpreted = interpret_mac(value, context)
                if interpreted.detail:
                    approximations.add(interpreted.detail)
    if approximations:
        warn(
            "source.approximate_dates",
            "Some Photo dates use best-effort interpretation; unrelated edits preserve their native bytes.",
            "PhotosDB",
            detail=" ".join(sorted(approximations)),
        )
    return tuple(issues)
