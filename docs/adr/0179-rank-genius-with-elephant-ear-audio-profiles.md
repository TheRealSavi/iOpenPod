# ADR-0179: Rank Genius with Elephant-Ear audio profiles

- Status: Accepted
- Date: 2026-10-24
- Extends: ADR-0176 and ADR-0178
- Preserves: ADR-0042, ADR-0123, ADR-0156, and ADR-0172

ADR-0188 reduces the authored candidate cap from 256 to 32 while preserving this
ranking and spacing policy.

## Context

The working native Genius Sync path uses metadata neighborhoods and placeholder
constraint keys. The user requests Elephant-Ear's audio-based candidate selection,
real artist and album keys, and native spacing with jitter. Short Tracks may use
their complete audio as the body without separate intro or outro analysis.

The reference is the user's Elephant-Ear project at commit
`3792a413353ca300321d8b2279cc76126920757c`, specifically `src/features.py` and
`src/models.py`. It profiles tempo, spectral centroid, and MFCC statistics over
20-second ends and the remaining body, then selects among three nearby bodies
using outro-to-intro distance. Its whole-Playlist greedy ordering is not a native
Genius interface: firmware receives candidate IDs and integer constraint keys,
not feature vectors or cross-field distance functions.

## Decision

The Application Layer computes a separate **Genius Audio Profile** for each eligible
music Track in the final desired Library. Each present segment contains 29 finite
values: tempo, centroid mean and variance, and 13 MFCC means and variances. At most
40 seconds uses the entire Track as body with absent intro and outro. Absence is
explicit, never a fabricated zero vector that could become a perfect match.

Candidate construction compares standardized body features, then repeatedly picks
the closest intro to the seed's outro from the next three nearest remaining bodies.
The body and transition comparisons stay anchored to the source Track: these are
relationships for every native seed, not a prescribed Host playback queue. Missing
ends fall back to body distance. Intro and outro features share one normalization
scale. Deterministic ties and bounded projection neighborhoods avoid a full
quadratic matrix on large Libraries. Libraries of up to 512 profiles use exact body
comparisons; larger Libraries use eight fixed projection neighborhoods.
The retained metadata and ring fallback supplies candidates for unavailable
profiles and preserves graph reachability. The existing 256-candidate cap remains
an application policy rather than a discovered firmware limit.

Genius metadata slots are `[1, artist_key, album_key, genius_id]`. Artist keys use
exact artist names; album keys use the existing case-insensitive album-title
equivalence with exact effective Album Artist identity, respecting ADR-0172.
Incomplete identities receive independent Track-specific labels. Length-framed
hash inputs provide stable nonzero labels without ambiguous text concatenation.
Intro, body, and outro vectors remain on the Host; no unconsumed acoustic labels
are stored as if firmware could evaluate their distances.

Two native opcode-3 spacing rules use `(field, floor, distance, jitter)`:

- Artist: `(1, 1, 6, 2)`.
- Album: `(2, 1, 10, 2)`.

These configure firmware counters, not guaranteed exact numbers of intervening
Tracks. The floor of one accounts for the reverse-engineered first-use key counter
starting at one; a floor of two could stall a single-artist or single-album Library.
This rationale still needs hardware confirmation. The proven compact control
suffix is retained; skip filtering, cluster restrictions, and additional
random-deferral rules are not enabled. Result counts remain 25 desired and 10
minimum. Existing native Mixes remain preserved.

The application service decodes source-bound audio through Storage's pinned
read-only tool inputs, sequentially and with cancellation and resource bounds.
New or replaced media uses its prepared Host source; retained Tracks use their
identity-bound Filesystem Session. Device source identities are checked after
analysis and before staging and publication. Analysis never authorizes media writes.
Decoding is limited to 15 minutes of mono 22,050 Hz float32 PCM and 300 seconds of
runtime per Track. Longer Tracks receive metadata fallback. Spectral statistics
and the mean tempogram are accumulated in bounded blocks rather than retaining
whole-song spectral matrices.

A disposable, bounded, versioned Host cache stores compact successful profiles
with source identity and file facts. Normal application composition supplies its
Storage-owned path. The cache allows at most 50,000 records and 64 MiB, evicting
older inserted records when necessary. No PCM, full Synesthesia Track Analysis, or
Chromaprint data is repurposed as this cache. Cache failure is recoverable; decoding failures retry
and receive metadata candidates. Source mutation, disconnection, and cancellation
remain fatal to the current preparation. Existing Synesthesia's runtime-only
contract is unchanged.

## Consequences

Cold Sync gains audio-analysis work; subsequent Syncs reuse unchanged profiles.
Existing NumPy and librosa dependencies suffice. The new profile and ranking code
does not depend on Elephant-Ear at runtime or import its notebooks, pandas, plots,
or mutable Playlist engine. iPodDB remains a pure native-format boundary and
Storage remains the device I/O boundary.

Tests must distinguish actual acoustic ranking from fallback, cover short and
silent input, cancellation, cache invalidation, source changes, key identity,
spacing serialization, and both Classic and SQLite Sync publication. Host tests
establish format correctness and safety; musical quality and the exact native
spacing behavior still require listening on hardware. The earlier successful
no-rule playback experiments do not validate these new rules.
