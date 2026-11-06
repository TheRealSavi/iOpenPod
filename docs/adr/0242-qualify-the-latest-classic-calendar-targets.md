# ADR-0242: Qualify the latest Classic Calendar Targets

- Status: Accepted
- Date: 2026-11-05, America/Detroit
- Extends: ADR-0196 and ADR-0241 profile qualification
- Retains: ADR-0240 non-blocking date policy and native-byte preservation

## Context

The requested support scope is the latest firmware for Classic 6, 6.5, 7 and 7.5.
Apple's current catalog offers four separate branches: updater 24 / 1.1.2,
33 / 2.0.1, 35 / 2.0.4 and 38 / 2.0.5. The latter two are not interchangeable
releases for one update target. Apple does not define a separate 7.5 retail
category on its model page, and the existing MC293/MC297 Device Profiles do not
establish the updater-35/38 distinction. See the
[identity evidence](../research/classic-latest-firmware-targets-2026-11-05.md).

Independent instruction inspection establishes the same saved city, DST and bias
field offsets in all four releases, with distinct Preferences extent/version pairs.
Clock mechanics and annual-rule behavior still differ. A retained physical
Classic 6.5 capture also has stale cached release 1.62 beside stronger hardware
evidence reporting RetailOS 2.0.1. Treating every observation as equally authoritative
would discard valid qualification. These differences require explicit identity
and format contracts, not another file-length heuristic.

## Decision

Maintain four latest Classic Calendar Targets. Their byte-only Preferences profiles
require these exact extent/version pairs: 2,952/0x3c, 2,956/0x3d, 2,956/0x3e and
2,960/0x3f. `ClassicPreferences` owns the shared full-width city and language fields;
`ClassicClockPreferences` owns raw saved DST and bias observations. Keep the
2.0.1 Alternate Audio specialization separate because the current task qualifies
calendar fields, not other generations' audio controls.

The Application Layer selects strongest-authority release and updater-family
observations independently, retaining conflicts at the strongest level. Explicit
updater identity must agree with the release and selected Device Profile. Preserve
the model-plus-exact-release fallback for known Classic 6/6.5 identities when no
updater ID is reported. The two later 160GB targets require explicit updater-family
evidence; a SKU, capacity, manufacture date or missing-family latest-version guess
must not choose between 35 and 38. Transport revision is never RetailOS evidence.

Qualified targets with unexpected Preferences framing remain opaque, avoiding
fallback to a narrower city field that could alias an unknown u32 ID to a known
u16 city. Unknown profiles and missing observations retain existing best-effort
Library date behavior. No qualification failure requires upgrading firmware or
blocks loading, playback reconciliation or saving.

All four qualified profiles withhold city 0x26's conflicting legacy London mapping.
The inspected city tables supply -300 minutes but do not establish the geographical
identity. Do not substitute a guessed city or treat current firmware offsets as
historical timezone rules. City/DST/bias fields remain observation-only; language
edits preserve every other byte.

Enable the existing lossless `dst` document profiles for qualified families
33, 35 and 38 independently of Preferences readability. Family 24 retains a
present `dst` file opaquely: its inspected manual/retained-DST clock paths do not
establish the later annual-file consumer. No rule file changes historical date
interpretation or becomes a save precondition.

## Consequences and validation

Saved clock observations and non-blocking Library date support now use the same
contract across all four latest targets. Identical fields do not imply identical
automatic-DST behavior or a proven raw-clock UTC origin. Historical releases are
outside this qualification scope; existing research remains evidence history.

Authored tests cover every profile's framing, full city width, raw clock words,
read-only fields, byte preservation and unresolved city. Virtual devices cover
all four targets, live evidence over stale cache, family/release conflicts, opaque
unexpected layouts, optional DST files, fold/gap playback commits and later saves.
The [support matrix](../classic-calendar-support.md) records the remaining physical
and semantic questions per target and links the pinned firmware checks.
