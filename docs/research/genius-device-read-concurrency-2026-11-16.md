# Genius device read concurrency

Date: 2026-11-16. Read-only measurements on three physical iPods; no application
behavior or architectural decision changed. Source baseline: `e206b805`.

## Question

ADR-0274 (PR #338) lets only one device Track read from the iPod at a time during
Genius analysis. John measured no change from it on a flash-modified
iPod. This investigation isolates the effect of that one change by storage type.

## Finding

Reading one device Track at a time shortens cold Genius analysis on hard-drive
iPods. On flash-modified iPods its effect depends on the Host's I/O scheduler:
from 17% less time to about 1% more.

| iPod | Storage | Library on device | Change in cold analysis time |
| --- | --- | --- | ---: |
| iPod 7G(a) (Eli), BFQ scheduler | Hard drive | 61 GB, 2,867 Tracks | 41% less |
| iPod 7G(a) (Eli), mq-deadline scheduler | Hard drive | 61 GB, 2,867 Tracks | 42% less |
| iPod 7G(b) (Eli), BFQ scheduler | Hard drive | 1.1 GB, 128 Tracks | 19% less |
| iPod 5.5G (Eli), BFQ scheduler | iFlash Quad, 128 GB | 59 GB, 2,903 Tracks | 0–17% less; two readers were erratic |
| iPod 5.5G (Eli), mq-deadline scheduler | iFlash Quad, 128 GB | 59 GB, 2,903 Tracks | 1% more |
| iPod classic 6.5G (John) | imCort dual SD adapter | 128 Tracks analyzed | None (225.7 s vs 225.6 s) |

iPod 7G(a) and iPod 7G(b) are two iPod classic 7G units with their original hard
drives. The gain grows with how far the drive must seek between two files: the
fuller drive gained about twice as much as the nearly empty one. It does not
depend on the scheduler: the fuller drive gained 41% under BFQ and 42% under
mq-deadline.

Both schedulers are operating-system defaults on Linux. BFQ is the default on
Fedora, which the measuring Host runs; Fedora's udev rules select it. mq-deadline
is the Linux kernel's own default for a device like this and applies wherever a
distribution does not override it.

Flash storage has no seek cost. On the flash 5.5G (Eli), one reader held a
steady 14.5–14.9 MB/s under either scheduler. Two readers depended on the
scheduler. Under BFQ they ranged from the
one-reader rate to 17% slower. Under mq-deadline they were steady and 1% faster
than one reader. BFQ treats the iPod as a rotational disk and briefly idles the
device after each read, which costs flash storage time without saving a seek.
John's flash iPod showed no difference, which matches the mq-deadline result.

ADR-0274's statement that flash storage slowed as much as the hard drive did not
reproduce: the largest flash loss measured here was 17%, against 41% on the full
hard drive. Its hard-drive figure, about 40% more read throughput, understates the
effect on a full drive: the real analysis read 67% faster.

## Method

### Real analysis, before and after

Two builds of `e206b805` differed only in whether a device Track takes the read
lock; both logged Genius analysis wall time. A harness opened the mounted iPod
through a read-only Filesystem Session and called `GeniusAnalysisService.analyze`
with the real FFmpeg decoder and profiler, six workers, and no profile cache.
Every sampled file was evicted from the page cache before each run, so every read
was cold. Nothing was written to the iPod.

`scripts/benchmark_genius_device_reads.py` repeats this measurement from one
build. `--device-readers 1` is the application's behavior and `--device-readers 2`
removes the single device read. It selects the same sample as the runs below for
the same Music files, Track count, and seed.

Each iPod ran the same fixed sample at least four times in the order before,
after, after, before. The kernel log was checked after each run; none recorded a
read error or USB reset. The Host used the BFQ scheduler unless stated.

iPod 7G(a) (Eli), 128 Tracks sampled across the library (2,654 MB):

| Run | Build | Wall time | Throughput |
| ---: | --- | ---: | ---: |
| 1 | Two readers | 220.4 s | 12.0 MB/s |
| 2 | One reader | 132.4 s | 20.0 MB/s |
| 3 | One reader | 132.0 s | 20.1 MB/s |
| 4 | Two readers | 226.3 s | 11.7 MB/s |

All four runs analyzed 126 Tracks and reported the same two as unavailable.

The same sample on iPod 7G(a) with the scheduler changed to mq-deadline, run with
`scripts/benchmark_genius_device_reads.py`:

| Run | Mode | Wall time | Throughput |
| ---: | --- | ---: | ---: |
| 1 | Two readers | 226.7 s | 11.7 MB/s |
| 2 | One reader | 129.6 s | 20.5 MB/s |
| 3 | One reader | 130.0 s | 20.4 MB/s |
| 4 | Two readers | 221.9 s | 12.0 MB/s |

These match the BFQ runs to within 3%, with the same 126 Tracks analyzed.

iPod 7G(b) (Eli), all 128 Tracks (971 MB of MP3):

| Run | Build | Wall time | Throughput |
| ---: | --- | ---: | ---: |
| 1 | Two readers | 73.4 s | 13.2 MB/s |
| 2 | One reader | 61.4 s | 15.8 MB/s |
| 3 | One reader | 61.4 s | 15.8 MB/s |
| 4 | Two readers | 77.3 s | 12.6 MB/s |

Flash 5.5G (Eli), 128 Tracks sampled across the library (2,679 MB), with a third
pair added because the two-reader runs disagreed:

| Run | Build | Wall time | Throughput |
| ---: | --- | ---: | ---: |
| 1 | Two readers | 219.9 s | 12.2 MB/s |
| 2 | One reader | 184.7 s | 14.5 MB/s |
| 3 | One reader | 181.9 s | 14.7 MB/s |
| 4 | Two readers | 194.8 s | 13.8 MB/s |
| 5 | Two readers | 180.4 s | 14.9 MB/s |
| 6 | One reader | 183.7 s | 14.6 MB/s |

All six runs analyzed 127 Tracks and reported the same one as unavailable. The
one-reader runs span 2.8 seconds; the two-reader runs span 39.5 seconds.

The same sample on the same iPod with the scheduler changed to mq-deadline, run
with `scripts/benchmark_genius_device_reads.py`:

| Run | Mode | Wall time | Throughput |
| ---: | --- | ---: | ---: |
| 1 | Two readers | 178.0 s | 15.1 MB/s |
| 2 | One reader | 180.2 s | 14.9 MB/s |
| 3 | One reader | 180.2 s | 14.9 MB/s |
| 4 | Two readers | 177.7 s | 15.1 MB/s |
| 5 | Two readers | 177.8 s | 15.1 MB/s |
| 6 | One reader | 180.1 s | 14.9 MB/s |

Each mode spans 0.3 seconds or less. Two readers finished 2.4 seconds sooner than
one, about 1%. The spread under BFQ is therefore attributed to that scheduler.

### Read throughput, one and two readers

Total throughput across readers over about 250 MB per run, page cache evicted,
USB 2.0, Linux with the BFQ scheduler:

| Read method | iPod 7G(b), hard drive: 1 reader | 2 readers | Flash 5.5G: 1 reader | 2 readers |
| --- | ---: | ---: | ---: | ---: |
| Buffered, 32 KiB reads | 21.7–22.2 MB/s | 19.6–19.7 MB/s | 15.2–15.4 MB/s | 14.7–14.9 MB/s |
| FFmpeg decode, application arguments | 16.7 MB/s | 13.2–13.8 MB/s | 13.3–14.3 MB/s | 12.5–13.0 MB/s |
| Direct I/O, 64 KiB reads | 21.2–21.6 MB/s | 12.7–13.2 MB/s | 13.5 MB/s | 12.7 MB/s |
| Direct I/O, 1 MiB reads | 22.1 MB/s | 12.4–12.6 MB/s | 15.8 MB/s | 15.6 MB/s |

A simulated pipeline kept two Tracks in flight, each an FFmpeg decode followed by
0.25 s of Host CPU work, with and without one read at a time:

| iPod | Two readers | One reader |
| --- | ---: | ---: |
| iPod 7G(b), hard drive | 12.3–12.6 MB/s | 15.2 MB/s |
| Flash 5.5G, files in one folder | 14.0–14.2 MB/s | 13.8 MB/s |
| Flash 5.5G, files across the library | 12.8–15.1 MB/s | 14.6 MB/s |

FFmpeg reads through the page cache with kernel readahead. Direct I/O bypasses
both, so it overstates the hard-drive penalty for a nearly empty drive and is not
what the application does. The simulated pipeline on flash sat within the range
the real analysis later showed, but did not reveal how much two readers vary.

### The earlier flash measurement

ADR-0274's flash figures, 15.3–15.4 MB/s for one reader and 9.8–10.4 MB/s for two,
came from `dd` with direct I/O on 2026-11-15. Repeating that command on the same
file lists gave 15.3–15.7 MB/s for one reader and 12.7 and 14.7 MB/s for two. Five
of the 64 files had since been replaced by a Sync.

The original run began 36 seconds before iOpenPod started on the same iPod, loaded
its Library, and committed two Storage transactions. That overlap may have slowed
the first two-reader run; the second has no logged activity to explain it. Both
runs used BFQ, whose two-reader results on this iPod vary widely. The lower
original figures are consistent with that, but their cause was not isolated.

## The 2026-11-15 Syncs

ADR-0274 cites a cold Sync of iPod 7G(a) at about 6,000 seconds before the Genius
changes and 3,054 seconds after. That comparison does not isolate this decision:

- The earlier figure was observed by Eli on a build that did not log Genius
  timing. The later one was logged.
- The later build also included ADR-0271 to ADR-0273.
- iPod 7G(a)'s drive returned unrecovered read errors during both Syncs. The kernel
  logged about 100 seconds of stalled reads in the earlier Sync and about 70
  seconds, with two USB resets, in the later one.

At the rates measured here, reading 61 GB takes about 5,100 seconds with two
readers and about 3,050 seconds with one. The serialized-read change therefore
plausibly accounts for most of that difference on this drive. This is an estimate
from a 128-Track sample, not a repeated full-library measurement.

## Limits

- Every measurement by Eli used one Linux Host. John's result is the only
  one from another Host; its operating system was not recorded in the PR.
- Only iPod 7G(a) was measured under both schedulers. iPod 7G(b) was measured under BFQ.
- The flash result rests on three runs per mode and scheduler on one iPod.
- iPod 7G(a) has known bad sectors. No run reported here logged a read error, but the
  drive is not a healthy reference.
- Two hard drives and two flash adapters are a small sample of the devices in use.
