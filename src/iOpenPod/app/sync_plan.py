"""Prepare an immutable Host-to-iPod Sync Plan from completed media scans."""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from iOpenPod.app.host_media_library import (
    HostMediaFileKind,
)
from iOpenPod.app.sync_track_details import track_tag_sha256, track_tag_values
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
    TRACK_DETAILS_CHANGED = "track_details_changed"
    AUDIO_PAYLOAD_CHANGED = "audio_payload_changed"
    TRACK_DETAILS_MATCH = "track_details_match"
    CONTENT_MATCH = "content_match"
    MISSING_IDENTITY = "missing_identity"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    CONFLICTING_IDENTITY = "conflicting_identity"
    USER_DESELECTED = "user_deselected"
    USER_MATCH = "user_match"


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
    metadata_changed: bool = False
    artwork_changed: bool = False
    audio_payload_changed: bool = False
    file_tags_changed: bool = False

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
        if self.action is not SyncPlanAction.UPDATE and (
            self.metadata_changed or self.artwork_changed
        ):
            raise ValueError("Only an Update action may report changed Track details")
        if self.action is not SyncPlanAction.UPDATE and (
            self.audio_payload_changed or self.file_tags_changed
        ):
            raise ValueError(
                "Only an Update action may report changed media payload or file tags"
            )

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
    file_tag_policy: str | None = field(default=None, kw_only=True)
    duplicate_groups: tuple[SyncDuplicateGroup, ...] = field(default=(), kw_only=True)
    duplicate_resolutions: tuple[SyncDuplicateResolution, ...] = field(
        default=(), kw_only=True
    )

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
    track: Track | None = None
    artwork_sha256: str | None = None
    track_details_refreshed: bool = False
    artwork_available: bool = True


@dataclass(frozen=True, slots=True)
class SyncDuplicateHost:
    """One distinct Host file, with details that distinguish Library entries."""

    host_path: str
    name: str
    detail: str = ""
    album: str = ""
    disc_number: int = 0
    track_number: int = 0


@dataclass(frozen=True, slots=True)
class SyncDuplicateIPod:
    """An existing iPod item and the user-owned history removal would discard."""

    ipod_id: int
    ipod_path: str | None
    name: str
    detail: str = ""
    album: str = ""
    disc_number: int = 0
    track_number: int = 0
    play_count: int = 0
    rating: int = 0
    playlist_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SyncDuplicatePair:
    """One explicit one-to-one Host-to-iPod association."""

    host_path: str
    ipod_id: int


@dataclass(frozen=True, slots=True)
class SyncDuplicateResolution:
    """User intent for a duplicate group; omitted files skip and iPod items stay."""

    group_id: str
    pairs: tuple[SyncDuplicatePair, ...] = ()
    added_host_paths: frozenset[str] = frozenset()
    removed_ipod_ids: frozenset[int] = frozenset()


