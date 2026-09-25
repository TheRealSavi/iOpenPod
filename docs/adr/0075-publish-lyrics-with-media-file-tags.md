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
