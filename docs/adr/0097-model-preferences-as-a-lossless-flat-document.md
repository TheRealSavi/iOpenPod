# ADR-0097: Model Preferences as a lossless flat document

- Status: Accepted
- Date: 2026-09-30
- Extends: ADR-0006 and ADR-0008

The firmware Preferences file has several evidenced layouts but no established
Chunk grammar or universal model-to-layout mapping. iPodDB represents it as an
immutable document over retained source bytes, using exact-length layout
definitions and the shared `BinaryStruct` reader/writer. This preserves one source
of offset/type knowledge without inventing iTunesDB Chunk headers for a flat file.

Binary iTunesPrefs uses a separate document and definition in the same module.
Its documented prefix has a marker and minimum extent; later tails are retained
without inventing a version scheme from unknown header bytes. Firmware Preferences
and iTunesPrefs must not share one settings structure: they have different owners,
fields, and layout evidence. The companion plist remains a separate artifact.

Only evidenced fields are editable. Unknown lengths and values remain lossless;
unknown timezones never acquire a Host or UTC fallback in this layer. A caller may
assert a known layout or explicitly request opaque treatment for an unverified
model. Device Registry continues to own device identity; Storage continues to own
physical reads and writes. The codec does not synchronize clocks or authorize
physical Preferences changes.

Explicit caller profiles enable fields whose evidence is limited to a model or
firmware: nano 3 DST, firmware 1.1.1 volume limits, and Shuffle VoiceOver. These are
format assertions, not a second Device Registry. Raw settings retain unknown
codes; named enums guide iTunesPrefs edits. Validation applies to changed fields
independently, so an unknown timezone or sync flag does not prevent an unrelated
edit. Tentative Shuffle capacity fields remain observation-only. Library-link
copies are preserved independently rather than repaired implicitly.

See [the public contract](../ipod-preferences.md) and
[format evidence](../research/ipod-preferences.md). Future timezone reconciliation
will consume this contract independently of firmware settings publication.
