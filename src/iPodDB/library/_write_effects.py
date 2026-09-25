"""Explain execution decisions through bounded references to requested changes."""

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_jump_table_mhod import (
    MhodLibraryJumpTablePrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.library._field_policy import BROWSE_FIELDS, PODCAST_FIELDS, changed_fields
from iPodDB.library._playlist_datasets import is_master, playlist_rows
from iPodDB.library._resolved_write import ResolvedWrite
from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.writing import LibraryChange, WriteChecksum, WriteEffect
from iPodDB.shared.chunk import DatabaseDocument


def compare_generated_values(
    requested: LibrarySnapshot, desired: LibrarySnapshot
) -> tuple[LibraryChange, ...]:
    result: list[LibraryChange] = []
    for subject, prior, after in (
        ("track", requested.tracks, desired.tracks),
        ("playlist", requested.playlists, desired.playlists),
    ):
        originals = {getattr(r, subject + "_id"): r for r in prior}
        for record in after:
            identity = getattr(record, subject + "_id")
            old = originals.get(identity)
            if record != old:
                result.append(
                    LibraryChange(
                        subject,
                        identity,
                        "add" if old is None else "edit",
                        getattr(record, "title" if subject == "track" else "name"),
                        changed_fields(old, record),
                    )
                )
    return tuple(result)


def describe_effects(
    document: DatabaseDocument[MhbdHeader],
    resolved: ResolvedWrite,
    generated_changes: tuple[LibraryChange, ...],
) -> tuple[WriteEffect, ...]:
    plan, original, desired = resolved.plan, resolved.original, resolved.desired
    changed, folders, podcasts = (
        resolved.changed_playlists,
        resolved.folders,
        resolved.podcast_playlists,
    )
    affected, structural, topology = (
        resolved.affected_datasets,
        resolved.structural_tracks,
        resolved.topology_changed,
    )
    indexes, target = resolved.indexes, plan.target
    effects: list[WriteEffect] = []
    ancestors: dict[int, set[int]] = {}
    for snapshot in (original, desired):
        parents = {p.playlist_id: p.parent_id for p in snapshot.playlists}
        for change_index, change in enumerate(plan.changes):
            if change.subject != "playlist" or (
                change.action == "edit"
                and not set(change.fields).intersection(
                    ("entries", "parent_id", "kind")
                )
            ):
                continue
            identity = change.record_id
            visited: set[int] = set()
            while (
                identity is not None and identity in parents and identity not in visited
            ):
                visited.add(identity)
                ancestors.setdefault(identity, set()).add(change_index)
                identity = parents[identity]
    browse_causes = tuple(
        i
        for i, c in enumerate(plan.changes)
        if (
            c.subject == "track"
            and (c.action != "edit" or BROWSE_FIELDS.intersection(c.fields))
        )
        or (c.subject == "library" and c.fields == ("tracks",))
    )
    podcast_causes = tuple(
        i
        for i, c in enumerate(plan.changes)
        if (
            c.subject == "track"
            and (c.action != "edit" or PODCAST_FIELDS.intersection(c.fields))
        )
        or (c.subject == "library" and c.fields == ("tracks",))
    )
    topology_causes = tuple(
        i
        for i, c in enumerate(plan.changes)
        if (c.subject == "playlist" and (c.action != "edit" or "parent_id" in c.fields))
        or (c.subject == "library" and c.fields == ("playlists",))
    )
    if resolved.generated_podcasts:
        topology_causes = tuple(sorted(set(topology_causes) | set(podcast_causes)))
    counterpart_causes = tuple(
        sorted(
            set(browse_causes)
            | (set(podcast_causes) if podcasts else set[int]())
            | {
                i
                for i, c in enumerate(plan.changes)
                if c.subject == "playlist"
                or (
                    c.subject == "library"
                    and c.fields in (("playlists",), ("device_name",))
                )
            }
        )
    )

    def effect(
        code: str,
        subject: str,
        identity: int | None,
        reason: str,
        fields: tuple[str, ...] = (),
        dataset: int | None = None,
    ) -> None:
        causes = tuple(
            i
            for i, c in enumerate(plan.changes)
            if c.subject == subject and (identity is None or c.record_id == identity)
        )
        if code == "artifact.signature":
            causes = tuple(range(len(plan.changes)))
        elif code == "library.browse_index":
            causes = (
                browse_causes or counterpart_causes
            )  # A new Master needs indexes too.
        elif code == "playlist.preorder":
            causes = topology_causes
        elif code in ("playlist.companion", "library.master"):
            causes = counterpart_causes
        elif code == "artwork.assets":
            causes = tuple(
                i
                for i, c in enumerate(plan.changes)
                if c.subject == "track"
                and (c.action != "edit" or "artwork_id" in c.fields)
            )
        elif code == "playlist.folder_aggregate":
            causes = (
                tuple(sorted(ancestors.get(identity, set())))
                if identity is not None
                else ()
            )
        elif subject == "playlist":
            if (
                identity in resolved.podcast_playlists
                or identity in resolved.generated_podcasts
            ):
                causes = tuple(sorted(set(causes) | set(podcast_causes)))
            elif identity is not None:
                causes = tuple(sorted(set(causes) | ancestors.get(identity, set())))
        effects.append(
            WriteEffect(code, subject, identity, reason, causes, fields, dataset)
        )

    for change in generated_changes:
        effect(
            "library.derived_values",
            change.subject,
            change.record_id,
            "Derive firmware membership, flags, or representable values from the requested edit.",
            change.fields,
        )
        if change.action == "add":
            effect(
                "library.native_identity",
                change.subject,
                change.record_id,
                "Allocate native identities and metadata for the generated record.",
            )
    for identity in sorted(changed):
        effect(
            "playlist.counterparts",
            "playlist",
            identity,
            "Apply this Playlist edit to established counterparts while retaining each dataset's private metadata.",
        )
    for folder in folders:
        effect(
            "playlist.folder_aggregate",
            "playlist",
            folder.playlist_id,
            "Rebuild descendant membership and direct-child rules.",
            ("entries", "parent_id"),
        )
    for identity in sorted(podcasts):
        effect(
            "playlist.podcast_groups",
            "playlist",
            identity,
            "Maintain contiguous podcast shows and native episode/group links.",
            ("entries",),
            3,
        )
    kinds = {s.chunk.header.dataset_type for s in document.find_chunks(MhsdHeader)}
    new_master = bool(affected.intersection((2, 3))) and 3 in kinds and 2 not in kinds
    if new_master:
        effect(
            "playlist.companion",
            "library",
            None,
            "Create the missing flat dataset 2 companion from dataset 3.",
            dataset=2,
        )
    if not kinds.intersection((2, 3)) and desired.playlists:
        new_master = True
    if structural or original.device_name != desired.device_name or new_master:
        effect(
            "library.master",
            "library",
            None,
            "Maintain Master membership, name, and required native browse structures.",
        )
    masters = tuple(
        row
        for kind, row in playlist_rows(document)
        if is_master(kind, row.chunk.header)
    )
    present_sorts = {
        c.prefix.sort_type
        for row in masters
        for c in row.chunk.children
        if isinstance(c.prefix, MhodLibraryIndexPrefix | MhodLibraryJumpTablePrefix)
    }
    for index in indexes:
        if (index.affected and index.sort_type in present_sorts) or (
            (new_master or (structural and masters))
            and index.sort_type in (3, 4, 5, 7, 0x12)
        ):
            effect(
                "library.browse_index",
                "library",
                None,
                f"Maintain browse order and alphabetical groups for sort type {index.sort_type}.",
            )
    album_index_fields = {
        "artist",
        "album_artist",
        "album",
        "show",
        "season_number",
        "track_number",
        "metadata.sort_artist",
        "metadata.sort_album_artist",
        "metadata.sort_album",
        "metadata.disc_number",
        "metadata.compilation",
    }
    if 36 in present_sorts and (
        structural
        or any(album_index_fields.intersection(c.fields) for c in plan.changes)
    ):
        effect(
            "library.browse_index",
            "library",
            None,
            "Maintain sort type 36's native album traversal and Master Playlist positions.",
        )
    if topology:
        effect(
            "playlist.preorder",
            "library",
            None,
            "Store visible Playlists in folder preorder.",
            ("playlists",),
        )
    for change in plan.changes:
        if change.subject == "media":
            effect(
                "media.replacement",
                "media",
                change.record_id,
                "Apply and independently verify supplied native codec facts for replacement content; retain its captured file dependency and the Track's identity.",
            )
        if change.subject == "library" and change.fields == ("tracks",):
            effect(
                "library.browse_groups",
                "library",
                None,
                "Refresh shared album metadata selected in Library Track order.",
                ("tracks",),
            )
        if change.subject == "track":
            if change.action == "delete" or "artwork_id" in change.fields:
                effect(
                    "artwork.ownership",
                    "track",
                    change.record_id,
                    "Reconcile both directions of artwork ownership; retain existing image ranges and photo data.",
                    ("artwork_id", "metadata.artwork_count"),
                )
            if change.action != "edit" or set(change.fields).intersection(
                (
                    "album",
                    "album_artist",
                    "artist",
                    "metadata.compilation",
                    "show",
                    "season_number",
                    "metadata.composer",
                    "metadata.sort_album_artist",
                    "metadata.sort_artist",
                    "metadata.podcast_rss_url",
                )
            ):
                effect(
                    "library.browse_groups",
                    "track",
                    change.record_id,
                    "Maintain affected album, artist, composer, and representative Track relationships.",
                )
            if change.action == "delete":
                effect(
                    "playlist.hidden_references",
                    "track",
                    change.record_id,
                    "Remove deleted Track references from hidden playlists while preserving their metadata.",
                )
        if change.action == "add":
            effect(
                "library.native_identity",
                change.subject,
                change.record_id,
                "Allocate collision-free native identities and required new-record metadata.",
            )
    for identity in plan.required_lyrics:
        effect(
            "media.lyrics",
            "track",
            identity,
            "Verify embedded lyrics independently of full metadata tagging; derive the resulting file size and publish the media with the database.",
            ("metadata.lyrics", "metadata.has_lyrics", "size_bytes"),
        )
    if plan.required_artwork or plan.requires_artwork_inventory:
        effect(
            "artwork.assets",
            "library",
            None,
            "Verify supplied artwork resources and append encoded covers to retained file prefixes; establish sizes and identities during asset preparation.",
        )
    if plan.changes_itunes and target.checksum is not WriteChecksum.NONE:
        effect(
            "artifact.signature",
            "library",
            None,
            "Finalize the required iTunesDB signature after serialization.",
        )
    return tuple(effects)
