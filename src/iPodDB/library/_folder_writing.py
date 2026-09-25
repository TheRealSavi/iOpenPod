"""Maintain folder aggregates, child rules, and physical preorder after hierarchy edits."""

from dataclasses import replace

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartNumericRuleData,
    MhodSmartRule,
    MhodSmartRulesPayload,
    MhodSmartRulesPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.library._document_edit import rebuild
from iPodDB.library._playlist_datasets import is_visible, playlist_rows
from iPodDB.library._playlist_writing import position_item
from iPodDB.library._resolved_write import ResolvedWrite
from iPodDB.library._smart_writing import smart_chunks
from iPodDB.library.playlists import SmartPlaylist
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk, chunk_as


def reconcile_folders(
    document: DatabaseDocument[MhbdHeader],
    resolved: ResolvedWrite,
    playlist_ids: dict[int, int],
    track_ids: dict[int, int],
    persistent_ids: dict[int, int],
) -> DatabaseDocument[MhbdHeader]:
    folders = {f.playlist_id: f for f in resolved.folders}
    inverse = {native: draft for draft, native in playlist_ids.items()}
    replacements: dict[int, ParsedChunk[ChunkHeader] | None] = {}
    for kind, selection in playlist_rows(document):
        chunk = selection.chunk
        if not is_visible(kind, chunk.header):
            continue
        identity = inverse.get(chunk.header.playlist_id)
        folder = folders.get(identity) if identity is not None else None
        if folder is None or not chunk.header.playlist_kind_flags & 0x100:
            continue
        old_items = {
            s.chunk.header.track_id: s.chunk for s in selection.find_chunks(MhipHeader)
        }
        metadata = tuple(
            chunk_as(c, MhodHeader)
            for c in chunk.children
            if isinstance(c.header, MhodHeader)
        )
        rules_row = next(
            (c for c in metadata if isinstance(c.payload, MhodSmartRulesPayload)), None
        )
        if rules_row is None:
            rules_row = new_itunes_chunk(
                MHOD,
                MhodHeader(mhod_type=51),
                prefix=MhodSmartRulesPrefix(magic=b"SLst", unk_0x1C=0x10001),
                payload=MhodSmartRulesPayload((), b""),
            )
        assert isinstance(rules_row.prefix, MhodSmartRulesPrefix) and isinstance(
            rules_row.payload, MhodSmartRulesPayload
        )
        rules = tuple(
            MhodSmartRule(
                0x28,
                1,
                0,
                bytes(40),
                MhodSmartNumericRuleData(
                    playlist_ids[child_id],
                    0,
                    1,
                    playlist_ids[child_id],
                    0,
                    1,
                    0,
                    0,
                    0,
                    0,
                    0,
                    b"",
                ),
            )
            for child_id in folder.child_ids
        )
        retained_rules = {
            r.data.from_value: r
            for r in rules_row.payload.rules
            if isinstance(r.data, MhodSmartNumericRuleData)
        }
        rules = tuple(
            retained_rules.get(r.data.from_value, r)
            if isinstance(r.data, MhodSmartNumericRuleData)
            else r
            for r in rules
        )
        rules_row = replace(
            rules_row,
            prefix=replace(rules_row.prefix, conjunction=1),
            payload=replace(rules_row.payload, rules=rules),
        )
        output_children = [
            c for c in chunk.children if not isinstance(c.header, MhipHeader)
        ]
        rule_position = next(
            (
                i
                for i, c in enumerate(output_children)
                if isinstance(c.header, MhodHeader) and c.header.mhod_type == 51
            ),
            None,
        )
        if rule_position is None:
            output_children.append(rules_row)
        else:
            output_children[rule_position] = rules_row
        if not any(c.header.mhod_type == 50 for c in metadata):
            output_children.append(smart_chunks(SmartPlaylist(), ())[0])
        for position, track_id in enumerate(folder.track_ids):
            native_id = track_ids[track_id]
            item = old_items.get(native_id) or new_itunes_chunk(
                MHIP,
                MhipHeader(
                    track_id=native_id, track_persistent_id=persistent_ids[track_id]
                ),
            )
            output_children.append(position_item(item, position))
        replacements[id(chunk)] = replace(chunk, children=tuple(output_children))
    document = rebuild(document, replacements)
    if resolved.topology_changed:
        for dataset in document.find_chunks(MhsdHeader):
            if dataset.chunk.header.dataset_type not in (2, 3):
                continue
            container = dataset.chunk.children[0]
            visible = {
                c.header.playlist_id: c
                for c in container.children
                if isinstance(c.header, MhypHeader)
                and is_visible(dataset.chunk.header.dataset_type, c.header)
                and c.header.playlist_id in inverse
            }
            order = iter(
                visible[playlist_ids[identity]]
                for identity in resolved.playlist_order
                if playlist_ids[identity] in visible
            )
            reordered = tuple(
                next(order)
                if isinstance(c.header, MhypHeader) and c.header.playlist_id in visible
                else c
                for c in container.children
            )
            document = document.replace_chunk(
                dataset,
                replace(
                    dataset.chunk, children=(replace(container, children=reordered),)
                ),
            )
    return document
