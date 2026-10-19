"""Both observed input shapes converge under explicit Sync normalization."""

from dataclasses import replace
from hashlib import sha256

import pytest
from tests.iPodDB.library.test_album_index import index_tracks
from tests.iPodDB.library.test_podcast_album_index import podcast_source

from iOpenPod.app.track_playback_policy import enforce_library_playback_policy
from iPodDB.iTunesDB.builder.build_iTunesDB import (
    new_itunes_chunk,
    new_string_mhod,
    new_url_mhod,
)
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhia import DEFINITION as MHIA
from iPodDB.iTunesDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPayload,
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPayload,
    MhodLibraryIndexPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.opaque_mhod import (
    MhodOpaquePayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, WriteResources, _write_preparation
from iPodDB.library.writing import FileDependency, PreparedMedia
from iPodDB.shared.chunk import DatabaseDocument


def observed_source(baseline: bool, *, missing_index: bool = False) -> IPodLibrary:
    document = parse_iTunesDB(
        podcast_source(media_type=4 if baseline else 5).serialize().itunes
    )
    document = replace(document, header=replace(document.header, db_id_2=900))
    for track_selection in document.find_chunks(MhitHeader):
        track_chunk = track_selection.chunk
        if track_chunk.header.track_id <= 2:
            document = document.replace_chunk(
                track_selection,
                replace(
                    track_chunk,
                    header=replace(
                        track_chunk.header, db_id_2_ref=900 if baseline else 800
                    ),
                    children=(
                        *track_chunk.children,
                        new_url_mhod(
                            MhodType.PODCAST_RSS_URL, "https://publisher.example/feed"
                        ),
                    ),
                ),
            )
    for selection in document.find_chunks(MhsdHeader):
        ds = selection.chunk
        if ds.header.dataset_type == 4:
            container = ds.children[0]
            album, music = container.children
            assert isinstance(album.header, MhiaHeader)
            album = replace(
                album,
                header=replace(album.header, album_track_db_id=101 if baseline else 0),
                children=(
                    *album.children,
                    new_string_mhod(
                        MhodType.ALBUM_ITEM_PODCAST_URL,
                        "https://publisher.example/feed",
                    ),
                    new_itunes_chunk(
                        MHOD,
                        MhodHeader(mhod_type=999),
                        payload=MhodOpaquePayload(b"private-album-data"),
                    ),
                ),
            )
            extra = (
                ()
                if baseline
                else (
                    new_itunes_chunk(
                        MHIA,
                        MhiaHeader(album_id=30, sql_id=30),
                        children=(
                            new_string_mhod(MhodType.ALBUM_ITEM_ALBUM, "Podcast"),
                        ),
                    ),
                )
            )
            document = document.replace_chunk(
                selection,
                replace(
                    ds, children=(replace(container, children=(album, music, *extra)),)
                ),
            )
    for selection in document.find_chunks(MhsdHeader):
        if selection.chunk.header.dataset_type not in (2, 3):
            continue
        kind = selection.chunk.header.dataset_type
        for playlist in selection.find_chunks(MhypHeader):
            chunk = playlist.chunk
            if chunk.header.master_flag:
                if missing_index:
                    document = document.replace_chunk(
                        playlist,
                        replace(
                            chunk,
                            children=tuple(
                                c
                                for c in chunk.children
                                if not isinstance(c.prefix, MhodLibraryIndexPrefix)
                                or c.prefix.sort_type != 36
                            ),
                        ),
                    )
                continue
            children = [
                c for c in chunk.children if not isinstance(c.header, MhipHeader)
            ]
            if kind == 3:
                children.append(
                    new_itunes_chunk(
                        MHIP,
                        MhipHeader(
                            podcast_group_flag=256,
                            group_id=10,
                            group_persistent_id=9990 if baseline else 0,
                            unk_mhip_0x12=0x8101 if baseline else 0,
                        ),
                        children=(new_string_mhod(MhodType.TITLE, "Podcast"),),
                    )
                )
            for identity in (1, 2):
                row_id = 10 + identity
                children.append(
                    new_itunes_chunk(
                        MHIP,
                        MhipHeader(
                            track_id=identity,
                            group_id=row_id,
                            group_id_ref=10 if kind == 3 and baseline else 0,
                            track_persistent_id=100 + identity,
                            mhip_persistent_id=1000 + kind * 10 + identity,
                        ),
                        children=(
                            new_itunes_chunk(
                                MHOD,
                                MhodHeader(mhod_type=100),
                                prefix=MhodPlaylistPositionPrefix(position=row_id),
                                payload=MhodPlaylistPositionPayload(),
                            ),
                        ),
                    )
                )
            document = document.replace_chunk(
                playlist,
                replace(
                    chunk,
                    header=replace(
                        chunk.header,
                        phase_game_flag=0x10B if baseline else 11,
                        sort_order=24 if baseline else 3,
                        db_id_2=900 if baseline else 800,
                    ),
                    children=tuple(children),
                ),
            )
    return IPodLibrary(write_iTunesDB(document))


def assert_normalized(data: bytes, *, tracks: int = 4) -> None:
    doc = parse_iTunesDB(data)
    assert len(doc.find_chunks(MhitHeader)) == tracks
    albums = doc.find_chunks(MhiaHeader)
    assert len(albums) == 2  # Podcast + unrelated music, no name-only shadow.
    podcast_tracks = [
        s.chunk.header
        for s in doc.find_chunks(MhitHeader)
        if s.chunk.header.media_type & 4
    ]
    refs = {t.album_id for t in podcast_tracks}
    assert len(refs) == 1
    album = next(s.chunk for s in albums if s.chunk.header.album_id in refs)
    assert album.header.album_track_db_id in {t.db_track_id for t in podcast_tracks}
    assert album.header.content_type_flag == 3
    assert all(
        t.media_type == 4 and t.db_id_2_ref == doc.header.db_id_2 == 900
        for t in podcast_tracks
    )
    for s in doc.find_chunks(MhypHeader):
        if not s.chunk.header.playlist_kind_flags & 1:
            continue
        assert s.chunk.header.sort_order == 24
        assert s.chunk.header.phase_game_flag == 0x10B
        assert s.chunk.header.db_id_2 == 900
        for row in s.find_chunks(MhipHeader):
            h = row.chunk.header
            if h.podcast_group_flag:
                assert h.group_persistent_id and h.unk_mhip_0x12 in (0x8001, 0x8101)
            else:
                assert {
                    c.prefix.position
                    for c in row.chunk.children
                    if isinstance(c.prefix, MhodPlaylistPositionPrefix)
                } == {h.group_id}
    assert b"private-album-data" in data


@pytest.mark.parametrize("baseline", [True, False])
@pytest.mark.parametrize("missing_index", [True, False])
def test_normalize_both_inputs_without_membership_edits_and_repeat(
    baseline: bool, missing_index: bool
) -> None:
    source = observed_source(baseline, missing_index=missing_index)
    original = source.serialize().itunes
    noop = source.prepare(source.analyze(source.begin_draft()))
    assert noop.prepared is not None and noop.prepared.itunes == original
    desired = enforce_library_playback_policy(source.snapshot)
    result = source.prepare(
        source.analyze(source.begin_draft(desired, normalize_podcasts=True)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    assert_normalized(result.prepared.itunes)
    assert index_tracks(result.prepared.itunes) == {2: (2, 1, 3, 4), 3: (2, 1, 3, 4)}
    reloaded = IPodLibrary(result.prepared.itunes)
    repeat = reloaded.prepare(
        reloaded.analyze(reloaded.begin_draft(normalize_podcasts=True)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert repeat.prepared is not None, repeat.issues
    assert repeat.prepared.itunes == result.prepared.itunes
    assert source.serialize().itunes == original
    before, after = parse_iTunesDB(original), parse_iTunesDB(result.prepared.itunes)
    for i in (3, 4):
        old = next(
            s.chunk
            for s in before.find_chunks(MhitHeader)
            if s.chunk.header.track_id == i
        )
        new = next(
            s.chunk
            for s in after.find_chunks(MhitHeader)
            if s.chunk.header.track_id == i
        )
        assert old.raw_header == new.raw_header and old.raw_body == new.raw_body


@pytest.mark.parametrize("baseline", [True, False])
def test_add_episode_to_either_input_and_keep_normalized_graph(baseline: bool) -> None:
    source = observed_source(baseline)
    first = source.snapshot.tracks[0]
    added = replace(
        first,
        track_id=-1,
        title="New episode",
        artist="Different episode guest",
        season_number=7,
        ipod=None,
        size_bytes=4,
        metadata=replace(
            first.metadata,
            release_date=3000,
            location="iPod_Control/Music/F00/added.mp3",
            sample_rate_hz=44100,
            file_format="MPEG audio file",
        ),
    )
    desired = enforce_library_playback_policy(
        replace(source.snapshot, tracks=(*source.snapshot.tracks, added))
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired, normalize_podcasts=True)),
        WriteResources(
            media=(
                PreparedMedia(
                    -1,
                    FileDependency(
                        added.metadata.location, 4, sha256(b"test").hexdigest()
                    ),
                    int.from_bytes(b"MP3 ", "big"),
                    1,
                    0xFFFF,
                    12,
                    0,
                ),
            ),
            pending_playback_sidecars=False,
        ),
    )
    assert result.prepared is not None, result.issues
    assert_normalized(result.prepared.itunes, tracks=5)
    identity = next(
        m.output_id
        for m in result.prepared.identities
        if m.subject == "track" and m.draft_id == -1
    )
    assert index_tracks(result.prepared.itunes) == {
        2: (identity, 2, 1, 3, 4),
        3: (identity, 2, 1, 3, 4),
    }


@pytest.mark.parametrize("baseline", [True, False])
def test_normalization_forces_retained_wrong_sort36_to_newest_first(
    baseline: bool,
) -> None:
    source = observed_source(baseline)
    document = parse_iTunesDB(source.serialize().itunes)
    for selection in document.find_chunks(MhodHeader):
        c = selection.chunk
        if isinstance(c.prefix, MhodLibraryIndexPrefix) and c.prefix.sort_type == 36:
            assert isinstance(c.payload, MhodLibraryIndexPayload)
            a, b, *rest = c.payload.indices
            document = document.replace_chunk(
                selection, replace(c, payload=replace(c.payload, indices=(b, a, *rest)))
            )
    source = IPodLibrary(write_iTunesDB(document))
    assert index_tracks(source.serialize().itunes) == {2: (1, 2, 3, 4), 3: (1, 2, 3, 4)}
    result = source.prepare(
        source.analyze(
            source.begin_draft(
                enforce_library_playback_policy(source.snapshot),
                normalize_podcasts=True,
            )
        ),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    assert index_tracks(result.prepared.itunes) == {2: (2, 1, 3, 4), 3: (2, 1, 3, 4)}


@pytest.mark.parametrize(
    "field", ["backlink", "playlist_flag", "group_id", "database_ref"]
)
def test_serialized_normalization_corruption_is_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    source = observed_source(False)

    def corrupt(document: DatabaseDocument[MhbdHeader]) -> bytes:
        if field == "backlink":
            album = next(
                s
                for s in document.find_chunks(MhiaHeader)
                if s.chunk.header.album_id == 10
            )
            document = document.replace_chunk(
                album,
                replace(
                    album.chunk, header=replace(album.chunk.header, album_track_db_id=0)
                ),
            )
        elif field == "playlist_flag":
            for playlist in document.find_chunks(MhypHeader):
                if playlist.chunk.header.playlist_kind_flags & 1:
                    document = document.replace_chunk(
                        playlist,
                        replace(
                            playlist.chunk,
                            header=replace(playlist.chunk.header, phase_game_flag=11),
                        ),
                    )
        elif field == "group_id":
            for item in document.find_chunks(MhipHeader):
                if item.chunk.header.podcast_group_flag:
                    document = document.replace_chunk(
                        item,
                        replace(
                            item.chunk,
                            header=replace(item.chunk.header, group_persistent_id=0),
                        ),
                    )
        else:
            for s in document.find_chunks(MhitHeader):
                if s.chunk.header.media_type & 4:
                    document = document.replace_chunk(
                        s,
                        replace(s.chunk, header=replace(s.chunk.header, db_id_2_ref=0)),
                    )
        return write_iTunesDB(document)

    monkeypatch.setattr(_write_preparation, "write_iTunesDB", corrupt)
    result = source.prepare(
        source.analyze(
            source.begin_draft(
                enforce_library_playback_policy(source.snapshot),
                normalize_podcasts=True,
            )
        ),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is None
    assert any(
        i.code.startswith("verification.") or i.code == "library.album_index"
        for i in result.issues
    ), result.issues


def test_podcast_repairs_preserve_noncanonical_unrelated_music_traversal() -> None:
    source = observed_source(False)
    document = parse_iTunesDB(source.serialize().itunes)
    for row in document.find_chunks(MhodHeader):
        chunk = row.chunk
        if (
            isinstance(chunk.prefix, MhodLibraryIndexPrefix)
            and chunk.prefix.sort_type == 36
        ):
            assert isinstance(chunk.payload, MhodLibraryIndexPayload)
            first, second, third, fourth = chunk.payload.indices
            document = document.replace_chunk(
                row,
                replace(
                    chunk,
                    payload=replace(
                        chunk.payload, indices=(first, second, fourth, third)
                    ),
                ),
            )
    source = IPodLibrary(write_iTunesDB(document))
    result = source.prepare(
        source.analyze(source.begin_draft(normalize_podcasts=True)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    assert index_tracks(result.prepared.itunes) == {2: (2, 1, 4, 3), 3: (2, 1, 4, 3)}


@pytest.mark.parametrize("conflict", [False, True])
def test_duplicate_album_preserves_private_bytes_and_rating_or_blocks(
    conflict: bool,
) -> None:
    source = observed_source(False)
    document = parse_iTunesDB(source.serialize().itunes)
    for row in document.find_chunks(MhiaHeader):
        if row.chunk.header.album_id not in (10, 30):
            continue
        shadow = row.chunk.header.album_id == 30
        raw = bytearray(row.chunk.raw_header)
        raw[0x30] = 0x7B if shadow else 0x6A if conflict else 0
        document = document.replace_chunk(
            row,
            replace(
                row.chunk,
                raw_header=bytes(raw),
                header=replace(row.chunk.header, album_rating=80 if shadow else 0),
            ),
        )
    source = IPodLibrary(write_iTunesDB(document))
    result = source.prepare(
        source.analyze(source.begin_draft(normalize_podcasts=True)),
        WriteResources(pending_playback_sidecars=False),
    )
    if conflict:
        assert result.prepared is None
        assert any(
            "conflicting private header data" in str(i.message) for i in result.issues
        )
    else:
        assert result.prepared is not None, result.issues
        doc = parse_iTunesDB(result.prepared.itunes)
        album = next(
            s.chunk
            for s in doc.find_chunks(MhiaHeader)
            if s.chunk.header.album_id == 10
        )
        assert album.header.album_rating == 80
        assert album.raw_header[0x30] == 0x7B
