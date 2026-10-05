# ADR-0075: Publish lyrics with media-file tags

- Status: Accepted
- Date: 2026-09-24
- Extends: ADR-0021, ADR-0030 and ADR-0034

Stock iPod lyrics need an embedded media tag as well as the iTunesDB presence flag.
Database-only semantic verification previously accepted edits that could not
satisfy that display path. The [upstream research](../research/itunesdb-lyrics.md)
also supports writing lyrics independently of optional general metadata tagging.

iPodDB now requires typed `PreparedLyrics` evidence for requested lyric changes
and incoming/replacement media with known lyrics. The evidence contains the
verified text and final file identity; the resulting file size is resource-derived.
Tagging does not authorize codec changes, so it does not require inventing a new
media inspection or changing retained native codec facts. Existing type-10 text
projection remains for compatibility with the application's lossless documents.

The Application Layer transforms privately captured bytes with the existing
Mutagen dependency, verifies the embedded text, and supplies that evidence.
Storage alone replaces device files, publishing media and database artifacts in
the same reviewed recovery transaction. Lyrics do not enable full metadata
writing, and unrelated edits do not inspect or normalize file tags. Unknown
file-only lyrics are retained until an explicit text edit supplies replacement
intent. Existing ID3v2.3/v2.4 versions are preserved to avoid the unrelated-frame
losses possible during version conversion; new tags follow the Original iOpenPod
v2.3 UTF-16 policy. Edits requiring migration from ID3v2.2 are blocked rather than
discarding unknown frames implicitly. Hardware compatibility remains to be verified.

## Preparation memory budget (2026-10-04)

The preparation capture budget bounds retained whole-media bytes, not lyric text
or a firmware display limit. Exceeding it must not truncate audio or block an
otherwise valid lyrics update. Storage captures private Host files and lends
seekable streams for focused tag edits. The Application Layer verifies the text
and fingerprints the result, retaining small outputs in memory and larger outputs
on disk until their issued review is saved or retired. Disk staging emits a warning
that identifies the original Host path, or the Device Path for a retained Track.
Actual preparation failures also identify the affected file.

Artwork capture reserves memory first; lyrics media uses the remainder or disk.
Temporary media on disk does not consume the artwork capture budget. Failed or
cancelled preparation releases its private files; replacing a review, closing the
connection, and completing publication release retained staging files. Device
preconditions, verified publication, and recoverable media/database replacement
remain required. Source media and full lyric text are preserved; this budget
establishes no iPod lyric-length policy.

[ADR-0117](0117-spill-prepared-library-content-to-host-storage.md) extends disk
overflow to captured and generated artwork and Photo batches. Artwork and lyrics
share the capture workspace's retained-memory accounting.
