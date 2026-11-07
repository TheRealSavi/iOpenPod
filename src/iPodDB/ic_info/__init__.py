"""Pure IC-Info conversion and merging; device persistence belongs to Storage."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TransferResult:
    """Prepared file bytes and incoming-key merge decisions."""

    data: bytes
    added_keys: int
    replaced_keys: int
    unchanged_keys: int


def transfer_and_merge(
    source: bytes,
    source_guid: bytes,
    destination_guid: bytes,
    destination_family: int,
    existing: bytes | None = None,
) -> TransferResult:
    """Prepare destination bytes without accessing a device or invoking firmware."""
    from iPodDB.ic_info.transfer import prepare_transfer

    return prepare_transfer(
        source, source_guid, destination_guid, destination_family, existing
    )
