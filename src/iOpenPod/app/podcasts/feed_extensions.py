"""Publisher fields whose namespace or structure must survive feed normalization."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DecimalException
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

from iOpenPod.app.podcasts.identity import normalize_feed_url
from iOpenPod.app.podcasts.models import PodcastChapterImage, PodcastLink

_ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
_PODCAST = "{https://podcastindex.org/namespace/1.0}"
_PODLOVE = "{http://podlove.org/simple-chapters}"
_ATOM = "{http://www.w3.org/2005/Atom}"
MAX_CHAPTER_IMAGES = 128


@dataclass(frozen=True, slots=True)
class EpisodeExtensions:
    author: str = ""
    chapter_images: tuple[PodcastChapterImage, ...] = ()
    chapter_document_url: str = ""


def publisher_url(value: str, base_url: str) -> str:
    try:
        if not value.strip():
            return ""
        resolved = urljoin(base_url, value.strip())
        normalized = normalize_feed_url(resolved)
        fragment = urlsplit(resolved).fragment
        return normalized + (f"#{fragment}" if fragment else "") if normalized else ""
    except ValueError:
        return ""


def image_time_ms(value: str) -> int | None:
    """Accept finite nonnegative decimal seconds without overflowing native time."""
    try:
        seconds = Decimal(value)
        if (
            not seconds.is_finite()
            or seconds < 0
            or seconds >= Decimal(0xFFFFFFFF) / 1000
        ):
            return None
        position = int((seconds * 1000).to_integral_value())
        return position if position < 0xFFFFFFFF else None
    except (DecimalException, ValueError, OverflowError):
        return None


def _podlove_time(value: str) -> int | None:
    parts = value.split(":")
    if len(parts) not in (2, 3):
        return image_time_ms(value)
    try:
        numbers = tuple(Decimal(part) for part in parts)
        if any(not n.is_finite() or n < 0 for n in numbers):
            return None
        if numbers[-1] >= 60 or (len(parts) == 3 and numbers[-2] >= 60):
            return None
        if any(n != n.to_integral_value() for n in numbers[:-1]):
            return None
        seconds = sum(n * (60**power) for power, n in enumerate(reversed(numbers)))
        return image_time_ms(str(seconds))
    except DecimalException:
        return None


def episode_extensions(payload: bytes, base_url: str) -> dict[str, EpisodeExtensions]:
    """Match only unique publisher identities; never merge unrelated entries."""
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return {}
    channel = root.find("channel")
    if channel is None:
        channel = root
    result: dict[str, EpisodeExtensions] = {}
    conflicts: set[str] = set()
    for entry in channel:
        if entry.tag not in ("item", f"{_ATOM}entry"):
            continue
        author = (
            entry.findtext(f"{_ITUNES}author", "").strip()
            or entry.findtext(f"{_ATOM}author/{_ATOM}name", "").strip()
            or entry.findtext("{http://purl.org/dc/elements/1.1/}creator", "").strip()
        )
        images: list[PodcastChapterImage] = []
        for child in entry.findall(f"{_PODLOVE}chapters/{_PODLOVE}chapter"):
            position = _podlove_time(child.get("start", ""))
            url = publisher_url(child.get("image", ""), base_url)
            if position is not None and url:
                images.append(PodcastChapterImage(position, url))
            if len(images) >= MAX_CHAPTER_IMAGES:
                break
        chapter_url = next(
            (
                url
                for child in entry.findall(f"{_PODCAST}chapters")
                if child.get("type", "").casefold()
                in ("application/json+chapters", "application/json")
                and (url := publisher_url(child.get("url", ""), base_url))
            ),
            "",
        )
        extension = EpisodeExtensions(author, tuple(images), chapter_url)
        identities = [entry.findtext("guid", ""), entry.findtext(f"{_ATOM}id", "")]
        identities.extend(
            publisher_url(child.get("url", ""), base_url)
            for child in entry.findall("enclosure")
        )
        identities.extend(
            publisher_url(child.get("href", ""), base_url)
            for child in entry.findall(f"{_ATOM}link")
            if child.get("rel") == "enclosure"
        )
        for identity in {text.strip() for text in identities if text.strip()}:
            if identity in result:
                conflicts.add(identity)
            result[identity] = extension
    return {key: value for key, value in result.items() if key not in conflicts}


class _DescriptionLinks(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[PodcastLink] = []
        self._url = ""
        self._label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a" and len(self.links) < 100:
            self._url = publisher_url(dict(attrs).get("href") or "", self.base_url)
            self._label = []

    def handle_data(self, data: str) -> None:
        if self._url:
            self._label.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._url:
            self.links.append(
                PodcastLink(self._url, " ".join("".join(self._label).split())[:255])
            )
            self._url = ""
            self._label = []


def description_links(
    description: str, website_url: str, base_url: str
) -> tuple[PodcastLink, ...]:
    parser = _DescriptionLinks(base_url)
    parser.feed(description)
    links = ([PodcastLink(website_url)] if website_url else []) + parser.links
    unique: dict[str, PodcastLink] = {}
    for link in links:
        unique.setdefault(link.url, link)
    return tuple(unique.values())[:100]
