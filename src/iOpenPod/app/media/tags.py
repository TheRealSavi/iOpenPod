"""Read native Host tags into the common Library's descriptive fields.

This is tag interpretation, not codec inspection or device compatibility policy.
Only recognized tags cross this boundary; binary payloads and private IDs do not.
"""

from __future__ import annotations

import math
import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, cast

from mutagen.apev2 import APETextValue
from mutagen.id3 import ID3, ID3TimeStamp
from mutagen.mp4 import AtomDataType, MP4FreeForm

from iOpenPod.app.media.content_type import classify_content_type
from iOpenPod.app.media.models import MediaTag
from iPodDB.library import ContentAdvisory, MediaType, Track

if TYPE_CHECKING:
    from iOpenPod.app.media.models import MediaInspection, MediaScanMetadata

# Native names precede editor/FFprobe aliases. Order defines conflict precedence.
_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("TIT2", "©nam", "title"),
    "artist": ("TPE1", "©ART", "artist", "Author"),
    "album": ("TALB", "©alb", "album", "WM/AlbumTitle"),
    "album_artist": ("TPE2", "aART", "albumartist", "album artist", "WM/AlbumArtist"),
    "genre": ("TCON", "©gen", "genre", "WM/Genre"),
    "date": ("TDRC", "TYER", "©day", "date", "year", "WM/Year"),
    "release_date": ("TDRL", "releasedate", "release date"),
    "track": ("TRCK", "trkn", "tracknumber", "track", "WM/TrackNumber"),
    "track_total": ("tracktotal", "totaltracks"),
    "disc": ("TPOS", "disk", "discnumber", "disc", "WM/PartOfSet"),
    "disc_total": ("disctotal", "totaldiscs"),
    "composer": ("TCOM", "©wrt", "composer", "WM/Composer"),
    "comment": ("©cmt", "comment", "Description"),
    "grouping": ("GRP1", "TIT1", "©grp", "grouping", "WM/ContentGroupDescription"),
    "subtitle": ("TIT3", "subtitle", "WM/SubTitle"),
    "description": ("TDES", "ldes", "desc", "description", "WM/SubTitleDescription"),
    "copyright": ("TCOP", "cprt", "copyright"),
    "compilation": ("TCMP", "cpil", "compilation", "WM/IsCompilation"),
    "bpm": ("TBPM", "tmpo", "bpm", "tempo", "WM/BeatsPerMinute"),
    "lyrics": ("©lyr", "lyrics", "unsyncedlyrics", "unsynchronisedlyrics", "WM/Lyrics"),
    "media_kind": (
        "stik",
        "media_type",
        "media type",
        "media_kind",
        "mediakind",
        "ITUNESMEDIATYPE",
    ),
    "podcast": ("PCST", "pcst", "podcast"),
    "category": ("TCAT", "catg", "category"),
    "podcast_rss_url": ("WFED", "purl", "podcasturl", "podcastfeedurl", "feedurl"),
    "podcast_enclosure_url": ("enclosureurl", "podcastenclosureurl"),
    "track_keywords": ("TKWD", "keyw", "keywords"),
    "show": ("tvsh", "show", "tvshow", "WM/TVShowName"),
    "episode": ("tven", "episode_id", "tvepisodeid", "WM/TVEpisodeID"),
    "season_number": (
        "tvsn",
        "season_number",
        "season",
        "tvseason",
        "tvseasonnumber",
        "WM/TVSeason",
    ),
    "episode_number": (
        "tves",
        "episode_sort",
        "episode_number",
        "episode",
        "tvepisode",
        "tvepisodenumber",
        "WM/TVEpisode",
    ),
    "tv_network": ("tvnn", "network", "tvnetwork", "WM/TVNetworkName"),
    "sort_title": (
        "TSOT",
        "sonm",
        "titlesort",
        "sort_name",
        "sorttitle",
        "WM/TitleSortOrder",
    ),
    "sort_artist": ("TSOP", "soar", "artistsort", "sortartist", "WM/ArtistSortOrder"),
    "sort_album": ("TSOA", "soal", "albumsort", "sortalbum", "WM/AlbumSortOrder"),
    "sort_album_artist": (
        "TSO2",
        "soaa",
        "albumartistsort",
        "sortalbumartist",
        "WM/AlbumArtistSortOrder",
    ),
    "sort_composer": (
        "TSOC",
        "soco",
        "composersort",
        "sortcomposer",
        "WM/ComposerSortOrder",
    ),
    "sort_show": ("sosn", "showsort", "sortshow", "tvshowsort"),
    "content_advisory": ("rtng", "ITUNESADVISORY", "CONTENTRATING"),
    "normalization_gain_db": ("replaygain_track_gain",),
    "sound_check": ("iTunNORM",),
    "gapless_album": ("pgap", "gaplessalbum", "ITUNESGAPLESS"),
    "content_provider": ("TPUB", "publisher", "WM/Publisher"),
    "purchase_account": ("apID", "ITUNESACCOUNT"),
    "purchaser_name": ("ownr", "ITUNESOWNER"),
}
TAG_NAMES = frozenset((*_ALIASES, "rating"))


