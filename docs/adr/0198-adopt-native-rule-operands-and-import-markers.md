# ADR-0198: Adopt native rule operands and import markers

- Status: Accepted
- Date: 2026-10-26
- Extends: ADR-0195/0196 firmware evidence and preservation policy
- Refines: ADR-0035 Smart choices and ADR-0098 city interpretation

## Context

A further comparison with the pinned Classic 120GB RetailOS 2.0.1 investigation
found disagreements in Podcast group discrimination, Smart boolean operands and
numeric ranges, and inherited city names. Lossless round trips alone do not reveal
these errors: the same bytes can be faithfully retained but incorrectly projected
or used to regenerate Playlist membership. The
[supporting report](../research/classic201-additional-contracts-2026-10-26.md)
records the evidence, source identities and remaining uncertainties.

## Decision

Interpret any nonzero MHIP byte `+0x11` as a Podcast group. Keep the existing raw
u16 field spanning `+0x10..+0x11`, expose one derived group predicate, and use it
throughout projection, reconciliation and verification. Preserve both retained
bytes; newly authored groups continue to use the canonical high byte `1`. This
does not change the separate MHYP Folder flag or introduce firmware import-order
repair.

For the evidenced Checked and Compilation Smart conditions, interpret the native
boolean operand as well as the equality/inequality action. The native Checked
field is an unchecked flag, so its semantic truth is inverted. Author canonical
false operands for Checked and true operands for Compilation. Preserve unchanged
alternative encodings instead of normalizing them. Other boolean fields keep
their existing policy until their consumers are established.

Restrict editable nonnegative numeric Smart operands to signed-64-bit range.
Retain imported active operands outside that semantic range as Unsupported Smart
Rules; an unused upper slot does not restrict a single-bound comparison.
Malformed UTF-16 Smart text also remains unsupported rather than becoming an
editable replacement-character string. Unsupported rules preserve raw bytes and
saved membership through automatic refresh and unrelated edits. Signed relative
date displacements, rolling Host date evaluation and existing text collation
policy remain separate contracts.

Correct four city-to-IANA mappings using the combination of city labels, firmware
offsets and IANA geographical evidence. Withhold the contradictory London mapping
for city `0x26` in the qualified Classic profile only. Its raw city word remains
available; a valid MHBD offset can still supply the existing diagnosed fixed-offset
fallback, including the reason city interpretation was withheld. Do not guess a
replacement geographical identity or silently apply saved DST/clock-bias values.
The public `CityTimezone.detail` carries the interpretation reason; the
Application Layer does not inspect internal city tables.

As in ADR-0195, applying shared MHIP and Smart semantics beyond the inspected
Classic image is an explicit compatibility inference. The Classic-specific city
exception requires that profile. These changes add no device mutation pathway,
firmware dependency or historical migration of previously written dates/rules.

## Consequences and validation

Noncanonical group markers no longer appear as Track occurrences or cause group
metadata to be flattened incorrectly. Corrected boolean projection can change
Host preview and automatic membership for existing native rules: the saved native
meaning takes precedence over an earlier incorrect Host label. Prior user intent
cannot be reconstructed from those bytes.

Regression coverage must inspect native marker/action/operand bytes independently,
preserve Unknown Data and duplicate occurrences, and exercise automatic refresh
and preparation. Timezone tests must use expected UTC instants and verify that
Preferences and retained database dates are not rewritten merely by interpretation.
Full-suite acceptance uses ADR-0197's eight-worker default. Physical execution of
the changed outputs and cross-platform acceptance remain separate validation.
