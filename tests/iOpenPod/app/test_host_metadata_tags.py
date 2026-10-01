"""Real native tags survive Host scanning and its persisted cache."""

import base64
import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any, Protocol, cast

import mutagen
import pytest
from mutagen import id3
from mutagen.apev2 import APEv2
from mutagen.asf import ASFUnicodeAttribute  # type: ignore[attr-defined]
from mutagen.id3 import PCST
from mutagen.mp4 import AtomDataType, MP4FreeForm
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_sync_execution import (
    _request,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.host_media_folders import create_host_media_folder
from iOpenPod.app.host_media_library import HostMediaScanner
from iOpenPod.app.media.inspection import MediaInspectionError, MediaInspector
from iOpenPod.app.media.lyrics import embedded_lyrics
from iOpenPod.app.media.tags import apply_tag_values, read_tag_values
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor
from iPodDB.library import (
    ContentAdvisory,
    LibrarySnapshot,
    MediaKind,
    MediaType,
    Track,
    TrackMetadata,
)
from storage import AtomicHostFile, HostPath

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "media"
FRAMES: Any = id3


class _MutagenReader(Protocol):
    def File(self, filething: Path) -> Any: ...


class Fingerprinter:
    def fingerprint(self, source: HostPath, *, checkpoint: Callable[[], None]) -> str:
        return "1,2,3"


def scan_twice(tmp_path: Path) -> Track:
    snapshots: list[LibrarySnapshot] = []
    for index in range(2):
        scanner = HostMediaScanner(
            AtomicHostFile(tmp_path / "cache.json"), fingerprinter=Fingerprinter()
        )
        pending = scanner.scan(
            (create_host_media_folder(tmp_path / "media"),), checkpoint=lambda: None
        )
        library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
        assert library.cache.reused == index
        snapshots.append(library.snapshot)
    assert snapshots[0] == snapshots[1]
    return snapshots[0].tracks[0]


def media_file(directory: Path, fixture: str) -> tuple[Path, Any]:
    directory.mkdir(exist_ok=True)
    path = directory / fixture
    path.write_bytes(base64.decodebytes((FIXTURES / f"{fixture}.b64").read_bytes()))
    parsed = cast("_MutagenReader", mutagen).File(path)
    assert parsed is not None
    if parsed.tags is None:
        parsed.add_tags()
    return path, parsed


@pytest.mark.parametrize("value", [0, 1])
def test_native_id3_podcast_flag(tmp_path: Path, value: int) -> None:
    selected = tmp_path / "media"
    _, parsed = media_file(selected, "tone.mp3")
    parsed.tags.add(PCST(value=value))  # type: ignore[no-untyped-call]
    parsed.save()
    track = scan_twice(tmp_path)
    assert track.media_kind is (MediaKind.PODCAST if value else MediaKind.MUSIC)
    assert track.metadata.podcast is bool(value)


@pytest.mark.parametrize("fixture", ["tone.mp3", "tone.wav", "tone.aiff"])
def test_native_id3_descriptive_fields(tmp_path: Path, fixture: str) -> None:
    path, parsed = media_file(tmp_path / "media", fixture)
    for name, value in {
        "TIT2": "Tagged title",
        "TPE1": "Artist",
        "TALB": "Album",
        "TPE2": "Album artist",
        "TCON": "(17)",
        "TDRC": "2024-05-17",
        "TDRL": "2024-06-01T12:30:00",
        "TRCK": "3/12",
        "TPOS": "2/3",
        "TCOM": "Composer",
        "TBPM": "123",
        "TCMP": "1",
        "TIT1": "Grouping",
        "TIT3": "Subtitle",
        "TCOP": "Copyright",
        "TSOP": "Artist sort",
        "TSOT": "Title sort",
        "TSOA": "Album sort",
        "TSO2": "Album artist sort",
        "TSOC": "Composer sort",
        "TCAT": "Arts",
        "TDES": "Episode description",
        "TKWD": "audio,interview",
    }.items():
        parsed.tags.add(getattr(FRAMES, name)(encoding=3, text=[value]))
    parsed.tags.add(FRAMES.WFED(url="https://example.test/feed.xml"))
    parsed.tags.add(
        FRAMES.USLT(encoding=3, lang="eng", desc="", text="  Verse one\nVerse two\n")
    )
    parsed.tags.add(
        FRAMES.USLT(encoding=3, lang="eng", desc="translation", text="Other lyrics")
    )
    parsed.tags.add(
        FRAMES.COMM(encoding=3, lang="eng", desc="iTunNORM", text=["technical data"])
    )
    parsed.tags.add(FRAMES.COMM(encoding=3, lang="eng", desc="", text=["A comment"]))
    parsed.tags.add(FRAMES.POPM(email="player@example.test", rating=196, count=999))
    for name, value in {
        "REPLAYGAIN_TRACK_GAIN": "-6.25 dB",
        "ITUNESADVISORY": "2",
        "SHOW": "A show",
        "EPISODE_ID": "S02E03",
        "SEASON": "2",
        "EPISODE": "3",
        "NETWORK": "A network",
        "SORT_SHOW": "Show sort",
    }.items():
        parsed.tags.add(FRAMES.TXXX(encoding=3, desc=name, text=[value]))
    parsed.save()
    original = path.read_bytes()
    track = scan_twice(tmp_path)
    assert path.read_bytes() == original
    assert (track.title, track.artist, track.album, track.album_artist) == (
        "Tagged title",
        "Artist",
        "Album",
        "Album artist",
    )
    assert (track.genre, track.year, track.track_number, track.rating) == (
        "Rock",
        2024,
        3,
        80,
    )
    assert track.play_count == 0  # A POPM counter is not device listening history.
    assert (track.show, track.episode, track.season_number, track.episode_number) == (
        "A show",
        "S02E03",
        2,
        3,
    )
    meta = track.metadata
    assert (meta.total_tracks, meta.disc_number, meta.total_discs) == (12, 2, 3)
    assert (meta.composer, meta.comment, meta.grouping, meta.subtitle) == (
        "Composer",
        "A comment",
        "Grouping",
        "Subtitle",
    )
    assert meta.compilation and meta.bpm == 123
    assert meta.release_date == int(
        datetime(2024, 6, 1, 12, 30, tzinfo=UTC).timestamp()
    )
    assert meta.normalization_gain_db == -6.25
    assert meta.content_advisory is ContentAdvisory.CLEAN
    assert meta.lyrics == "  Verse one\nVerse two\n" and meta.has_lyrics
    assert (
        meta.sort_title,
        meta.sort_artist,
        meta.sort_album,
        meta.sort_album_artist,
        meta.sort_composer,
        meta.sort_show,
    ) == (
        "Title sort",
        "Artist sort",
        "Album sort",
        "Album artist sort",
        "Composer sort",
        "Show sort",
    )
    assert meta.podcast_rss_url == "https://example.test/feed.xml"
    assert (
        meta.category,
        meta.tv_network,
        meta.copyright,
        meta.description,
        meta.track_keywords,
    ) == ("Arts", "A network", "Copyright", "Episode description", "audio,interview")


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (9, MediaKind.MOVIE),
        (10, MediaKind.TV_SHOW),
        (6, MediaKind.MUSIC_VIDEO),
        (21, MediaKind.PODCAST),
    ],
)
def test_mp4_video_fields(tmp_path: Path, kind: int, expected: MediaKind) -> None:
    _, parsed = media_file(tmp_path / "media", "multi-track.m4v")
    parsed.tags.update(
        {
            "stik": [kind],
            "tvsh": ["Series"],
            "tven": ["S02E07"],
            "tvsn": [2],
            "tves": [7],
            "tvnn": ["Network"],
            "sosn": ["Series sort"],
            "ldes": ["Long description"],
            "desc": ["Short description"],
            "©lyr": ["Line one\nLine two"],
            "cpil": True,
            "pgap": True,
            "rtng": [4],
            "tmpo": [120],
            "trkn": [(3, 10)],
            "disk": [(1, 2)],
            "purl": ["https://example.test/feed"],
            "catg": ["TV"],
            "keyw": ["episode"],
            "apID": ["account@example.test"],
            "ownr": ["Purchaser"],
            "----:com.apple.iTunes:replaygain_track_gain": [MP4FreeForm(b"-4.5 dB")],  # type: ignore[no-untyped-call]
        }
    )
    parsed.save()
    track = scan_twice(tmp_path)
    assert track.media_kind is expected
    assert (track.show, track.episode, track.season_number, track.episode_number) == (
        "Series",
        "S02E07",
        2,
        7,
    )
    assert track.metadata.description == "Long description"
    assert (track.metadata.tv_network, track.metadata.sort_show) == (
        "Network",
        "Series sort",
    )
    assert track.metadata.lyrics == "Line one\nLine two"
    assert track.metadata.compilation and track.metadata.gapless_album
    assert track.metadata.content_advisory is ContentAdvisory.EXPLICIT
    assert track.rating == 0  # rtng is content advisory, never stars.
    assert track.metadata.normalization_gain_db == -4.5
    assert (
        track.track_number,
        track.metadata.total_tracks,
        track.metadata.disc_number,
        track.metadata.total_discs,
    ) == (3, 10, 1, 2)
    assert track.metadata.podcast is (kind == 21)
    assert track.metadata.podcast_rss_url == "https://example.test/feed"
    assert track.metadata.purchase_account == "account@example.test"
    assert track.metadata.purchaser_name == "Purchaser"


