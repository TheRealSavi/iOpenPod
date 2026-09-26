"""Prepare an immutable Host-to-iPod Sync Plan from completed media scans."""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from iOpenPod.app.host_media_library import (
    HostMediaFileKind,
)
from iPodDB.library import PhotoRepresentationKind

if TYPE_CHECKING:
    from iOpenPod.app.host_media_library import HostMediaLibrary
    from iOpenPod.app.library_sync_helper import (
        IPodImageFingerprint,
        IPodMediaLibrary,
        IPodTrackFingerprint,
        SyncDetails,
    )
    from iPodDB.library import LibrarySnapshot, Track


class SyncPlanAction(StrEnum):
    """One proposed outcome for a correlated Track or Photo."""

    ADD = "add"
    UPDATE = "update"
    REMOVE = "remove"
    UNCHANGED = "unchanged"
    ATTENTION = "attention"


class SyncPlanMediaKind(StrEnum):
    """The source-neutral media families currently compared by Sync."""

    TRACK = "track"
    PHOTO = "photo"


class SyncPlanBasis(StrEnum):
    """Typed evidence explaining why one Sync Plan action was selected."""

    HOST_ONLY = "host_only"
    IPOD_ONLY = "ipod_only"
    HOST_FACTS_CHANGED = "host_facts_changed"
    HOST_FACTS_MATCH = "host_facts_match"
    CONTENT_MATCH = "content_match"
    MISSING_IDENTITY = "missing_identity"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    CONFLICTING_IDENTITY = "conflicting_identity"
    USER_DESELECTED = "user_deselected"


@dataclass(frozen=True, slots=True)
class SyncPlanItem:
    """One reviewable comparison result; it does not authorize device mutation."""

    action: SyncPlanAction
    media_kind: SyncPlanMediaKind
    basis: SyncPlanBasis
    name: str
    detail: str = ""
    host_path: str | None = None
    ipod_path: str | None = None
    ipod_id: int | None = None
    host_size_changed: bool = False
    host_modified_changed: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("A Sync Plan item needs a display name")
        if self.action is SyncPlanAction.ADD and self.host_path is None:
            raise ValueError("An Add action needs a Host source")
        if self.action is SyncPlanAction.REMOVE and self.ipod_id is None:
            raise ValueError("A Remove action needs an iPod identity")
        if self.action in {SyncPlanAction.UPDATE, SyncPlanAction.UNCHANGED} and (
            self.host_path is None or self.ipod_id is None
        ):
            raise ValueError("A correlated action needs both Host and iPod sources")
        if self.action is not SyncPlanAction.UPDATE and (
            self.host_size_changed or self.host_modified_changed
        ):
            raise ValueError("Only an Update action may report changed Host facts")

    @property
    def search_text(self) -> str:
        """Return one pre-normalized value for GUI proxy filtering."""

        return "\x1f".join(
            (
                self.name,
                self.detail,
                self.host_path or "",
                self.ipod_path or "",
                self.action.value,
                self.media_kind.value,
            )
        ).casefold()


@dataclass(frozen=True, slots=True)
class SyncPlan:
    """One immutable, review-only account of a completed scan comparison."""

    items: tuple[SyncPlanItem, ...]

    def count(self, action: SyncPlanAction) -> int:
        return sum(item.action is action for item in self.items)

    @property
    def change_count(self) -> int:
        return sum(
            item.action
            in {
                SyncPlanAction.ADD,
                SyncPlanAction.UPDATE,
                SyncPlanAction.REMOVE,
            }
            for item in self.items
        )

    @property
    def attention_count(self) -> int:
        return self.count(SyncPlanAction.ATTENTION)


@dataclass(frozen=True, slots=True)
class _Candidate:
    media_kind: SyncPlanMediaKind
    fingerprint: str | None
    name: str
    detail: str
    path: str | None
    item_id: int | None = None
    size_bytes: int = 0
    modified_ns: int = 0
    sync: SyncDetails | None = None


