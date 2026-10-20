# ADR-0161: Repair video playback metadata during Sync

- Status: Accepted
- Date: 2026-10-20
- Amends: ADR-0147, ADR-0150, and ADR-0160

Nano 5 playback experiments isolated missing SQLite `video_info` descriptors.
N519 and N521 contained byte-identical media and shared `has_subtitles=1`,
`characteristics_valid=1`, native subtitle track ID 3, and stream index 2.
N519's language was NULL and failed; N521's packed ISO 639-2 `eng` value 5575
worked. N522 with language zero failed. N512 and N518 also contained identical
media; N518 enabled captions with `has_closed_captions=1` and
`characteristics_valid=1`. This establishes sufficient descriptor bundles on the
tested Nano, not the independent necessity of every field. The Classic's
successful movie-clock correction remains the policy in ADR-0160.

The Application Layer inspects the final MP4 after tagging and supplies typed
video playback metadata bound to its file fingerprint. iPodDB applies observed
subtitle presence, caption presence, validity, and subtitle selection after
SQLite retention, then reads the authored fields back for verification.
Native track IDs and zero-based stream indices are distinct and come from the
actual final file. Select the default retained `tx3g` stream, otherwise the first
in file order. Pack its actual three-letter language; absent or invalid language
is `und`, never assumed English. Captions describe retained `c608` tracks.
Unknown-language firmware rendering remains unverified.

A user-directed Sync, including **Refresh Library** with no media changes,
inspects retained videos whose descriptors are absent or incomplete. Storage
lends a pinned, seekable read handle to FFprobe; no full-file staging, remux,
tag edit, or re-encoding is needed. Captured content fingerprints become
publication preconditions. Complete existing descriptors avoid repeat probing.
New or retagged video files are inspected even when previous descriptors exist;
observations supersede stale file-bound values while unrelated audio, store, and
unknown metadata survive. Inspection failures block incoming video preparation;
unreadable retained videos produce warnings and remain eligible for later repair.
Cancellation, connection loss, and changed reviewed files stop publication.

These descriptors remain supplemental file observations under ADR-0150.
iTunesCDB remains the semantic Library authority. The experiments changed no
native CDB subtitle fields, so this fix does not reinterpret the currently
unknown `0x173` byte or change `video_flag_2` semantics. Classic profiles do not
write SQLite and gain no additional video inspection or binary-field changes.
Saved stream-choice serialization and preparation digests also stay unchanged:
the metadata repair itself must not request a media replacement.

Regression tests cover normal Sync on virtual Nano 5 and Classic devices,
metadata-only repair with unchanged video hashes, timestamps, and CDB bytes,
repeat Sync, preservation of unrelated supplemental values, and rejection when
media changes after preparation. Existing subtitle layout, clock, text, timing,
and caption-copy regressions remain required. These checks establish the software
contract; physical playback acceptance comes from the experiments above and
subsequent device testing.
