"""Bounded, data-only parsing of common Host Playlist formats."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin
from xml.etree import ElementTree

from storage.host_input import resolve_local_file_reference

if TYPE_CHECKING:
    from collections.abc import Callable

    from storage import HostPath

PLAYLIST_EXTENSIONS = frozenset(
    {".m3u", ".m3u8", ".pls", ".xspf", ".wpl", ".asx", ".wax", ".wvx"}
)
MAX_PLAYLIST_BYTES = 8 * 1024 * 1024
MAX_PLAYLIST_REFERENCES = 100_000
_XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"


@dataclass(frozen=True, slots=True)
class ParsedHostPlaylist:
    title: str
    references: tuple[HostPath, ...]
    warning: str = ""


@dataclass(frozen=True, slots=True)
class _Reference:
    value: str
    uri: bool = False


def parse_host_playlist(
    payload: bytes, source: HostPath, *, checkpoint: Callable[[], None]
) -> ParsedHostPlaylist:
    """Parse bytes only; Storage resolves spelling without touching targets."""

    if len(payload) > MAX_PLAYLIST_BYTES:
        raise ValueError("Playlist exceeds the 8 MiB scan limit")
    extension = source.path.suffix.casefold()
    title = source.path.stem
    if extension in {".m3u", ".m3u8"}:
        text = _decode_text(payload, utf8=extension == ".m3u8")
        references: list[_Reference] = []
        for line in text.splitlines():
            checkpoint()
            value = line.strip()
            if value.startswith("#EXT-X-"):
                raise ValueError("Streaming HLS playlists are not supported")
            if value.startswith("#PLAYLIST:"):
                title = value.removeprefix("#PLAYLIST:").strip() or title
            elif value and not value.startswith("#"):
                _append(references, _Reference(value))
    elif extension == ".pls":
        entries: dict[int, _Reference] = {}
        section = ""
        count = 0
        for line in _decode_text(payload).splitlines():
            checkpoint()
            value = line.strip()
            if value.startswith("[") and value.endswith("]"):
                section = value.casefold()
                continue
            if section != "[playlist]":
                continue
            match = re.fullmatch(r"File([0-9]{1,9})\s*=\s*(.*)", value, re.I)
            if match is not None:
                count += 1
                if count > MAX_PLAYLIST_REFERENCES:
                    raise ValueError("Playlist contains too many file references")
                number = int(match.group(1))
                if number < 1 or number in entries:
                    raise ValueError("PLS contains invalid or duplicate entry numbers")
                entries[number] = _Reference(match.group(2))
        if not entries and "[playlist]" not in _decode_text(payload).casefold():
            raise ValueError("PLS is missing its playlist section")
        references = [entry for _, entry in sorted(entries.items())]
    elif extension in PLAYLIST_EXTENSIONS:
        title, references = _xml_references(payload, source, checkpoint)
    else:
        raise ValueError("Unsupported Playlist format")

    paths: list[HostPath] = []
    skipped = 0
    for reference in references:
        checkpoint()
        try:
            path = resolve_local_file_reference(
                reference.value, source, uri=reference.uri
            )
        except ValueError:
            skipped += 1
            continue
        paths.append(path)
    return ParsedHostPlaylist(
        title,
        tuple(paths),
        f"Skipped {skipped} unsafe or non-local Playlist references."
        if skipped
        else "",
    )


def _append(references: list[_Reference], reference: _Reference) -> None:
    if len(references) >= MAX_PLAYLIST_REFERENCES:
        raise ValueError("Playlist contains too many file references")
    references.append(reference)


def _decode_text(payload: bytes, *, utf8: bool = False) -> str:
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        return payload.decode("utf-16")
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        if utf8:
            raise
        return payload.decode("cp1252")


class _BoundedTreeBuilder(ElementTree.TreeBuilder):
    def __init__(self, checkpoint: Callable[[], None]) -> None:
        super().__init__()
        self._checkpoint = checkpoint
        self._depth = 0
        self._elements = 0

    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise ValueError("Playlist XML must not contain a DTD or entity declarations")

    def start(self, tag: str, attrs: dict[str, str]) -> ElementTree.Element:
        self._checkpoint()
        self._depth += 1
        self._elements += 1
        if self._depth > 64 or self._elements > 500_000:
            raise ValueError("Playlist XML exceeds its structural limits")
        return super().start(tag, attrs)

    def end(self, tag: str) -> ElementTree.Element:
        self._depth -= 1
        return super().end(tag)


def _xml_references(
    payload: bytes, source: HostPath, checkpoint: Callable[[], None]
) -> tuple[str, list[_Reference]]:
    parser = ElementTree.XMLParser(target=_BoundedTreeBuilder(checkpoint))
    try:
        root = ElementTree.fromstring(payload, parser=parser)
    except ElementTree.ParseError as error:
        raise ValueError(f"Malformed Playlist XML: {error}") from error
    references: list[_Reference] = []
    extension = source.path.suffix.casefold()
    if extension == ".xspf":
        namespace = "{http://xspf.org/ns/0/}" if root.tag.startswith("{") else ""
        if root.tag != namespace + "playlist":
            raise ValueError("XSPF is missing its playlist root")
        title = root.findtext(namespace + "title", "").strip()
        base = _base(Path(source).as_uri(), root)
        for track_list in root.findall(namespace + "trackList"):
            for track in track_list.findall(namespace + "track"):
                checkpoint()
                track_base = _base(_base(base, track_list), track)
                # Locations are alternatives for one occurrence, not extra Tracks.
                alternatives = [
                    urljoin(_base(track_base, node), (node.text or "").strip())
                    for node in track.findall(namespace + "location")
                    if (node.text or "").strip()
                ]
                for location in alternatives:
                    try:
                        resolve_local_file_reference(location, source, uri=True)
                    except ValueError:
                        continue
                    _append(references, _Reference(location, True))
                    break
                else:
                    if alternatives:
                        _append(references, _Reference(alternatives[0], True))
    elif extension == ".wpl":
        if root.tag.casefold() != "smil":
            raise ValueError("WPL is missing its smil root")
        title = root.findtext("head/title", "").strip()
        for body in root.findall("body"):
            for node in body.iter("media"):
                checkpoint()
                if value := node.get("src"):
                    # WMP commonly writes native paths here, including literal #
                    # and percent characters. Its backslash separators are
                    # normalized before Storage resolves the local reference;
                    # explicit file URIs still decode.
                    _append(references, _Reference(value.replace("\\", "/")))
    else:
        if root.tag.casefold() != "asx":
            raise ValueError("ASX is missing its asx root")
        title = ""
        base = Path(source).as_uri()
        for node in root:
            if node.tag.casefold() == "title":
                title = (node.text or "").strip()
            if node.tag.casefold() == "base":
                base = urljoin(base, _attribute(node, "href"))
        for entry in root:
            if entry.tag.casefold() != "entry":
                continue
            for node in entry:
                checkpoint()
                if node.tag.casefold() == "ref" and (value := _attribute(node, "href")):
                    # ASX REF siblings are fallback alternatives as well.
                    _append(
                        references,
                        _Reference(urljoin(base, value.replace("\\", "/")), True),
                    )
                    break
    return title or source.path.stem, references


def _base(parent: str, node: ElementTree.Element) -> str:
    return urljoin(parent, node.get(_XML_BASE, ""))


def _attribute(node: ElementTree.Element, name: str) -> str:
    return next(
        (value for key, value in node.attrib.items() if key.casefold() == name), ""
    )
