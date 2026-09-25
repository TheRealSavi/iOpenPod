"""Playlist format behavior, bounded parsing, and data-only reference handling."""

from pathlib import Path

import pytest

from iOpenPod.app import host_playlists
from iOpenPod.app.host_playlists import parse_host_playlist
from storage import HostPath


@pytest.mark.parametrize(
    ("extension", "payload", "title"),
    [
        (
            "m3u",
            b"#EXTM3U\n#PLAYLIST:Road trip\n#EXTINF:123,One\nOne.mp3\nTwo.mp3\nOne.mp3",
            "Road trip",
        ),
        ("m3u8", "\ufeffOne.mp3\nTwo.mp3\nOne.mp3".encode(), "Mix"),
        (
            "pls",
            b"[playlist]\nFile3=One.mp3\nFile1=One.mp3\nFile2=Two.mp3\nNumberOfEntries=3\nVersion=2",
            "Mix",
        ),
        (
            "xspf",
            b'<playlist xmlns="http://xspf.org/ns/0/" version="1"><title>Road trip</title><trackList><track><location>One.mp3</location></track><track><location>Two.mp3</location></track><track><location>One.mp3</location></track></trackList></playlist>',
            "Road trip",
        ),
        (
            "wpl",
            b'<?wpl version="1.0"?><smil><head><title>Road trip</title></head><body><seq><media src="One.mp3"/><media src="Two.mp3"/><media src="One.mp3"/></seq></body></smil>',
            "Road trip",
        ),
        (
            "asx",
            b'<ASX version="3.0"><TITLE>Road trip</TITLE><ENTRY><REF HREF="One.mp3"/></ENTRY><ENTRY><REF HREF="Two.mp3"/></ENTRY><ENTRY><REF HREF="One.mp3"/></ENTRY></ASX>',
            "Road trip",
        ),
        (
            "wax",
            b'<asx><entry><ref href="One.mp3"/></entry><entry><ref href="Two.mp3"/></entry><entry><ref href="One.mp3"/></entry></asx>',
            "Mix",
        ),
        (
            "wvx",
            b'<asx><entry><ref href="One.mp3"/></entry><entry><ref href="Two.mp3"/></entry><entry><ref href="One.mp3"/></entry></asx>',
            "Mix",
        ),
    ],
)
def test_common_formats_preserve_title_order_and_duplicate_occurrences(
    tmp_path: Path, extension: str, payload: bytes, title: str
) -> None:
    result = parse_host_playlist(
        payload, HostPath(tmp_path / f"Mix.{extension}"), checkpoint=lambda: None
    )
    assert result.title == title
    assert result.references == tuple(
        HostPath(tmp_path / name) for name in ("One.mp3", "Two.mp3", "One.mp3")
    )
    assert not result.warning


@pytest.mark.parametrize("encoding", ["cp1252", "utf-8-sig", "utf-16", "utf-16-be"])
def test_text_encodings(tmp_path: Path, encoding: str) -> None:
    text = "Café.mp3\n"
    payload = text.encode(encoding)
    if encoding == "utf-16-be":
        payload = b"\xfe\xff" + payload
    parsed = parse_host_playlist(
        payload, HostPath(tmp_path / "Mix.m3u"), checkpoint=lambda: None
    )
    assert parsed.references == (HostPath(tmp_path / "Café.mp3"),)


def test_xspf_uses_only_track_locations_and_one_alternative_per_occurrence(
    tmp_path: Path,
) -> None:
    payload = b'<playlist xmlns="http://xspf.org/ns/0/" xml:base="Music/"><location>ignored.mp3</location><trackList><track><location>https://example.org/remote.mp3</location><location>Song%20One.mp3</location><location>duplicate.mp3</location></track><track xml:base="../Other/"><location>Song%20Two.mp3</location></track></trackList></playlist>'
    parsed = parse_host_playlist(
        payload, HostPath(tmp_path / "Mix.xspf"), checkpoint=lambda: None
    )
    assert parsed.references == (
        HostPath(tmp_path / "Music" / "Song One.mp3"),
        HostPath(tmp_path / "Other" / "Song Two.mp3"),
    )


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-be"])
def test_xml_dtd_entities_are_rejected_in_all_encodings(
    tmp_path: Path, encoding: str
) -> None:
    xml_encoding = "utf-16" if encoding.startswith("utf-16") else encoding
    payload = (
        '<?xml version="1.0" encoding="'
        + xml_encoding
        + '"?><!DOCTYPE playlist [<!ENTITY bad SYSTEM "file:///secret.txt">]><playlist><trackList><track><location>&bad;</location></track></trackList></playlist>'
    ).encode(encoding)
    with pytest.raises(ValueError, match=r"DTD|entity"):
        parse_host_playlist(
            payload, HostPath(tmp_path / "Mix.xspf"), checkpoint=lambda: None
        )


@pytest.mark.parametrize(
    ("extension", "payload"),
    [
        ("xspf", b"<playlist>"),
        ("xspf", b"<unrelated><location>Song.mp3</location></unrelated>"),
        ("m3u8", b"#EXTM3U\n#EXT-X-TARGETDURATION:10\nsegment.mp3"),
        ("pls", b"[playlist]\nFile1=One.mp3\nFile1=Two.mp3"),
    ],
)
def test_malformed_and_streaming_documents_fail_closed(
    tmp_path: Path, extension: str, payload: bytes
) -> None:
    with pytest.raises(ValueError):
        parse_host_playlist(
            payload, HostPath(tmp_path / f"Mix.{extension}"), checkpoint=lambda: None
        )


def test_bad_references_are_reported_without_losing_valid_entries(
    tmp_path: Path,
) -> None:
    payload = (
        b"https://example.org/remote.mp3\nfile://server/share/a.mp3\nNUL.mp3\nGood.mp3"
    )
    parsed = parse_host_playlist(
        payload, HostPath(tmp_path / "Mix.m3u8"), checkpoint=lambda: None
    )
    assert parsed.references == (HostPath(tmp_path / "Good.mp3"),)
    assert "3" in parsed.warning


def test_reference_and_xml_depth_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host_playlists, "MAX_PLAYLIST_REFERENCES", 2)
    with pytest.raises(ValueError, match="too many"):
        parse_host_playlist(
            b"a.mp3\nb.mp3\nc.mp3",
            HostPath(tmp_path / "Mix.m3u"),
            checkpoint=lambda: None,
        )
    with pytest.raises(ValueError, match="structural"):
        parse_host_playlist(
            b"<playlist>" + b"<n>" * 65 + b"</n>" * 65 + b"</playlist>",
            HostPath(tmp_path / "Mix.xspf"),
            checkpoint=lambda: None,
        )


def test_parsing_is_cancellable(tmp_path: Path) -> None:
    def cancel() -> None:
        raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        parse_host_playlist(b"a.mp3", HostPath(tmp_path / "Mix.m3u"), checkpoint=cancel)


def test_wpl_accepts_native_relative_names_with_literal_uri_characters(
    tmp_path: Path,
) -> None:
    payload = (
        b'<smil><body><seq><media src="Artist\\Song #1 100%.mp3"/></seq></body></smil>'
    )
    parsed = parse_host_playlist(
        payload, HostPath(tmp_path / "Mix.wpl"), checkpoint=lambda: None
    )
    assert parsed.references == (HostPath(tmp_path / "Artist" / "Song #1 100%.mp3"),)
