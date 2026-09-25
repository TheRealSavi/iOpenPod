"""Collect independent source-folder constraints before any reconciliation pass."""

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartNumericRuleData,
    MhodSmartRulesPayload,
    MhodSmartRulesPrefix,
)
from iPodDB.library._playlist_datasets import is_visible, playlist_rows
from iPodDB.library._resolved_write import FolderWrite
from iPodDB.library.writing import WriteIssue
from iPodDB.shared.chunk import DatabaseDocument


def folder_issues(
    document: DatabaseDocument[MhbdHeader], folders: tuple[FolderWrite, ...]
) -> tuple[WriteIssue, ...]:
    affected = {f.playlist_id: f for f in folders}
    issues: list[WriteIssue] = []
    for kind, selection in playlist_rows(document):
        chunk = selection.chunk
        folder = affected.get(chunk.header.playlist_id)
        if folder is None or not is_visible(kind, chunk.header):
            continue
        rules = next(
            (c for c in chunk.children if isinstance(c.payload, MhodSmartRulesPayload)),
            None,
        )
        if rules is None:
            continue
        assert isinstance(rules.payload, MhodSmartRulesPayload)
        messages: list[tuple[str, str]] = []
        if not isinstance(rules.prefix, MhodSmartRulesPrefix) or (
            len(rules.payload.rules) > 1 and rules.prefix.conjunction != 1
        ):
            messages.append(
                (
                    "playlist.folder_conjunction",
                    "The affected folder has an unsupported rule conjunction.",
                )
            )
        if any(
            r.field_id != 0x28
            or r.action_id != 1
            or not isinstance(r.data, MhodSmartNumericRuleData)
            for r in rules.payload.rules
        ):
            messages.append(
                (
                    "playlist.folder_rules",
                    "An affected folder has unsupported aggregate rules that cannot safely be replaced.",
                )
            )
        elif {
            r.data.from_value
            for r in rules.payload.rules
            if isinstance(r.data, MhodSmartNumericRuleData)
        } != set(folder.previous_child_ids):
            messages.append(
                (
                    "playlist.folder_relationship",
                    "The affected folder's saved rules disagree with its visible child relationships.",
                )
            )
        issues.extend(
            WriteIssue(
                code,
                message,
                phase="resolution",
                subject="playlist",
                record_id=folder.playlist_id,
                field="entries",
                detail=f"Dataset {kind}; retain this relationship or resolve the conflicting source rules.",
                offset=rules.offset,
            )
            for code, message in messages
        )
    return tuple(issues)
