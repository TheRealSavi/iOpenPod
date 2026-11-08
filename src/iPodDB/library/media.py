"""Native audio facts from observed encoding and explicit audiobook intent."""

from enum import StrEnum

from iPodDB.library.writing import FileDependency, MediaContent, PreparedMedia


class AudioEncoding(StrEnum):
    MP3 = "mp3"
    AAC = "aac"
    ALAC = "alac"
    WAV = "wav"
    AIFF = "aiff"


def prepared_audio(
    track_id: int,
    file: FileDependency,
    encoding: AudioEncoding,
    *,
    audiobook: bool = False,
) -> PreparedMedia:
    """Encode observed audio facts without claiming unmeasured gapless data.

    Filetype/format flags follow Original iOpenPod's constants/mhit_writer;
    MPEG types 12 (MP3) and 51 (AAC) follow libgpod's itdb_track_set_defaults.
    AAC in an audiobook container is still AAC, never the Audible codec.
    AAC Audiobooks use M4B; ALAC retains the M4A/zero-MPEG-type lossless convention.
    Both can have an M4B filename without changing their codec flags.
    """
    code, mp3, av, mpeg = {
        AudioEncoding.MP3: (b"MP3 ", 1, 0xFFFF, 12),
        AudioEncoding.AAC: (b"M4A ", 0, 0xFFFF, 51),
        AudioEncoding.ALAC: (b"M4A ", 0, 0xFFFF, 0),
        AudioEncoding.WAV: (b"WAV ", 0, 0, 0),
        AudioEncoding.AIFF: (b"AIFF", 0, 0, 0),
    }[encoding]
    if audiobook and encoding is AudioEncoding.AAC:
        code = b"M4B "
    return PreparedMedia(track_id, file, int.from_bytes(code, "big"), mp3, av, mpeg, 0)


def prepared_video(
    track_id: int, file: FileDependency, *, has_audio: bool
) -> PreparedMedia:
    """Native facts for independently verified H.264/AAC video in an M4V container."""
    return PreparedMedia(
        track_id,
        file,
        int.from_bytes(b"M4V ", "big"),
        0,
        0xFFFF,
        51 if has_audio else 0,
        0,
        content=MediaContent.AUDIO_VIDEO if has_audio else MediaContent.VIDEO,
    )
