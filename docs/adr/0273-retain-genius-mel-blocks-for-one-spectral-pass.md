# ADR-0273: Retain Genius mel blocks for one spectral pass

- Status: Accepted
- Date: 2026-11-15
- Amends: ADR-0179's spectral-memory policy
- Complements: ADR-0271 and ADR-0272

## Context

Genius MFCCs require one 80 dB floor for the complete audio segment. ADR-0179
avoided retaining whole-segment spectral matrices by transforming every block
twice: first to find the floor, then to accumulate features. Repeating the STFT
and mel transform costs analysis time even though the 128-band mel output is
much smaller than the 1,025-bin magnitude spectrum.

## Decision

Compute each spectral block once. Accumulate centroid statistics immediately,
retain its 128-band mel output until the whole-segment floor is known, and release
each retained block after accumulating its MFCCs and onsets. Full magnitude
spectra and the mean tempogram continue to use bounded blocks. Audio features,
profile versions, source checks and cancellation behavior remain unchanged.

The existing 15-minute, mono 22,050 Hz float32 decode limit bounds PCM to about
80 MB per Track. Retained mel blocks add up to about 40 MB per segment. Accept
this additional memory in exchange for avoiding duplicate spectral work; retain
ADR-0271's two-device-Track limit and maximum six Host workers. A RAM-aware worker
policy is not required by this decision.

## Consequences

An isolated Windows measurement using synthetic 15-minute Tracks and the normal
numerical-library thread settings peaked at about 425 MiB with the previous
two-worker profiler and 485 MiB with retained mel blocks. Six concurrent profiles
peaked near 1 GiB. These process measurements include Python and audio libraries
but exclude the full GUI and FFmpeg processes; they are observations, not a
guaranteed total-application memory bound. Temporary arrays and library workspaces
contribute beyond the retained PCM and mel sizes.

The audio-buffer cost is bounded by concurrent Tracks rather than Library size.
Completed profiles remain compact; decoded audio and mel blocks are not cached.
Low-memory or already-busy Hosts can experience memory pressure at higher worker
counts. The accepted tradeoff favors faster analysis within the existing bounds.
