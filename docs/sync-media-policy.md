# Sync media preparation policy

> Historical implementation record: this document includes a recipe/cache and
> encoder policy not present in the current source. Current post-Review execution
> follows [ADR-0076](adr/0076-execute-reviewed-sync-through-storage.md). The earlier
> behavior and validation claims below are retained as research, not as evidence
> that the current execution path implements or tests each capability.

Current Sync automatically converts incompatible video for the Active iPod using
H.264 Baseline with the fixed `medium` preset and CRF `23`, matching the Original
iOpenPod's defaults. There are no video encoder settings. The Device Profile supplies
resolution, frame-rate, H.264 level, and bitrate limits; its bitrate ceiling and a
buffer twice that size constrain CRF output. Compatible video streams can be copied
without re-encoding. iPods without video support reject video items. The conservative
5th/5.5th-generation bounds described below remain in effect.

## Historical policy

Device Registry supplies encoding bounds. Conversion resolves one immutable recipe
from observed streams, effective settings, and the installed FFmpeg encoders. The
recipe captures encoder identity, exact stream selection, arguments, device limits,
and output estimates. An explicitly selected unavailable encoder blocks the item.
Lossy input is never promoted to lossless solely because lossless is preferred.

Audio defaults retain supported audio, convert WAV to ALAC when supported, and use
Auto encoder preference FDK AAC, AudioToolbox AAC, native AAC, LAME MP3, then Shine
MP3 when lossy conversion is required. Supported lossless preparation uses 16-bit
mono/stereo output at supported rates no greater than 48 kHz. This continues the
bounded import policy from ADR-0032 and the Original implementation. AAC output
uses LC; quality scales are encoder-specific. Spoken-word mono and 64 kb/s apply
when conversion occurs. They do not force an otherwise unnecessary conversion.
The installed encoder's reported sample rates constrain conversion output. An
unsupported rate is reduced to an available rate within device limits; when an
encoder requires upsampling, 44.1 kHz is preferred. Explicit 44.1 kHz forcing must
remain effective, including for 48 kHz sources.

Planning rejects Shine's locally failing 32 kHz, mono, 192 kb/s combination with a
diagnostic offering 44.1 kHz or another encoder. MP3 targets below 32 kHz cannot
exceed 160 kb/s. AAC LC targets cannot exceed six times sample rate times channels
in bits per second, consistent with the 6144-bit-per-channel, 1024-sample frame
limit enforced by FFmpeg's
[AAC encoder](https://github.com/FFmpeg/FFmpeg/blob/master/libavcodec/aacenc.c).
These checks apply after sample-rate and channel resolution, including spoken-word
mono and video audio. Invalid requests block the affected item during review.

Video output uses H.264 Baseline, square pixels, aspect-preserving even dimensions,
no cropping or upscaling, and a frame rate no greater than 30 fps. The default
audio stream wins, otherwise the first. Subtitle losses appear in review. The
fifth-generation output policy uses the conservative 320-by-240 Baseline Level 1.3
mode at 768 kb/s documented by the Original device research. The separate VGA
low-complexity mode requires additional firmware/bitstream evidence and is not
inferred from the generic Level 3.0 label previously in the catalog.

Differing nominal and average frame rates prevent direct copying. Conversion uses
an explicit constant rational frame rate bounded by the Device Profile, preserving
the nominal rate when it is lower. Review reports the timing change. Independent
output inspection checks both nominal and average rates against the device limit;
an average below that limit does not excuse faster bursts.

Apple documents Baseline Level 3.0, 640-by-480 H.264 and a 2.5 Mb/s ceiling for the
[fourth-generation nano](https://support.apple.com/en-ca/112320). The current
third/fourth-generation conversion policies retain their existing conservative
dimension and bitrate bounds. Fifth-generation nano preparation uses its VGA
Baseline policy, with the same bounded 2.5 Mb/s ceiling; Apple's
[launch documentation](https://www.apple.com/newsroom/2009/09/09Apple-Introduces-New-iPod-nano-With-Built-in-Video-Camera/)
also evidences H.264 VGA playback. The
[seventh-generation specification](https://support.apple.com/en-us/112039)
allows 720-by-576 H.264 at Level 3.0 but does not give an H.264 bitrate ceiling.
The application chooses a conservative 2.5 Mb/s encoder ceiling for that profile;
this is an output policy, not a claim about the maximum decoder bitrate. Video
audio currently uses a conservative 160 kb/s compatibility bound and 128 kb/s
conversion target.

Supported `mov_text` subtitles are stream-copied. Retained chapter counts, titles,
and boundaries (within two milliseconds of muxer rounding) are independently
checked. Formats that cannot retain chapters and omitted alternate media streams
produce review diagnostics. Verification rejects lost chapters/subtitles and
truncated outputs before publication.

Recipes use the installed FFmpeg options documented by its
[encoders](https://ffmpeg.org/ffmpeg-codecs.html) and
[filters](https://ffmpeg.org/ffmpeg-filters.html). Every prepared output is inspected
independently before use. Cache keys include source SHA-256, complete recipe, and
encoder identity. Cache hits verify artifact bytes and metadata; publication still
requires reviewed Host/device preconditions. Pinned entries cannot be evicted.

Back Sync supports ID3 POPM plus namespaced TXXX history, MP4 iTunes freeform fields,
and FLAC/Ogg Vorbis/Opus comments. Rating values use the common 0-100 scale; ID3
POPM uses explicit Windows Media Player star mapping and a rounded 0-255 mapping
for generic owners. The last written per-owner observations detect subsequent
external rating/count changes without the application's own POPM masking them.
Conflicting concurrent owner changes are reported rather than silently chosen.
Count and timestamp tag names and mappings
are explicit in the shared tag transformer. Unrelated tags and media payloads
remain unchanged. Format support does not imply that every third-party player
reads these history fields.

Automated fixtures currently exercise compatible MP3 copying, WAV/FLAC-to-ALAC,
native AAC, silent H.264 conversion, cache reuse and pinning, and MP3/MP4/WAV/FLAC
history payload preservation. No physical-device playback validation is implied.
The local encoder/rate-control matrix additionally exercises FDK AAC CBR/VBR,
AudioToolbox CBR/VBR/ABR/CVBR, native AAC CBR, LAME CBR/VBR/ABR, and Shine CBR.
Recipe resolution is deterministic; independent inspection checks output duration
and audio bitrate as well as stream/container facts. Exhaustive settings boundaries,
representative media coverage and supported-device hardware records remain
validation work.
See [Sync validation](sync-validation.md) for the exercised combinations and known
backend limits; encoder advertisement alone is not playback validation.
