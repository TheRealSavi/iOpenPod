# Synthetic incoming-media fixtures

These base64-encoded files contain generated tones, silence, solid colors, an
embedded image, chapter labels, and subtitle text. They contain no downloaded or
device-owned media. Regenerate with `uv run scripts/generate_media_fixtures.py`
using a locally installed FFmpeg. `generator.json` records the generating version;
encoded bytes may change between versions and should be reviewed.

| Fixture | Purpose |
| --- | --- |
| `tone.wav`, `tone.aiff` | PCM endianness, sample rate, channels, duration |
| `tone.mp3` | MPEG audio independently of its filename |
| `tone-vbr.mp3` | Observed VBR mode must reach the native VBR flag |
| `tone.m4a` | AAC LC, tags and exact stream timing |
| `lossless.m4a` | ALAC in the same container family as AAC |
| `surround.flac` | 96 kHz, six channels and 24-bit source precision; inspection does not imply device support |
| `silent.mp4` | H.264 motion video with no audio and a 30000/1001 frame rate |
| `source.mkv` | Incoming video in a container that needs a separate device decision |
| `chapters-cover.m4a` | Attached artwork is not a movie; exact chapter intervals |
| `multi-track.mov` | Two audio languages and a QuickTime `text` subtitle sample entry |
| `multi-track.m4v` | The same stream codec with an MP4 `tx3g` sample entry |

The public inspector tests use the real FFprobe executable when installed and skip
those cases otherwise. Parser fault tests and process timeout/output/cancellation
tests do not require FFprobe. All inputs are copied to misleading `.bin` filenames
before inspection. These are inspection fixtures, not universal codec compatibility
or firmware playback evidence.