def prepare_sync_plan(
    host: HostMediaLibrary,
    ipod: IPodMediaLibrary,
    ipod_library: LibrarySnapshot,
) -> SyncPlan:
    """Correlate completed Host and iPod scans without mutating either source.

    Proven prior Host paths are considered first so changed source content remains
    associated with the iPod item it previously produced. Remaining items correlate
    by content identity. Duplicate or missing identities stay visible but receive no
    destructive action.
    """

    host_candidates = _host_candidates(host)
    ipod_candidates = _ipod_candidates(ipod, ipod_library)
    host_remaining = set(range(len(host_candidates)))
    ipod_remaining = set(range(len(ipod_candidates)))
    pairs: list[tuple[int, int]] = []
    attention: list[SyncPlanItem] = []

    for index, candidate in enumerate(host_candidates):
        if candidate.fingerprint is None:
            host_remaining.discard(index)
            attention.append(_attention_item(candidate, SyncPlanBasis.MISSING_IDENTITY))
    for index, candidate in enumerate(ipod_candidates):
        if candidate.fingerprint is None:
            ipod_remaining.discard(index)
            attention.append(_attention_item(candidate, SyncPlanBasis.MISSING_IDENTITY))

    _pair_by_prior_path(
        host_candidates,
        ipod_candidates,
        host_remaining,
        ipod_remaining,
        pairs,
        attention,
    )
    _pair_by_content(
        host_candidates,
        ipod_candidates,
        host_remaining,
        ipod_remaining,
        pairs,
        attention,
    )

    items = [
        _paired_item(host_candidates[host_index], ipod_candidates[ipod_index])
        for host_index, ipod_index in pairs
    ]
    items.extend(_host_only_item(host_candidates[index]) for index in host_remaining)
    items.extend(_ipod_only_item(ipod_candidates[index]) for index in ipod_remaining)
    items.extend(attention)
    return SyncPlan(tuple(sorted(items, key=_item_sort_key)))


def select_sync_plan(
    comparison: SyncPlan,
    *,
    selected_host_paths: frozenset[str],
    selected_ipod_removals: frozenset[tuple[SyncPlanMediaKind, int]],
) -> SyncPlan:
    """Derive the reviewed plan from explicit desired-device membership.

    Host-only media is absent until selected. Correlated Host media that the user
    deselects becomes an explicit removal. iPod-only removal candidates are absent
    until the user opts into each one on the Review page. Attention items remain
    visible because selection cannot make unsafe correlation evidence actionable;
    a Host-only item with a missing identity is the one safe exception because an
    explicit one-way Add does not require correlation.
    """

    items: list[SyncPlanItem] = []
    for item in comparison.items:
        if item.host_path is not None:
            if host_path_identity(item.host_path) in selected_host_paths:
                if (
                    item.action is SyncPlanAction.ATTENTION
                    and item.basis is SyncPlanBasis.MISSING_IDENTITY
                    and item.media_kind is SyncPlanMediaKind.TRACK
                    and item.ipod_id is None
                ):
                    items.append(
                        SyncPlanItem(
                            action=SyncPlanAction.ADD,
                            media_kind=item.media_kind,
                            basis=SyncPlanBasis.HOST_ONLY,
                            name=item.name,
                            detail=item.detail,
                            host_path=item.host_path,
                        )
                    )
                else:
                    items.append(item)
                continue
            if item.action is SyncPlanAction.ATTENTION:
                items.append(item)
                continue
            if item.ipod_id is not None:
                items.append(
                    SyncPlanItem(
                        action=SyncPlanAction.REMOVE,
                        media_kind=item.media_kind,
                        basis=SyncPlanBasis.USER_DESELECTED,
                        name=item.name,
                        detail=item.detail,
                        host_path=item.host_path,
                        ipod_path=item.ipod_path,
                        ipod_id=item.ipod_id,
                    )
                )
            continue

        if item.action is SyncPlanAction.ATTENTION:
            items.append(item)
            continue
        if (
            item.action is SyncPlanAction.REMOVE
            and item.ipod_id is not None
            and (item.media_kind, item.ipod_id) in selected_ipod_removals
        ):
            items.append(item)

    return SyncPlan(tuple(sorted(items, key=_item_sort_key)))


def host_path_identity(value: str) -> str:
    """Return the normalized identity used for Host-path correlation and selection."""

    return os.path.normcase(os.path.normpath(os.path.abspath(value)))


