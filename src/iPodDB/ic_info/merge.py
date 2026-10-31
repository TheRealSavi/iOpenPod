"""Merge prepared records by account/key identity, retaining destination data."""

from dataclasses import dataclass, replace

from iPodDB.ic_info.records import Account, Record, Store, inspect_store


@dataclass(frozen=True, slots=True)
class MergeResult:
    """Merged decoded records and counts of incoming key decisions."""

    store: Store
    added_keys: int
    replaced_keys: int
    unchanged_keys: int


def merge_prepared_stores(destination: Store, incoming: Store) -> MergeResult:
    """Merge keys already encrypted for the destination's GUID and sessions.

    Shared accounts must retain the destination's exact session record and
    version. The transfer layer establishes this by decoding session material
    and reencrypting incoming values, never by comparing RSA ciphertext alone.
    Incoming keys win identifier conflicts; unrelated destination records stay.
    """
    if destination.guid != incoming.guid:
        raise ValueError("Cannot merge IC-Info groups for different devices.")
    # Revalidate caller-created models rather than trusting cached projections.
    destination = inspect_store(destination.root, destination.guid)
    incoming = inspect_store(incoming.root, incoming.guid)
    old_accounts = {row.record.identifier: row for row in destination.accounts}
    replacements: dict[int, Record] = {}
    additions: list[Record] = []
    added = replaced_count = unchanged = 0
    for account in incoming.accounts:
        old = old_accounts.get(account.record.identifier)
        if old is None:
            additions.append(account.record)
            added += len(account.keys)
            continue
        _require_shared_context(old, account)
        old_keys = {key.identifier: key for key in old.keys}
        new_keys = {
            key.identifier: (
                key
                if key.identifier not in old_keys
                else _replace_key_values(old_keys[key.identifier], key)
            )
            for key in account.keys
        }
        for key in account.keys:
            previous = old_keys.get(key.identifier)
            if previous is None:
                added += 1
            elif previous == new_keys[key.identifier]:
                unchanged += 1
            else:
                replaced_count += 1
        children = tuple(
            new_keys.get(row.identifier, row) if row.tag == b"key " else row
            for row in old.record.children
        ) + tuple(key for key in account.keys if key.identifier not in old_keys)
        replacements[account.record.identifier] = replace(old.record, children=children)

    # Insert new accounts before the retained tail, without reconstructing or
    # discarding unknown group/root records.
    group_children: list[Record] = []
    inserted = False
    for row in destination.group.children:
        if row.tag == b"tail" and not inserted:
            group_children.extend(additions)
            inserted = True
        group_children.append(
            replacements.get(row.identifier, row) if row.tag == b"user" else row
        )
    if not inserted:
        group_children.extend(additions)
    group = replace(destination.group, children=tuple(group_children))
    root = destination.root.replace_child(group)
    return MergeResult(
        inspect_store(root, destination.guid), added, replaced_count, unchanged
    )


def _require_shared_context(old: Account, incoming: Account) -> None:
    if old.version != incoming.version or old.session != incoming.session:
        raise ValueError(
            "IC-Info merge requires reconciled account sessions and versions."
        )


def _replace_key_values(previous: Record, incoming: Record) -> Record:
    """Replace bundled fields, retaining unknown destination key extensions."""
    known = {b"valu", b"type", b"sign"}
    replacements = {tag: incoming.child(tag) for tag in known}
    children = [replacements.get(row.tag, row) for row in previous.children]
    present = {row.tag for row in previous.children}
    children.extend(
        replacements[tag] for tag in (b"valu", b"type", b"sign") if tag not in present
    )
    for row in incoming.children:
        if row.tag in known or row in children:
            continue
        if any(
            old.tag == row.tag and old.identifier == row.identifier for old in children
        ):
            raise ValueError("Conflicting unknown IC-Info key metadata.")
        children.append(row)
    return replace(previous, children=tuple(children))
