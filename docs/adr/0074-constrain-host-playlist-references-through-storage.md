# ADR-0074: Constrain Host Playlist references through Storage

- Status: Accepted
- Date: 2026-09-24
- Extends: ADR-0031 and ADR-0063

Host Playlist documents supply untrusted file references, not filesystem authority.
The Application Layer parses bounded bytes into ordered references; Storage owns
local path validation, regular-file observations, bounded reads, and private
captures. This preserves Storage's independence from Playlist formats while keeping
untrusted paths out of direct application file reads.

The Host Media Scan supports M3U/M3U8, PLS, XSPF, WPL, and ASX/WAX/WVX. It preserves
Track order and duplicate occurrences, uses document titles when supplied, and
accepts relative paths and local file URIs. XSPF honors XML Base and chooses the first
allowed local location from each Track's alternatives. ASX uses static ENTRY/REF
membership; dynamic events, nested Playlist references, and repeat directives do not
expand membership. WPL imports media entries in document order. Network URLs, remote
file authorities, UNC/device paths, alternate data streams, and reserved Windows
names are rejected. Windows mapped network drives are unavailable as indirect
targets. Ordinary paths are not percent-decoded or shell-expanded; file URIs are
decoded once. The stricter policy deliberately does not carry forward the Original
iOpenPod's remote-authority fallback and speculative path probing.

Playlist reads are limited to 8 MiB before allocation and during reading. Parsing
limits entries to 100,000 and XML to 64 levels and 500,000 elements. XML DTDs and
entity declarations are rejected by the parser, including UTF-16 documents. HLS
manifests are rejected. Parsing and capture honor cancellation. Malformed documents
remain empty Playlists with scan issues, so one bad file does not erase the rest of
the Host Media Library. Fingerprinting explicitly selects a single-file demuxer
instead of allowing a disguised Playlist to trigger decoder format autodetection.
This is not a sandbox for defects in third-party media decoders.

The review boundary is the actual selected media catalog, including media-type and
recursion settings. Files within a chosen folder can therefore still need approval.
The dialog starts with no files accepted, lists referencing Playlists and availability,
and supports individual decisions, Accept All, Deny All, and Cancel Scan. Only
available, supported audio/video files can be approved. Approval is scoped to this
scan and to each file's observed identity, size, and modification time. Cached
metadata never grants approval. Photos, nested Playlists, directories, missing files,
and unsafe paths cannot expand access through this dialog.

Storage rejects symbolic links and reparse points in every path component. Reads
pin directory components with descriptors on POSIX and non-delete-sharing handles
on Windows. Approved external files are copied through Storage into private temporary
files before metadata and fingerprint inspection. This costs temporary disk space
proportional to one accepted file at a time but prevents a path replacement from
redirecting the inspector. External media authorizes embedded artwork only, not
neighboring images. Later lazy reads of that embedded artwork retain the same
Storage observation and use its pinned read-only stream. Changes before inspection are reported and omitted; changes
before final publication invalidate the result. The selected catalog is rechecked
after the review pause. The existing cheap cache discriminator still does not
authenticate hostile in-place edits that preserve all observed file facts.

The same Storage boundary now covers selected-folder enumeration, Track metadata,
folder artwork, Photos, and their lazy display reads. Storage returns generic
directory entries and owns validated, seekable read-only streams; the Application
Layer classifies media and parses these streams or already-captured bytes. Parsers
never receive a Host filename to open themselves. Storage checks identity and file
facts before and after reads and owns cancellation and closure, avoiding mandatory
whole-file copies for ordinary metadata inspection. Fingerprint processes and
temporary device-scan captures also run through Storage-owned lifetimes.

Host Media Scan Cache v6 invalidates earlier Playlist interpretations and decoder
results. Its discriminated schema remains unchanged. General Sync execution and
publication of new Playlists to an iPod remain outside this Host Media Scan change.

Format evidence: the [XSPF specification](https://www.xspf.org/spec) defines ordered
Tracks, alternative locations, and XML Base; Microsoft's
[Windows Media metafile reference](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/wmp/windows-media-metafile-elements-reference)
defines ASX ENTRY/REF membership. The
[Chromaprint command source](https://github.com/acoustid/chromaprint/blob/master/src/cmd/fpcalc.cpp)
documents and implements the explicit input-format option. Original iOpenPod's
`playlist_parser.py` and its tests supplied the M3U/PLS/XSPF behavioral baseline;
there is no runtime dependency on that project.
