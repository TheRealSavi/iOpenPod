# Native Genius next-Track latency investigation

## Report and scope

The user reports that an iPod can pause noticeably before choosing the next
native Genius Track. This is a playback observation, not a measured CPU trace.
This investigation compares the generated Genius Data with published format
research and private virtual-device artifacts. Its candidate-count finding led
to [ADR-0188](../adr/0188-bound-authored-genius-candidate-rows.md); no device
files were changed during this investigation.

Original iOpenPod generated empty Genius tables. Its behavior cannot provide a
next-Track performance baseline for the generated graph. The initial iOpenPod 2.0
Classic and nano experiments established that a native Genius Playlist or Mix
appeared and began playing; they did not time continued next-Track selection.
See [the generation investigation](genius-generation-2026-10-24.md).

## Findings

The generator previously wrote up to 256 ordered candidates for every music
Track and always fills each row to that cap or the size of the Library minus one.
Each uncompressed relationship uses a fixed eight-byte Genius ID, plus a
12-byte row header. The candidate BLOB therefore has the same size and comparison
width regardless of the ID's numeric magnitude. SQLite's signed integer storage
can vary the index size slightly, but normalization would require coordinated
identity replacement across the Library and Genius companions. It is not an
evidenced playback optimization.

The private virtual rehearsal has these aggregate results:

| Artifact | Music Tracks | Candidates per Track | Total candidate edges | Candidate BLOB bytes |
| --- | ---: | ---: | ---: | ---: |
| Classic | 112 | 111 | 12,432 | 100,800 |
| nano | 19 | 18 | 342 | 2,964 |

This is a complete graph on both small Libraries. At the previous 256 cap, a
larger Library can give the firmware 2,060 candidate BLOB bytes per Track. A
32-candidate row uses 268 bytes. Published device captures report 15, 19,
20, or 32 candidates per row; those observations do not prove that 32 is an
optimal or universal limit. See the upstream [format study](https://github.com/dotm5/Genius-Mix-Research/blob/57b7ae865a10177f725c90e946e1199c00411e53/docs/FORMAT.md).

The current configuration adds two artist and album spacing rules to the
previously tested no-rule payload. The upstream firmware investigation describes
candidate checks, metadata caching, and repeated passes that relax spacing after
rejection. Its distance counters can therefore cost work even when the candidate
row is short. This is especially plausible when nearby candidates share the
same artist or album key. The first Classic hardware experiment used the no-rule
payload, but it did not measure next-Track latency, so there is no controlled
before/after timing. See [ADR-0179](../adr/0179-rank-genius-with-elephant-ear-audio-profiles.md)
and the upstream [constraint evaluation](https://github.com/dotm5/Genius-Mix-Research/blob/57b7ae865a10177f725c90e946e1199c00411e53/docs/FORMAT.md).

## Decision boundary

The current evidence favors candidate traversal and spacing retries over
large-integer arithmetic. It cannot apportion the observed pause between them
or rule out unrelated playback work. Reducing the cap alone would have no effect
on a Library of 33 or fewer music Tracks, and a smaller row could require more
graph expansion to reach 25 desired Playlist Tracks. A connected graph is a
structural property, not proof of prompt or successful native playback.

ADR-0188 reduces authored rows to 32 while retaining the rules and IDs. A
hardware comparison should time repeated next-Track selections and record queue
contents before and after that single change. If pauses persist, compare the
same candidate graph with and without spacing rules. Preserve every other field
and verify references, reachability, output bytes, and recovery before any
device trial. The two comparisons should remain separate so a measured change
can be attributed to one variable.
