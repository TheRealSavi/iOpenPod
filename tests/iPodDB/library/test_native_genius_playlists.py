"""Canonical Genius Playlist classification and bounded semantic editing."""

import struct
from dataclasses import replace

import pytest
from tests.iPodDB.binary_fixtures import parse_mhod
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.genius_seed_mhod import (
    MhodGeniusSeedFields,
    MhodGeniusSeedPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_prefs_mhod import (
    MhodSmartPrefsPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartRulesPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodPayloadKind
from iPodDB.iTunesDB.writer.mhod_encoder import encode_mhod_body
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    IPodLibrary,
    Playlist,
    PlaylistKind,
    SmartPlaylist,
    _write_preparation,
)
from iPodDB.library._smart_writing import smart_chunks
from iPodDB.library.writing import WriteResources
from iPodDB.shared.chunk import DatabaseDocument


def genius_library(*seeds: bytes, include_smart: bool = True) -> IPodLibrary:
    """Add independently encoded MHOD 54 to both retained native counterparts."""

    document = parse_iTunesDB(library(mirrored=True).serialize().itunes)
    smart = smart_chunks(SmartPlaylist(), ()) if include_smart else ()
    if smart:
        # Native Genius carries Smart bodies with private preference bytes.
        prefs = smart[0].prefix_as(MhodSmartPrefsPrefix)
        smart = (
            replace(
                smart[0],
                prefix=replace(
                    prefs,
                    attachment_inhibit=1,
                    padding_0x27=b"\x00\x05\x00" + prefs.padding_0x27[3:],
                ),
            ),
            smart[1],
        )
    metadata = (*smart, *(parse_mhod(54, seed) for seed in seeds))
    for row in document.find_chunks(MhypHeader):
        if row.chunk.header.playlist_id == 10:
            document = document.replace_chunk(
                row, replace(row.chunk, children=(*metadata, *row.chunk.children))
            )
    return IPodLibrary(write_iTunesDB(document))


def _native_genius_bytes(data: bytes) -> tuple[bytes, ...]:
    return tuple(
        row.chunk.raw_header + row.chunk.raw_body
        for playlist in parse_iTunesDB(data).find_chunks(MhypHeader)
        if playlist.chunk.header.playlist_id == 10
        for row in playlist.find_chunks(MhodHeader)
        if row.chunk.header.mhod_type in (50, 51, 54)
    )


@pytest.mark.parametrize("include_smart", (False, True))
def test_native_marker_classifies_genius_with_persistent_seed(
    include_smart: bool,
) -> None:
    source = genius_library(struct.pack("<Q", 101), include_smart=include_smart)
    playlist = source.snapshot.playlists[0]
    assert playlist.kind is PlaylistKind.GENIUS
    assert playlist.smart is None
    assert playlist.genius_seed_persistent_id == 101
    assert playlist.track_ids == (1, 2, 1)


def test_title_and_smart_rules_are_not_genius_markers() -> None:
    source = genius_library()
    playlist = source.snapshot.playlists[0]
    assert playlist.kind is PlaylistKind.SMART
    assert playlist.smart is not None
    assert playlist.genius_seed_persistent_id is None


@pytest.mark.parametrize("seed", (b"", b"\x01", bytes(7), bytes(9), bytes(8)))
def test_unavailable_seed_still_prevents_smart_classification(seed: bytes) -> None:
    source = genius_library(seed)
    original = source.serialize().itunes
    assert source.snapshot.playlists[0].kind is PlaylistKind.GENIUS
    assert source.snapshot.playlists[0].genius_seed_persistent_id is None
    result = source.prepare(source.analyze(source.begin_draft()))
    assert result.prepared is not None, result.issues
    assert result.prepared.itunes == original


def test_conflicting_duplicate_seeds_do_not_choose_an_arbitrary_track() -> None:
    source = genius_library(struct.pack("<Q", 101), struct.pack("<Q", 102))
    assert source.snapshot.playlists[0].kind is PlaylistKind.GENIUS
    assert source.snapshot.playlists[0].genius_seed_persistent_id is None


@pytest.mark.parametrize("seed", (struct.pack("<Q", 101), b"future layout"))
@pytest.mark.parametrize("edit", ("title", "track"))
def test_ordinary_edits_retain_genius_and_smart_bodies_exactly(
    seed: bytes, edit: str
) -> None:
    source = genius_library(seed)
    original = source.serialize().itunes
    snapshot = source.snapshot
    if edit == "title":
        desired = replace(
            snapshot,
            playlists=(replace(snapshot.playlists[0], name="Renamed"),),
        )
    else:
        track = snapshot.tracks[0]
        desired = replace(
            snapshot,
            tracks=(replace(track, title="Renamed Track"), *snapshot.tracks[1:]),
        )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert _native_genius_bytes(result.prepared.itunes) == _native_genius_bytes(
        original
    )
    checked = IPodLibrary(result.prepared.itunes).snapshot.playlists[0]
    assert checked.kind is PlaylistKind.GENIUS
    assert checked.track_ids == (1, 2, 1)


def test_ordinary_semantic_path_cannot_create_genius_playlist() -> None:
    source = library()
    desired = replace(
        source.snapshot,
        playlists=(
            *source.snapshot.playlists,
            Playlist(-1, "New", PlaylistKind.GENIUS),
        ),
    )
    plan = source.analyze(source.begin_draft(desired))
    assert plan.blocked
    assert "playlist.genius_creation" in {issue.code for issue in plan.issues}


@pytest.mark.parametrize("kind", (PlaylistKind.PLAYLIST, PlaylistKind.SMART))
@pytest.mark.parametrize("to_genius", (False, True))
def test_ordinary_semantic_path_cannot_convert_genius_kind(
    kind: PlaylistKind, to_genius: bool
) -> None:
    source = (
        genius_library()
        if to_genius and kind is PlaylistKind.SMART
        else library()
        if to_genius
        else genius_library(struct.pack("<Q", 101))
    )
    changed = replace(
        source.snapshot.playlists[0],
        kind=PlaylistKind.GENIUS if to_genius else kind,
        smart=SmartPlaylist() if not to_genius and kind is PlaylistKind.SMART else None,
    )
    desired = replace(source.snapshot, playlists=(changed,))
    plan = source.analyze(source.begin_draft(desired))
    assert plan.blocked
    assert "playlist.genius_kind" in {issue.code for issue in plan.issues}


@pytest.mark.parametrize("edit", ("seed", "membership"))
def test_native_seed_and_manual_membership_edits_are_rejected(edit: str) -> None:
    source = genius_library(struct.pack("<Q", 101))
    playlist = source.snapshot.playlists[0]
    changed = (
        replace(playlist, genius_seed_persistent_id=102)
        if edit == "seed"
        else replace(playlist, entries=playlist.entries[:1])
    )
    desired = replace(source.snapshot, playlists=(changed,))
    plan = source.analyze(source.begin_draft(desired))
    assert plan.blocked
    assert f"playlist.genius_{edit}" in {issue.code for issue in plan.issues}


@pytest.mark.parametrize("seed", (struct.pack("<Q", 101), b"future layout"))
def test_track_deletion_can_prune_native_genius_membership(seed: bytes) -> None:
    source = genius_library(seed)
    playlist = source.snapshot.playlists[0]
    desired = replace(
        source.snapshot,
        tracks=source.snapshot.tracks[:1],
        playlists=(
            replace(
                playlist,
                entries=tuple(e for e in playlist.entries if e.track_id != 2),
            ),
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired, delete_omissions=True)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.playlists[0].track_ids == (1, 1)
    assert _native_genius_bytes(result.prepared.itunes) == _native_genius_bytes(
        source.serialize().itunes
    )


def test_known_native_genius_seed_deletion_keeps_members_and_reseeds_counterparts() -> (
    None
):
    source = genius_library(struct.pack("<Q", 101))
    playlist = source.snapshot.playlists[0]
    desired = replace(
        source.snapshot,
        tracks=source.snapshot.tracks[1:],
        playlists=(replace(playlist, entries=playlist.entries[1:2]),),
    )
    plan = source.analyze(source.begin_draft(desired, delete_omissions=True))
    assert not plan.blocked
    result = source.prepare(plan, WriteResources(pending_playback_sidecars=False))
    assert result.prepared is not None, result.issues
    saved = result.prepared.snapshot.playlists[0]
    assert saved.playlist_id == playlist.playlist_id
    assert saved.name == playlist.name
    assert saved.track_ids == (2,)
    assert saved.genius_seed_persistent_id == 102
    original_metadata = _native_genius_bytes(source.serialize().itunes)
    final_metadata = _native_genius_bytes(result.prepared.itunes)
    assert len(original_metadata) == len(final_metadata)
    for before, after in zip(original_metadata, final_metadata, strict=True):
        if before.endswith(struct.pack("<Q", 101)):
            assert after == before[:-8] + struct.pack("<Q", 102)
        else:
            assert after == before


def test_track_deletion_removes_a_newly_empty_genius_playlist() -> None:
    source = genius_library(struct.pack("<Q", 101))
    desired = replace(source.snapshot, tracks=())
    draft = source.begin_draft(desired, delete_omissions=True)
    assert not draft.snapshot.playlists
    result = source.prepare(
        source.analyze(draft), WriteResources(pending_playback_sidecars=False)
    )
    assert result.prepared is not None, result.issues
    assert not result.prepared.snapshot.playlists


def test_seed_deletion_can_explicitly_remove_its_native_genius_playlist() -> None:
    source = genius_library(struct.pack("<Q", 101))
    desired = replace(source.snapshot, tracks=source.snapshot.tracks[1:], playlists=())
    result = source.prepare(
        source.analyze(source.begin_draft(desired, delete_omissions=True)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    assert not result.prepared.snapshot.playlists


def test_already_dangling_captured_seed_does_not_block_noop() -> None:
    source = genius_library(struct.pack("<Q", 999))
    original = source.serialize()
    result = source.prepare(source.analyze(source.begin_draft()))
    assert result.prepared is not None, result.issues
    assert result.prepared.itunes == original.itunes


def test_seed_codec_uses_shared_little_endian_u64_definition() -> None:
    chunk = parse_mhod(54, bytes.fromhex("0807060504030201"))
    assert chunk.payload_as(MhodGeniusSeedPayload).seed == MhodGeniusSeedFields(
        seed_track_persistent_id=0x0102030405060708
    )
    changed = replace(
        chunk,
        payload=MhodGeniusSeedPayload(MhodGeniusSeedFields(0xFEDCBA9876543210)),
    )
    encoded, _ = encode_mhod_body(changed, MhodPayloadKind.GENIUS_SEED)
    assert encoded == bytes.fromhex("1032547698badcfe")


@pytest.mark.parametrize("body", (b"", b"short", bytes(9), b"future layout"))
def test_unknown_seed_body_has_exact_inverse(body: bytes) -> None:
    chunk = parse_mhod(54, body)
    assert chunk.payload_as(MhodGeniusSeedPayload).seed is None
    encoded, _ = encode_mhod_body(chunk, MhodPayloadKind.GENIUS_SEED)
    assert encoded == body


@pytest.mark.parametrize(
    "change",
    (
        "remove_seed",
        "duplicate_seed",
        "seed_body",
        "seed_header",
        "smart_preferences",
        "smart_rules",
        "unknown_seed_body",
    ),
)
def test_verification_withholds_tampered_native_genius_payloads(
    change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = genius_library(
        b"future layout" if change == "unknown_seed_body" else struct.pack("<Q", 101)
    )
    original = source.serialize()
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], title="Changed"),
            *source.snapshot.tracks[1:],
        ),
    )
    tampered = False

    def corrupt_once(document: DatabaseDocument[MhbdHeader]) -> bytes:
        nonlocal tampered
        if tampered:
            return write_iTunesDB(document)
        tampered = True
        playlist = next(
            row
            for row in document.find_chunks(MhypHeader)
            if row.chunk.header.playlist_id == 10
        )
        mhod_type = (
            50
            if change == "smart_preferences"
            else 51
            if change == "smart_rules"
            else 54
        )
        index = next(
            i
            for i, child in enumerate(playlist.chunk.children)
            if isinstance(child.header, MhodHeader)
            and child.header.mhod_type == mhod_type
        )
        child = playlist.chunk.child_as(index, MhodHeader)
        children = list(playlist.chunk.children)
        if change == "remove_seed":
            del children[index]
        elif change == "duplicate_seed":
            children.insert(index, child)
        elif change == "seed_header":
            children[index] = replace(
                child, header=replace(child.header, unk_mhod_0x10=999)
            )
        elif change == "smart_preferences":
            prefix = child.prefix_as(MhodSmartPrefsPrefix)
            children[index] = replace(
                child,
                prefix=replace(prefix, attachment_inhibit=255),
            )
        elif change == "smart_rules":
            prefix_rules = child.prefix_as(MhodSmartRulesPrefix)
            children[index] = replace(
                child, prefix=replace(prefix_rules, format_version=0, unknown_0x1E=999)
            )
        else:
            children[index] = replace(
                child,
                payload=MhodGeniusSeedPayload(unknown_data=b"changed future layout")
                if change == "unknown_seed_body"
                else MhodGeniusSeedPayload(seed=MhodGeniusSeedFields(102)),
            )
        changed = document.replace_chunk(
            playlist, replace(playlist.chunk, children=tuple(children))
        )
        return write_iTunesDB(changed)

    monkeypatch.setattr(_write_preparation, "write_iTunesDB", corrupt_once)
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None
    assert "verification.playlist_genius_payloads" in {
        issue.code for issue in result.issues
    }
    assert source.serialize() == original
