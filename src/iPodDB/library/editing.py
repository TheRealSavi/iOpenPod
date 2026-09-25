"""Validated metadata edits over common records, without changing source documents."""

from dataclasses import dataclass, replace
from typing import Any, cast

from iPodDB.library._field_policy import TRACK_POLICY, FieldOwnership, value_at
from iPodDB.library._track_writing import validate_track
from iPodDB.library.models import ContentAdvisory, Track, TrackChapter
from iPodDB.library.writing import WriteIssue

type MetadataValue = str | int | float | bool | tuple[TrackChapter, ...] | None


@dataclass(frozen=True, slots=True)
class TrackFieldEdit:
    """One explicitly changed semantic field; omitted fields keep their values."""

    field: str
    value: MetadataValue


class TrackEditError(ValueError):
    def __init__(self, issues: tuple[WriteIssue, ...]) -> None:
        self.issues = issues
        super().__init__(
            "\n".join(f"Track {i.record_id} · {i.field}: {i.message}" for i in issues)
        )


def editable_track_fields() -> tuple[str, ...]:
    return tuple(p.path for p in TRACK_POLICY if p.ownership is FieldOwnership.EDITABLE)


def _valid_type(path: str, value: object, default: object) -> bool:
    if path == "metadata.normalization_gain_db":
        return value is None or type(value) in (int, float)
    if path == "metadata.content_advisory":
        return isinstance(value, ContentAdvisory)
    if path == "metadata.chapters":
        # Dataclass annotations do not enforce types at this runtime boundary.
        return isinstance(value, tuple) and all(
            isinstance(c, TrackChapter)
            and type(c.start_ms) is int
            and isinstance(cast("object", c.title), str)
            for c in cast("tuple[object, ...]", value)
        )
    if type(default) is float:
        return type(value) in (int, float)
    return type(value) is type(default)


def metadata_edit_issues(before: Track, after: Track) -> tuple[WriteIssue, ...]:
    """Validate a metadata-only replacement using the writer's field ownership."""
    editable = frozenset(editable_track_fields())
    issues: list[WriteIssue] = []
    defaults = Track(0, "", "", "", 0)
    for policy in TRACK_POLICY:
        path = policy.path
        value, prior = value_at(after, path), value_at(before, path)
        if value == prior and type(value) is type(prior):
            continue
        if path not in editable or not _valid_type(
            path, value, value_at(defaults, path)
        ):
            issues.append(
                WriteIssue(
                    "track.unsupported_edit",
                    "Choose an editable metadata field and a value of the correct type.",
                    subject="track",
                    record_id=before.track_id,
                    field=path,
                )
            )
    if issues:
        return tuple(issues)
    return validate_track(before, after)


def edit_track_metadata(track: Track, edits: tuple[TrackFieldEdit, ...]) -> Track:
    """Return a validated replacement, or reject all edits with structured issues.

    Source-dependent checks (including native timezone and retained short headers)
    remain part of Library preparation. This does not authorize a device write.
    """
    # Dynamic dataclass construction stays private; field ownership and concrete
    # runtime value types are checked before the replacement can escape.
    top: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    allowed = frozenset(editable_track_fields())
    seen: set[str] = set()
    issues: list[WriteIssue] = []
    for edit in edits:
        if edit.field not in allowed or edit.field in seen:
            issues.append(
                WriteIssue(
                    "track.unsupported_edit",
                    "This field is read-only, unknown, or specified more than once.",
                    subject="track",
                    record_id=track.track_id,
                    field=edit.field,
                )
            )
        elif edit.field.startswith("metadata."):
            metadata[edit.field[9:]] = edit.value
        else:
            top[edit.field] = edit.value
        seen.add(edit.field)
    if issues:
        raise TrackEditError(tuple(issues))
    updated = replace(track, **top, metadata=replace(track.metadata, **metadata))
    issues.extend(metadata_edit_issues(track, updated))
    if issues:
        raise TrackEditError(tuple(issues))
    return updated
