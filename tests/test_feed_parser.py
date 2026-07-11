from __future__ import annotations

import gzip

from iopenpod.podcasts.feed_parser import fetch_feed


def _feed_xml(title: str = "Example Show") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{title}</title>
    <description>Show description</description>
    <item>
      <guid>episode-1</guid>
      <title>Episode 1</title>
      <description>Episode description</description>
      <enclosure url="https://example.test/episode-1.mp3" type="audio/mpeg" length="123" />
      <pubDate>Sat, 23 May 2026 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
""".encode()


class _Raw:
    def __init__(self, data: bytes) -> None:
        self.decode_content = True
        self._data = data

    def read(self) -> bytes:
        return self._data


class _Response:
    def __init__(self, data: bytes, encoding: str) -> None:
        self.raw = _Raw(data)
        self.headers = {"Content-Encoding": encoding}
        self.closed = False

    def raise_for_status(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_fetch_feed_tolerates_invalid_gzip_header(monkeypatch) -> None:
    response = _Response(_feed_xml("Plain XML With Bad Header"), "gzip")

    def fake_get(url, **kwargs):
        assert url == "https://example.test/feed.xml"
        assert kwargs["stream"] is True
        assert kwargs["headers"]["Accept-Encoding"] == "identity"
        return response

    monkeypatch.setattr("iopenpod.podcasts.feed_parser.requests.get", fake_get)

    feed = fetch_feed("https://example.test/feed.xml")

    assert feed.title == "Plain XML With Bad Header"
    assert feed.episodes[0].title == "Episode 1"
    assert response.closed is True


def test_fetch_feed_decodes_valid_gzip_response(monkeypatch) -> None:
    response = _Response(gzip.compress(_feed_xml("Compressed Feed")), "gzip")
    monkeypatch.setattr(
        "iopenpod.podcasts.feed_parser.requests.get",
        lambda *_args, **_kwargs: response,
    )

    feed = fetch_feed("https://example.test/feed.xml")

    assert feed.title == "Compressed Feed"
    assert feed.episodes[0].audio_url == "https://example.test/episode-1.mp3"
