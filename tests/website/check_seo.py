"""Check the rendered site's crawl paths, metadata, structured data, and FAQ parity.

Run after a real Jekyll build. The homepage canonical determines the host and
baseurl, so the same checks apply to custom-domain and project-path builds.
External URLs are checked for syntax, not availability; this check is offline.
"""

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit
from xml.etree import ElementTree


@dataclass(frozen=True)
class Reference:
    tag: str
    url: str


class Page(HTMLParser):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.ids: list[str] = []
        self.questions: list[str] = []
        self.answers: list[str] = []
        self.schemas: list[str] = []
        self.titles: list[str] = []
        self.h1s: list[str] = []
        self.metadata: dict[str, list[str]] = {}
        self.canonicals: list[str] = []
        self.references: list[Reference] = []
        self.images: list[dict[str, str | None]] = []
        self.refreshes: list[str] = []
        self.breadcrumb_nav = False
        self.language = ""
        self.in_faq = False
        self.capture: str | None = None
        self.buffer = ""
        raw = path.read_text(encoding="utf-8")
        assert "{{" not in raw and "{%" not in raw, f"{path}: unrendered Liquid"
        self.feed(raw)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        identifier = attributes.get("id")
        if identifier:
            self.ids.append(identifier)
        if tag == "html":
            self.language = attributes.get("lang") or ""
        if tag == "meta":
            key = attributes.get("name") or attributes.get("property")
            if key:
                self.metadata.setdefault(key, []).append(
                    attributes.get("content") or ""
                )
            if (attributes.get("http-equiv") or "").lower() == "refresh":
                self.refreshes.append(attributes.get("content") or "")
        if tag == "link" and attributes.get("rel") == "canonical":
            self.canonicals.append(attributes.get("href") or "")
        if tag in {"a", "link", "use"} and attributes.get("href"):
            self.references.append(Reference(tag, attributes["href"] or ""))
        if tag in {"img", "script", "source"} and attributes.get("src"):
            self.references.append(Reference(tag, attributes["src"] or ""))
        if tag == "img":
            self.images.append(attributes)
        if (
            tag == "nav"
            and "breadcrumb" in (attributes.get("aria-label") or "").lower()
        ):
            self.breadcrumb_nav = True
        if tag == "details" and (identifier or "").startswith("faq-"):
            self.in_faq = True
        if (
            tag in {"title", "h1"}
            or (self.in_faq and tag in {"summary", "p"})
            or (tag == "script" and attributes.get("type") == "application/ld+json")
        ):
            self.capture = tag
            self.buffer = ""

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.buffer += data

    def handle_endtag(self, tag: str) -> None:
        if tag == self.capture:
            destination = {
                "summary": self.questions,
                "p": self.answers,
                "script": self.schemas,
                "title": self.titles,
                "h1": self.h1s,
            }[tag]
            destination.append(self.buffer.strip())
            self.capture = None
        if tag == "details":
            self.in_faq = False

    def meta(self, name: str) -> str:
        values = self.metadata.get(name, [])
        assert len(values) == 1 and values[0].strip(), (
            f"{self.path}: expected exactly one nonempty {name} meta tag"
        )
        return values[0]

    @property
    def canonical(self) -> str:
        assert len(self.canonicals) == 1, f"{self.path}: expected one canonical URL"
        return self.canonicals[0]

    @property
    def noindex(self) -> bool:
        return any(
            "noindex" in value.lower() for value in self.metadata.get("robots", [])
        )

    def schema_nodes(self) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for raw in self.schemas:
            document = json.loads(raw)
            assert document.get("@context") == "https://schema.org", self.path
            nodes.extend(document.get("@graph", [document]))
        return nodes