@dataclass(frozen=True, slots=True)
class SyncDuplicateGroup:
    """Similar media and proven relationships, never an instruction to merge."""

    group_id: str
    media_kind: SyncPlanMediaKind
    hosts: tuple[SyncDuplicateHost, ...]
    ipods: tuple[SyncDuplicateIPod, ...]
    established_pairs: tuple[SyncDuplicatePair, ...] = ()
    requires_resolution: bool = False
    _hosts: tuple[_Candidate, ...] = field(default=(), repr=False, kw_only=True)
    _ipods: tuple[_Candidate, ...] = field(default=(), repr=False, kw_only=True)

    def pairable_ipod_ids(self, host_path: str) -> tuple[int, ...]:
        """Return candidates for one Host file without storing a Cartesian product."""

        identity = host_path_identity(host_path)
        if any(
            host_path_identity(p.host_path) == identity for p in self.established_pairs
        ):
            return ()
        host = next(
            (
                h
                for h in self._hosts
                if h.path and host_path_identity(h.path) == identity
            ),
            None,
        )
        if host is None:
            return ()
        established_ids = {pair.ipod_id for pair in self.established_pairs}
        return tuple(
            item.item_id
            for item in self._ipods
            if item.item_id is not None
            and item.item_id not in established_ids
            and _can_pair_duplicate(host, item)
            and (
                host.media_kind is SyncPlanMediaKind.TRACK
                or _paired_item(host, item, None).action is not SyncPlanAction.ATTENTION
            )
        )

    def resolved_items(
        self,
        resolution: SyncDuplicateResolution,
        *,
        file_tag_policy: str | None,
    ) -> tuple[SyncPlanItem, ...]:
        """Validate choices and derive items from this group's captured evidence."""

        if resolution.group_id != self.group_id:
            raise ValueError("The resolution refers to a different duplicate group")
        hosts = {host_path_identity(h.path): h for h in self._hosts if h.path}
        ipods = {i.item_id: i for i in self._ipods if i.item_id is not None}
        paired_hosts = {host_path_identity(p.host_path) for p in self.established_pairs}
        paired_ipods = {p.ipod_id for p in self.established_pairs}
        items: list[SyncPlanItem] = []
        for pair in resolution.pairs:
            path = host_path_identity(pair.host_path)
            if path in paired_hosts or pair.ipod_id in paired_ipods:
                raise ValueError(
                    "Duplicate associations must be one-to-one and preserve known pairs"
                )
            if path not in hosts or pair.ipod_id not in ipods:
                raise ValueError("A duplicate association refers to a different group")
            host, ipod = hosts[path], ipods[pair.ipod_id]
            if not _can_pair_duplicate(host, ipod):
                raise ValueError(
                    "The duplicate association has no matching scan evidence"
                )
            items.append(_explicit_paired_item(host, ipod, file_tag_policy))
            paired_hosts.add(path)
            paired_ipods.add(pair.ipod_id)
        added = {host_path_identity(path) for path in resolution.added_host_paths}
        if not added <= hosts.keys() or added & paired_hosts:
            raise ValueError(
                "A separate Add must name an unpaired Host file in this group"
            )
        if (
            not resolution.removed_ipod_ids <= ipods.keys()
            or resolution.removed_ipod_ids & paired_ipods
        ):
            raise ValueError("A removal must name an unpaired iPod item in this group")

        items.extend(
            _host_only_item(h) for path, h in hosts.items() if path not in paired_hosts
        )
        items.extend(
            _ipod_only_item(i)
            for item_id, i in ipods.items()
            if item_id not in paired_ipods
        )
        return tuple(items)


