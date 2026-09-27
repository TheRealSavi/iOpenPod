from __future__ import annotations

from iopenpod.subsonic import artwork
from iopenpod.subsonic.client import SubsonicConnectionError


class _FakeClient:
    """Minimal client stub for artwork tests."""

    def __init__(self, cover_bytes_by_id: dict[str, bytes]) -> None:
        self._covers = cover_bytes_by_id
        self.placeholder_cover_hash: str | None = None

    def get_cover_art_bytes(self, cover_art_id: str) -> bytes:
        if cover_art_id not in self._covers:
            raise SubsonicConnectionError("no cover")
        return self._covers[cover_art_id]


def test_detect_placeholder_caches_hash(monkeypatch) -> None:
    placeholder = b"x" * 200
    monkeypatch.setattr(artwork, "art_hash", lambda b: "PLACEHASH")
    c = _FakeClient({"": placeholder})
    result = artwork.detect_placeholder_cover(c)  # type: ignore[arg-type]
    assert result == "PLACEHASH"
    assert c.placeholder_cover_hash == "PLACEHASH"


def test_detect_placeholder_returns_none_when_server_errors(monkeypatch) -> None:
    c = _FakeClient({})  # empty id not in dict -> raises
    result = artwork.detect_placeholder_cover(c)  # type: ignore[arg-type]
    assert result is None
    assert c.placeholder_cover_hash is None


def test_detect_placeholder_ignores_tiny_images(monkeypatch) -> None:
    c = _FakeClient({"": b"tiny"})  # < _MIN_ARTWORK_BYTES
    result = artwork.detect_placeholder_cover(c)  # type: ignore[arg-type]
    assert result is None
    assert c.placeholder_cover_hash is None


def test_classify_cover_no_id_means_no_artwork(monkeypatch) -> None:
    has, h = artwork.classify_cover(_FakeClient({}), None)  # type: ignore[arg-type]
    assert has is False
    assert h is None


def test_classify_cover_real_artwork(monkeypatch) -> None:
    real = b"r" * 500
    monkeypatch.setattr(artwork, "art_hash", lambda b: "REALHASH")
    c = _FakeClient({"cov1": real})
    has, h = artwork.classify_cover(c, "cov1")  # type: ignore[arg-type]
    assert has is True
    assert h == "REALHASH"


def test_classify_cover_filters_placeholder(monkeypatch) -> None:
    placeholder = b"p" * 500
    monkeypatch.setattr(artwork, "art_hash", lambda b: "PH" if b == placeholder else "OTHER")
    c = _FakeClient({"": placeholder, "cov1": placeholder})
    artwork.detect_placeholder_cover(c)  # type: ignore[arg-type]
    has, h = artwork.classify_cover(c, "cov1")  # type: ignore[arg-type]
    assert has is False
    assert h is None


def test_classify_cover_optimistic_when_detection_disabled(monkeypatch) -> None:
    # placeholder_cover_hash is None (detection disabled); fetch error -> optimistic True
    monkeypatch.setattr(artwork, "art_hash", lambda b: "X")
    c = _FakeClient({})  # cov1 missing -> raises
    has, h = artwork.classify_cover(c, "cov1")  # type: ignore[arg-type]
    assert has is True
    assert h is None