@pytest.mark.parametrize("lyric_tag", ["LYRICS", "UNSYNCEDLYRICS", "UNSYNCED LYRICS"])
def test_vorbis_comment_aliases(tmp_path: Path, lyric_tag: str) -> None:
    _, parsed = media_file(tmp_path / "media", "surround.flac")
    parsed.tags.update(
        {
            lyric_tag: ["  First line\nSecond line\n"],
            "ALBUM ARTIST": ["Ensemble"],
            "TRACKNUMBER": ["4"],
            "TRACKTOTAL": ["12"],
            "DISCNUMBER": ["2"],
            "DISCTOTAL": ["3"],
            "COMPOSER": ["Composer"],
            "BPM": ["90"],
            "COMPILATION": ["true"],
            "ARTISTSORT": ["Artist sort"],
            "REPLAYGAIN_TRACK_GAIN": ["+1.25 dB"],
            "MEDIA_TYPE": ["Podcast"],
            "PODCASTURL": ["https://example.test/feed"],
        }
    )
    parsed.save()
    assert embedded_lyrics(parsed) == "  First line\nSecond line\n"
    track = scan_twice(tmp_path)
    assert track.media_kind is MediaKind.PODCAST
    assert track.album_artist == "Ensemble"
    assert (
        track.metadata.lyrics == "  First line\nSecond line\n"
        and track.metadata.has_lyrics
    )
    assert (
        track.track_number,
        track.metadata.total_tracks,
        track.metadata.disc_number,
        track.metadata.total_discs,
    ) == (4, 12, 2, 3)
    assert track.metadata.composer == "Composer" and track.metadata.bpm == 90
    assert track.metadata.compilation and track.metadata.sort_artist == "Artist sort"
    assert track.metadata.normalization_gain_db == 1.25


