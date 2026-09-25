# iTunesDB lyrics and embedded media metadata

## Scope and sources

Investigated on 2026-09-24. This note separates database-format evidence from
media-tag behavior and firmware compatibility. It does not establish that lyrics
are the only embedded metadata consumed by every stock iPod generation.

The source revisions examined were:

- libgpod: `gtkpod/libgpod` commit
  `7982c5554f78dde47fd006afbeff659201d6db3d` (2012-05-04).
- GTKpod: `gtkpod/gtkpod` commit
  `63a725df4e0a4bfc0c07e0b208c14280e9b2c285` (2014-08-17).
- Original iOpenPod: local commit
  `a20242428b93b672d14b37230772dbad75139c69`.

Context7 was queried for libgpod twice but returned unrelated libraries. The
investigation therefore used the upstream source repositories. Context7 supplied
Mutagen's own ID3 documentation for the encoding and conversion caveats below.

## The database flag and the media text are separate

libgpod documents `Itdb_Track.lyrics_flag` as presence of an MP3 `USLT` frame or
an MP4 lyrics atom, with `1` for present and `0` for absent. Its parser reads a
single byte at MHIT offset 176 (`0xB0`), and its writer emits that flag. The Track
structure does not contain a lyrics text member. The supported MHOD enumeration
and Track writer have no type-10 lyrics-text implementation. This establishes the
flag's purpose; it does **not** prove that retained type-10 Chunks are invalid or
may be discarded.
[Track definition](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb.h#L1479-L1482),
[parser](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L2563),
[writer](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L4046),
[MHOD definitions](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L167-L180).

In a 2007 support response about a fifth-generation iPod, GTKpod maintainer Todd
Zullinger explains that the firmware consults `lyrics_flag` before reading the
file's lyric tag. Adding the tag without updating the flag is insufficient for
that device. Consequently, writing text only into an iTunesDB MHOD is also not a
complete implementation of this documented display path.
[Maintainer explanation](https://sourceforge.net/p/gtkpod/mailman/message/6159939/).

GTKpod implements lyric writing separately from its general tag-writing option.
`write_lyrics_to_file` first selects the device file; the general `id3_write`
preference controls its fallback to a local file. It invokes the filetype lyric
writer and updates `lyrics_flag` from the write result and nonempty text. A
successful write also invalidates the old file hash. This supports a focused
lyrics pass independent of an optional complete metadata pass. Its failure
handling is historical behavior, not a transaction-safety design to copy.
[Application workflow](https://github.com/gtkpod/gtkpod/blob/63a725df4e0a4bfc0c07e0b208c14280e9b2c285/libgtkpod/file.c#L2140-L2208).

## Native media representations

For MP3, GTKpod reads and writes `USLT`. The ID3v2.3 specification defines its
payload as an encoding byte, three-byte language, terminated content descriptor,
and lyric text, including newlines. Multiple `USLT` frames are legal when their
language/descriptor pairs differ. `SYLT` is a distinct synchronized-lyrics frame;
its presence is not equivalent to the `USLT` path evidenced here.
[GTKpod MP3 implementation](https://github.com/gtkpod/gtkpod/blob/63a725df4e0a4bfc0c07e0b208c14280e9b2c285/plugins/filetype_mp3/mp3file.c#L2836-L2909),
[ID3v2.3 sections 4.9 and 4.10](https://id3.org/id3v2.3.0?action=raw).

For MP4-family containers, GTKpod's AtomicParsley bridge identifies the atom as
`moov.udta.meta.ilst.©lyr.data`, where `©` is byte `0xA9` in the atom name. It
builds an iTunes-style UTF-8 text data atom and removes it for absent/empty lyrics.
This is a container metadata edit; adding ID3 to an MP4 file is not this format.
The bridge is evidence for the representation, not independent proof of every
supported codec or device generation.
[Atom names](https://github.com/gtkpod/gtkpod/blob/63a725df4e0a4bfc0c07e0b208c14280e9b2c285/libs/atomic-parsley/AtomicParsleyBridge.cpp#L45-L63),
[lyrics atom construction](https://github.com/gtkpod/gtkpod/blob/63a725df4e0a4bfc0c07e0b208c14280e9b2c285/libs/atomic-parsley/AtomicParsleyBridge.cpp#L579-L606).

## ID3 encoding and preservation caveats

The examined GTKpod MP3 writer contains a comment claiming the iPod understands
only UTF-8 lyrics. The code nevertheless preserves the selected existing encoding
unless a preference requests an upgrade from Latin-1 to UTF-8. The comment has no
device/firmware matrix or reproducible fixture. It is not enough evidence for a
universal encoding requirement.
[Encoding selection](https://github.com/gtkpod/gtkpod/blob/63a725df4e0a4bfc0c07e0b208c14280e9b2c285/plugins/filetype_mp3/mp3file.c#L2873-L2896).

ID3v2.3 specifies Latin-1 or BOM-prefixed 16-bit Unicode; ID3v2.4 adds UTF-8 and
UTF-16BE. Tag version and text encoding must therefore be considered together.
[ID3v2.3 section 3.3](https://id3.org/id3v2.3.0?action=raw),
[ID3v2.4 frame overview](https://id3.org/id3v2.4.0-frames?action=raw).

Mutagen's default ID3 load/save path upgrades to v2.4. Explicit v2.3 saving
converts UTF-8 text to UTF-16 and joins multiple text values. Version conversion
can also remove frames without a supported equivalent. Therefore, constructing
`USLT(encoding=3)` and then saving with `v2_version=3` does **not** produce UTF-8
lyrics. A focused update must explicitly account for existing tag versions,
unknown frames, ID3v1, artwork, and unrelated text values; a library save is not
automatically byte-preserving outside the changed lyric frame.
[Mutagen ID3 version documentation](https://mutagen.readthedocs.io/en/latest/user/id3.html#id3-versions).

## Original iOpenPod baseline

Original iOpenPod's `sync/rockbox_metadata.py` separates
`write_track_lyrics_metadata` from the complete Rockbox metadata pass. It replaces
MP3 `USLT` or MP4 `©lyr`, removes lyrics for an empty request, skips a matching
value, and returns the resulting file size. The MP3 implementation removes all
`USLT` variants and writes one English, empty-descriptor frame using v2.3. These
are baseline implementation choices; the code's firmware-compatibility and
unrelated-frame-preservation comments are not independent verification.
[Original implementation](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sync/rockbox_metadata.py#L146-L205),
[MP3 writer](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sync/rockbox_metadata.py#L692-L709),
[MP4 writer](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sync/rockbox_metadata.py#L756-L771).

## SQLite and implementation implications

libgpod defines an `Extras.itdb` lyrics table with `item_pid`, `checksum`, and
`lyrics` columns. Its implementation explicitly leaves lyric-table updates
unsupported. This schema is not evidence for a working checksum algorithm or
permission to replace embedded lyrics with SQLite text on later devices.
[Schema](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_sqlite_queries.h#L34),
[unsupported update](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_sqlite.c#L419-L429).

The resulting implementation requirements are inferences from this evidence and
the repository's existing safety contracts:

- Coordinate a verified embedded-lyrics edit with the database presence flag and
  resulting media size. A database-only edit cannot claim completion.
- Keep focused lyric writing independent of optional complete metadata writing.
- Preserve retained database Unknown Data, including unchanged type-10 Chunks.
- Preserve existing unrelated media tags and payload; do not populate all Track
  metadata or silently strip it during a focused lyric edit.
- Prepare media changes away from the device, capture write preconditions, and
  publish through Storage with the database in a recoverable transaction.
- Cover add, replace, clear, Unicode, multiline text, stale inputs, existing tag
  versions, and unrelated-tag preservation. Firmware display compatibility still
  requires real-device evidence; serialization round trips alone cannot prove it.

These requirements preserve [ADR-0002](../adr/0002-separate-the-four-primary-subsystems.md)
and [ADR-0006](../adr/0006-require-lossless-ipoddb-round-trips.md). No physical
device writes or firmware display tests were performed during this research.
