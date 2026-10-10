"""Public preparation behavior, including preservation and failure isolation."""

import hashlib
from dataclasses import replace

import pytest

from iPodDB.ArtworkDB.ithmb import (
    DecodedImage,
    IthmbLayout,
    IthmbPixelFormat,
    decode_ithmb,
)
from iPodDB.ArtworkDB.ithmb_writer import encode_ithmb
from iPodDB.iTunesDB.builder.build_iTunesDB import (
    new_itunes_chunk,
    new_iTunesDB,
    new_string_mhod,
)
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import DEFINITION as MHIT
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhlp import DEFINITION as MHLP
from iPodDB.iTunesDB.shared.chunk_defs.mhlt import DEFINITION as MHLT
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import DEFINITION as MHYP
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.signature import (
    sign_hash58,
    sign_hash72,
    verify_hash58,
    verify_hash72,
)
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    ArtworkPixels,
    CoverFormat,
    IPodLibrary,
    Playlist,
    PlaylistEntry,
    PlaylistKind,
    PlaylistSortOrder,
    SmartField,
    SmartOperator,
    SmartPlaylist,
    SmartRule,
    SmartRuleGroup,
    Track,
    order_playlist_entries,
)
from iPodDB.library.writing import (
    ArtworkAsset,
    FileDependency,
    PreparedMedia,
    SourceFile,
    WriteChecksum,
    WriteResources,
    WriteTarget,
)
from iPodDB.shared.chunk import EmptyChunkHeader, ParsedChunk, RawPayload


def library(*, mirrored: bool = False, conflicting: bool = False) -> IPodLibrary:
    tracks = tuple(
        new_itunes_chunk(
            MHIT,
            MhitHeader(track_id=i, db_track_id=100 + i, length=1000, media_type=1),
            children=(
                new_string_mhod(MhodType.TITLE, "Earlier title"),
                new_string_mhod(MhodType.TITLE, f"Track {i}"),
            ),
        )
        for i in (1, 2)
    )
    playlist = new_itunes_chunk(
        MHYP,
        MhypHeader(playlist_id=10, unk_mhyp_0x38=987),
        children=(
            new_string_mhod(MhodType.TITLE, "Playlist"),
            *(
                new_itunes_chunk(
                    MHIP,
                    MhipHeader(
                        track_id=i, timestamp=200 + n, mhip_persistent_id=300 + n
                    ),
                )
                for n, i in enumerate((1, 2, 1))
            ),
        ),
    )
    master = new_itunes_chunk(
        MHYP,
        MhypHeader(playlist_id=1000, master_flag=1),
        children=(new_string_mhod(MhodType.TITLE, "My iPod"),),
    )
    dataset = new_itunes_chunk(
        MHSD,
        MhsdHeader(dataset_type=3),
        children=(
            new_itunes_chunk(MHLP, EmptyChunkHeader(), children=(master, playlist)),
        ),
    )
    datasets: tuple[ParsedChunk[MhsdHeader], ...] = (
        new_itunes_chunk(
            MHSD,
            MhsdHeader(dataset_type=1),
            children=(new_itunes_chunk(MHLT, EmptyChunkHeader(), children=tracks),),
        ),
        dataset,
        new_itunes_chunk(
            MHSD,
            MhsdHeader(dataset_type=999),
            payload=RawPayload(b"unknown dataset must survive"),
        ),
    )
    if mirrored:
        counterpart = (
            replace(
                playlist,
                children=(
                    new_string_mhod(MhodType.TITLE, "Conflict"),
                    *playlist.children[1:],
                ),
            )
            if conflicting
            else playlist
        )
        datasets += (
            new_itunes_chunk(
                MHSD,
                MhsdHeader(dataset_type=2),
                children=(
                    new_itunes_chunk(
                        MHLP, EmptyChunkHeader(), children=(master, counterpart)
                    ),
                ),
            ),
        )
    return IPodLibrary(write_iTunesDB(new_iTunesDB(MhbdHeader(), datasets=datasets)))


@pytest.mark.parametrize("delete_omissions", [False, True])
def test_unchanged_and_reverted_drafts_are_byte_exact_and_source_bound(
    delete_omissions: bool,
) -> None:
    source = library()
    draft = source.begin_draft(delete_omissions=delete_omissions)
    result = source.prepare(source.analyze(draft))
    assert result.prepared is not None, result.issues
    assert result.prepared.itunes == source.serialize().itunes
    other = library()
    assert other.prepare(other.analyze(draft)).prepared is None
    assert other.analyze(draft).issues[0].code == "draft.wrong_source"