def _pair_by_prior_path(
    hosts: tuple[_Candidate, ...],
    ipods: tuple[_Candidate, ...],
    host_remaining: set[int],
    ipod_remaining: set[int],
    pairs: list[tuple[int, int]],
    attention: list[SyncPlanItem],
) -> None:
    host_groups: dict[tuple[SyncPlanMediaKind, str], list[int]] = defaultdict(list)
    ipod_groups: dict[tuple[SyncPlanMediaKind, str], list[int]] = defaultdict(list)
    for index in host_remaining:
        path = hosts[index].path
        if path:
            host_groups[(hosts[index].media_kind, host_path_identity(path))].append(
                index
            )
    for index in ipod_remaining:
        sync = ipods[index].sync
        if sync is not None and sync.host_path_hint.strip():
            ipod_groups[
                (ipods[index].media_kind, host_path_identity(sync.host_path_hint))
            ].append(index)
    _pair_unique_groups(
        host_groups,
        ipod_groups,
        hosts,
        ipods,
        host_remaining,
        ipod_remaining,
        pairs,
        attention,
    )


def _pair_by_content(
    hosts: tuple[_Candidate, ...],
    ipods: tuple[_Candidate, ...],
    host_remaining: set[int],
    ipod_remaining: set[int],
    pairs: list[tuple[int, int]],
    attention: list[SyncPlanItem],
) -> None:
    host_groups: dict[tuple[SyncPlanMediaKind, str], list[int]] = defaultdict(list)
    ipod_groups: dict[tuple[SyncPlanMediaKind, str], list[int]] = defaultdict(list)
    for index in host_remaining:
        fingerprint = hosts[index].fingerprint
        if fingerprint is not None:
            host_groups[(hosts[index].media_kind, fingerprint)].append(index)
    for index in ipod_remaining:
        fingerprint = ipods[index].fingerprint
        if fingerprint is not None:
            ipod_groups[(ipods[index].media_kind, fingerprint)].append(index)
    _pair_unique_groups(
        host_groups,
        ipod_groups,
        hosts,
        ipods,
        host_remaining,
        ipod_remaining,
        pairs,
        attention,
    )


def _pair_unique_groups(
    host_groups: dict[tuple[SyncPlanMediaKind, str], list[int]],
    ipod_groups: dict[tuple[SyncPlanMediaKind, str], list[int]],
    hosts: tuple[_Candidate, ...],
    ipods: tuple[_Candidate, ...],
    host_remaining: set[int],
    ipod_remaining: set[int],
    pairs: list[tuple[int, int]],
    attention: list[SyncPlanItem],
) -> None:
    for key in host_groups.keys() & ipod_groups.keys():
        host_indexes = [index for index in host_groups[key] if index in host_remaining]
        ipod_indexes = [index for index in ipod_groups[key] if index in ipod_remaining]
        if not host_indexes or not ipod_indexes:
            continue
        if len(host_indexes) == 1 and len(ipod_indexes) == 1:
            host_index = host_indexes[0]
            ipod_index = ipod_indexes[0]
            host_remaining.remove(host_index)
            ipod_remaining.remove(ipod_index)
            pairs.append((host_index, ipod_index))
            continue
        for index in host_indexes:
            host_remaining.remove(index)
            attention.append(
                _attention_item(hosts[index], SyncPlanBasis.AMBIGUOUS_IDENTITY)
            )
        for index in ipod_indexes:
            ipod_remaining.remove(index)
            attention.append(
                _attention_item(ipods[index], SyncPlanBasis.AMBIGUOUS_IDENTITY)
            )


