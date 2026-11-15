# ADR-0272: Use one maths thread per Genius worker

- Status: Accepted
- Date: 2026-11-15
- Extends: ADR-0271

## Context

Genius profiling uses NumPy and SciPy, whose matrix operations call OpenBLAS.
OpenBLAS sizes one thread pool to every logical CPU, and its idle threads
busy-wait before sleeping. During a live two-worker Sync on a 16-thread CPU, the
application process used about 14 cores across 77 threads.

Media preparation divides CPUs between concurrent FFmpeg jobs, giving each job
`available_compute_threads() // min(workers, jobs)` threads. That split was
measured against a single BLAS thread per worker. The test decoded and profiled 52
FLAC, MP3, and AAC Tracks on an idle 8-core, 16-thread Ryzen 7 7800X3D:

| Workers | Default BLAS | CPU split | One BLAS thread |
| ---: | ---: | ---: | ---: |
| 1 | 418 ms | 411 ms | 398 ms |
| 2 | 347 ms | 225 ms | 210 ms |
| 6 | 288 ms | 117 ms | 110 ms |
| 8 | 265 ms | 121 ms | 109 ms |
| 16 | 234 ms | 124 ms | 123 ms |

Each profile's matrices are small: 128 mel bands by at most 1,024 frames. BLAS
threading did not speed up even one worker.

## Decision

While Genius analysis runs, BLAS libraries use one thread. Parallelism comes from
the analysis workers (ADR-0271). The limit is applied with `threadpoolctl` for
the duration of analysis and restored after every worker stops.

`threadpoolctl` becomes a direct dependency. It was already installed and
distributed through scikit-learn, so this adds no package to the distribution. A
minimal local stub in `typings/` declares the API iOpenPod uses, because the
package ships no type information.

## Consequences

Six workers profile about three times as many Tracks per second as two workers
with default BLAS threading on the measured machine. They also no longer occupy
every core with busy-waiting threads.

BLAS thread limits are process-wide, so other NumPy work in the application during
Genius analysis also runs single-threaded. Sync runs Genius analysis after media
preparation, when no other analysis is expected.
