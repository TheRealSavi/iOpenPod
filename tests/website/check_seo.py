"""Validate rendered FAQ content against its search metadata after a Jekyll build."""

import json
import sys
from html.parser import HTMLParser
from pathlib import Path


class Page(HTMLParser):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.questions: list[str] = []
        self.answers: list[str] = []
        self.schemas: list[str] = []
        self.in_faq = False
        self.capture: str | None = None
        self.buffer = ""
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        identifier = attributes.get("id")
        if identifier:
            self.ids.append(identifier)
        if tag == "details" and (identifier or "").startswith("faq-"):
            self.in_faq = True
        if (self.in_faq and tag in {"summary", "p"}) or (
            tag == "script" and attributes.get("type") == "application/ld+json"
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
            }[tag]
            destination.append(self.buffer.strip())
            self.capture = None
        if tag == "details":
            self.in_faq = False


def main() -> None:
    built = Path(sys.argv[1])
    home = Page(built / "index.html")
    setup = Page(built / "install-help" / "index.html")
    expected = json.loads(
        (Path(__file__).parents[2] / "website/_data/faq.json").read_text(
            encoding="utf-8"
        )
    )
    schemas = [json.loads(raw) for raw in home.schemas]
    faqs = [item for item in schemas if item.get("@type") == "FAQPage"]
    assert len(faqs) == 1, "Homepage must have exactly one FAQ schema"
    assert len(home.ids) == len(set(home.ids)), "Duplicate page IDs"
    assert {"migration", "faq", "community"} <= set(home.ids)
    assert home.questions == [item["question"] for item in expected]
    assert home.answers == [item["answer"] for item in expected]
    assert [item["name"] for item in faqs[0]["mainEntity"]] == home.questions
    assert [
        item["acceptedAnswer"]["text"] for item in faqs[0]["mainEntity"]
    ] == home.answers
    assert faqs[0]["@id"].endswith("/#faq")
    assert all(json.loads(raw).get("@type") != "FAQPage" for raw in setup.schemas), (
        "Do not publish FAQ schema on pages without the FAQs"
    )
    print(f"PASS: {len(home.questions)} visible FAQs match JSON-LD and source data.")


if __name__ == "__main__":
    main()
