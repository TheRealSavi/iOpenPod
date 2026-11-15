# ADR-0270: Keep lyrics out of MHOD 10

- Status: Accepted
- Date: 2026-11-15
- Amends: ADR-0075 and ADR-0206

[Issue 333](https://github.com/TheRealSavi/iOpenPod/issues/333) reports a Mini 2
database that loads after removing application-authored type-10 lyrics. The
[firmware investigation](../research/mini2-mhod10-memory-2026-11-15.md) shows that
Mini 1/2 import this text into a separate pool, with sorting and cloning consumers.
Its native meaning remains unidentified. Classic and Nano 1 lyrics instead use
media tags and the native presence flag. Serialized database size alone cannot
predict the firmware's memory demand; this report establishes no 16 MiB cutoff.

iPodDB no longer authors or projects MHOD 10 as lyrics on any device. The Chunk
type is named `UNKNOWN_TEXT_10`; its string encoding remains known. Retained
records stay byte-exact through unrelated edits, media replacements, and lyrics
edits. We do not infer application provenance from type, text, or an enabled flag.
Automatic removal of existing records would risk erasing native data and is not
part of this change. Existing bloated databases require a separately reviewed
repair with provenance evidence; ordinary Sync prevents new cache growth.

`AudioCapabilities.supports_lyrics` describes the catalog's native display policy:
Video-generation iPods, Classics, and Nanos enable it; earlier iPods and Minis do
not. This is a product authoring policy, not a claim of firmware verification on
every listed model. Host lyrics reading, export, explicit Library lyrics edits,
and optional Rockbox tagging are independent of native display support.

Sync compares and prepares lyrics when native display or Rockbox tagging needs
them. Unsupported native targets otherwise preserve lyrics already embedded in
copied media without preparing them or authoring an enabled native flag. Ordinary
saves receive the same Device Profile capability as initialization. Explicit
Library edits still require verified media evidence on every target; they author
an enabled native flag only on capable devices. Untouched flags remain lossless.

Lyrics text lives in media tags, incoming Host metadata, or an explicit Library
Draft. Binary Library Snapshots contain no lyrics text. Lazy file reads supply the
Player and editor. An explicit edit carries Track identities separately from the
text so clearing unloaded lyrics remains reviewable intent, including on devices
with no native flag. Unrelated full-tag edits retain the existing file text.
PreparedLyrics verifies complete text and final file identity; database reparse
verification checks native fields without pretending the text is in iTunesDB.
SQLite's genuine Extras.itdb lyrics table remains supported, populated from
verified file evidence and retaining untouched source rows.

Sync retains distinct Host and iPod tag baselines. When the native lyrics flag is
set or Rockbox file tags are enabled, a changed Host baseline must publish a
possible lyrics clear even if both projected strings are empty. This
conservatively permits one extra tag update when a Host tag change has already
converged with the device. Ordinary metadata changes without lyrics evidence or
Rockbox file tags do not trigger lyrics preparation. Stable baselines avoid
repeated updates without a new on-device or Host text cache.

The existing Classic native representation checks, complete-text verification,
private staging, and coordinated recoverable publication continue to apply.
Validation covers native capability gating, explicit clearing, retained type-10
bytes, file-tag preservation, SQLite publication, and repeated Sync. Physical
device confirmation remains separate from these regression tests.
