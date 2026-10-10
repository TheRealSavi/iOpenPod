"""Sort 36 through the public API, with ordering extracted from captured bytes."""

import base64
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    IPodLibrary,
    Track,
    TrackMetadata,
    WriteResources,
    _album_index,
)
from iPodDB.library.writing import FileDependency, IssueSeverity, PreparedMedia
from iPodDB.shared.chunk import DatabaseDocument

FIXTURES = Path(__file__).parents[2] / "fixtures" / "iTunesDB"


def captured_source(name: str = "captured-album-index-36") -> IPodLibrary:
    data = base64.b64decode(
        b"".join((FIXTURES / f"{name}.b64").read_bytes().split()),
        validate=True,
    )
    manifest = json.loads((FIXTURES / f"{name}.json").read_text())
    assert hashlib.sha256(data).hexdigest() == manifest["fixture_sha256"]
    return IPodLibrary(data)


def index_tracks(data: bytes) -> dict[int, tuple[int, ...]]:
    result: dict[int, tuple[int, ...]] = {}
    for ds in parse_iTunesDB(data).find_chunks(MhsdHeader):
        for master in ds.find_chunks(MhypHeader):
            if not master.chunk.header.master_flag:
                continue
            ids = tuple(
                c.header.track_id
                for c in master.chunk.children
                if isinstance(c.header, MhipHeader)
            )
            for c in master.chunk.children:
                if _album_index.is_album_index(c):
                    assert isinstance(c.payload, MhodLibraryIndexPayload)
                    result[ds.chunk.header.dataset_type] = tuple(
                        ids[i] for i in c.payload.indices
                    )
    return result


def reordered_source(positions: tuple[int, ...]) -> IPodLibrary:
    source = captured_source("captured-album-index-36-overrides")
    document = parse_iTunesDB(source.serialize().itunes)
    for selection in document.find_chunks(MhodHeader):
        if not _album_index.is_album_index(selection.chunk):
            continue
        payload = selection.chunk.payload
        assert isinstance(payload, MhodLibraryIndexPayload)
        document = document.replace_chunk(
            selection,
            replace(
                selection.chunk,
                payload=replace(
                    payload, indices=tuple(payload.indices[i] for i in positions)
                ),
            ),
        )
    return IPodLibrary(write_iTunesDB(document))


@pytest.mark.parametrize(
    "name", ["captured-album-index-36", "captured-album-index-36-overrides"]
)
def test_captured_order_and_noop_are_exact(name: str) -> None:
    source = captured_source(name)
    original = source.serialize().itunes
    manifest = json.loads((FIXTURES / f"{name}.json").read_text())
    assert index_tracks(original) == {
        int(kind): tuple(ids) for kind, ids in manifest["ordered_track_ids"].items()
    }
    result = source.prepare(source.analyze(source.begin_draft()))
    assert result.prepared is not None, result.issues
    assert result.prepared.itunes == original


