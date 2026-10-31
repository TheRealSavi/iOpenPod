"""Prepare game authorization publication without owning a device connection."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import TYPE_CHECKING, cast

from iOpenPod.app.display_text import SourceText, exception_text, source_text
from storage import (
    DevicePath,
    FileContent,
    StorageTransaction,
    TransactionWrite,
)

if TYPE_CHECKING:
    from device_registry import DeviceEvidence, DeviceIdentifier, DeviceProfile
    from storage import FilePrecondition, FilesystemSession

AUTHORIZATION_PATH = DevicePath("iPod_Control/iTunes/IC-Info.sidb")
MAX_AUTHORIZATION_BYTES = 0x80000
_TESTED_RELEASES = {
    13: (1, 3, 0),
    20: (1, 3, 0),
    25: (1, 3, 0),
    24: (1, 1, 2),
    33: (2, 0, 1),
    35: (2, 0, 4),
    38: (2, 0, 5),
    26: (1, 1, 3),
    31: (1, 0, 4),
    34: (1, 0, 2),
}

# Representative codec families for the identified model when reported family
# evidence is absent, conflicting, or outside the researched list.
_MODEL_CODEC_FAMILIES = {
    ("iPod", "5th Gen"): 13,
    ("iPod", "5.5th Gen"): 25,
    ("iPod Classic", "6th Gen"): 24,
    ("iPod Classic", "6.5th Gen"): 33,
    ("iPod Classic", "7th Gen"): 35,
    ("iPod Nano", "3rd Gen"): 26,
    ("iPod Nano", "4th Gen"): 31,
    ("iPod Nano", "5th Gen"): 34,
}


@dataclass(frozen=True, slots=True)
class GameCompatibility:
    """Captured qualification and codec choice for one confirmation."""

    families: tuple[int, ...]
    firmware: tuple[str, ...]
    model_number: str
    codec_family: int
    warning: str = ""


@dataclass(frozen=True, slots=True)
class GamesResult:
    """Publication counts, never account identifiers or key material."""

    added_keys: int
    replaced_keys: int
    unchanged_keys: int
    changed: bool


@dataclass(frozen=True, slots=True)
class PreparedGames:
    transaction: StorageTransaction | None
    result: GamesResult


def _strongest_values[T](items: tuple[DeviceIdentifier[T], ...]) -> tuple[T, ...]:
    if not items:
        return ()
    authority = max(item.authority for item in items)
    return tuple(item.value for item in items if item.authority == authority)


def describe_unavailability(evidence: DeviceEvidence, reason: str) -> SourceText:
    """Attach the actual highest-authority values used by qualification."""
    families = sorted(set(_strongest_values(evidence.updater_family_ids)))
    firmware = sorted(set(_strongest_values(evidence.firmware_versions)))
    return source_text(
        "{reason}\nReported updater family: {families}\nReported firmware: {firmware}",
        reason=reason,
        families=", ".join(map(str, families))
        if families
        else source_text("Not reported"),
        firmware=", ".join(firmware) if firmware else source_text("Not reported"),
    )


def destination_family(evidence: DeviceEvidence) -> int:
    """Require unambiguous family and RetailOS evidence for an inspected build."""
    families = set(_strongest_values(evidence.updater_family_ids))
    versions = _strongest_values(evidence.firmware_versions)
    if not families or not versions:
        reason = source_text("The updater family or firmware release was not reported.")
        raise ValueError(describe_unavailability(evidence, reason))
    if len(families) != 1:
        reason = source_text(
            "Conflicting updater families were reported; game authorization cannot choose a family."
        )
        raise ValueError(describe_unavailability(evidence, reason))
    family = next(iter(families))
    if family not in _TESTED_RELEASES:
        reason = source_text(
            "This updater family is not supported for game authorization. Supported families: {families}.",
            families=", ".join(map(str, sorted(_TESTED_RELEASES))),
        )
        raise ValueError(describe_unavailability(evidence, reason))
    releases: set[tuple[int, int, int] | None] = set()
    for version in versions:
        match = re.fullmatch(
            r"([0-9]{1,3})\.([0-9]{1,3})(?:\.([0-9]{1,3}))?", version.strip()
        )
        releases.add(
            None
            if match is None
            else (int(match[1]), int(match[2]), int(match[3] or 0))
        )
    if releases != {_TESTED_RELEASES[family]}:
        if None in releases:
            reason = source_text(
                "The reported firmware release could not be interpreted."
            )
        elif len(releases) > 1:
            reason = source_text(
                "Conflicting firmware releases were reported; game authorization cannot choose a release."
            )
        else:
            reason = source_text(
                "Game authorization is not supported for this firmware release."
            )
        required = _TESTED_RELEASES[family]
        reason = source_text(
            "{reason}\nVerified firmware for updater family {family}: {firmware}.",
            reason=reason,
            family=str(family),
            firmware=".".join(map(str, required if required[2] else required[:2])),
        )
        raise ValueError(describe_unavailability(evidence, reason))
    return family


def compatibility(
    evidence: DeviceEvidence, profile: DeviceProfile
) -> GameCompatibility:
    """Keep verification separate from an explicitly confirmed best-effort attempt."""
    families = tuple(sorted(set(_strongest_values(evidence.updater_family_ids))))
    firmware = tuple(sorted(set(_strongest_values(evidence.firmware_versions))))
    warning = ""
    try:
        family = destination_family(evidence)
    except ValueError as error:
        warning = exception_text(error)
        if len(families) == 1 and families[0] in _TESTED_RELEASES:
            family = families[0]
        else:
            family = _MODEL_CODEC_FAMILIES.get((profile.family, profile.generation), 0)
            if not family:
                raise ValueError(
                    source_text(
                        "No game authorization codec is available for this iPod model."
                    )
                ) from error
            warning = source_text(
                "{detail}\nContinuing will try the authorization format for {model}.",
                detail=warning,
                model=profile.display_name,
            )
    return GameCompatibility(families, firmware, profile.model_number, family, warning)


def execution_family(
    evidence: DeviceEvidence,
    profile: DeviceProfile,
    approved: GameCompatibility | None,
) -> int:
    """An override applies only to the exact identity values the user reviewed."""
    if approved is None:
        return destination_family(evidence)
    if compatibility(evidence, profile) != approved:
        raise ValueError(
            source_text(
                "The iPod family or firmware changed after confirmation. Try again."
            )
        )
    return approved.codec_family


def bundled_source() -> tuple[bytes, bytes]:
    """Load and authenticate the explicitly bundled Classic source resource."""
    root = files("iOpenPod").joinpath("assets", "games")
    decoded: object = json.loads(
        root.joinpath("source.json").read_text(encoding="utf-8")
    )
    if not isinstance(decoded, dict):
        raise ValueError("The bundled game authorization metadata is invalid.")
    metadata = cast("dict[str, object]", decoded)
    guid_hex: object = metadata.get("guid")
    expected_hash: object = metadata.get("sha256")
    if not isinstance(guid_hex, str) or not isinstance(expected_hash, str):
        raise ValueError("The bundled game authorization metadata is incomplete.")
    guid = bytes.fromhex(guid_hex)
    source = root.joinpath("classic65-IC-Info.sidb").read_bytes()
    if len(guid) != 8 or hashlib.sha256(source).hexdigest() != expected_hash:
        raise ValueError("The bundled game authorization source failed verification.")
    return source, guid


def prepare(
    session: FilesystemSession,
    *,
    source: bytes,
    source_guid: bytes,
    destination_guid: bytes,
    family: int,
    dependencies: tuple[FilePrecondition, ...],
) -> PreparedGames:
    """Capture the existing file, convert/merge bytes, and validate one plan."""
    from iPodDB.ic_info import transfer_and_merge

    snapshot = (
        session.read_snapshot(AUTHORIZATION_PATH, max_bytes=MAX_AUTHORIZATION_BYTES)
        if session.exists(AUTHORIZATION_PATH)
        else None
    )
    existing = None if snapshot is None else snapshot.data
    converted = transfer_and_merge(
        source, source_guid, destination_guid, family, existing
    )
    changed = converted.data != existing
    result = GamesResult(
        converted.added_keys, converted.replaced_keys, converted.unchanged_keys, changed
    )
    if not changed:
        if (
            snapshot is None
            or session.fingerprint(AUTHORIZATION_PATH) != snapshot.fingerprint
        ):
            raise ValueError("The game authorization file changed during preparation.")
        return PreparedGames(None, result)
    transaction = StorageTransaction(
        (
            TransactionWrite(
                AUTHORIZATION_PATH,
                converted.data,
                FileContent(
                    len(converted.data), hashlib.sha256(converted.data).hexdigest()
                ),
                expected=None if snapshot is None else snapshot.fingerprint,
            ),
        ),
        dependencies=dependencies,
        host_recovery=True,
    )
    session.validate_transaction(transaction)
    return PreparedGames(transaction, result)