@pytest.mark.parametrize("excess_bytes", [0, 1])
def test_database_write_limit_includes_exact_boundary(excess_bytes: int) -> None:
    source = library()
    desired = replace(source.snapshot, device_name="Renamed iPod")
    draft = source.begin_draft(desired)
    baseline = source.prepare(source.analyze(draft))
    assert baseline.prepared is not None
    limit = len(baseline.prepared.itunes) - excess_bytes

    result = source.prepare(
        source.analyze(draft, target=WriteTarget(max_database_bytes=limit))
    )

    assert (result.prepared is None) == bool(excess_bytes), result.issues
    if excess_bytes:
        assert any(
            "Your iPod's hardware can only support up to " in issue.message
            and "MB in its database." in issue.message
            for issue in result.issues
        )


def test_selective_title_edit_retains_duplicate_metadata_unknown_dataset_and_source() -> (
    None
):
    source = library()
    original = source.serialize().itunes
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], title="Edited"),
            source.snapshot.tracks[1],
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.tracks[0].title == "Edited"
    assert b"unknown dataset must survive" in result.prepared.itunes
    assert "Earlier title".encode("utf-16-le") in result.prepared.itunes
    assert source.serialize().itunes == original


def test_duplicate_occurrence_reorder_preserves_each_items_private_metadata() -> None:
    source = library()
    playlist = source.snapshot.playlists[0]
    reordered = replace(
        playlist,
        entries=(playlist.entries[2], playlist.entries[0], playlist.entries[1]),
    )
    desired = replace(source.snapshot, playlists=(reordered,))
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    dataset = next(
        s
        for s in parse_iTunesDB(result.prepared.itunes).find_chunks(MhsdHeader)
        if s.chunk.header.dataset_type == 3
    )
    rows = dataset.find_chunks(MhipHeader)
    assert tuple(row.chunk.header.timestamp for row in rows) == (202, 200, 201)
    assert tuple(row.chunk.header.mhip_persistent_id for row in rows) == (302, 300, 301)


def test_sort_order_change_reorders_occurrences_and_writes_fresh_positions() -> None:
    source = library()
    playlist = source.snapshot.playlists[0]
    entries = order_playlist_entries(
        playlist.entries,
        source.snapshot.tracks,
        PlaylistSortOrder.TITLE,
    )
    desired = replace(
        source.snapshot,
        playlists=(
            replace(
                playlist,
                sort_order=PlaylistSortOrder.TITLE,
                entries=entries,
            ),
        ),
    )

    result = source.prepare(source.analyze(source.begin_draft(desired)))

    assert result.prepared is not None, result.issues
    document = parse_iTunesDB(result.prepared.itunes)
    playlist_row = next(
        row
        for dataset in document.find_chunks(MhsdHeader)
        if dataset.chunk.header.dataset_type == 3
        for row in dataset.find_chunks(MhypHeader)
        if not row.chunk.header.master_flag
    )
    items = playlist_row.find_chunks(MhipHeader)
    assert playlist_row.chunk.header.sort_order == PlaylistSortOrder.TITLE
    assert tuple(item.chunk.header.track_id for item in items) == (1, 1, 2)
    assert tuple(
        next(
            child.prefix.position
            for child in item.chunk.children
            if isinstance(child.prefix, MhodPlaylistPositionPrefix)
        )
        for item in items
    ) == (0, 1, 2)
    assert result.prepared.snapshot.playlists[0].sort_order is PlaylistSortOrder.TITLE
    assert tuple(
        entry.position for entry in result.prepared.snapshot.playlists[0].entries
    ) == (0, 1, 2)


@pytest.mark.parametrize("conflicting", [False, True])
def test_dataset_mirrors_are_checked_before_edits(conflicting: bool) -> None:
    source = library(mirrored=True, conflicting=conflicting)
    desired = replace(
        source.snapshot,
        playlists=(replace(source.snapshot.playlists[0], name="Renamed"),),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert (result.prepared is None) == conflicting, result.issues
    if conflicting:
        assert any(issue.code == "playlist.ambiguous_mirror" for issue in result.issues)


def test_multiple_errors_reject_whole_candidate_and_keep_draft() -> None:
    source = library()
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, rating=999) for t in source.snapshot.tracks),
        playlists=(
            replace(
                source.snapshot.playlists[0], entries=(PlaylistEntry("missing", 99),)
            ),
        ),
    )
    draft = source.begin_draft(desired)
    result = source.prepare(source.analyze(draft))
    assert result.prepared is None
    assert len(result.issues) >= 3
    assert draft.snapshot is desired
    assert source.snapshot.tracks[0].rating == 0