def test_invalid_optional_values_do_not_erase_valid_tags() -> None:
    track = apply_tag_values(
        Track(1, "Fallback", "", "", 100),
        read_tag_values(
            {
                "title": ["Title"],
                "BPM": ["NaN"],
                "TRACKNUMBER": ["-1"],
                "SEASON": ["9" * 5000],
                "REPLAYGAIN_TRACK_GAIN": ["inf"],
                "COMPILATION": ["false"],
                "DATE": ["not a date"],
                "UNSYNCEDLYRICS": ["Lyrics"],
            }
        ),
        suffix=".flac",
        video=False,
    )
    assert track.title == "Title" and track.metadata.lyrics == "Lyrics"
    assert (
        track.metadata.bpm
        == track.track_number
        == track.season_number
        == track.year
        == 0
    )
    assert track.metadata.normalization_gain_db is None
    assert not track.metadata.compilation


def test_ape_and_asf_text_wrappers_and_lyrics_precedence() -> None:
    ape: Any = APEv2()  # type: ignore[no-untyped-call]
    ape["Artist"] = "First artist\0Second artist"
    ape["UNSYNCEDLYRICS"] = "Fallback lyrics"
    ape["LYRICS"] = "Preferred lyrics"
    values = {tag.name: tag.value for tag in read_tag_values(ape)}
    assert values["artist"] == "First artist"
    assert values["lyrics"] == "Preferred lyrics"
    asf: Any = ASFUnicodeAttribute
    values = {
        tag.name: tag.value
        for tag in read_tag_values(
            {
                "WM/Lyrics": [asf("ASF lyrics")],
                "Author": [asf("Author")],
                "WM/AlbumArtist": [asf("Album artist")],
            }
        )
    }
    assert values["lyrics"] == "ASF lyrics" and values["artist"] == "Author"
    assert values["album_artist"] == "Album artist"