@pytest.mark.parametrize(
    ("position", "field", "value", "expected_positions"),
    [
        (0, "sort_album_artist", "ZZZ", (1, 2, 3, 0, 4, 5, 6)),
        # Removing an explicit override changes how the same text is compared.
        (1, "sort_album_artist", "", (0, 2, 3, 1, 4, 5, 6)),
        (2, "sort_album", "The Aardvark", (0, 1, 2, 3, 4, 5, 6)),
        (6, "compilation", False, (6, 0, 1, 2, 3, 4, 5)),
    ],
)
def test_reported_sort_overrides_empty_albums_and_compilations(
    position: int, field: str, value: str | bool, expected_positions: tuple[int, ...]
) -> None:
    source = captured_source("captured-album-index-36-overrides")
    original = source.serialize().itunes
    before = index_tracks(original)[3]
    changed = next(t for t in source.snapshot.tracks if t.track_id == before[position])
    if field == "compilation":
        assert isinstance(value, bool)
        metadata = replace(changed.metadata, compilation=value)
    elif field == "sort_album":
        assert isinstance(value, str)
        metadata = replace(changed.metadata, sort_album=value)
    else:
        assert isinstance(value, str)
        metadata = replace(changed.metadata, sort_album_artist=value)
    changed = replace(changed, metadata=metadata)
    desired = replace(
        source.snapshot,
        tracks=tuple(
            changed if t.track_id == changed.track_id else t
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert index_tracks(result.prepared.itunes) == {
        kind: tuple(before[i] for i in expected_positions) for kind in (2, 3)
    }
    assert source.serialize().itunes == original


@pytest.mark.parametrize("legacy", [False, True])
def test_profile_selection_preserves_legacy_support_and_warns_for_unknown_order(
    legacy: bool,
) -> None:
    source = captured_source("captured-album-index-36-overrides")
    original = source.serialize().itunes
    before = index_tracks(original)[3]
    # A constructed legacy order exercises the pre-existing policy. The other
    # order puts The Zeta before Fixture Artist B, which neither family supports.
    positions = (6, 0, 3, 1, 2, 5, 4) if legacy else (1, 0, 2, 3, 4, 5, 6)
    source = reordered_source(positions)
    retained = source.serialize().itunes
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, metadata=replace(t.metadata, sort_album_artist="ZZZ"))
            if t.track_id == before[0]
            else t
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    if legacy:
        assert result.prepared is not None, result.issues
        assert index_tracks(result.prepared.itunes) == {
            kind: tuple(before[i] for i in (6, 3, 1, 2, 0, 5, 4)) for kind in (2, 3)
        }
        assert not any(i.code == "library.album_index" for i in result.issues)
    else:
        assert result.prepared is not None, result.issues
        assert index_tracks(result.prepared.itunes) == {
            kind: tuple(before[i] for i in (1, 2, 3, 0, 4, 5, 6)) for kind in (2, 3)
        }
        warnings = [i for i in result.issues if i.code == "library.album_index"]
        assert len(warnings) == 2
        assert all(i.severity is IssueSeverity.WARNING for i in warnings)
        assert all(i.subject == "playlist" and i.record_id == 1 for i in warnings)
    assert source.serialize().itunes == retained


def test_unknown_collation_is_preserved_until_album_order_needs_rebuilding() -> None:
    source = reordered_source((1, 0, 2, 3, 4, 5, 6))
    original = source.serialize().itunes
    noop = source.prepare(source.analyze(source.begin_draft()))
    assert noop.prepared is not None, noop.issues
    assert noop.prepared.itunes == original
    assert not any(i.code == "library.album_index" for i in noop.issues)
    first, *others = source.snapshot.tracks
    desired = replace(
        source.snapshot, tracks=(replace(first, title="Changed"), *others)
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert index_tracks(result.prepared.itunes) == index_tracks(original)
    assert not any(i.code == "library.album_index" for i in result.issues)


def test_default_collation_does_not_accept_a_malformed_source_index() -> None:
    source = reordered_source((1, 1, 2, 3, 4, 5, 6))
    first, *others = source.snapshot.tracks
    desired = replace(
        source.snapshot, tracks=(replace(first, album="Changed"), *others)
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None
    assert any(
        i.code == "library.album_index" and i.severity is IssueSeverity.ERROR
        for i in result.issues
    )


@pytest.mark.parametrize("field", ["title", "rating", "sort_title"])
def test_unrelated_edits_preserve_the_captured_album_order(field: str) -> None:
    source = captured_source()
    original = source.serialize().itunes
    first, *others = source.snapshot.tracks
    if field == "sort_title":
        changed = replace(first, metadata=replace(first.metadata, sort_title="ZZZ"))
    elif field == "title":
        changed = replace(first, title="ZZZ")
    else:
        changed = replace(first, rating=80)
    desired = replace(source.snapshot, tracks=(changed, *others))
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert index_tracks(result.prepared.itunes) == index_tracks(original)
    assert source.serialize().itunes == original


def test_master_reordering_remaps_positions_and_keeps_captured_ties() -> None:
    source = captured_source()
    original = source.serialize().itunes
    desired = replace(source.snapshot, tracks=tuple(reversed(source.snapshot.tracks)))
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    assert index_tracks(result.prepared.itunes) == index_tracks(original)


def test_album_sort_edit_moves_the_whole_native_album() -> None:
    source = captured_source()
    original = source.serialize().itunes
    before = index_tracks(original)[3]
    # Move the first anonymized album after all named artists.
    first_id = before[0]
    first = next(t for t in source.snapshot.tracks if t.track_id == first_id)
    assert first.ipod is not None
    album_id = first.ipod.album_id
    members = {
        t.track_id
        for t in source.snapshot.tracks
        if t.ipod and t.ipod.album_id == album_id
    }
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, metadata=replace(t.metadata, sort_album_artist="ZZZ"))
            if t.track_id in members
            else t
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    after = index_tracks(result.prepared.itunes)[3]
    assert tuple(i for i in after if i not in members) == tuple(
        i for i in before if i not in members
    )
    assert after.index(first_id) > before.index(first_id)
    assert tuple(i for i in after if i in members) == tuple(
        i for i in before if i in members
    )


def test_track_removal_filters_the_captured_order() -> None:
    source = captured_source()
    removed = 40  # A nonrepresentative Track from the fourth anonymized album.
    original = source.serialize().itunes
    desired = replace(
        source.snapshot,
        tracks=tuple(t for t in source.snapshot.tracks if t.track_id != removed),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired, delete_omissions=True)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    assert index_tracks(result.prepared.itunes) == {
        kind: tuple(i for i in ids if i != removed)
        for kind, ids in index_tracks(original).items()
    }


@pytest.mark.parametrize(
    ("existing_album", "unknown_collation"),
    [(False, False), (True, False), (False, True)],
)
def test_track_addition_joins_the_correct_album(
    existing_album: bool, unknown_collation: bool
) -> None:
    source = captured_source()
    if unknown_collation:
        source = reordered_source((1, 0, 2, 3, 4, 5, 6))
    original = index_tracks(source.serialize().itunes)[3]
    first = next(t for t in source.snapshot.tracks if t.track_id == original[0])
    track = Track(
        -1,
        "Added",
        first.artist if existing_album else "QQQ artist",
        first.album if existing_album else "QQQ album",
        1000,
        album_artist=first.album_artist if existing_album else "QQQ artist",
        size_bytes=4,
        track_number=2,
        metadata=TrackMetadata(
            location="iPod_Control/Music/F00/added.mp3",
            sample_rate_hz=44100,
            file_format="MPEG audio file",
            sort_album=first.metadata.sort_album if existing_album else "",
            disc_number=1,
        ),
    )
    media = PreparedMedia(
        -1,
        FileDependency(track.metadata.location, 4, hashlib.sha256(b"test").hexdigest()),
        int.from_bytes(b"MP3 ", "big"),
        1,
        0xFFFF,
        12,
        0,
    )
    desired = replace(source.snapshot, tracks=(*source.snapshot.tracks, track))
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(media=(media,), pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    identity = next(
        m.output_id
        for m in result.prepared.identities
        if m.subject == "track" and m.draft_id == -1
    )
    for order in index_tracks(result.prepared.itunes).values():
        expected = (
            (original[1], original[0], *original[2:]) if unknown_collation else original
        )
        assert tuple(i for i in order if i != identity) == expected
        assert order.count(identity) == 1
        if existing_album:
            assert order.index(identity) == order.index(first.track_id) + 1
        elif unknown_collation:
            # Q follows the Fixture artists, before the The/Thistle artists.
            assert order.index(identity) == 1
    album_issues = [i for i in result.issues if i.code == "library.album_index"]
    assert len(album_issues) == (2 if unknown_collation else 0)
    assert all(i.severity is IssueSeverity.WARNING for i in album_issues)


def test_disc_and_track_edits_update_member_order_and_review_effect() -> None:
    source = captured_source()
    track_id = 40
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, track_number=1, metadata=replace(t.metadata, disc_number=1))
            if t.track_id == track_id
            else t
            for t in source.snapshot.tracks
        ),
    )
    plan = source.analyze(source.begin_draft(desired))
    assert plan.resolution is not None
    assert any("sort type 36" in e.reason for e in plan.resolution.effects)
    result = source.prepare(plan)
    assert result.prepared is not None, result.issues
    order = index_tracks(result.prepared.itunes)[3]
    assert order.index(41) < order.index(40) < order.index(42)