def test_omissions_are_blocked_by_default_even_if_plan_errors_are_removed() -> None:
    source = library()
    original = source.serialize()
    desired = replace(
        source.snapshot,
        tracks=(replace(source.snapshot.tracks[0], title="An independent edit"),),
        playlists=(),
    )
    draft = source.begin_draft(desired)
    plan = source.analyze(draft)
    assert {
        (issue.subject, issue.record_id)
        for issue in plan.issues
        if issue.code == "draft.deletion_not_enabled"
    } == {("track", 2), ("playlist", 10)}
    assert plan.blocked
    for submitted in (plan, replace(plan, issues=())):
        result = source.prepare(
            submitted, WriteResources(pending_playback_sidecars=False)
        )
        assert result.prepared is None
        assert any(i.code == "draft.deletion_not_enabled" for i in result.issues)
    assert draft.snapshot is desired
    assert source.serialize() == original


@pytest.mark.parametrize("mirrored", [False, True])
def test_explicit_omission_deletion_removes_playlists_and_preserves_hidden_records(
    mirrored: bool,
) -> None:
    source = library(mirrored=mirrored)
    original = source.serialize()
    desired = replace(source.snapshot, playlists=())
    draft = source.begin_draft(desired, delete_omissions=True)
    result = source.prepare(source.analyze(draft))
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.playlists == ()
    assert result.prepared.snapshot.tracks == source.snapshot.tracks
    native = parse_iTunesDB(result.prepared.itunes).find_chunks(MhypHeader)
    assert len(native) == 2
    assert all(p.chunk.header.master_flag for p in native)
    assert b"unknown dataset must survive" in result.prepared.itunes
    assert source.serialize() == original
    assert not source.begin_draft(desired).delete_omissions


def test_omission_opt_in_does_not_allow_dangling_playlist_references() -> None:
    source = library()
    desired = replace(source.snapshot, tracks=source.snapshot.tracks[:1])
    result = source.prepare(
        source.analyze(source.begin_draft(desired, delete_omissions=True)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is None
    assert any(i.code == "playlist.missing_track" for i in result.issues)
    assert not any(i.code == "draft.deletion_not_enabled" for i in result.issues)


def test_removing_playlist_entries_does_not_require_record_deletion_opt_in() -> None:
    source = library()
    playlist = source.snapshot.playlists[0]
    desired = replace(
        source.snapshot, playlists=(replace(playlist, entries=playlist.entries[:1]),)
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.tracks == source.snapshot.tracks
    assert result.prepared.snapshot.playlists[0].track_ids == (1,)


def test_omission_deletes_tracks_only_with_consistent_membership_and_sidecar_context() -> (
    None
):
    source = library()
    playlist = source.snapshot.playlists[0]
    desired = replace(
        source.snapshot,
        tracks=source.snapshot.tracks[:1],
        playlists=(
            replace(
                playlist, entries=tuple(e for e in playlist.entries if e.track_id == 1)
            ),
        ),
    )
    plan = source.analyze(source.begin_draft(desired, delete_omissions=True))
    assert any(c.action == "delete" and c.subject == "track" for c in plan.changes)
    assert source.prepare(plan).prepared is None
    result = source.prepare(plan, WriteResources(pending_playback_sidecars=False))
    assert result.prepared is not None, result.issues
    assert len(result.prepared.snapshot.tracks) == 1


def test_new_track_requires_media_and_returns_native_identity_mapping() -> None:
    source = library()
    track = Track(
        -1,
        "New",
        "",
        "",
        1000,
        size_bytes=4,
        metadata=replace(
            source.snapshot.tracks[0].metadata,
            location="iPod_Control/Music/F00/new.mp3",
            sample_rate_hz=44100,
            file_format="MP3 audio file",
        ),
    )
    desired = replace(source.snapshot, tracks=(*source.snapshot.tracks, track))
    plan = source.analyze(source.begin_draft(desired))
    assert source.prepare(plan).prepared is None
    media = PreparedMedia(
        -1,
        FileDependency(track.metadata.location, 4, hashlib.sha256(b"test").hexdigest()),
        filetype=int.from_bytes(b"MP3 ", "big"),
        mp3_flag=1,
        audio_format_flag=0,
        mpeg_audio_type=0,
        gapless_audio_payload_size=0,
    )
    result = source.prepare(
        plan, WriteResources(media=(media,), pending_playback_sidecars=False)
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.tracks[-1].track_id > 0
    assert result.prepared.retained_files == (media.file,)
    assert any(
        m.subject == "track" and m.draft_id == -1 for m in result.prepared.identities
    )
    conflict = source.prepare(
        plan,
        WriteResources(
            media=(media,),
            file_inventory=(replace(media.file, sha256="00" * 32),),
            pending_playback_sidecars=False,
        ),
    )
    assert conflict.prepared is None
    assert any(issue.code == "resources.conflicting_file" for issue in conflict.issues)


def test_new_folder_and_supported_smart_rules_prepare_without_enabling_ui_mutations() -> (
    None
):
    source = library()
    folder = Playlist(-1, "Folder", PlaylistKind.FOLDER)
    smart = Playlist(
        -2,
        "Smart",
        PlaylistKind.SMART,
        parent_id=-1,
        smart=SmartPlaylist(
            rules=SmartRuleGroup(
                rules=(SmartRule(SmartField.TITLE, SmartOperator.CONTAINS, "Track"),)
            )
        ),
    )
    desired = replace(
        source.snapshot, playlists=(*source.snapshot.playlists, folder, smart)
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert len(result.prepared.snapshot.playlists) == 3


@pytest.mark.parametrize("kind", tuple(IthmbPixelFormat))
def test_cover_encoder_roundtrips_layout_and_color(kind: IthmbPixelFormat) -> None:
    pixels = DecodedImage(4, 4, bytes((255, 0, 0)) * 16)
    stride = 4 if kind is IthmbPixelFormat.I420_LE else 8
    layout = IthmbLayout(4, 4, stride, kind)
    result = decode_ithmb(encode_ithmb(pixels, layout), layout)
    assert (result.width, result.height) == (4, 4)
    assert result.pixels[0] > 240 and result.pixels[1] < 10 and result.pixels[2] < 10


def test_artwork_output_preserves_file_prefix_and_clears_both_links() -> None:
    source = library()
    cover = CoverFormat(1055, 4, 4, 8, IthmbPixelFormat.RGB565_LE)
    target = WriteTarget(cover_formats=(cover,), artwork_root_value=2)
    asset = ArtworkAsset(-1, ArtworkPixels(4, 4, bytes((255, 0, 0)) * 16))
    prefix = b"untouched prefix"
    dependency = FileDependency(
        "iPod_Control/Artwork/F1055_1.ithmb",
        len(prefix),
        hashlib.sha256(prefix).hexdigest(),
    )
    resources = WriteResources(
        artwork=(asset,),
        file_inventory=(dependency,),
        files=(SourceFile(dependency, prefix),),
    )
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], artwork_id=-1),
            source.snapshot.tracks[1],
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), target), resources
    )
    assert result.prepared is not None, result.issues
    data = result.prepared.artwork_files[0].data
    assert isinstance(data, bytes)
    assert data.startswith(prefix)
    assert result.prepared.artwork is not None
    reread = IPodLibrary(result.prepared.itunes).with_artwork(result.prepared.artwork)
    cleared = replace(
        reread.snapshot,
        tracks=(
            replace(reread.snapshot.tracks[0], artwork_id=0),
            reread.snapshot.tracks[1],
        ),
    )
    removal = reread.prepare(reread.analyze(reread.begin_draft(cleared), target))
    assert removal.prepared is not None, removal.issues
    assert removal.prepared.snapshot.tracks[0].artwork_id == 0
    assert not removal.prepared.artwork_files