def _paired_item(host: _Candidate, ipod: _Candidate) -> SyncPlanItem:
    sync = ipod.sync
    if sync is None:
        return _item(
            SyncPlanAction.UNCHANGED,
            SyncPlanBasis.CONTENT_MATCH,
            host,
            ipod,
        )

    size_changed = host.size_bytes != sync.host_size_bytes
    modified_changed = host.modified_ns != sync.host_modified_ns
    same_prior_path = host.path is not None and (
        host_path_identity(host.path) == host_path_identity(sync.host_path_hint)
    )
    fingerprints_conflict = host.fingerprint != ipod.fingerprint
    if (
        same_prior_path
        and fingerprints_conflict
        and not (size_changed or modified_changed)
    ):
        return _item(
            SyncPlanAction.ATTENTION,
            SyncPlanBasis.CONFLICTING_IDENTITY,
            host,
            ipod,
        )
    if size_changed or modified_changed:
        return _item(
            SyncPlanAction.UPDATE,
            SyncPlanBasis.HOST_FACTS_CHANGED,
            host,
            ipod,
            host_size_changed=size_changed,
            host_modified_changed=modified_changed,
        )
    return _item(
        SyncPlanAction.UNCHANGED,
        SyncPlanBasis.HOST_FACTS_MATCH,
        host,
        ipod,
    )


def _item(
    action: SyncPlanAction,
    basis: SyncPlanBasis,
    host: _Candidate,
    ipod: _Candidate,
    *,
    host_size_changed: bool = False,
    host_modified_changed: bool = False,
) -> SyncPlanItem:
    return SyncPlanItem(
        action=action,
        media_kind=host.media_kind,
        basis=basis,
        name=host.name,
        detail=host.detail or ipod.detail,
        host_path=host.path,
        ipod_path=ipod.path,
        ipod_id=ipod.item_id,
        host_size_changed=host_size_changed,
        host_modified_changed=host_modified_changed,
    )


def _host_only_item(candidate: _Candidate) -> SyncPlanItem:
    return SyncPlanItem(
        action=SyncPlanAction.ADD,
        media_kind=candidate.media_kind,
        basis=SyncPlanBasis.HOST_ONLY,
        name=candidate.name,
        detail=candidate.detail,
        host_path=candidate.path,
    )


def _ipod_only_item(candidate: _Candidate) -> SyncPlanItem:
    return SyncPlanItem(
        action=SyncPlanAction.REMOVE,
        media_kind=candidate.media_kind,
        basis=SyncPlanBasis.IPOD_ONLY,
        name=candidate.name,
        detail=candidate.detail,
        ipod_path=candidate.path,
        ipod_id=candidate.item_id,
    )


def _attention_item(
    candidate: _Candidate,
    basis: SyncPlanBasis,
) -> SyncPlanItem:
    return SyncPlanItem(
        action=SyncPlanAction.ATTENTION,
        media_kind=candidate.media_kind,
        basis=basis,
        name=candidate.name,
        detail=candidate.detail,
        host_path=candidate.path if candidate.item_id is None else None,
        ipod_path=candidate.path if candidate.item_id is not None else None,
        ipod_id=candidate.item_id,
    )


def _host_candidates(library: HostMediaLibrary) -> tuple[_Candidate, ...]:
    tracks_by_path: dict[str, Track] = {
        host_path_identity(track.metadata.location): track
        for track in library.snapshot.tracks
        if track.metadata.location
    }
    photo_details: dict[str, str] = {}
    if library.snapshot.photos is not None:
        for photo in library.snapshot.photos.photos:
            for representation in photo.representations:
                if representation.kind is PhotoRepresentationKind.FULL_RESOLUTION:
                    photo_details[host_path_identity(representation.relative_path)] = (
                        f"{representation.width} x {representation.height}"
                        if representation.width and representation.height
                        else ""
                    )
                    break

    candidates: list[_Candidate] = []
    for source in library.sources:
        if source.kind is HostMediaFileKind.PLAYLIST:
            continue
        path = os.fspath(source.path)
        if source.kind in {HostMediaFileKind.AUDIO, HostMediaFileKind.VIDEO}:
            track = tracks_by_path.get(host_path_identity(path))
            candidates.append(
                _Candidate(
                    media_kind=SyncPlanMediaKind.TRACK,
                    fingerprint=_identity(source.acoustic_fingerprint),
                    name=(
                        track.title.strip()
                        if track is not None and track.title.strip()
                        else Path(path).name
                    ),
                    detail=_track_detail(track),
                    path=path,
                    size_bytes=source.size_bytes,
                    modified_ns=source.modified_ns,
                )
            )
        else:
            candidates.append(
                _Candidate(
                    media_kind=SyncPlanMediaKind.PHOTO,
                    fingerprint=_identity(source.content_sha256),
                    name=Path(path).name,
                    detail=photo_details.get(host_path_identity(path), ""),
                    path=path,
                    size_bytes=source.size_bytes,
                    modified_ns=source.modified_ns,
                )
            )
    return tuple(candidates)


