# ADR-0229: Report Phase activity and stage ETA

- Status: Accepted
- Date: 2026-11-03
- Extends: ADR-0096, ADR-0164 and ADR-0228

Phase preparation reports immutable activity and ETA snapshots through Library
write progress and source-owned status progress. The shared status controls place
a compact ETA immediately before the progress bar; its tooltip gives the existing
stage-specific estimate and uncertainty range. The left-hand message identifies
the current activity, analysis method, live backend and completed eligible Tracks.
The current song remains available in the progress-bar tooltip.

The preparation caller owns the existing ETA estimator. Completed, verified audio
duration is its work unit, accounting for different song lengths. Eligibility and
persistent-ID deduplication define the total. A new preparation starts fresh; at
least three timed samples are required before forecasting. Checkpoints refresh
feedback at most once per second unless activity changes, without inventing
within-song progress. Long gaps withdraw the numerical estimate. Cache reuse,
model startup, fallback and changing song complexity can affect accuracy. The ETA
ends at Phase preparation, excluding later Library publication and verification.

The isolated worker optionally publishes bounded, atomic, request-scoped activity
metadata. The parent polls at most four times per second. Missing, invalid, stale
or inaccessible telemetry does not fail analysis. These messages never authorize
scheduling, cache provenance, file publication or completion. GPU names are
best-effort display metadata; backend selection and CPU retry remain authoritative.
The shared activity type ships as source alongside the existing worker modules.

Status rotation and terminal transitions carry or clear the estimate together with
its owning source. Existing cancellation ownership, input prefetch, algorithm,
analysis parameters and musical output are unchanged.
