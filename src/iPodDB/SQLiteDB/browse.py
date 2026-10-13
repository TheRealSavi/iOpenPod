"""Deterministic Original-style browse ranks and calculated group metadata."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable


def sort_name(value: str) -> str:
    for article in ("the ", "an ", "a "):
        if value.casefold().startswith(article):
            return value[len(article) :]
    return value


def name_ranks(names: Iterable[str]) -> dict[str, int]:
    """Original non-album ordering: normalized keys, steps of 100, missing=100."""
    values = tuple(names)
    keys = sorted({sort_name(name).casefold() for name in values if name})
    ranks = {key: (index + 1) * 100 for index, key in enumerate(keys)}
    return {name: ranks.get(sort_name(name).casefold(), 100) for name in values}


@dataclass(slots=True)
class _Group:
    artists: set[int] = field(default_factory=set[int])
    albums: set[int] = field(default_factory=set[int])
    compilations: set[int] = field(default_factory=set[int])
    songs: bool = False
    music_videos: bool = False
    movies: bool = False
    non_compilation: bool = False
    sort_name: str = ""


def complete_browse_metadata(connection: sqlite3.Connection) -> None:
    """Aggregate once over items; do not scan the Library once per group."""
    groups: dict[str, dict[int, _Group]] = {
        table: defaultdict(_Group)
        for table in ("genre_map", "album", "artist", "track_artist", "composer")
    }
    for row in connection.execute(
        "SELECT genre_id,album_pid,artist_pid,track_artist_pid,composer_pid,"
        "is_song,is_music_video,is_movie,is_compilation,sort_album_artist,sort_artist,sort_composer FROM item"
    ):
        (
            genre,
            album,
            artist,
            track_artist,
            composer,
            song,
            video,
            movie,
            compilation,
            sort_aa,
            sort_artist,
            sort_composer,
        ) = row
        for table, identity, name in (
            ("genre_map", genre, ""),
            ("album", album, ""),
            ("artist", artist, sort_aa),
            ("track_artist", track_artist, sort_artist),
            ("composer", composer, sort_composer),
        ):
            group = groups[table][identity]
            group.artists.add(track_artist if table == "album" else artist)
            group.albums.add(album)
            if compilation:
                group.compilations.add(album)
            group.songs |= bool(song)
            group.music_videos |= bool(video)
            group.movies |= bool(movie)
            group.non_compilation |= not compilation
            if not group.sort_name:
                group.sort_name = name or ""
    for identity, group in groups["genre_map"].items():
        connection.execute(
            "UPDATE genre_map SET has_music=?,artist_count_calc=?,album_count_calc=?,compilation_count_calc=? WHERE id=?",
            (
                int(group.songs or group.music_videos),
                len(group.artists),
                len(group.albums),
                len(group.compilations),
                identity,
            ),
        )
    for table in ("artist", "track_artist", "composer"):
        ranks = name_ranks(g.sort_name for g in groups[table].values())
        for identity, group in groups[table].items():
            connection.execute(
                f"UPDATE {table} SET name_order=?,sort_name=? WHERE pid=?",
                (ranks[group.sort_name], group.sort_name or None, identity),
            )
            if table == "composer":
                connection.execute(
                    "UPDATE composer SET has_music=? WHERE pid=?",
                    (int(group.songs or group.music_videos), identity),
                )
            else:
                connection.execute(
                    f"UPDATE {table} SET has_songs=?,has_music_videos=? WHERE pid=?",
                    (int(group.songs), int(group.music_videos), identity),
                )
                if table == "track_artist":
                    connection.execute(
                        "UPDATE track_artist SET has_non_compilation_tracks=?,album_count=? WHERE pid=?",
                        (int(group.non_compilation), len(group.albums), identity),
                    )
    artist_orders = dict(connection.execute("SELECT pid,name_order FROM artist"))
    artwork_albums: dict[int, int] = {}
    for pid, artist, artwork in connection.execute(
        "SELECT pid,artist_pid,artwork_status FROM album"
    ):
        group = groups["album"][pid]
        connection.execute(
            "UPDATE album SET has_songs=?,has_music_videos=?,has_movies=?,artist_count_calc=?,artist_order=? WHERE pid=?",
            (
                int(group.songs),
                int(group.music_videos),
                int(group.movies),
                len(group.artists),
                artist_orders.get(artist, 100),
                pid,
            ),
        )
        if artwork:
            artwork_albums.setdefault(artist, pid)
    for artist, album in artwork_albums.items():
        connection.execute(
            "UPDATE artist SET artwork_status=1,artwork_album_pid=? WHERE pid=?",
            (album, artist),
        )
