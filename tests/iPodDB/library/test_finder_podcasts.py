"""Synthetic regressions for the 2026-10-18 four-model Finder captures.

Keep the observed field relationships without distributing media, account IDs,
publisher descriptions, or full device databases. See the capture research note.
"""

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from tests.iPodDB.library.test_browse_relationships import browse_source
from tests.iPodDB.library.test_playlist_datasets import podcast_source, rows

from iPodDB.iTunesDB.builder.build_iTunesDB import (
    new_itunes_chunk,
    new_string_mhod,
    new_url_mhod,
)
from iPodDB.iTunesDB.cdb import compress_iTunesCDB, decompress_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
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
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    IPodLibrary,
    MediaKind,
    MediaType,
    WriteResources,
    WriteTarget,
)

if TYPE_CHECKING:
    from iPodDB.shared.chunk import ParsedChunk


def finder_source(*, compressed: bool = False) -> IPodLibrary:
    document = parse_iTunesDB(podcast_source().serialize().itunes)
    for selection in document.find_chunks(MhitHeader):
        track = selection.chunk
        identity = track.header.track_id
        document = document.replace_chunk(
            selection,
            replace(
                track,
                header=replace(
                    track.header,
                    media_type=5,
                    podcast_now_playing_flag=1,
                    has_artwork=2,
                    artwork_count=1,
                    artwork_size=47353,
                    artwork_id_ref=0,
                ),
                children=(
                    *track.children,
                    new_url_mhod(
                        MhodType.PODCAST_RSS_URL,
                        f"https://publisher.example/{identity}.rss",
                    ),
                    new_url_mhod(
                        MhodType.PODCAST_GUID,
                        f"episode-guid-{identity}",
                    ),
                ),
            ),
        )
    for dataset in (3, 2):
        playlist_selection = rows(document, dataset)[1]
        items: list[ParsedChunk[MhipHeader]] = []
        for identity in (1, 2):
            group = identity * 100
            if dataset == 3:
                items.append(
                    new_itunes_chunk(
                        MHIP,
                        MhipHeader(podcast_group_flag=0x100, group_id=group),
                        children=(new_string_mhod(MhodType.TITLE, str(identity)),),
                    )
                )
            items.append(
                new_itunes_chunk(
                    MHIP,
                    MhipHeader(
                        track_id=identity,
                        group_id=group + 1,
                        group_id_ref=0,
                        mhip_persistent_id=1000 + identity + dataset,
                    ),
                    children=(
                        new_itunes_chunk(
                            MHOD,
                            MhodHeader(mhod_type=100),
                            prefix=MhodPlaylistPositionPrefix(position=group + 1),
                            payload=MhodPlaylistPositionPayload(),
                        ),
                    ),
                )
            )
        document = document.replace_chunk(
            playlist_selection,
            replace(
                playlist_selection.chunk,
                children=(*playlist_selection.chunk.children, *items),
            ),
        )
    if compressed:
        document = replace(
            document,
            children=tuple(
                c
                for c in document.children
                if not isinstance(c.header, MhsdHeader) or c.header.dataset_type != 2
            ),
        )
    data = write_iTunesDB(document)
    return IPodLibrary(compress_iTunesCDB(data) if compressed else data)


@pytest.mark.parametrize("compressed", (False, True))
def test_compound_podcasts_read_without_inventing_artwork_or_group_repairs(
    compressed: bool,
) -> None:
    source = finder_source(compressed=compressed)
    original = source.serialize().itunes
    noop = source.prepare(source.analyze(source.begin_draft()))
    assert noop.prepared is not None, noop.issues
    assert noop.prepared.itunes == original
    assert source.snapshot.playlists[0].track_ids == (1, 2)
    for track in source.snapshot.tracks:
        assert track.media_kind is MediaKind.PODCAST
        assert set(track.media_types) == {MediaType.AUDIO, MediaType.PODCAST}
        assert track.metadata.podcast
        assert track.metadata.podcast_rss_url.endswith(f"/{track.track_id}.rss")
        assert track.metadata.podcast_guid == f"episode-guid-{track.track_id}"
        assert track.artwork_id == 0
        assert track.metadata.artwork_count == 1
        assert track.metadata.chapters == ()