def prepare_sync_plan(
    host: HostMediaLibrary,
    ipod: IPodMediaLibrary,
    ipod_library: LibrarySnapshot,
    *,
    file_tag_policy: str | None = None,
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

    _pair_by_prior_path(
        host_candidates,
        ipod_candidates,
        host_remaining,
        ipod_remaining,
        pairs,
        attention,
    )

    for index in tuple(host_remaining):
        candidate = host_candidates[index]
        if candidate.fingerprint is None:
            host_remaining.discard(index)
            attention.append(_attention_item(candidate, SyncPlanBasis.MISSING_IDENTITY))
    for index in tuple(ipod_remaining):
        candidate = ipod_candidates[index]
        if candidate.fingerprint is None:
            ipod_remaining.discard(index)
            attention.append(_attention_item(candidate, SyncPlanBasis.MISSING_IDENTITY))

    _pair_by_content(
        host_candidates,
        ipod_candidates,
        host_remaining,
        ipod_remaining,
        pairs,
        attention,
    )

    items = [
        _paired_item(
            host_candidates[host_index], ipod_candidates[ipod_index], file_tag_policy
        )
        for host_index, ipod_index in pairs
    ]
    items.extend(_host_only_item(host_candidates[index]) for index in host_remaining)
    items.extend(_ipod_only_item(ipod_candidates[index]) for index in ipod_remaining)
    items.extend(attention)
    return SyncPlan(
        tuple(sorted(items, key=_item_sort_key)),
        file_tag_policy=file_tag_policy,
        duplicate_groups=_duplicate_groups(
            host_candidates, ipod_candidates, pairs, attention, ipod_library
        ),
    )


def select_sync_plan(
    comparison: SyncPlan,
    *,
    selected_host_paths: frozenset[str],
    selected_ipod_removals: frozenset[tuple[SyncPlanMediaKind, int]],
    duplicate_resolutions: tuple[SyncDuplicateResolution, ...] | None = None,
) -> SyncPlan:
    """Derive the reviewed plan from explicit desired-device membership.

    Host-only media is absent until selected. Correlated Host media that the user
    deselects becomes an explicit removal. iPod-only removal candidates are absent
    until the user opts into each one on the Review page. Attention items remain
    visible because selection cannot make unsafe correlation evidence actionable;
    a Host-only item with a missing identity is the one safe exception because an
    explicit one-way Add does not require correlation.
    """

    if duplicate_resolutions is not None:
        comparison = resolve_sync_duplicates(comparison, duplicate_resolutions)
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

    return SyncPlan(
        tuple(sorted(items, key=_item_sort_key)),
        file_tag_policy=comparison.file_tag_policy,
        duplicate_groups=comparison.duplicate_groups,
        duplicate_resolutions=comparison.duplicate_resolutions,
    )


def host_path_identity(value: str) -> str:
    """Return the normalized identity used for Host-path correlation and selection."""

    return os.path.normcase(os.path.normpath(os.path.abspath(value)))


def resolve_sync_duplicates(
    comparison: SyncPlan,
    resolutions: tuple[SyncDuplicateResolution, ...],
) -> SyncPlan:
    """Apply checked one-to-one choices, leaving all other copies as opt-in actions.

    Callers retain Host membership and removal selection independently. A resolution
    never adds or removes a file merely because it resembles another file. Candidate
    evidence is captured with the comparison; execution must derive it again from
    its bound scans before accepting this plan.
    """

    groups = {group.group_id: group for group in comparison.duplicate_groups}
    seen_groups: set[str] = set()
    replaced_hosts: set[tuple[SyncPlanMediaKind, str]] = set()
    replaced_ipods: set[tuple[SyncPlanMediaKind, int]] = set()
    preserved_pairs: set[tuple[SyncPlanMediaKind, str, int]] = set()
    replacements: list[SyncPlanItem] = []
    for resolution in resolutions:
        if resolution.group_id in seen_groups:
            raise ValueError("A duplicate group may only be resolved once")
        seen_groups.add(resolution.group_id)
        group = groups.get(resolution.group_id)
        if group is None:
            raise ValueError("The duplicate group is not part of this comparison")
        replaced_hosts.update(
            (group.media_kind, host_path_identity(host.host_path))
            for host in group.hosts
        )
        replaced_ipods.update((group.media_kind, ipod.ipod_id) for ipod in group.ipods)
        preserved_pairs.update(
            (group.media_kind, host_path_identity(pair.host_path), pair.ipod_id)
            for pair in group.established_pairs
        )
        replacements.extend(
            group.resolved_items(resolution, file_tag_policy=comparison.file_tag_policy)
        )
    items: list[SyncPlanItem] = []
    for item in comparison.items:
        host_key = host_path_identity(item.host_path) if item.host_path else None
        belongs = (
            host_key is not None and (item.media_kind, host_key) in replaced_hosts
        ) or (
            item.ipod_id is not None
            and (item.media_kind, item.ipod_id) in replaced_ipods
        )
        established = (
            host_key is not None
            and item.ipod_id is not None
            and (item.media_kind, host_key, item.ipod_id) in preserved_pairs
        )
        if not belongs or established:
            items.append(item)
    items.extend(replacements)
    return SyncPlan(
        tuple(sorted(items, key=_item_sort_key)),
        file_tag_policy=comparison.file_tag_policy,
        duplicate_groups=comparison.duplicate_groups,
        duplicate_resolutions=resolutions,
    )


def _can_pair_duplicate(host: _Candidate, ipod: _Candidate) -> bool:
    return host.media_kind is ipod.media_kind and (
        (host.fingerprint is not None and host.fingerprint == ipod.fingerprint)
        or (
            host.path is not None
            and ipod.sync is not None
            and bool(ipod.sync.host_path_hint.strip())
            and host_path_identity(host.path)
            == host_path_identity(ipod.sync.host_path_hint)
        )
    )


def _explicit_paired_item(
    host: _Candidate, ipod: _Candidate, file_tag_policy: str | None
) -> SyncPlanItem:
    item = _paired_item(host, ipod, file_tag_policy)
    if item.action is SyncPlanAction.ATTENTION:
        raise ValueError("Conflicting source facts need a fresh scan before pairing")
    metadata_changed = (
        host.track is not None
        and ipod.track is not None
        and track_tag_values(host.track) != track_tag_values(ipod.track)
    )
    return replace(
        item,
        action=SyncPlanAction.UPDATE,
        basis=SyncPlanBasis.USER_MATCH,
        metadata_changed=metadata_changed,
        artwork_changed=_artwork_changed(host, ipod, facts_changed=True),
        file_tags_changed=host.media_kind is SyncPlanMediaKind.TRACK
        and file_tag_policy is not None
        and (ipod.sync is None or ipod.sync.file_tag_policy != file_tag_policy),
    )


def _duplicate_groups(
    hosts: tuple[_Candidate, ...],
    ipods: tuple[_Candidate, ...],
    pairs: list[tuple[int, int]],
    attention: list[SyncPlanItem],
    library: LibrarySnapshot,
) -> tuple[SyncDuplicateGroup, ...]:
    """Find connected evidence groups in linear space, including already paired copies."""

    candidates = (*hosts, *ipods)
    parents = list(range(len(candidates)))

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def join(first: int, second: int) -> None:
        parents[root(second)] = root(first)

    fingerprints: dict[tuple[SyncPlanMediaKind, str], int] = {}
    paths: dict[tuple[SyncPlanMediaKind, str], int] = {}
    for index, candidate in enumerate(candidates):
        if candidate.fingerprint:
            fingerprint_key = (candidate.media_kind, candidate.fingerprint)
            if fingerprint_key in fingerprints:
                join(fingerprints[fingerprint_key], index)
            else:
                fingerprints[fingerprint_key] = index
        path = (
            candidate.path
            if index < len(hosts)
            else (candidate.sync.host_path_hint if candidate.sync else None)
        )
        if path:
            path_key = (candidate.media_kind, host_path_identity(path))
            if path_key in paths:
                join(paths[path_key], index)
            else:
                paths[path_key] = index
    components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(candidates)):
        components[root(index)].append(index)
    component_pairs: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for host_index, ipod_index in pairs:
        component_pairs[root(host_index)].append((host_index, ipod_index))
    playlist_names: dict[int, list[str]] = defaultdict(list)
    for playlist in library.playlists:
        for track_id in set(playlist.track_ids):
            playlist_names[track_id].append(playlist.name)
    ambiguous_hosts = {
        host_path_identity(item.host_path)
        for item in attention
        if item.host_path and item.basis is SyncPlanBasis.AMBIGUOUS_IDENTITY
    }
    groups: list[SyncDuplicateGroup] = []
    for component_id, indexes in components.items():
        host_indexes = {index for index in indexes if index < len(hosts)}
        ipod_indexes = {index - len(hosts) for index in indexes if index >= len(hosts)}
        if len(host_indexes) < 2 and len(ipod_indexes) < 2:
            continue
        group_hosts = tuple(
            sorted(
                (hosts[index] for index in host_indexes),
                key=lambda h: host_path_identity(h.path or ""),
            )
        )
        group_ipods = tuple(
            sorted(
                (ipods[index] for index in ipod_indexes),
                key=lambda i: i.item_id if i.item_id is not None else -1,
            )
        )
        media_kind = candidates[indexes[0]].media_kind
        host_members = tuple(
            SyncDuplicateHost(
                h.path,
                h.name,
                h.detail,
                h.track.album if h.track else "",
                h.track.metadata.disc_number if h.track else 0,
                h.track.track_number if h.track else 0,
            )
            for h in group_hosts
            if h.path is not None
        )
        ipod_members = tuple(
            SyncDuplicateIPod(
                i.item_id,
                i.path,
                i.name,
                i.detail,
                i.track.album if i.track else "",
                i.track.metadata.disc_number if i.track else 0,
                i.track.track_number if i.track else 0,
                i.track.play_count if i.track else 0,
                i.track.rating if i.track else 0,
                tuple(playlist_names[i.item_id])
                if media_kind is SyncPlanMediaKind.TRACK
                else (),
            )
            for i in group_ipods
            if i.item_id is not None
        )
        identity = repr(
            (
                media_kind.value,
                tuple(host_path_identity(h.host_path) for h in host_members),
                tuple(i.ipod_id for i in ipod_members),
            )
        )
        groups.append(
            SyncDuplicateGroup(
                group_id=hashlib.sha256(identity.encode()).hexdigest(),
                media_kind=media_kind,
                hosts=host_members,
                ipods=ipod_members,
                established_pairs=tuple(
                    SyncDuplicatePair(hosts[h].path or "", ipods[i].item_id or 0)
                    for h, i in sorted(component_pairs[component_id])
                ),
                requires_resolution=any(
                    host_path_identity(h.host_path) in ambiguous_hosts
                    for h in host_members
                ),
                _hosts=group_hosts,
                _ipods=group_ipods,
            )
        )
    return tuple(sorted(groups, key=lambda group: group.group_id))


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


