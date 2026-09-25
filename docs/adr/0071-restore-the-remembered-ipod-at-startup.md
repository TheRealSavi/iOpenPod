# ADR-0071: Restore the remembered iPod at startup

- Status: Accepted
- Date: 2026-09-24
- Amends: ADR-0069's startup trigger

## Context

ADR-0069 limited discovery to an open Device Picker. That left a previously selected,
connected iPod unloaded at startup until the user opened the picker, contrary to the
restoration behavior in ADR-0027.

## Decision

When global settings contain a previous Volume Identity, startup runs one background
discovery pass with the picker closed. An exact, ready match enters the existing
selection workflow. A missing or ambiguous match leaves no Active iPod. Discovery
failures remain non-modal; selection failures follow the existing selection path.

The startup pass does not schedule another pass. Repeating discovery remains tied to
Device Picker visibility, as in ADR-0069. Closing the picker does not cancel a
startup restoration already in progress.

## Consequences

The previous Active iPod can load without picker interaction. Hosts without a saved
Volume Identity do not scan at startup. Later connections still require the picker
until native connection monitoring is implemented.