@pytest.mark.parametrize(
    "name",
    ["captured-album-index-36", "captured-album-index-36-overrides", "unknown-order"],
)
def test_verifier_rejects_an_incorrect_album_index_writer(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    source = (
        reordered_source((1, 0, 2, 3, 4, 5, 6))
        if name == "unknown-order"
        else captured_source(name)
    )
    original = source.serialize().itunes
    writer = _album_index.prepare_album_index

    def corrupt(
        source_document: DatabaseDocument[MhbdHeader],
        candidate: DatabaseDocument[MhbdHeader],
        previous: tuple[Track, ...],
        desired: tuple[Track, ...],
        original_payload: MhodLibraryIndexPayload,
    ) -> _album_index.PreparedAlbumIndex:
        prepared = writer(
            source_document, candidate, previous, desired, original_payload
        )
        return replace(
            prepared,
            payload=replace(
                prepared.payload, indices=tuple(reversed(prepared.payload.indices))
            ),
        )

    monkeypatch.setattr(_album_index, "prepare_album_index", corrupt)
    desired = replace(source.snapshot, tracks=tuple(reversed(source.snapshot.tracks)))
    if name == "unknown-order":
        first, *others = source.snapshot.tracks
        desired = replace(
            source.snapshot, tracks=(replace(first, album="Changed"), *others)
        )
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is None
    assert any(i.code == "verification.playlist_index" for i in result.issues)
    assert source.serialize().itunes == original