@pytest.mark.parametrize("compressed", (False, True))
@pytest.mark.parametrize("change", ("album", "remove", "repair"))
def test_affected_finder_podcast_groups_gain_explicit_parent_links(
    compressed: bool,
    change: str,
) -> None:
    source = finder_source(compressed=compressed)
    first, second = source.snapshot.tracks
    desired = replace(
        source.snapshot,
        tracks=(replace(first, album="Renamed show"), second)
        if change == "album"
        else (second,)
        if change == "remove"
        else (first, second),
        playlists=tuple(
            replace(
                p, entries=tuple(e for e in p.entries if e.track_id != first.track_id)
            )
            if change == "remove"
            else p
            for p in source.snapshot.playlists
        ),
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(
                desired,
                delete_omissions=change == "remove",
                repair_podcast_links=change == "repair",
            ),
            WriteTarget(compressed_database=compressed),
        ),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    data = result.prepared.itunes
    checked = parse_iTunesDB(
        decompress_iTunesCDB(data).logical_bytes if compressed else data
    )
    albums = {t.track_id: t.album for t in result.prepared.snapshot.tracks}
    groups: dict[int, str] = {}
    for selection in rows(checked, 3)[1].find_chunks(MhipHeader):
        item = selection.chunk
        if item.header.podcast_group_flag & 0x100:
            groups[item.header.group_id] = next(
                c.payload.value
                for c in item.children
                if isinstance(c.payload, MhodStringPayload)
            )
        else:
            assert groups[item.header.group_id_ref] == albums[item.header.track_id]
            assert item.header.mhip_persistent_id == 1003 + item.header.track_id
            assert next(
                c.prefix.position
                for c in item.children
                if isinstance(c.prefix, MhodPlaylistPositionPrefix)
            ) == (0 if change == "remove" else item.header.track_id * 100 + 1)
    flat = rows(checked, 2)[1].find_chunks(MhipHeader)
    assert all(not i.chunk.header.group_id_ref for i in flat)
    assert all(not i.chunk.header.podcast_group_flag for i in flat)
    assert {
        i.chunk.header.track_id: next(
            c.prefix.position
            for c in i.chunk.children
            if isinstance(c.prefix, MhodPlaylistPositionPrefix)
        )
        for i in flat
    } == {
        i.chunk.header.track_id: next(
            c.prefix.position
            for c in i.chunk.children
            if isinstance(c.prefix, MhodPlaylistPositionPrefix)
        )
        for i in rows(checked, 3)[1].find_chunks(MhipHeader)
        if i.chunk.header.track_id
    }


@pytest.mark.parametrize("malformation", ("duplicate_title", "foreign_reference"))
def test_ambiguous_retained_show_relationships_are_not_guessed(
    malformation: str,
) -> None:
    document = parse_iTunesDB(finder_source().serialize().itunes)
    items = rows(document, 3)[1].find_chunks(MhipHeader)
    selection = items[2] if malformation == "duplicate_title" else items[1]
    chunk = selection.chunk
    damaged = (
        replace(chunk, children=(new_string_mhod(MhodType.TITLE, "1"),))
        if malformation == "duplicate_title"
        else replace(chunk, header=replace(chunk.header, group_id_ref=999))
    )
    data = write_iTunesDB(document.replace_chunk(selection, damaged))
    source = IPodLibrary(data)
    noop = source.prepare(source.analyze(source.begin_draft()))
    assert noop.prepared is not None
    assert noop.prepared.itunes == data
    first, second = source.snapshot.tracks
    desired = replace(
        source.snapshot, tracks=(replace(first, album="Renamed show"), second)
    )
    changed = source.prepare(source.analyze(source.begin_draft(desired)))
    assert changed.prepared is None
    assert any("ambiguous" in issue.message for issue in changed.issues)


def test_written_podcast_album_has_content_type_three() -> None:
    document = parse_iTunesDB(browse_source().serialize().itunes)
    for selection in document.find_chunks(MhitHeader):
        document = document.replace_chunk(
            selection,
            replace(
                selection.chunk, header=replace(selection.chunk.header, media_type=5)
            ),
        )
    source = IPodLibrary(write_iTunesDB(document))
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(track, album="Podcast show") for track in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    document = parse_iTunesDB(result.prepared.itunes)
    linked = {
        selection.chunk.header.album_id
        for selection in document.find_chunks(MhitHeader)
    }
    assert len(linked) == 1
    assert all(
        selection.chunk.header.content_type_flag == 3
        for selection in document.find_chunks(MhiaHeader)
        if selection.chunk.header.album_id in linked
    )
