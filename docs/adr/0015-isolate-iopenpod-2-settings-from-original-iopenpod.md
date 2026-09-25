# ADR-0015: Isolate iOpenPod 2.0 global settings from Original iOpenPod

- Status: Accepted
- Date: 2026-08-31

## Context

ADR-0014 selected `settings.json` for iOpenPod 2.0 on the premise that no existing
user settings occupied that file. Review of the Original iOpenPod and an existing
Host configuration showed that premise was incorrect: the Original iOpenPod already
uses `settings.json` in the same conventional configuration directory.

Sharing the file would couple two independent schemas. iOpenPod 2.0 could discard
Original iOpenPod objects and arrays that its narrower value codec does not
understand, while the Original iOpenPod writer could discard 2.0 keys that it does
not own. Preserving unknown values in only one application would not make the shared
file safe in both directions.

## Decision

- iOpenPod 2.0 stores global settings in `settings-v2.json` under the same
  platform-conventional directories selected by ADR-0014.
- The Original iOpenPod's `settings.json` remains a separate v1-owned file. iOpenPod
  2.0 does not read, migrate, or rewrite it.
- The former Qt `QSettings` backend is still removed without migration or fallback.
- Storage continues to resolve the Host configuration location and atomically
  persist bytes. iOpenPod continues to own the typed settings schema and JSON
  encoding.

This decision supersedes ADR-0014 only where that record names `settings.json` and
states that no existing settings file requires separation. Its Storage boundary,
atomic-persistence rules, and remaining consequences stay in force.

## Consequences

Running iOpenPod 2.0 cannot erase or reinterpret Original iOpenPod settings, and the
Original iOpenPod cannot erase 2.0 preferences when it saves its own schema. Users
who run both applications keep independent appearance, window, and future product
settings.

Existing experimental iOpenPod 2.0 values that were written into the v1
`settings.json` file are deliberately not imported. The next 2.0 launch starts from
typed defaults and creates `settings-v2.json` when the first setting changes.
