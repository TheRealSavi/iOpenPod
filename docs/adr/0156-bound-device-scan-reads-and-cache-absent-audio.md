# ADR-0156: Bound device scan reads and cache absent audio

- Status: Accepted
- Date: 2026-10-19
- Amends: ADR-0123's device capture and optional acoustic retry policies

## Context

Acoustic Fingerprints analyze the first 120 seconds, but cold iPod scans first
copied every byte of each media file to the Host. An unchanged video without an
audio stream repeated that copy and its unsuccessful acoustic analysis on every
scan. Host scans also repeated the same unsuccessful acoustic analysis.

## Decision

The native fpcalc adapter reads missing or stale iPod Tracks through
`FilesystemSession.read_with_tool`. Storage validates the Device Path and current
connection, supplies a pinned, seekable read-only input, owns process cancellation,
and revalidates the connection before accepting the result. The shared tool runner
validates file identity and file facts. The Application Layer rechecks the original
scan facts before caching evidence. Native device decodes run serially; injected
Host-only analysis adapters retain the existing bounded capture fallback.

The decoder can seek to container indexes and read the audio analysis window
without an unconditional whole-file copy or checksum. This is not a fixed byte
budget: container layout, bitrate, and duration determine actual reads. Full
capture, hashing, and verification remain mandatory where publication requires
content identity. Scan analysis never substitutes for that evidence.

Recognize fpcalc's specific missing-audio-stream diagnostic as a completed
no-audio result. Do not generalize decoder errors, missing tools, timeouts, source
changes, or interrupted reads into that result. Those failures remain retryable.
An audio stream containing silence is still analyzed normally.

Host Media Scan Cache v15 and iPod Analysis Cache v2 persist the explicit no-audio
state independently of metadata and successful Acoustic Fingerprints. Reuse it
only under the existing identity, path, size, and modification-time gates. Changed
files are analyzed again. Metadata failures remain retryable even when absence of
audio is already known. Preserve the missing-acoustic-evidence diagnostic and the
existing matching fallback; absence of audio is not a matching fingerprint.

Host cache versions 9 through 14 and iPod analysis cache v1 retain their successful
evidence during migration. They do not acquire fabricated no-audio results.
The Library Sync Helper format and committed Sync Details are unchanged. A Host
analysis cache never supplies Sync provenance or authorizes device writes.

## Validation and limits

Real-tool tests cover video with and without audio, scanner restarts, changed-file
invalidation, and absence of device captures and helper writes. Storage tests cover
seekable range reads on a large input, read-only sessions, cancellation after
session invalidation, and rejection of an escaping link. Cache migration and
unrelated decoder failures retain regression coverage.

The same-size, same-modification-time cache limitation from ADR-0123 remains.
Timing and read-volume improvements on physical USB devices still depend on their
filesystems, container layout, and decoder behavior.
