# ADR-0031: Inspect captured Host media before planning imports

- Status: Accepted
- Date: 2026-09-11
- Extends: ADR-0021 and ADR-0030

Incoming media needs observed stream/container facts before the application can
decide whether to copy, convert, or reject it for a Device Profile. These facts are
distinct from a Track's requested Library classification and from native iTunesDB
encoding. An audiobook, Podcast, or movie cannot be identified from its extension
alone. Embedded cover images also appear as video streams. Inspect every stream;
retain sample entries, dispositions, channels, sample precision, profile/level,
dimensions, rates, timing, chapters, and tags as typed immutable values. Missing
facts remain absent. Integer ticks and rational time bases preserve exact timing.

The pure Library API accepts these distinctions through keyword-only
`PreparedMedia.content: MediaContent`, with the existing audio contract as its
default. Audio and audio/video require positive duration and audio sample rate;
silent video requires positive duration with zero audio timing; documents require
zero duration and audio timing. Content without audio cannot carry sample counts,
gapless flags, delay/padding, or an audio payload size. Embedded covers are not timed
video. Library categories remain independent: the caller supplies observed content
and native codec facts, and the application owns target compatibility. Unrelated
metadata edits do not revalidate or repair retained source timing.

Storage streams an explicitly selected Host file into a private temporary snapshot
and records its content hash and source fingerprint. The Application Layer probes
that snapshot, then Storage removes it on success, failure, or cancellation.
This costs temporary disk space proportional to the file, but the inspector cannot
observe different source bytes while a user edits the original. Later publication
must verify the captured hash again; the temporary path is never save authority.

FFprobe supplies audio/video/container observations through one application
`MediaInspector.inspect` interface. An explicit executable path or PATH discovery
is used without shell execution, downloads, or hard-coded installation locations.
The process has cancellation, a deadline, bounded stdout/stderr, and Windows hidden
launching. Only selected single-file demuxers and the file protocol are allowed;
playlist/network indirection is not part of this file inspection operation.
MOV external data references remain disabled. This adds an executable requirement
for incoming-media inspection without adding or replacing a Python dependency.
FFprobe is not needed to browse or edit already-loaded Library metadata.

The [FFprobe documentation](https://ffmpeg.org/ffprobe.html) describes per-stream
output and attached-picture distinctions. The [MOV demuxer documentation](https://ffmpeg.org/ffmpeg-formats.html#mov_002fmp4_002f3gp)
documents external-reference behavior. Original iOpenPod provides additional
evidence for audio limits and subtitle sample-entry checks, but its decisions are
not copied as authoritative format or capability rules.

Successful inspection is not full-file decode verification, DRM authorization,
device compatibility, gapless payload analysis, or an import plan. Device policy,
media conversion, native codec mapping, incoming-file transaction composition,
Library drafting/UI integration, and non-stream document media such as PDF/EPUB
were separate future work when this decision was accepted. ADR-0032 subsequently
adds bounded music policy, native mapping, drafts, and transaction composition;
music import UI, conversion, and the Sync engine remain unimplemented. Generic iTunesDB
media classifications do not by themselves establish that any target iPod can play
or display a file.
