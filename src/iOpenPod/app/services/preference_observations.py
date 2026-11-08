"""Project pure saved-field observations and capture optional preference files.

Inspection never grants edit authority or adds a Library write dependency. Each
optional file has its own bounded Storage snapshot and nonblocking error state.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace

from iOpenPod.app.display_text import exception_text, source_text
from iOpenPod.app.models.ipod_preferences import (
    IPodPreference,
    IPodPreferenceSection,
    PreferenceFileStatus,
)
from iPodDB.preferences import PreferenceInspection
from storage import DevicePath, FileFingerprint, FilesystemSession, StorageError


@dataclass(frozen=True, slots=True)
class InspectedPreferenceFile:
    section: IPodPreferenceSection
    source: bytes | None = None
    fingerprint: FileFingerprint | None = None


def observation_rows(inspection: PreferenceInspection) -> tuple[IPodPreference, ...]:
    """Keep evidence-derived interpretation and raw values separate from editing."""
    return tuple(
        IPodPreference(
            item.key,
            item.label,
            item.value,
            detail=item.detail,
            raw_value=item.raw_value,
            category=item.category,
        )
        for item in inspection.observations
    )


def merge_preference_rows(
    observed: tuple[IPodPreference, ...], editable: tuple[IPodPreference, ...]
) -> tuple[IPodPreference, ...]:
    """Overlay independently qualified editors, retaining observation context."""
    edits = {row.key: row for row in editable}
    merged: list[IPodPreference] = []
    for row in observed:
        edit = edits.pop(row.key, None)
        merged.append(
            replace(row, title=edit.title, value=edit.value, edit=edit.edit)
            if edit is not None
            else row
        )
    return (*merged, *edits.values())


def capture_inspection_file(
    session: FilesystemSession,
    *,
    key: str,
    title: str,
    path: DevicePath,
    inspect: Callable[[bytes], PreferenceInspection],
    checkpoint: Callable[[], None],
) -> InspectedPreferenceFile:
    """Read once, verify freshness, and keep optional format errors local."""
    checkpoint()
    section = IPodPreferenceSection(
        key,
        title,
        PreferenceFileStatus.MISSING,
        detail=source_text("This iPod has no file for these settings."),
    )
    try:
        if not session.exists(path):
            return InspectedPreferenceFile(section)
        snapshot = session.read_snapshot(path, max_bytes=1024 * 1024)
        checkpoint()
        if session.fingerprint(path) != snapshot.fingerprint:
            return InspectedPreferenceFile(
                replace(
                    section,
                    status=PreferenceFileStatus.UNREADABLE,
                    detail=source_text(
                        "These settings changed while they were being read. Reload the iPod to try again."
                    ),
                )
            )
        inspection = inspect(snapshot.data)
        rows = observation_rows(inspection)
        return InspectedPreferenceFile(
            replace(
                section,
                status=PreferenceFileStatus.AVAILABLE
                if rows
                else PreferenceFileStatus.UNKNOWN,
                rows=rows,
                detail="\n".join(inspection.issues),
            ),
            snapshot.data,
            snapshot.fingerprint,
        )
    except (StorageError, ValueError) as error:
        if not session.is_active:
            raise
        return InspectedPreferenceFile(
            replace(
                section,
                status=PreferenceFileStatus.UNREADABLE,
                detail=source_text(
                    "Could not read these settings: {detail}",
                    detail=exception_text(error),
                ),
            )
        )