class _Tags(Protocol):
    def get(self, key: str) -> object: ...


class _TagKeys(Protocol):
    def keys(self) -> list[str]: ...


def _key(value: str) -> str:
    return re.sub(r"[ _-]", "", value.casefold())


def _text(value: object, depth: int = 0) -> str:
    if depth > 4:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, APETextValue):
        return next((part for part in str(value).split("\0") if part.strip()), "")
    if isinstance(value, MP4FreeForm):
        encoding = {AtomDataType.UTF8: "utf-8", AtomDataType.UTF16: "utf-16-be"}.get(
            value.dataformat
        )
        if encoding is None:
            return ""
        try:
            return value.decode(encoding)
        except UnicodeError:
            return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | ID3TimeStamp):
        return str(value)
    if isinstance(value, tuple):
        parts = cast("tuple[object, ...]", value)
        if len(parts) == 2 and all(type(part) is int for part in parts):
            return "/".join(str(part) for part in parts)
        return ""
    if isinstance(value, list):
        return next(
            (
                text
                for item in cast("list[object]", value)
                if (text := _text(item, depth + 1)).strip()
            ),
            "",
        )
    # ID3 text/integer frames, ASF attributes, and APE text values have distinct
    # wrappers. In particular PCST.value must never be tested via frame truthiness.
    for attribute in ("text", "value", "url"):
        nested: object = getattr(value, attribute, None)
        if nested is not None:
            return _text(nested, depth + 1)
    return ""


def read_tag_values(tags: object) -> tuple[MediaTag, ...]:
    """Normalize supported native tags without exposing Mutagen to consumers."""
    if tags is None or not hasattr(tags, "get"):
        return ()
    reader = cast("_Tags", tags)
    names: dict[str, str] = {}
    keys: set[str] | None = None
    if hasattr(tags, "keys"):
        keys = set(cast("_TagKeys", tags).keys())
        for name in sorted(keys):
            if name.startswith("TXXX:"):
                name_key = name[5:]
            elif name.startswith("----:com.apple.iTunes:"):
                name_key = name.split(":", 2)[2]
            else:
                name_key = name
            names.setdefault(_key(name_key), name)
    result: dict[str, str] = {}
    for field, aliases in _ALIASES.items():
        for alias in aliases:
            if keys is not None:
                key = alias if alias in keys else names.get(_key(alias))
                if key is None:
                    continue
                value = reader.get(key)
            else:
                value = reader.get(alias)
                if value is None:
                    value = reader.get(alias.upper())
            text = _text(value)
            if text.strip():
                result[field] = text if field == "lyrics" else text.strip()
                break
    if isinstance(tags, ID3):
        native = cast("Any", tags)
        podcast = native.get("PCST")
        if podcast is not None:
            result["podcast"] = "1" if podcast.value else "0"
        for comment in native.getall("COMM"):
            if comment.desc.casefold() == "itunnorm":
                result["sound_check"] = _text(comment.text).strip()
                break
        for frame_name, field in (("USLT", "lyrics"), ("COMM", "comment")):
            frames = sorted(
                native.getall(frame_name), key=lambda f: (bool(f.desc), f.desc, f.lang)
            )
            for frame in frames:
                if field == "comment" and frame.desc.casefold().startswith("itun"):
                    continue
                text = _text(frame.text)
                if text.strip():
                    result[field] = text if field == "lyrics" else text.strip()
                    break
        genre = native.get("TCON")
        if genre is not None and genre.genres:
            result["genre"] = str(genre.genres[0])
        ratings = sorted(native.getall("POPM"), key=lambda f: f.email)
        if ratings:
            value = ratings[0].rating
            result["rating"] = str(
                0
                if value == 0
                else 20
                if value <= 31
                else 40
                if value <= 95
                else 60
                if value <= 159
                else 80
                if value <= 223
                else 100
            )
    # FFprobe qualifies ID3 USLT language/description with a lyrics- prefix.
    if "lyrics" not in result:
        for name in sorted(names.values()):
            if (
                name.casefold().startswith("lyrics-")
                and (text := _text(reader.get(name))).strip()
            ):
                result["lyrics"] = text
                break
    return tuple(MediaTag(name, value) for name, value in sorted(result.items()))