def test_synchronized_lyrics_are_not_misrepresented_as_plain_text() -> None:
    tags: Any = FRAMES.ID3()
    tags.add(
        FRAMES.SYLT(
            encoding=3, lang="eng", format=2, type=1, desc="", text=[("Word", 0)]
        )
    )
    assert "lyrics" not in {tag.name for tag in read_tag_values(tags)}
    tags.add(FRAMES.USLT(encoding=3, lang="eng", desc="", text=""))
    tags.add(FRAMES.USLT(encoding=3, lang="fra", desc="translated", text="Paroles"))
    assert {tag.name: tag.value for tag in read_tag_values(tags)}["lyrics"] == "Paroles"


def test_sound_check_and_fractional_bpm() -> None:
    native: Any = FRAMES.ID3()
    native.add(FRAMES.COMM(encoding=3, lang="eng", desc="", text=["User comment"]))
    native.add(
        FRAMES.COMM(
            encoding=3,
            lang="eng",
            desc="iTunNORM",
            text=["000007D0 000003E8 " + "00000000 " * 8],
        )
    )
    native.add(FRAMES.TBPM(encoding=3, text=["120.5"]))
    track = apply_tag_values(
        Track(1, "", "", "", 1), read_tag_values(native), suffix=".mp3", video=False
    )
    assert track.metadata.normalization_gain_db == pytest.approx(-3.0102999566)
    assert track.metadata.comment == "User comment" and track.metadata.bpm == 120
    native.add(FRAMES.TXXX(encoding=3, desc="REPLAYGAIN_TRACK_GAIN", text=["-1 dB"]))
    track = apply_tag_values(
        Track(1, "", "", "", 1), read_tag_values(native), suffix=".mp3", video=False
    )
    assert track.metadata.normalization_gain_db == -1


def test_freeform_text_encoding_and_binary_rejection() -> None:
    freeform: Any = MP4FreeForm
    tags = {
        "----:com.apple.iTunes:UNSYNCEDLYRICS": [
            freeform(
                "Paroles 日本語".encode("utf-16-be"), dataformat=AtomDataType.UTF16
            )
        ],
        "----:com.apple.iTunes:REPLAYGAIN_TRACK_GAIN": [
            freeform(b"-4 dB", dataformat=AtomDataType.IMPLICIT)
        ],
        "----:com.apple.iTunes:ARTISTSORT": [freeform(b"\xff\xff")],
    }
    values = {tag.name: tag.value for tag in read_tag_values(tags)}
    assert values == {"lyrics": "Paroles 日本語"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2024", datetime(2024, 1, 1, tzinfo=UTC)),
        ("2024-05", datetime(2024, 5, 1, tzinfo=UTC)),
        ("1960-01-01", datetime(1960, 1, 1, tzinfo=UTC)),
        ("2024-05-17T01:00:00+02:00", datetime(2024, 5, 16, 23, tzinfo=UTC)),
    ],
)
def test_release_dates_do_not_depend_on_host_timezone(
    value: str, expected: datetime
) -> None:
    track = apply_tag_values(
        Track(1, "", "", "", 1),
        read_tag_values({"date": value}),
        suffix=".flac",
        video=False,
    )
    assert track.metadata.release_date == int(
        (expected - datetime(1970, 1, 1, tzinfo=UTC)).total_seconds()
    )


def test_enrichment_keeps_reviewed_values_and_specialized_classification() -> None:
    reviewed = Track(
        1,
        "Reviewed title",
        "Reviewed artist",
        "",
        100,
        media_types=(MediaType.TV_SHOW,),
        show="Reviewed show",
        metadata=TrackMetadata(lyrics="Reviewed lyrics", normalization_gain_db=0.0),
    )
    enriched = apply_tag_values(
        reviewed,
        read_tag_values(
            {
                "title": ["Source title"],
                "show": ["Source show"],
                "lyrics": ["Source lyrics"],
                "REPLAYGAIN_TRACK_GAIN": ["-4 dB"],
                "tvnetwork": ["Network"],
            }
        ),
        suffix=".mp4",
        video=True,
        fill_only=True,
    )
    assert enriched == replace(
        reviewed,
        metadata=replace(reviewed.metadata, has_lyrics=True, tv_network="Network"),
    )


