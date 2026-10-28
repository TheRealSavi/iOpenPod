# ADR-0206: Validate native lyrics publication

- Status: Accepted
- Date: 2026-10-28
- Amends: ADR-0075

Classic 120GB RetailOS 2.0.1 provides an exact database-to-player lyrics trace.
MHIT `+0xB0` bit zero becomes runtime TrackRecord `+0x8F` bit four. The Library
projection now uses that low bit; unchanged raw bytes and unrelated upper bits
remain lossless. Explicit lyrics writes still author canonical zero or one.

Replacement media must also reconcile a retained enabled flag when both the old
lazy text projection and new text are empty. Require `PreparedLyrics` evidence
for that replacement, then derive the flag from the verified replacement text.
An empty projection on an unchanged Track remains insufficient to clear its flag.

Successful Mutagen read-back is necessary but insufficient evidence of native
lyrics compatibility. For Classic Device Profiles, check the final private file
before issuing `PreparedLyrics`, including after optional full metadata/artwork
tagging. Use bounded reads and seeks through the Storage-owned stream; never
read an entire media payload to inspect its tags. Generic Host reading/export
and other device families retain their existing policy. Applying the verified
2.0.1 contract across the Classic family is a conservative authoring policy,
not a claim of physical verification on every generation.

The verifier checks the embedded text selected by the traced path against the
complete requested text. It checks the 10,240-byte cap, supported ID3 encodings,
descriptor/BOM/termination handling, and the difference between standard v2.4
synchsafe sizes and the native ordinary big-endian sizes of traversed frames.
Small v2.4 layouts which satisfy both interpretations need not be rejected merely
because of their version. MP4 validation checks the supported audio suffix,
`moov/udta/meta/ilst/©lyr` path, single `data` child, and UTF-8 payload.

Equal text is no longer sufficient to skip an explicit Classic lyrics preparation.
If its native representation fails verification, the focused writer can reauthor
USLT/©lyr with the existing version policy and verify again. This repairs cases
such as v2.4 encoding two becoming supported UTF-8. Compatible no-ops remain
byte-exact; unrelated tags and encoded audio remain preserved.

Do not silently truncate text or downgrade an entire ID3 tag. Mutagen version
conversion can discard unrelated version-specific frames. If the final native
representation cannot preserve the full requested text, preparation reports the
specific incompatibility and blocks publication of that prepared result. Source
media and the requested text are retained. Explicit clearing remains possible
even when the old lyrics exceeded a native bound. Removing lyrics is verified
by the existing tag read-back contract, without requiring old text to display.

For podcast/audiobook lyrics writes, Review explains that Classic ExtraInfo
prefers MHOD 14 description text. Retain the user's lyrics and description as
separate fields; do not copy lyrics into descriptions or alter Host player display
precedence to mimic the firmware UI. The native presence flag, successful byte
retrieval, and visible text remain separate concepts.

The firmware evidence and remaining questions are summarized in
[the adoption notes](../research/lyrics-firmware-adoption.md). No synchronized
lyrics conversion, external `.lrc` discovery, automatic rewrite of unchanged
libraries, or physical-device test is introduced by this decision.

Validation covers raw flag preservation, native-layout boundary fixtures,
real Mutagen writes with encoded-media preservation, and application preparation
against virtual devices. Native runtime rendering remains unverified.