def _ipod_candidates(
    media: IPodMediaLibrary,
    library: LibrarySnapshot,
) -> tuple[_Candidate, ...]:
    tracks_by_id = {track.track_id: track for track in library.tracks}
    candidates = [
        _ipod_track_candidate(record, tracks_by_id.get(record.track_id))
        for record in media.tracks
    ]
    scanned_track_ids = {record.track_id for record in media.tracks}
    candidates.extend(
        _Candidate(
            media_kind=SyncPlanMediaKind.TRACK,
            fingerprint=None,
            name=track.title.strip() or f"Track {track.track_id}",
            detail=_track_detail(track),
            path=track.metadata.location or None,
            item_id=track.track_id,
        )
        for track in library.tracks
        if track.track_id not in scanned_track_ids
    )

    photos = () if library.photos is None else library.photos.photos
    photos_by_id = {photo.photo_id: photo for photo in photos}
    candidates.extend(
        _ipod_image_candidate(record, photos_by_id.get(record.image_id))
        for record in media.images
    )
    scanned_image_ids = {record.image_id for record in media.images}
    for photo in photos:
        if photo.photo_id in scanned_image_ids:
            continue
        path = next(
            (
                representation.relative_path
                for representation in photo.representations
                if representation.kind is PhotoRepresentationKind.FULL_RESOLUTION
            ),
            None,
        )
        candidates.append(
            _Candidate(
                media_kind=SyncPlanMediaKind.PHOTO,
                fingerprint=None,
                name=_path_name(path) if path else f"Photo {photo.photo_id}",
                detail="",
                path=path,
                item_id=photo.photo_id,
            )
        )
    return tuple(candidates)


def _ipod_track_candidate(
    record: IPodTrackFingerprint,
    track: Track | None,
) -> _Candidate:
    return _Candidate(
        media_kind=SyncPlanMediaKind.TRACK,
        fingerprint=_identity(record.acoustic_fingerprint),
        name=(
            track.title.strip()
            if track is not None and track.title.strip()
            else _path_name(str(record.path))
        ),
        detail=_track_detail(track),
        path=str(record.path),
        item_id=record.track_id,
        size_bytes=record.size_bytes,
        modified_ns=record.modified_ns,
        sync=record.sync,
    )


def _ipod_image_candidate(
    record: IPodImageFingerprint,
    _photo: object,
) -> _Candidate:
    name = (
        _path_name(record.sync.host_path_hint)
        if record.sync is not None and record.sync.host_path_hint.strip()
        else _path_name(str(record.path))
    )
    return _Candidate(
        media_kind=SyncPlanMediaKind.PHOTO,
        fingerprint=_identity(record.content_sha256),
        name=name or f"Photo {record.image_id}",
        detail="",
        path=str(record.path),
        item_id=record.image_id,
        size_bytes=record.size_bytes,
        modified_ns=record.modified_ns,
        sync=record.sync,
    )


def _track_detail(track: Track | None) -> str:
    if track is None:
        return ""
    return " · ".join(value for value in (track.artist, track.album) if value.strip())


def _identity(value: str | None) -> str | None:
    normalized = "" if value is None else value.strip()
    return normalized or None


def _path_name(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1]


def _item_sort_key(item: SyncPlanItem) -> tuple[int, str, str]:
    priority = {
        SyncPlanAction.ADD: 0,
        SyncPlanAction.UPDATE: 1,
        SyncPlanAction.REMOVE: 2,
        SyncPlanAction.ATTENTION: 3,
        SyncPlanAction.UNCHANGED: 4,
    }
    return priority[item.action], item.media_kind.value, item.name.casefold()


__all__ = [
    "SyncPlan",
    "SyncPlanAction",
    "SyncPlanBasis",
    "SyncPlanItem",
    "SyncPlanMediaKind",
    "host_path_identity",
    "prepare_sync_plan",
    "select_sync_plan",
]
