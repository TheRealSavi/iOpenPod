# ADR-0290: Require rhythm, dynamics and vocal evidence for mood Mixes

- Status: Accepted
- Date: 2026-11-18
- Amends: ADR-0179, ADR-0187
- Preserves: ADR-0184 ownership and native playback contracts

## Context

Focus and Energy proposed most of one Library using overlapping tempo and
centroid thresholds. A large candidate pool is valid, but the old rules could
mistake steady distorted music for calm music. The requested Focus definition
is very calm music with very few vocals, including occasional calm singing.
Tempo, brightness and MFCC statistics cannot establish vocal absence.

## Decision

Version 2 of the Genius Audio Profile retains the 29 segment features and adds
typed body measurements: spectral activity (positive log-mel change per second),
beat strength above the nonperiodic tempogram floor, 10th-to-90th percentile RMS
dynamic range, spectral flatness and audible-frame fraction. Reuse the existing
STFT and bounded tempogram work. Only frame-sized scalar series are additionally
retained. No new dependency or second media decode is introduced.

Pure Application Layer policy combines these measurements into calmness,
steadiness and energy fits. These are documented product heuristics, not trained
probabilities. A distinct beat supports tempo evidence; tempo alone cannot make
Energy. Noisy, bright, compressed music cannot qualify as Focus merely because
its statistics are steady. Focus requires calmness at least 0.7, steadiness at
least 0.65 and energy at most 0.35. Relax allows vocals. Love still requires an
explicit title or album cue and does not infer lyrical sentiment. Missing new
measurements, silence and very short excerpts do not supply mood seeds.

Focus additionally requires optional vocal evidence. Reuse the explicitly
installed managed instrument-analysis runtime and its cached six-source model.
When Focus is requested, or enabled automatic Mixes are evaluated, only acoustically calm
candidates receive inference. One lazily started worker is retained per preparation,
its requests are serialized, waiting checks cancellation, and it closes on every
exit. Absence of the runtime or checkpoint does not start an installation or
download. Missing evidence stays unknown and cannot qualify for Focus.

Analyze the complete audio up to 48 seconds, otherwise six eight-second windows
distributed across it. Exclude one second at each window edge. One-second audible
windows count as vocal when the estimated vocal stem has at least 10% of the sum
of source powers. Focus allows at most 15% occupied windows. This is a conservative
occupancy estimate, not a calibrated singing detector: instrument leakage can
reject instrumentals, and unsampled vocals can be missed. See the
[real-audio probes](../research/genius-mood-vocal-analysis-2026-11-18.md).

Store compact evidence with provider identity in the source-bound version-2 Host
cache. It contains no PCM or separated stems. Reanalyze a calm cached profile when
requested vocal evidence is absent or belongs to a different provider. Ordinary
BPM-only analysis does not run the model. Cache failure and optional evidence
failure never make a Track instrumental; cancellation and source changes retain
their existing fatal behavior. Existing version-1 cache entries are not reused
as if they contained the new measurements.

Native Genius relationship ranking balances feature families rather than counting
each MFCC statistic equally. Ignore MFCC0 mean (which includes recording gain) and
variance (dynamics, now measured separately) as timbre evidence. For complete
version-2 profiles, rhythm/dynamics/texture measurements
share 40% of body distance; existing spectral/timbre/tempo features share 60%.
Transition comparisons remain anchored to the seed. Optional vocal evidence does
not change the global graph because only some Tracks receive it. Bounded search,
metadata fallback, native spacing and graph reachability remain intact.

There is no arbitrary track-count cap or quota. All confident matches remain
eligible, and weak matches never pad a Mix to the ten-seed minimum. Existing Mixes
retain their ownership and membership until explicitly recreated or rotated; this
change does not silently replace user collections. The UI labels members as
starting Tracks and does not sum their durations into a purported playback length.

## Consequences

The next analysis is cold for the version-2 cache. Focus can require substantial
additional CPU work; cached results avoid repeating it. New installations need
the existing optional instrument-analysis setup for Focus vocal evidence. The
other mood proposals remain available from acoustic analysis alone.

Tests cover gain invariance, spectral block consistency, pronounced beats, dense
noisy music, missing evidence, sparse versus sustained vocals, provider changes,
cache round trips, worker lifetime, cancellation and native publication. These
establish implementation behavior, not universal musical quality. Listening tests
remain necessary. Firmware relationship traversal can leave the starting pool;
this change does not impose a hard no-vocals constraint on every played Track.
