"""Choose firmware-facing filenames from encoding and Library classification."""

from iPodDB.library import AudioEncoding, MediaKind


def audio_file_details(encoding: AudioEncoding, kind: MediaKind) -> tuple[str, str]:
    extension, description = {
        AudioEncoding.MP3: ("mp3", "MPEG audio file"),
        AudioEncoding.AAC: ("m4a", "AAC audio file"),
        AudioEncoding.ALAC: ("m4a", "Apple Lossless audio file"),
        AudioEncoding.WAV: ("wav", "WAV audio file"),
        AudioEncoding.AIFF: ("aiff", "AIFF audio file"),
    }[encoding]
    if kind is MediaKind.AUDIOBOOK and encoding in (
        AudioEncoding.AAC,
        AudioEncoding.ALAC,
    ):
        extension = "m4b"
    return extension, description
