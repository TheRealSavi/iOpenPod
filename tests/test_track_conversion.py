from iopenpod.sync._track_conversion import (
    ipod_filetype_for_extension,
    pc_track_to_info,
    track_dict_to_info,
)
from iopenpod.sync.pc_library import PCTrack


def _video_track() -> PCTrack:
    return PCTrack(
        path="/library/caption_probe.mov",
        relative_path="caption_probe.mov",
        filename="caption_probe.mov",
        extension=".mov",
        mtime=0.0,
        size=1,
        title="Caption probe",
        artist="Artist",
        album="Album",
        album_artist=None,
        genre=None,
        year=None,
        track_number=None,
        track_total=None,
        disc_number=None,
        disc_total=None,
        duration_ms=1_000,
        bitrate=None,
        sample_rate=None,
        rating=None,
        is_video=True,
    )


def test_mov_video_uses_m4v_itunesdb_filetype() -> None:
    info = pc_track_to_info(
        _video_track(),
        ":iPod_Control:Music:F00:CAPT.mov",
        was_transcoded=False,
    )

    assert info.filetype == "m4v"


def test_mov_extension_uses_m4v_itunesdb_filetype() -> None:
    assert ipod_filetype_for_extension(".mov") == "m4v"


def test_existing_mov_filetype_is_read_as_an_ipod_video() -> None:
    info = track_dict_to_info({"Title": "Caption probe", "Location": ":iPod_Control:Music:F00:CAPT.mov", "filetype": "MOV"})

    assert info.filetype == "m4v"
