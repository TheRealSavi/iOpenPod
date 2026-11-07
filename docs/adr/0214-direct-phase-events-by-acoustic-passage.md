# ADR-0214: Direct Phase events by acoustic passage

- Status: Accepted
- Date: 2026-10-30
- Supersedes: ADR-0210's transient selection policy
- Extended by: [ADR-0215](0215-follow-phase-parts-and-recurring-hooks.md)
- Selection policy superseded by: [ADR-0217](0217-preserve-phase-evidence-for-native-difficulty.md)

Phase Gameplay Analysis now selects percussive or pitched attacks over approximate
musical passages. Separate harmonic onset evidence enables a foreground pitched
line to take focus over continuing percussion. Energy and harmonic-share changes
provide handoff opportunities, with minimum residence and hysteresis preventing
rapid switching. Percussion can answer gaps in pitched activity. Pulse tracking
remains independent, and selected events retain their original timing.

The Application Layer owns this policy and bounded audio analysis. iPodDB continues
to own typed events and encoding; Storage owns publication. We use the existing
librosa dependency without coupling Phase saves to Synesthesia or optional model
availability. Acoustic families are not literal instrument identities. Explicit
vocals and recurring-hook recognition require further evidence and work.

Algorithm version `librosa-phase-2` invalidates older cached charts through the
existing provenance checks. Synthetic mixed-audio and selection tests establish
the intended handoffs, pauses, determinism, and cancellation. The known native
encoding is retained; actual gameplay quality and downstream magnitude semantics
still require native gameplay evaluation. Constants and limitations are documented
in [Phase audio analysis](../phase-audio-analysis.md).
