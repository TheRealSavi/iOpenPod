from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


def _clean_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class AlbumIdentity:
    album: str | None
    album_artist: str | None
    artist: str | None
    show_name: str | None


def album_identity_from_track(track: object) -> AlbumIdentity:
    return AlbumIdentity(
        album=_clean_text(getattr(track, "album", None)),
        album_artist=_clean_text(getattr(track, "album_artist", None)),
        artist=_clean_text(getattr(track, "artist", None)),
        show_name=_clean_text(getattr(track, "show_name", None)),
    )


def album_identity_from_mapping(track: Mapping[str, object]) -> AlbumIdentity:
    return AlbumIdentity(
        album=_clean_text(track.get("Album") or track.get("album")),
        album_artist=_clean_text(
            track.get("Album Artist") or track.get("album_artist")
        ),
        artist=_clean_text(track.get("Artist") or track.get("artist")),
        show_name=_clean_text(
            track.get("Show")
            or track.get("Show Name")
            or track.get("TV Show")
            or track.get("show_name")
        ),
    )


def albums_match(left: AlbumIdentity, right: AlbumIdentity) -> bool:
    """Match albums using libgpod's album equality rules."""
    if left.show_name != right.show_name:
        return False
    if left.album != right.album:
        return False
    if left.album_artist and right.album_artist:
        return left.album_artist == right.album_artist
    return left.artist == right.artist


@dataclass
class AlbumGroup(Generic[T]):
    identity: AlbumIdentity
    tracks: list[T]


def group_tracks_by_album_identity(
    tracks: Iterable[T],
    identity_fn: Callable[[T], AlbumIdentity],
) -> list[AlbumGroup]:
    """Group tracks into albums using libgpod-compatible matching."""
    groups: list[AlbumGroup] = []
    buckets: dict[tuple[str, str], list[int]] = {}

    for track in tracks:
        identity = identity_fn(track)
        bucket = (identity.album or "", identity.show_name or "")
        candidate_idxs = buckets.get(bucket, [])

        match_idx = None
        for idx in candidate_idxs:
            if albums_match(identity, groups[idx].identity):
                match_idx = idx
                break

        if match_idx is None:
            match_idx = len(groups)
            groups.append(AlbumGroup(identity=identity, tracks=[]))
            buckets.setdefault(bucket, []).append(match_idx)

        groups[match_idx].tracks.append(track)

    return groups
