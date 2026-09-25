# Reusable stage ETA

`iOpenPod.app.core.eta` estimates time for a measurable stage of an operation.
It has no Qt, Storage, device, filesystem, or third-party dependencies. An ETA is
feedback, never authorization to commit, cancel, flush, or declare success.

## Using the estimator

```python
from iOpenPod.app.core.eta import EtaEstimator

eta = EtaEstimator(total=total_bytes)
# Supply cumulative bytes, including partial-file progress, after each chunk.
estimate = eta.update(completed_bytes, total=total_bytes)
# Periodically refresh even if the worker has not reported more progress.
estimate = eta.snapshot()
# Intentional waiting does not belong in the throughput measurements.
eta.pause()
# ...wait for a user decision...
eta.resume()
```

Use one consistent unit: bytes for transfers, items for similarly expensive tasks,
or caller-defined weighted work for a heterogeneous plan. An initial `completed`
value is a baseline; the estimator does not pretend to have timed earlier work.
Totals may grow, shrink to at least the completed count, or become `None` during
discovery. Unknown totals retain timing evidence but produce no remaining time.
An explicitly known zero total is complete. A decreasing counter is an error.

`ProgressEta.update(phase, completed, total, unit="items")` is a convenience adapter
for existing progress events. It starts fresh when the phase or unit changes, or
a counter restarts. Call `reset()` between operations. Each instance retains only
the current stage. For a repeated stage, give each occurrence a distinct phase key
or explicitly reset, even when the first counter equals the previous value.

Instances are confined to one owning thread; their frozen `EtaEstimate` values can
be published across threads. Supply `clock=` for deterministic tests. The default
clock is monotonic, and all durations are seconds. Non-finite inputs, backwards
time, negative work, and totals below completed work raise `ValueError`.

## Estimation model

The Original iOpenPod's `application/progress.py` is the behavioral baseline for
stage-scoped progress. Its callback-weighted item-duration EMA is replaced here
by a bounded, robust model that accepts cumulative work without looping per unit:

1. Aggregate observations across at least 0.5 seconds before calculating a rate.
   Duplicate timestamps and frequent chunk callbacks cannot create infinite rates
   or artificially increase the estimator's evidence count.
2. Smooth log throughput with a six-second exponential half-life. The smoothing
   weight depends on elapsed time, not the number of callbacks. Log space treats
   multiplicative speed differences symmetrically and avoids dependence on units.
3. Clip isolated innovations around the median of at most 31 recent log rates,
   using three robust standard deviations (scaled median absolute deviation) with
   a minimum factor-of-two tolerance. This resists cache hits and scheduling bursts.
4. Three consecutive observations beyond a factor of two from the current rate
   establish a new regime. Rebase to their median and retire obsolete history,
   so outlier rejection cannot indefinitely hide a persistent slowdown or speedup.
5. Track exponentially weighted log-rate dispersion. A heuristic range includes
   that variation, startup uncertainty, and stale-observation uncertainty. This is
   a plausible working range, **not a calibrated statistical confidence interval**.
6. Require at least three timed samples and two seconds of evidence before showing
   remaining time. Silence beyond the normal callback cadence lowers effective
   throughput and broadens the range. Silence lasting at least 15 seconds or three
   typical sample intervals withdraws the ETA. Duplicate counters do not refresh
   the last-progress time. Polling never trains the model or invents progress.

Timing settings are supplied through the immutable `EtaConfig`. Persistent pauses
are explicit: `pause()` and `resume()` exclude user waiting even inside a partial
sample. A stalled estimator can recover when work resumes. Numerically
unrepresentable forecasts remain unavailable instead of publishing infinity or
zero. Memory use is bounded independently of operation size and event count.

## Application integration

The reusable `GUI/widgets/eta_label.py` adapts progress on the GUI thread. A parented
one-second Qt timer refreshes silence handling; operation completion, failure,
cancellation, or a new operation clears its history and stops that timer. Shared
presentation rounds durations, displays a range when uncertainty is broad, and
labels every forecast **left in this stage**. Reaching a work total says
**Finishing this stage**, never **operation complete**.

- Backup capture uses cumulative bytes, including progress within a large file.
- Restore, Restore Recovery, and Backup Export use their existing file counters.
- The Sync Workspace estimates the existing Host Media Scan and iPod Media Scan
  stages independently. Waiting at the external-Playlist review clears the estimate.
- Finalization and unknown-size work have no invented completion time.

General Sync execution is still future work. Its eventual worker can use the same
math module and display, with a separate phase key for copying, transcoding,
verification, and publication. Neither lower-level Storage nor iPodDB needs to
import application ETA code.

## Limits and verification

Progress receipt times are the GUI's current timing observations. Delayed event
delivery can temporarily reduce accuracy; the sampling window and robust filter
limit isolated bursts. Producers with precise timing requirements can instead own
an estimator in their worker and publish immutable estimates.

File-count estimates assume future files resemble recent files; byte estimates are
preferable when sizes differ. Cache reuse, compression, concurrency, and a change
in the remaining file mix can change future cost. The model cannot forecast unseen
stages or an indefinite durability barrier. It deliberately does not persist
device-specific training or predict time across unrelated stages.

Deterministic tests cover steady and irregular throughput, chunk frequency, bursts,
sustained rate changes, variable workloads, long item cadence, stalls and recovery,
pauses, changing totals, numerical limits, and reset boundaries. Qt tests exercise
the actual Backup/restore and Sync progress routes and timer-driven stale feedback.