def inspection_tag_values(
    observed: MediaInspection | MediaScanMetadata,
) -> tuple[MediaTag, ...]:
    """Container tags win; a preferred playable stream fills missing fields."""
    streams = observed.audio_streams or observed.video_streams
    preferred = next(
        (stream for stream in streams if stream.default), next(iter(streams), None)
    )
    container = read_tag_values({tag.name: tag.value for tag in observed.tags})
    stream = (
        read_tag_values({tag.name: tag.value for tag in preferred.tags})
        if preferred is not None
        else ()
    )
    values = {tag.name: tag.value for tag in (*stream, *container)}
    return tuple(MediaTag(name, value) for name, value in sorted(values.items()))


def _number(text: str, maximum: int = 0xFFFFFFFF) -> int | None:
    if not text.isascii() or not text.isdigit() or len(text) > 10:
        return None
    number = int(text)
    return number if number <= maximum else None


def _release_date(text: str) -> int | None:
    try:
        if re.fullmatch(r"\d{4}", text, re.ASCII):
            text += "-01-01"
        elif re.fullmatch(r"\d{4}-\d{2}", text, re.ASCII):
            text += "-01"
        date = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
        seconds = int((date - datetime(1970, 1, 1, tzinfo=UTC)).total_seconds())
        return seconds if -2_082_844_800 < seconds <= 2_212_122_495 else None
    except ValueError:
        return None


