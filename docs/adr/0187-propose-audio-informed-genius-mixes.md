# ADR-0187: Propose audio-informed Genius Mixes

- Status: Accepted
- Date: 2026-10-24
- Extends: ADR-0179 and ADR-0184

## Context

The fixed Genius Mix catalog in ADR-0184 uses genre tags alone. The existing
Genius Audio Profile already measures tempo, spectral centroid, and spectral
variation with librosa during Library preparation. The user wants Mixes such as
Focus, Love, Energy, and Relax. Acoustic measurements can suggest pace and texture,
but cannot establish a song's romantic subject or guarantee the mood of firmware
playback.

## Decision

Add four fixed mood definitions to the Application Layer catalog. Focus, Energy,
and Relax use conservative, deterministic rules over the body segment's tempo,
spectral centroid, and normalized centroid variance. Silence, malformed profiles,
and Tracks without profiles supply no mood seeds. Love additionally requires an
explicit title or album word cue for love or romance. These rules are suggestions,
not emotion or lyric classification.

The Add dialog previews mood definitions when the Library has at least ten music
Tracks. The chooser shows each Mix name without track counts or analysis process
details. The existing source-bound, bounded Genius analysis is reused during
Library preparation; no GUI-thread decode
or separate device read is introduced. Final eligibility still requires ten
matching analyzed Tracks. If a selected mood lacks that evidence, preparation
rejects the addition and leaves the Library unchanged. Automatic Count and Expiry
use the same final proposals and ownership policy as genre Mixes.

Only matching Track identities are written as native Mix seeds. iPodDB receives
the same typed Mix additions as before, with no acoustic vectors or new runtime
dependency. Firmware may traverse Genius relationships outside the seed set.

## Consequences

The catalog grows from 18 to 22 definitions, so the maximum automatic Count grows
accordingly. Cold save may analyze audio before finding that a selected mood has
too few seeds. Missing or undecodable audio reduces mood availability without
creating false matches. Rules are deliberately simple and need listening tests
against varied personal Libraries and physical iPods before tuning. Love has low
recall when tags omit explicit cues, and none of the four labels is a claim about
lyrics or emotional intent.
