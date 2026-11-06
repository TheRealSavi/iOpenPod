# ADR-0243: Use Whenever for calendar interpretation

- Status: Accepted
- Date: 2026-11-06
- Complements: ADR-0240, ADR-0241, ADR-0242

## Context

The latest Classic investigations distinguish a Raw Hardware Clock, a Firmware
Calendar, saved corrections, annual DST selectors, and native date words. None
provides enough history to recover every event's UTC instant. The user requested
a complete datetime migration to Whenever while retaining nonblocking Library
behavior and documenting both evidence and uncertainty.

Python's naive/aware datetime distinction allowed Host local input, UTC wire
dates and native calendar coordinates to share one type. Platform timestamp
conversion also made some pre-1970 displays fail on Windows.

## Decision

Use `whenever>=0.11.0,<0.12` for application calendar operations. The locked release
supports Python 3.12 and provides explicit `Instant`, `PlainDateTime`, `Date`,
`ZonedDateTime`, `OffsetDateTime` and `TimeDelta` types. Use the 0.11 API spellings;
deprecated compatibility names are not the project API.

Native date words and semantic Library Unix seconds remain integers. Replacing
those contracts with calendar objects would discard unset/sentinel distinctions,
overflow evidence or exact native bytes. Whenever operates at interpretation,
input, display and Host clock boundaries. iPodDB continues to own native
conversion without importing the Application Layer.

Device Time Context captures an IANA key or a whole-second `TimeDelta` effective
offset strictly between minus and plus 24 hours, provenance and the independent
database header offset. An IANA key chooses
Whenever's available timezone rules; it is not a snapshot of a tzdb release or
the firmware's annual selectors. Native conversion never uses `SYSTEM_TZ` or the
current clock. The ADR-0240 fold, gap, range and unknown-zone policies remain.

Host input must explicitly choose how to interpret an absent timezone. Shared
ISO input parsing lives in `iOpenPod.app.core.dates`; explicit offsets take
precedence, metadata editor input uses `SYSTEM_TZ`, and unqualified media date
tags use UTC. Host gaps/folds use Whenever's compatible disambiguation. Converting
fractional instants to integer Unix seconds floors, including negative values.
Refresh Whenever's cached Host zone at startup/activation, unqualified input
acceptance and background delivery boundaries. Failed Host-zone resolution uses
UTC for valid unqualified editor input and defers Last.fm delivery. This never
alters a captured Device Time Context; it does not require per-cell refreshes.

Persisted Host JSON timestamps retain their existing UTC `+00:00` format and
microsecond precision. Backup IDs retain their existing fixed UTC format.
Authenticated update issuance and expiry use strict `Instant` checks; optional
Library-date approximation must not weaken signatures, expiry or rollback rules.

Keep stdlib datetime/timedelta values only at required third-party ABI boundaries:
Python 3.12 `plistlib` input/output and WinRT elapsed-duration interop. MHOD type 55
plist date objects expose `Instant`; newly authored values floor to the adapter's
microsecond precision in the typed model before serialization. Integer date keys
in playback plists retain their native integer contract.
Unchanged source bytes remain lossless. Retain monotonic/performance clocks and
sleep for elapsed work, timeouts and playback: wall-clock instants are unsuitable
for those measurements.

## Consequences and validation

This adds a runtime dependency and its platform dependency (`tzlocal` on Windows).
Keep `tzdata` for portable IANA data. Frozen application and update-helper builds
use a Whenever hook for lazy submodules, package metadata and timezone resources;
the native extension and supported Python fallback both need discoverable imports.

Development typing also needs a version-bound correction: Whenever 0.11.0 uses
lowercase `typing_extensions.sentinel`, which the supported Pyright/Pylance
bundled declarations do not recognize. Following ADR-0170's local-stub approach,
`python -m scripts.prepare_typing` generates a shared typing-only copy with an
opaque nominal type for `SYSTEM_TZ`. Other API declarations remain intact, strict
argument checking remains enabled, and site-packages/runtime behavior is unchanged.
See [development typing](../../typings/README.md#whenever-timezone-annotations).

The library does not solve unknown RTC initialization, missing city history,
ambiguous DST file prefix semantics or firmware/IANA differences. Those remain
explicit research questions. See the [engineering guide](../datetime-engineering.md)
for the inventory, interpretations, precision policies and validation boundaries.

Regression coverage includes signed dates, ambiguous/missing local times,
unavailable zones, native preservation, plist precision, unchanged Host wire
formats and strict update validity. Run Whenever deprecation and DST warnings as
errors in focused migration checks. Packaged import checks complement source
tests; they do not prove execution on every supported OS or Classic device.

Sources: [Whenever project](https://github.com/ariebovenberg/whenever),
[0.11.0 distribution and platform metadata](https://pypi.org/project/whenever/0.11.0/),
the locked release's `__init__.pyi`, and the local firmware evidence linked from
the engineering guide.