def apply_tag_values(
    track: Track,
    values: tuple[MediaTag, ...],
    *,
    suffix: str,
    video: bool,
    fill_only: bool = False,
) -> Track:
    """Project tags; optional enrichment preserves already reviewed values."""
    tags = {tag.name: tag.value for tag in values}
    metadata = track.metadata

    def text(name: str, current: str) -> str:
        return current if fill_only and current else tags.get(name, current)

    def number(name: str, current: int, maximum: int = 0xFFFFFFFF) -> int:
        raw = tags.get(name, "")
        if name == "bpm" and re.fullmatch(r"\d{1,5}\.\d+", raw, re.ASCII):
            raw = raw.split(".", 1)[0]
        parsed = _number(raw, maximum)
        return current if parsed is None or (fill_only and current) else parsed

    def flag(name: str, current: bool) -> bool:
        value = tags.get(name, "").casefold()
        if (fill_only and current) or value not in (
            "0",
            "1",
            "true",
            "false",
            "yes",
            "no",
        ):
            return current
        return value in ("1", "true", "yes")

    for name in ("track", "disc"):
        parts = tags.get(name, "").split("/", 1)
        tags[name] = parts[0].strip()
        if len(parts) == 2 and parts[1].strip():
            tags[name + "_total"] = parts[1].strip()
    tags["year"] = tags.get("date", "")[:4]
    gain = metadata.normalization_gain_db
    if not (fill_only and gain is not None):
        raw_gain = tags.get("normalization_gain_db", "")
        if re.fullmatch(r"[+-]?\d+(?:\.\d+)?\s*(?:dB)?", raw_gain, re.IGNORECASE):
            value = float(re.sub(r"\s*dB$", "", raw_gain, flags=re.IGNORECASE))
            if (
                math.isfinite(value)
                and -100 <= value <= 100
                and 0 < round(1000 * 10 ** (-value / 10)) <= 0xFFFFFFFF
            ):
                gain = value
    if gain is None:
        sound_check = tags.get("sound_check", "").split()
        if len(sound_check) == 10 and all(
            re.fullmatch(r"[0-9a-fA-F]{8}", part) for part in sound_check
        ):
            energy = max(int(sound_check[0], 16), int(sound_check[1], 16))
            if energy:
                gain = 10 * math.log10(1000 / energy)
    advisory = metadata.content_advisory
    if not fill_only or advisory is ContentAdvisory.UNSPECIFIED:
        advisory = {
            "0": ContentAdvisory.UNSPECIFIED,
            "1": ContentAdvisory.EXPLICIT,
            "4": ContentAdvisory.EXPLICIT,
            "2": ContentAdvisory.CLEAN,
            "explicit": ContentAdvisory.EXPLICIT,
            "clean": ContentAdvisory.CLEAN,
        }.get(tags.get("content_advisory", "").casefold(), advisory)
    released = metadata.release_date
    if not (fill_only and released):
        released = (
            _release_date(tags.get("release_date", tags.get("date", ""))) or released
        )
    media_types = track.media_types
    if media_types in ((MediaType.AUDIO,), (MediaType.VIDEO,)) or (
        not fill_only and ("media_kind" in tags or "podcast" in tags)
    ):
        media_types = (classify_content_type(suffix, tags, video=video),)
    lyrics = text("lyrics", metadata.lyrics)
    return replace(
        track,
        title=text("title", track.title),
        artist=text("artist", track.artist),
        album=text("album", track.album),
        album_artist=text("album_artist", track.album_artist),
        genre=text("genre", track.genre),
        year=number("year", track.year, 9999),
        track_number=number("track", track.track_number),
        rating=number("rating", track.rating, 100),
        media_types=media_types,
        show=text("show", track.show),
        episode=text("episode", track.episode),
        season_number=number("season_number", track.season_number),
        episode_number=number("episode_number", track.episode_number),
        metadata=replace(
            metadata,
            total_tracks=number("track_total", metadata.total_tracks),
            disc_number=number("disc", metadata.disc_number),
            total_discs=number("disc_total", metadata.total_discs),
            compilation=flag("compilation", metadata.compilation),
            bpm=number("bpm", metadata.bpm, 65535),
            release_date=released,
            normalization_gain_db=gain,
            content_advisory=advisory,
            gapless_album=flag("gapless_album", metadata.gapless_album),
            podcast=MediaType.PODCAST in media_types
            or MediaType.VIDEO_PODCAST in media_types,
            has_lyrics=metadata.has_lyrics or bool(lyrics.strip()),
            lyrics=lyrics,
            composer=text("composer", metadata.composer),
            comment=text("comment", metadata.comment),
            grouping=text("grouping", metadata.grouping),
            subtitle=text("subtitle", metadata.subtitle),
            description=text("description", metadata.description),
            copyright=text("copyright", metadata.copyright),
            category=text("category", metadata.category),
            podcast_rss_url=text("podcast_rss_url", metadata.podcast_rss_url),
            podcast_enclosure_url=text(
                "podcast_enclosure_url", metadata.podcast_enclosure_url
            ),
            track_keywords=text("track_keywords", metadata.track_keywords),
            tv_network=text("tv_network", metadata.tv_network),
            sort_title=text("sort_title", metadata.sort_title),
            sort_artist=text("sort_artist", metadata.sort_artist),
            sort_album=text("sort_album", metadata.sort_album),
            sort_album_artist=text("sort_album_artist", metadata.sort_album_artist),
            sort_composer=text("sort_composer", metadata.sort_composer),
            sort_show=text("sort_show", metadata.sort_show),
            content_provider=text("content_provider", metadata.content_provider),
            purchase_account=text("purchase_account", metadata.purchase_account),
            purchaser_name=text("purchaser_name", metadata.purchaser_name),
        ),
    )