def test_hash58_detects_tampering_and_preserves_non_signature_header_data() -> None:
    source = library()
    guid = bytes.fromhex("0011223344556677")
    output = sign_hash58(source.serialize().itunes, guid)
    assert verify_hash58(output, guid)
    assert not verify_hash58(output[:-1] + bytes((output[-1] ^ 1,)), guid)
    assert (
        parse_iTunesDB(output).header.db_id
        == parse_iTunesDB(source.serialize().itunes).header.db_id
    )
    desired = replace(
        source.snapshot,
        playlists=(replace(source.snapshot.playlists[0], name="Signed"),),
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(desired),
            WriteTarget(checksum=WriteChecksum.HASH58, firewire_guid=guid),
        )
    )
    assert result.prepared is not None, result.issues
    assert verify_hash58(result.prepared.itunes, guid)


def test_hash58_refreshes_a_retained_classic_hash72_before_signing() -> None:
    guid = bytes.fromhex("0011223344556677")
    iv = bytes(range(16))
    random_part = bytes(range(20, 32))
    original = library().serialize().itunes
    dual_signed = sign_hash58(
        sign_hash72(original, iv, random_part, hashing_scheme=1), guid
    )
    source = IPodLibrary.parse(dual_signed)
    desired = replace(
        source.snapshot,
        playlists=(replace(source.snapshot.playlists[0], name="Signed twice"),),
    )

    result = source.prepare(
        source.analyze(
            source.begin_draft(desired),
            WriteTarget(checksum=WriteChecksum.HASH58, firewire_guid=guid),
        )
    )

    assert result.prepared is not None, result.issues
    assert result.prepared.itunes[0x72:0xA0] != dual_signed[0x72:0xA0]
    assert verify_hash72(result.prepared.itunes, iv, random_part, hashing_scheme=1)
    assert verify_hash58(result.prepared.itunes, guid)
