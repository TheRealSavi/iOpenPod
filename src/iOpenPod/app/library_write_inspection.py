"""Bounded, observational JSON for a captured draft and its write attempt.

This is a developer report, not a draft persistence format or a save command.
Only common Library records enter it; retained Chunk trees stay inside iPodDB.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from iOpenPod.app.library_write import (
        LibraryPreparationRequest,
        LibraryReview,
        LibrarySaveResult,
        WriteTraceEvent,
    )
    from iPodDB.library import (
        LibraryChange,
        LibrarySnapshot,
        Photo,
        PhotoAlbum,
        PhotoLibrary,
        Playlist,
        PreparedLibrary,
        Track,
    )

type JsonValue = (
    str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
)


@dataclass(frozen=True, slots=True)
class InspectionLimits:
    max_changes: int = 200
    max_sequence_items: int = 50
    max_text_chars: int = 512
    max_depth: int = 12
    max_nodes: int = 12_000

    def __post_init__(self) -> None:
        if any(
            type(getattr(self, f.name)) is not int or getattr(self, f.name) <= 0
            for f in fields(self)
        ):
            raise ValueError("Inspection limits must be positive integers")


def _artifact(data: bytes) -> dict[str, JsonValue]:
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


class _Encoder:
    def __init__(self, limits: InspectionLimits) -> None:
        self.limits = limits
        self.remaining = limits.max_nodes
        self.truncated = False

    def value(self, value: object, depth: int = 0) -> JsonValue:
        if self.remaining <= 0 or depth >= self.limits.max_depth:
            self.truncated = True
            return {"omitted": "inspection budget"}
        self.remaining -= 1
        if value is None or isinstance(value, bool | int):
            return value
        if isinstance(value, Enum):
            return self.value(value.value, depth + 1)
        if isinstance(value, str):
            if len(value) <= self.limits.max_text_chars:
                return value
            self.truncated = True
            return {
                "prefix": value[: self.limits.max_text_chars],
                "omitted_characters": len(value) - self.limits.max_text_chars,
            }
        if isinstance(value, float):
            if math.isfinite(value):
                return value
            non_finite: dict[str, JsonValue] = {"non_finite": str(value)}
            return non_finite
        if isinstance(value, bytes):
            return _artifact(value)
        if isinstance(value, tuple):
            sequence = cast("tuple[object, ...]", value)
            count = min(
                len(sequence), self.limits.max_sequence_items, max(0, self.remaining)
            )
            items = [self.value(item, depth + 1) for item in sequence[:count]]
            omitted = len(sequence) - count
            if omitted:
                self.truncated = True
            return {"items": items, "count": len(sequence), "omitted": omitted}
        if is_dataclass(value) and not isinstance(value, type):
            return {
                f.name: self.value(getattr(value, f.name), depth + 1)
                for f in fields(value)
            }
        # Do not inspect arbitrary object internals or reprs (which may hold paths).
        return {"unavailable_type": type(value).__name__}


class _Changes:
    def __init__(
        self,
        before: LibrarySnapshot,
        desired: LibrarySnapshot,
        prepared: PreparedLibrary | None,
        selected: tuple[LibraryChange, ...],
        *,
        resolved: LibrarySnapshot | None = None,
    ) -> None:
        self.snapshots = (
            before,
            desired,
            resolved,
            prepared.snapshot if prepared else None,
        )
        identities = {(c.subject, c.record_id) for c in selected}
        if prepared is not None:
            identities.update(
                (i.subject, i.output_id)
                for i in prepared.identities
                if (i.subject, i.draft_id) in identities
            )
        indexes: list[dict[tuple[str, int], Track | Playlist | Photo | PhotoAlbum]] = []
        for snapshot in self.snapshots:
            index: dict[tuple[str, int], Track | Playlist | Photo | PhotoAlbum] = {}
            if snapshot is not None:
                for track in snapshot.tracks:
                    key = ("track", track.track_id)
                    if key in identities:
                        index[key] = track
                for playlist in snapshot.playlists:
                    key = ("playlist", playlist.playlist_id)
                    if key in identities:
                        index[key] = playlist
                if snapshot.photos is not None:
                    for photo in snapshot.photos.photos:
                        key = ("photo", photo.photo_id)
                        if key in identities:
                            index[key] = photo
                    for album in snapshot.photos.albums:
                        key = ("photo_album", album.album_id)
                        if key in identities:
                            index[key] = album
            indexes.append(index)
        self.records = tuple(indexes)
        self.mappings = (
            {}
            if prepared is None
            else {
                (item.subject, item.draft_id): item.output_id
                for item in prepared.identities
            }
        )

    def inspect(self, change: LibraryChange, encoder: _Encoder) -> JsonValue:
        output_id = change.record_id
        if change.subject == "library" or change.record_id is None:
            records: tuple[object, ...] = self.snapshots
        else:
            identity = (change.subject, change.record_id)
            output_id = self.mappings.get(identity, change.record_id)
            records = (
                self.records[0].get(identity),
                self.records[1].get(identity),
                self.records[2].get(identity),
                self.records[3].get((change.subject, output_id)),
            )
        names = change.fields
        if not names:
            record = (
                records[0] if change.action == "delete" else records[1] or records[2]
            )
            if is_dataclass(record) and not isinstance(record, type):
                names = tuple(f.name for f in fields(record))
        values: list[JsonValue] = []
        for name in names:
            row: dict[str, JsonValue] = {"field": name}
            for label, record in zip(
                ("before", "desired", "resolved", "prepared"), records, strict=True
            ):
                value = record
                for part in name.split("."):
                    value = None if value is None else getattr(value, part)
                # Collection order changes should not dump every complete Track.
                if (
                    change.subject == "library"
                    and name in ("tracks", "playlists")
                    and value is not None
                ):
                    attr = "track_id" if name == "tracks" else "playlist_id"
                    value = tuple(
                        getattr(item, attr)
                        for item in cast("tuple[object, ...]", value)
                    )
                elif (
                    change.subject == "library"
                    and name == "photos"
                    and value is not None
                ):
                    photos = cast("PhotoLibrary", value)
                    value = {
                        "photo_ids": tuple(item.photo_id for item in photos.photos),
                        "album_ids": tuple(item.album_id for item in photos.albums),
                        "format_ids": tuple(item.format_id for item in photos.formats),
                    }
                row[label] = encoder.value(value)
            values.append(row)
        return {
            "subject": change.subject,
            "record_id": change.record_id,
            "output_id": output_id,
            "action": change.action,
            "name": encoder.value(change.name),
            "fields": values,
        }


def inspect_change(
    change: LibraryChange, request: LibraryPreparationRequest, review: LibraryReview
) -> str:
    """Inspect a selected change without spending the whole-report change budget."""
    encoder = _Encoder(InspectionLimits())
    changes = _Changes(
        request.source.library,
        request.snapshot,
        review.result.prepared,
        (change,),
        resolved=review.plan.resolution.snapshot
        if review.plan and review.plan.resolution
        else None,
    )
    return json.dumps(
        changes.inspect(change, encoder), indent=2, ensure_ascii=True, allow_nan=False
    )


def inspect_library_write(
    request: LibraryPreparationRequest | None,
    review: LibraryReview | None,
    *,
    state: str,
    trace: tuple[WriteTraceEvent, ...] = (),
    save: LibrarySaveResult | None = None,
    request_is_current: bool | None = None,
    current_revision: tuple[int, int] | None = None,
    limits: InspectionLimits | None = None,
) -> str:
    """Render captured data only: no analysis, preparation, device reads or saves."""
    limits = limits or InspectionLimits()
    encoder = _Encoder(limits)
    report: dict[str, JsonValue] = {
        "schema": "iopenpod.library-write-inspection",
        "version": 2,
        "purpose": "observational; cannot be submitted for saving",
        "state": state,
        "request_is_current": request_is_current,
        "current_workspace_revision": encoder.value(current_revision),
        "trace": encoder.value(trace),
    }
    if request is not None:
        report["request"] = {
            "workspace_generation": request.workspace_generation,
            "workspace_revision": request.workspace_revision,
            "source_connection": request.source.candidate.id.value,
            "delete_omissions": request.delete_omissions,
            "source_database": request.source.database_name,
            "source_fingerprint": {
                "size": request.source.database_fingerprint.size,
                "sha256": request.source.database_fingerprint.sha256,
            },
            "source_artwork_fingerprint": None
            if request.source.artwork_database_fingerprint is None
            else {
                "size": request.source.artwork_database_fingerprint.size,
                "sha256": request.source.artwork_database_fingerprint.sha256,
            },
            "source_photos_fingerprint": None
            if request.source.photos_database_fingerprint is None
            else {
                "size": request.source.photos_database_fingerprint.size,
                "sha256": request.source.photos_database_fingerprint.sha256,
            },
            "original_counts": {
                "tracks": len(request.source.library.tracks),
                "playlists": len(request.source.library.playlists),
                "photos": 0
                if request.source.library.photos is None
                else len(request.source.library.photos.photos),
                "photo_albums": 0
                if request.source.library.photos is None
                else len(request.source.library.photos.albums),
            },
            "desired_counts": {
                "tracks": len(request.snapshot.tracks),
                "playlists": len(request.snapshot.playlists),
                "photos": 0
                if request.snapshot.photos is None
                else len(request.snapshot.photos.photos),
                "photo_albums": 0
                if request.snapshot.photos is None
                else len(request.snapshot.photos.albums),
            },
        }
    if review is not None:
        report["file_changes"] = encoder.value(review.file_changes)
        plan, prepared = review.plan, review.result.prepared
        report["issues"] = encoder.value(review.result.issues)
        report["worker_measurements"] = encoder.value(review.result.measurements)
        if plan is not None:
            report["source_revision"] = plan.draft.source_revision
            report["target"] = {
                f.name: encoder.value(getattr(plan.target, f.name))
                for f in fields(plan.target)
                if f.name != "firewire_guid"
            }
            target = cast("dict[str, JsonValue]", report["target"])
            target["signing_identity_supplied"] = bool(plan.target.firewire_guid)
            report["requirements"] = {
                "media": encoder.value(plan.required_media),
                "lyrics": encoder.value(plan.required_lyrics),
                "artwork": encoder.value(plan.required_artwork),
                "artwork_inventory": plan.requires_artwork_inventory,
                "sidecar_inventory": plan.requires_sidecar_inventory,
            }
            if request is not None:
                count = min(len(plan.changes), limits.max_changes)
                changes = _Changes(
                    request.source.library,
                    plan.draft.snapshot,
                    prepared,
                    plan.changes[:count],
                    resolved=plan.resolution.snapshot if plan.resolution else None,
                )
                report["changes"] = {
                    "count": len(plan.changes),
                    "omitted": len(plan.changes) - count,
                    "items": [
                        changes.inspect(c, encoder) for c in plan.changes[:count]
                    ],
                }
                encoder.truncated |= len(plan.changes) > count
                if plan.resolution is not None:
                    resolution = plan.resolution
                    generated = resolution.generated_changes[: limits.max_changes]
                    generated_values = _Changes(
                        request.source.library,
                        plan.draft.snapshot,
                        prepared,
                        generated,
                        resolved=resolution.snapshot,
                    )
                    report["resolution"] = {
                        "counts": {
                            "tracks": len(resolution.snapshot.tracks),
                            "playlists": len(resolution.snapshot.playlists),
                            "photos": 0
                            if resolution.snapshot.photos is None
                            else len(resolution.snapshot.photos.photos),
                            "photo_albums": 0
                            if resolution.snapshot.photos is None
                            else len(resolution.snapshot.photos.albums),
                        },
                        "generated_changes": {
                            "count": len(resolution.generated_changes),
                            "omitted": len(resolution.generated_changes)
                            - len(generated),
                            "items": [
                                generated_values.inspect(c, encoder) for c in generated
                            ],
                        },
                        "effects": encoder.value(resolution.effects),
                        "preservation": encoder.value(resolution.preservation),
                    }
                    encoder.truncated |= len(generated) < len(
                        resolution.generated_changes
                    )
        resources = review.resources
        if resources is not None:
            report["supplied_resources"] = {
                "media": encoder.value(resources.media),
                "lyrics": encoder.value(resources.lyrics),
                "artwork_ids": encoder.value(
                    tuple(a.artwork_id for a in resources.artwork)
                ),
                "source_files": encoder.value(
                    tuple(f.dependency for f in resources.files)
                ),
                "file_inventory": encoder.value(resources.file_inventory),
                "pending_playback_sidecars": resources.pending_playback_sidecars,
            }
        report["prepared"] = (
            None
            if prepared is None
            else {
                "itunes": _artifact(prepared.itunes),
                "artwork": None
                if prepared.artwork is None
                else _artifact(prepared.artwork),
                "photos": None
                if prepared.photos is None
                else _artifact(prepared.photos),
                "changed_artwork_files": encoder.value(prepared.artwork_files),
                "retained_files": encoder.value(prepared.retained_files),
                "retained_artwork_ranges": encoder.value(prepared.retained_artwork),
                "identities": encoder.value(prepared.identities),
            }
        )
    if save is not None:
        report["save"] = {
            "accepted": save.active is not None,
            "issues": encoder.value(save.issues),
            "recovery_path": encoder.value(save.recovery_path),
        }
    report["limits"] = encoder.value(limits)
    report["truncated"] = encoder.truncated
    return json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False)