@pytest.mark.parametrize("suffix", [".mp4", ".mkv"])
def test_video_container_tags_without_audio(tmp_path: Path, suffix: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None or shutil.which("ffprobe") is None:
        pytest.skip("Video container fixtures require FFmpeg and FFprobe")
    source = tmp_path / "source.mp4"
    source.write_bytes(base64.decodebytes((FIXTURES / "silent.mp4.b64").read_bytes()))
    selected = tmp_path / "media"
    selected.mkdir()
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(source),
            "-c",
            "copy",
            "-metadata",
            "title=Video title",
            "-metadata",
            "media_type=10",
            "-metadata",
            "show=Series",
            "-metadata",
            "season_number=2",
            "-metadata",
            "episode_sort=3",
            "-metadata",
            "episode_id=S02E03",
            str(selected / f"episode{suffix}"),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    track = scan_twice(tmp_path)
    assert track.title == "Video title" and track.media_kind is MediaKind.TV_SHOW
    assert (track.show, track.season_number, track.episode_number, track.episode) == (
        "Series",
        2,
        3,
        "S02E03",
    )
    assert track.length_ms > 0 and track.metadata.sample_rate_hz == 0


def test_old_cache_is_rebuilt_for_new_tag_interpretation(tmp_path: Path) -> None:
    _, parsed = media_file(tmp_path / "media", "tone.mp3")
    parsed.tags.add(FRAMES.PCST(value=1))
    parsed.save()
    scan_twice(tmp_path)
    cache = tmp_path / "cache.json"
    document = json.loads(cache.read_text(encoding="utf-8"))
    document["version"] = 8
    cache.write_text(json.dumps(document), encoding="utf-8")
    scanner = HostMediaScanner(AtomicHostFile(cache), fingerprinter=Fingerprinter())
    pending = scanner.scan(
        (create_host_media_folder(tmp_path / "media"),), checkpoint=lambda: None
    )
    assert pending.cache.inspected == 1 and pending.cache.reused == 0
    assert (
        scanner.complete(pending, frozenset(), checkpoint=lambda: None)
        .snapshot.tracks[0]
        .media_kind
        is MediaKind.PODCAST
    )


def test_unavailable_probe_retains_basic_file_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = tmp_path / "media"
    selected.mkdir()
    (selected / "source.mkv").write_bytes(
        base64.decodebytes((FIXTURES / "source.mkv.b64").read_bytes())
    )

    def unavailable(*args: object, **kwargs: object) -> None:
        raise MediaInspectionError("media.probe_unavailable", "FFprobe missing")

    monkeypatch.setattr(MediaInspector, "inspect", unavailable)
    scanner = HostMediaScanner(fingerprinter=Fingerprinter())
    pending = scanner.scan(
        (create_host_media_folder(selected),), checkpoint=lambda: None
    )
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert len(library.snapshot.tracks) == 1
    assert library.snapshot.tracks[0].title == "source"
    assert any("FFprobe missing" in issue.detail for issue in library.issues)


@pytest.mark.parametrize("fixture", ["tone.mp3", "surround.flac"])
def test_host_tags_reach_verified_sync_and_embedded_lyrics(
    tmp_path: Path, fixture: str
) -> None:
    if any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")):
        pytest.skip("Real Sync preparation requires FFmpeg and FFprobe")
    path, parsed = media_file(tmp_path / "media", fixture)
    if fixture.endswith(".mp3"):
        parsed.tags.add(FRAMES.PCST(value=1))
        parsed.tags.add(
            FRAMES.USLT(
                encoding=3, lang="eng", desc="", text="Native lyrics\nNext line"
            )
        )
        parsed.tags.add(FRAMES.TCOM(encoding=3, text=["Composer"]))
        parsed.tags.add(FRAMES.TSOP(encoding=3, text=["Artist sort"]))
    else:
        parsed.tags.update(
            {
                "PODCAST": ["1"],
                "UNSYNCEDLYRICS": ["Native lyrics\nNext line"],
                "COMPOSER": ["Composer"],
                "ARTISTSORT": ["Artist sort"],
            }
        )
    parsed.save()
    original = path.read_bytes()
    scanner = HostMediaScanner(fingerprinter=Fingerprinter())
    pending = scanner.scan(
        (create_host_media_folder(tmp_path / "media"),), checkpoint=lambda: None
    )
    host = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    device = build_device(tmp_path)
    try:
        result = SyncExecutor(device.coordinator).execute(
            _request(device, host), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        added = next(
            track
            for track in result.active.library.tracks
            if track.metadata.composer == "Composer"
        )
        assert added.media_kind is MediaKind.PODCAST and added.metadata.podcast
        assert added.metadata.sort_artist == "Artist sort" and added.metadata.has_lyrics
        assert (
            embedded_lyrics(
                cast("_MutagenReader", mutagen).File(
                    device.root / added.metadata.location
                )
            )
            == "Native lyrics\nNext line"
        )
        assert path.read_bytes() == original
    finally:
        device.coordinator.close()
