# ADR-0274: Read one device Track at a time for Genius analysis

- Status: Accepted
- Date: 2026-11-15
- Amends: ADR-0271

## Context

ADR-0183 and ADR-0271 allow two device Tracks to be analyzed at once, so two
FFmpeg decoders can read from the device concurrently. Genius analysis of
retained Tracks reads each uncached file from the device in full. On a
hard-drive iPod, concurrent reads make the drive seek between files.

Direct, uncached reads of 16 iPod Music files per run over USB 2.0:

| Concurrent readers | iPod classic, hard drive | iPod 5.5G, flash storage |
| ---: | ---: | ---: |
| 1 | 22.2–22.6 MB/s | 15.3–15.4 MB/s |
| 2 | 15.9–16.2 MB/s | 9.8–10.4 MB/s |

On the hard drive, read size made no difference. A cold Sync of the iPod classic
spent about 6,000 seconds in Genius analysis for a 57 GB Music library,
consistent with device-bound reads.

Flash storage does not seek, yet concurrent reads slowed it as much. The cause was
not isolated; the iPod's USB bridge or the storage may favor sequential reads.
The storage type cannot be detected reliably: Linux reported the flash iPod as
rotational, and an iPod fitted with flash storage identifies as its original
hard-drive model.

The iPod Media Scan already uses one serialized device capture overlapped with
decoding (ADR-0123).

## Decision

At most two device Tracks remain in flight, but only one reads from the device at
a time. A Track releases the read once its PCM is decoded and is then profiled
while the next device Track reads. Waiting for the read checks cancellation and
skipping (ADR-0200) at short intervals. Staged Host captures do not take the
device read and are unaffected.

The two device Tracks in flight may read in either order. Results remain in
Library order.

## Consequences

Device reads proceed one at a time at the device's sequential rate, and profiling
overlaps the next read. On the measured iPods this raises read throughput by about
40% for the hard drive and 50% for flash storage, which bounds cold Genius
analysis of retained Tracks.

A cold Sync of the iPod classic with this decision and ADR-0271 to ADR-0273
analyzed 2,867 Tracks, 2,817 of them read from the
device, in 3,054 seconds. Holding the device read accounted for 3,042 seconds,
about 19 MB/s across the Music library, so the step remains device-bound and
further CPU or GPU work would not shorten it. Of 2,817 profiles shared with the
earlier cache, 2,816 matched to within floating-point rounding; the other decoded
to a different duration.

A Sync of the flash iPod analyzed 824 device Tracks and 745 staged Host captures
in 1,078 seconds, of which 1,067 seconds held the device read.

The decision applies to every device, regardless of storage type.

Peak device PCM memory is unchanged: two device Tracks in flight, as before.