def _paired_item(
    host: _Candidate, ipod: _Candidate, file_tag_policy: str | None
) -> SyncPlanItem:
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
    expected_fingerprint = (
        sync.host_content_sha256
        if host.media_kind is SyncPlanMediaKind.PHOTO and sync.host_content_sha256
        else ipod.fingerprint
    )
    fingerprints_conflict = (
        host.media_kind is SyncPlanMediaKind.PHOTO
        and host.fingerprint is not None
        and expected_fingerprint is not None
        and host.fingerprint != expected_fingerprint
    )
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
    if host.media_kind is SyncPlanMediaKind.TRACK:
        # Reuse the bounded Acoustic Fingerprints already calculated by scans.
        # Equality intentionally accepts re-encodings and changes outside the
        # analysis window. Missing evidence falls back to changed Host file facts.
        audio_payload_changed = (
            host.fingerprint != ipod.fingerprint
            if host.fingerprint is not None and ipod.fingerprint is not None
            else size_changed or modified_changed
        )
        metadata_changed = False
        if host.track is not None and ipod.track is not None:
            if sync.host_tag_sha256 is not None and sync.ipod_tag_sha256 is not None:
                metadata_changed = (
                    track_tag_sha256(host.track) != sync.host_tag_sha256
                    or track_tag_sha256(ipod.track) != sync.ipod_tag_sha256
                ) and track_tag_values(host.track) != track_tag_values(ipod.track)
            elif size_changed or modified_changed or host.track_details_refreshed:
                metadata_changed = track_tag_values(host.track) != track_tag_values(
                    ipod.track
                )
            elif sync.ipod_tag_sha256 is not None:
                metadata_changed = track_tag_sha256(ipod.track) != sync.ipod_tag_sha256
            elif sync.ipod_baseline_pending:
                # A migrated helper has Sync provenance but no post-commit iPod
                # tag baseline. Compare the two current semantic projections
                # rather than accepting the current iPod value as that baseline.
                metadata_changed = track_tag_values(host.track) != track_tag_values(
                    ipod.track
                )
        artwork_changed = _artwork_changed(
            host, ipod, facts_changed=size_changed or modified_changed
        )
        file_tags_changed = (
            file_tag_policy is not None and sync.file_tag_policy != file_tag_policy
        )
        if (
            audio_payload_changed
            or metadata_changed
            or artwork_changed
            or file_tags_changed
        ):
            return _item(
                SyncPlanAction.UPDATE,
                (
                    SyncPlanBasis.AUDIO_PAYLOAD_CHANGED
                    if audio_payload_changed
                    else SyncPlanBasis.TRACK_DETAILS_CHANGED
                ),
                host,
                ipod,
                host_size_changed=size_changed,
                host_modified_changed=modified_changed,
                metadata_changed=metadata_changed,
                artwork_changed=artwork_changed,
                audio_payload_changed=audio_payload_changed,
                file_tags_changed=file_tags_changed,
            )
        return _item(
            SyncPlanAction.UNCHANGED,
            SyncPlanBasis.TRACK_DETAILS_MATCH
            if size_changed or modified_changed
            else SyncPlanBasis.HOST_FACTS_MATCH,
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


def _artwork_changed(
    host: _Candidate, ipod: _Candidate, *, facts_changed: bool
) -> bool:
    if not host.artwork_available:
        return False
    host_artwork = host.track is not None and host.track.artwork_id != 0
    ipod_artwork_id = 0 if ipod.track is None else ipod.track.artwork_id
    sync = ipod.sync
    if not host_artwork:
        return ipod_artwork_id != 0 and (
            facts_changed
            or (
                sync is not None
                and (sync.host_artwork_sha256 is not None or sync.ipod_baseline_pending)
            )
        )
    if ipod_artwork_id == 0 or host.artwork_sha256 is None:
        return True
    return (
        sync is None
        or sync.ipod_baseline_pending
        or sync.host_artwork_sha256 != host.artwork_sha256
        or sync.ipod_artwork_id != ipod_artwork_id
    )


def _item(
    action: SyncPlanAction,
    basis: SyncPlanBasis,
    host: _Candidate,
    ipod: _Candidate,
    *,
    host_size_changed: bool = False,
    host_modified_changed: bool = False,
    metadata_changed: bool = False,
    artwork_changed: bool = False,
    audio_payload_changed: bool = False,
    file_tags_changed: bool = False,
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
        metadata_changed=metadata_changed,
        artwork_changed=artwork_changed,
        audio_payload_changed=audio_payload_changed,
        file_tags_changed=file_tags_changed,
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
    artwork_by_id = {
        source.artwork_id: source.content_sha256 for source in library.artwork_sources
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
    seen_paths: set[str] = set()
    rechecked_paths = {
        host_path_identity(path) for path in library.rechecked_track_paths
    }
    unavailable_artwork_paths = {
        host_path_identity(path) for path in library.unavailable_artwork_paths
    }
    for source in library.sources:
        if source.kind is HostMediaFileKind.PLAYLIST:
            continue
        path = os.fspath(source.path)
        identity = host_path_identity(path)
        if identity in seen_paths:
            continue
        seen_paths.add(identity)
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
                    track=track,
                    track_details_refreshed=host_path_identity(path) in rechecked_paths,
                    artwork_available=identity not in unavailable_artwork_paths,
                    artwork_sha256=(
                        artwork_by_id.get(track.artwork_id)
                        if track is not None and track.artwork_id
                        else ""
                    ),
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
            track=track,
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
        track=track,
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
    "SyncDuplicateGroup",
    "SyncDuplicateHost",
    "SyncDuplicateIPod",
    "SyncDuplicatePair",
    "SyncDuplicateResolution",
    "SyncPlan",
    "SyncPlanAction",
    "SyncPlanBasis",
    "SyncPlanItem",
    "SyncPlanMediaKind",
    "host_path_identity",
    "prepare_sync_plan",
    "resolve_sync_duplicates",
    "select_sync_plan",
]
