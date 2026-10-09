# ADR-0083: Tolerate Host-native media variants during preparation

- Status: Accepted
- Date: 2026-09-26
- Extends: ADR-0031, ADR-0074 and ADR-0082
- Amended by: [ADR-0136](0136-allow-network-filesystems-as-host-media-sources.md)
  for ordinary network filesystem paths

## Context

Host media may come from macOS folders whose filenames contain characters that
Windows treats specially, including colons and backslashes. Treating every Host
path as a Windows path prevents valid macOS media from reaching Sync. Media
containers can also carry multiple editions or audio tracks, while FFmpeg builds
do not expose identical options for every AAC encoder.

## Decision

Storage validates local path spelling according to the active Host platform. On
POSIX Hosts, a backslash remains a filename character and colons are accepted in
local names; Windows path, reserved-name, network, device, and
alternate-data-stream protections remain in force where applicable. UNC and
device-style references remain rejected on every Host.

Video preparation selects the stream marked as the container default, or the
first stream in probe order when no default is marked, for both motion video and
audio. When selection removes additional streams, preparation remuxes or
transcodes the selected streams and reports the choice as a warning. Supported
subtitle streams retain their existing handling; unsupported streams are not
copied to the iPod.

Lossy encoder options are scoped to the encoder that consumes them. The native
AAC profile option is sent to FDK AAC and native AAC, but not AudioToolbox AAC
(`aac_at`), which receives its supported mode option instead.

## Consequences

Common macOS filenames can be imported from local folders and playlists without
renaming them. Multi-stream videos no longer fail solely because an edition or
commentary stream is present, while the selected stream is visible in Sync
diagnostics. A source with no marked default still has deterministic behavior,
but the first stream may not be the user's preferred language or camera angle.
AAC-AT preparation works with FFmpeg builds that reject `profile=aac_low`.
