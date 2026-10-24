"""Capture Mix ownership and publish it in the Library's Storage transaction."""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from time import time
from typing import TYPE_CHECKING, cast

from iOpenPod.app.core.settings.device import SETTINGS_PATH, load_device_settings
from iOpenPod.app.genius_mixes import (
    GENIUS_MIX_POLICY,
    MIX_CATALOG,
    ManagedMix,
    MixPolicy,
    MixState,
    plan_mixes,
)
from iPodDB.library.genius import project_genius_browse
from storage import (
    DevicePath,
    FileContent,
    FilePrecondition,
    StorageError,
    TransactionWrite,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from iOpenPod.app.genius_audio import GeniusAudioProfile
    from iOpenPod.app.library_write import LibraryPreparationRequest
    from iPodDB.library.genius import GeniusUpdate
    from storage import FilesystemSession

MIX_STATE_PATH = DevicePath("iPod_Control/iOpenPod/genius-mixes-v1.json")
_LIBRARY = DevicePath("iPod_Control/iTunes/iTunes Library.itlp/Library.itdb")
_LIMIT = 64 * 1024


def encode_mix_state(state: MixState) -> bytes:
    return (
        json.dumps(
            {
                "version": 1,
                "mixes": [
                    {
                        "container_id": entry.container_id,
                        "definition": entry.definition_key,
                        "added_at": entry.added_at,
                    }
                    for entry in state.entries
                ],
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode()


def decode_mix_state(data: bytes) -> MixState:
    document: object = json.loads(data)
    if not isinstance(document, dict):
        raise ValueError("Invalid Genius Mix ownership document")
    payload = cast("dict[str, object]", document)
    if type(payload.get("version")) is not int or payload["version"] != 1:
        raise ValueError("Unsupported Genius Mix ownership version")
    rows = payload.get("mixes")
    if not isinstance(rows, list):
        raise ValueError("Invalid Genius Mix ownership records")
    records = cast("list[object]", rows)
    if len(records) > len(MIX_CATALOG):
        raise ValueError("Invalid Genius Mix ownership records")
    entries: list[ManagedMix] = []
    keys = {definition.key for definition in MIX_CATALOG}
    for value in records:
        if not isinstance(value, dict):
            raise ValueError("Invalid Genius Mix ownership record")
        row = cast("dict[str, object]", value)
        identity, key, added = (
            row.get("container_id"),
            row.get("definition"),
            row.get("added_at"),
        )
        if (
            type(identity) is not int
            or not 0 < identity < 1 << 64
            or not isinstance(key, str)
            or key not in keys
            or "added_at" not in row
            or (added is not None and (type(added) is not int or added < 0))
        ):
            raise ValueError("Invalid Genius Mix ownership fields")
        entries.append(ManagedMix(identity, key, added))
    if len({entry.container_id for entry in entries}) != len(entries) or len(
        {entry.definition_key for entry in entries}
    ) != len(entries):
        raise ValueError("Duplicate Genius Mix ownership")
    return MixState(tuple(entries))


def _capture(session: FilesystemSession) -> tuple[MixState, FilePrecondition]:
    if not session.exists(MIX_STATE_PATH):
        return MixState(), FilePrecondition(MIX_STATE_PATH, None)
    source = session.read_snapshot(MIX_STATE_PATH, max_bytes=_LIMIT)
    return decode_mix_state(source.data), FilePrecondition(
        MIX_STATE_PATH, source.fingerprint
    )


def load_mix_state(session: FilesystemSession) -> MixState:
    try:
        state, _ = _capture(session)
        return state
    except (ValueError, StorageError) as error:
        if not session.is_active:
            raise
        return MixState(
            error=f"Genius Mix ownership could not be read. Reload the iPod. {error}"
        )


def prune_mix_ownership(
    session: FilesystemSession,
    expected: MixState,
    planned: MixState,
    removed_ids: frozenset[int],
) -> tuple[MixState, FilePrecondition, TransactionWrite]:
    """Retire ownership of collections emptied by this Library publication."""
    state, before = _capture(session)
    if state != expected:
        raise ValueError("Genius Mix ownership changed. Reload the iPod before saving.")
    desired = replace(
        planned,
        entries=tuple(e for e in planned.entries if e.container_id not in removed_ids),
    )
    data = encode_mix_state(desired)
    return (
        desired,
        before,
        TransactionWrite(
            MIX_STATE_PATH,
            data,
            FileContent(len(data), sha256(data).hexdigest()),
            before.fingerprint,
        ),
    )


def prepare_mix_changes(
    session: FilesystemSession,
    request: LibraryPreparationRequest,
    update: GeniusUpdate,
    *,
    profiles: Mapping[int, GeniusAudioProfile] | None = None,
    remove_ids: tuple[int, ...] = (),
) -> tuple[
    GeniusUpdate, MixState, tuple[FilePrecondition, ...], TransactionWrite | None
]:
    state, state_before = _capture(session)
    if state != request.source.genius_mix_state:
        raise ValueError("Genius Mix ownership changed. Reload the iPod before saving.")
    policy = None
    preconditions = [state_before]
    if request.rotate_genius_mixes:
        settings = load_device_settings(session)
        if not settings.writable:
            raise ValueError(
                "Genius Mix settings could not be verified. Reload the iPod."
            )
        preconditions.append(FilePrecondition(SETTINGS_PATH, settings.revision))
        value = dict(settings.values).get(
            GENIUS_MIX_POLICY.key, GENIUS_MIX_POLICY.default
        )
        if not GENIUS_MIX_POLICY.validate(value):
            raise ValueError(
                "Invalid automatic Genius Mix settings. Update the settings before Sync."
            )
        policy = MixPolicy.decode(value)
    if session.exists(_LIBRARY):
        source = session.read_snapshot(_LIBRARY, max_bytes=1024 * 1024 * 1024)
        preconditions.append(FilePrecondition(_LIBRARY, source.fingerprint))
        browse = project_genius_browse(
            replace(request.source.library, playlists=()), sqlite_library=source.data
        )
        if browse.issues:
            raise ValueError(
                "Genius Mix collections could not be verified. Reload the iPod."
            )
    else:
        preconditions.append(FilePrecondition(_LIBRARY, None))
        browse = project_genius_browse(request.source.library)
    plan = plan_mixes(
        request.snapshot,
        browse,
        state,
        manual_keys=request.add_genius_mixes,
        remove_ids=remove_ids,
        policy=policy,
        profiles=profiles,
        now=int(time()),
    )
    write = None
    if plan.state != state:
        data = encode_mix_state(plan.state)
        write = TransactionWrite(
            MIX_STATE_PATH,
            data,
            FileContent(len(data), sha256(data).hexdigest()),
            state_before.fingerprint,
        )
    return (
        replace(update, mix_additions=plan.additions, mix_removals=plan.removals),
        plan.state,
        tuple(preconditions),
        write,
    )