def local_target(url: str, home_url: str, built: Path) -> Path | None:
    """Resolve a URL inside this build, rejecting accidental baseurl escapes."""
    parsed = urlsplit(url)
    home = urlsplit(home_url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc != home.netloc:
        return None
    assert parsed.scheme == home.scheme, f"Internal URL uses a different scheme: {url}"
    assert parsed.path.startswith(home.path), f"URL escapes site baseurl: {url}"
    relative = unquote(parsed.path[len(home.path) :])
    target = built / relative
    assert target.resolve().is_relative_to(built.resolve()), f"Unsafe URL path: {url}"
    if target.is_dir():
        target /= "index.html"
    assert target.is_file(), f"Missing internal target: {url} ({target})"
    return target


def check_reference(
    reference: Reference,
    page: Page,
    home_url: str,
    built: Path,
    pages: dict[Path, Page],
) -> Path | None:
    url = urljoin(page.canonical, reference.url)
    parsed = urlsplit(url)
    assert parsed.scheme in {"https", "http", "mailto", "tel"}, (
        f"{page.path}: unsupported URL scheme: {reference.url}"
    )
    if parsed.scheme in {"http", "https"}:
        assert parsed.netloc and not re.search(r"\s", url), f"Malformed URL: {url}"
    target = local_target(url, home_url, built)
    if target in pages and parsed.fragment:
        fragment = unquote(parsed.fragment).split(":~:text=", 1)[0]
        assert not fragment or fragment in pages[target].ids, (
            f"{page.path}: missing fragment #{fragment} in {target}"
        )
    return target


def check_schema(page: Page, home_url: str) -> None:
    nodes = page.schema_nodes()
    identifiers = [node["@id"] for node in nodes]
    assert len(identifiers) == len(set(identifiers)), (
        f"{page.path}: duplicate schema IDs"
    )
    by_type = {node["@type"]: node for node in nodes}
    assert len(by_type) == len(nodes), f"{page.path}: duplicate schema types"
    assert {"WebSite", "WebPage", "SoftwareApplication"} <= by_type.keys(), page.path
    website = by_type["WebSite"]
    assert website["@id"] == home_url + "#website" and website["url"] == home_url
    webpage = by_type["WebPage"]
    assert webpage["url"] == page.canonical
    assert webpage["@id"] == page.canonical + "#webpage"
    assert webpage["name"] == page.titles[0]
    assert webpage["description"] == page.meta("description")
    assert webpage["isPartOf"]["@id"] == website["@id"]
    software = by_type["SoftwareApplication"]
    assert software["@id"] == home_url + "#softwareapplication"
    assert webpage["about"]["@id"] == software["@id"]
    assert software["name"] == "iOpenPod"
    assert software["isAccessibleForFree"] is True
    assert software["offers"]["price"] == "0"
    assert software["offers"]["priceCurrency"] == "USD"
    assert software["offers"]["url"] == home_url + "#install"
    assert software["installUrl"] == home_url + "install-help/"
    assert software["downloadUrl"] == (
        "https://github.com/TheRealSavi/iOpenPod/releases/latest"
    )
    assert software["isBasedOn"]["@type"] == "SoftwareSourceCode"
    assert software["isBasedOn"]["codeRepository"] == (
        "https://github.com/TheRealSavi/iOpenPod"
    )
    assert not {"aggregateRating", "review"} & software.keys(), (
        "Do not invent software ratings or reviews"
    )
    path = page.canonical.removeprefix(home_url)
    if path.startswith("guides/") or path == "install-help/":
        assert page.breadcrumb_nav, f"{page.path}: breadcrumbs must be visible"
        breadcrumb = by_type["BreadcrumbList"]
        assert webpage["breadcrumb"]["@id"] == breadcrumb["@id"]
        crumbs = breadcrumb["itemListElement"]
        expected_urls = [home_url]
        if path.startswith("guides/") and path != "guides/":
            expected_urls.append(home_url + "guides/")
        expected_urls.append(page.canonical)
        assert [item["item"] for item in crumbs] == expected_urls, page.path
        assert [item["position"] for item in crumbs] == list(range(1, len(crumbs) + 1))
        assert all(
            item["@type"] == "ListItem" and item["name"].strip() for item in crumbs
        )


def check_faq(home: Page, pages: dict[Path, Page]) -> int:
    expected = json.loads(
        (Path(__file__).parents[2] / "website/_data/faq.json").read_text(
            encoding="utf-8"
        )
    )
    faqs = [item for item in home.schema_nodes() if item["@type"] == "FAQPage"]
    assert len(faqs) == 1, "Homepage must have exactly one FAQ schema"
    assert {"migration", "faq", "community"} <= set(home.ids)
    assert home.questions == [item["question"] for item in expected]
    assert home.answers == [item["answer"] for item in expected]
    assert [item["name"] for item in faqs[0]["mainEntity"]] == home.questions
    assert [
        item["acceptedAnswer"]["text"] for item in faqs[0]["mainEntity"]
    ] == home.answers
    assert faqs[0]["@id"] == home.canonical + "#faq"
    for page in pages.values():
        if page is not home:
            assert all(item["@type"] != "FAQPage" for item in page.schema_nodes()), (
                f"{page.path}: FAQ schema requires the visible FAQ content"
            )
    return len(home.questions)


def main() -> None:
    assert len(sys.argv) == 2, "Usage: check_seo.py PATH_TO_RENDERED_SITE"
    built = Path(sys.argv[1]).resolve()
    pages: dict[Path, Page] = {}
    for path in sorted(built.rglob("*.html")):
        raw = path.read_text(encoding="utf-8").strip()
        if raw == f"google-site-verification: {path.name}":
            assert re.fullmatch(r"google[0-9a-f]+\.html", path.name), path
            continue
        pages[path] = Page(path)
    home = pages[built / "index.html"]
    home_url = home.canonical
    assert urlsplit(home_url).scheme == "https" and home_url.endswith("/"), home_url
    indexable: dict[Path, Page] = {}
    navigation: dict[Path, set[Path]] = {}
    asset_versions: set[str] = set()
    references_checked = 0
    for path, page in pages.items():
        navigation[path] = set()
        assert page.language == "en", f"{path}: missing page language"
        assert len(page.ids) == len(set(page.ids)), f"{path}: duplicate HTML IDs"
        assert len(page.titles) == 1 and page.titles[0], f"{path}: expected one title"
        canonical_target = local_target(page.canonical, home_url, built)
        assert canonical_target is not None and canonical_target in pages, (
            f"{path}: canonical must identify a page"
        )
        parsed = urlsplit(page.canonical)
        assert not parsed.fragment and not parsed.query, f"{path}: noncanonical URL"
        for reference in page.references:
            target = check_reference(reference, page, home_url, built, pages)
            if target and target.suffix in {".css", ".js"}:
                query = urlsplit(reference.url).query
                assert re.fullmatch(r"v=\d+", query), (
                    f"{path}: local stylesheet/script needs a build version: {reference.url}"
                )
                asset_versions.add(query)
            if target in pages and reference.tag == "a":
                navigation[path].add(target)
            references_checked += 1
        for img in page.images:
            assert "alt" in img, f"{path}: image missing alt: {img}"
            source = img.get("src") or ""
            # The closed viewer gets its source and alt from the clicked screenshot.
            if not source and img.get("class") == "screenshot-viewer-image":
                assert "screenshot-viewer" in page.ids
                continue
            assert source, f"{path}: image missing src"
            if local_target(urljoin(page.canonical, source), home_url, built):
                assert all(
                    (img.get(key) or "").isdigit() for key in ("width", "height")
                ), f"{path}: local image needs explicit dimensions: {source}"
        if page.refreshes:
            assert len(page.refreshes) == 1, f"{path}: ambiguous redirect"
            target_url = page.refreshes[0].partition("url=")[2].strip()
            assert target_url and urljoin(page.canonical, target_url) == page.canonical
            assert canonical_target != path and not pages[canonical_target].refreshes, (
                f"{path}: redirect loop or chain"
            )
            assert not page.schemas, (
                f"{path}: redirects must not duplicate page schemas"
            )
            continue
        relative_path = path.relative_to(built).as_posix()
        assert not page.noindex or relative_path == "404.html", (
            f"{path}: unexpected noindex on a content page"
        )
        route = relative_path.removesuffix("index.html")
        assert page.canonical == home_url + route, f"{path}: canonical route mismatch"
        assert len(page.h1s) == 1 and page.h1s[0], f"{path}: expected one nonempty h1"
        page.meta("description")
        assert page.meta("og:url") == page.canonical
        for name in (
            "og:title",
            "og:description",
            "og:site_name",
            "og:image:alt",
            "twitter:title",
            "twitter:description",
            "twitter:image:alt",
        ):
            page.meta(name)
        assert page.meta("twitter:card") == "summary_large_image"
        for name in ("og:image", "twitter:image"):
            image_url = page.meta(name)
            assert urlsplit(image_url).scheme == "https", f"{path}: invalid {name} URL"
            local_target(image_url, home_url, built)
        check_schema(page, home_url)
        if not page.noindex:
            indexable[path] = page
    assert (built / "404.html") in pages and pages[built / "404.html"].noindex
    assert len(asset_versions) == 1, "All pages must share one asset build version"
    reachable: set[Path] = set()
    pending = [home.path]
    while pending:
        path = pending.pop()
        if path not in reachable:
            reachable.add(path)
            pending.extend(navigation[path] - reachable)
    assert indexable.keys() <= reachable, (
        f"Pages unreachable from the homepage: {indexable.keys() - reachable}"
    )
    for label, values in (
        ("titles", [page.titles[0] for page in indexable.values()]),
        ("descriptions", [page.meta("description") for page in indexable.values()]),
    ):
        duplicates = [value for value, count in Counter(values).items() if count > 1]
        assert not duplicates, f"Duplicate {label}: {duplicates}"
    sitemap = ElementTree.parse(built / "sitemap.xml")
    urls = [element.text for element in sitemap.findall(".//{*}loc")]
    assert len(urls) == len(set(urls)), "Duplicate sitemap entries"
    assert set(urls) == {page.canonical for page in indexable.values()}, (
        "Sitemap must contain exactly the indexable pages; omit redirects, 404, "
        "and verification files"
    )
    robots = (built / "robots.txt").read_text(encoding="utf-8")
    assert "Sitemap: " + home_url + "sitemap.xml" in robots
    assert "User-agent: *" in robots and "Allow: /" in robots
    assert not re.search(r"^Disallow:\s*/\s*$", robots, re.MULTILINE), (
        "Site blocks crawling"
    )
    faq_count = check_faq(home, pages)
    print(
        f"PASS: {len(indexable)} indexable pages; {references_checked} URL references; "
        f"canonical, social, schema, sitemap, robots, images, and {faq_count} FAQs "
        f"verified for {home_url}"
    )


if __name__ == "__main__":
    main()
