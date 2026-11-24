# ADR-0295: Distinguish Podcast Episodes sharing an enclosure

- Status: Accepted
- Date: 2026-11-24
- Extends: ADR-0037, ADR-0091, and ADR-0149

The Tin Foil Hat RSS feed publishes two Episodes with one Enclosure URL and
distinct Podcast GUIDs. Deriving both Episode identities from the enclosure
rejected the whole feed during subscription, refresh, and discovery artwork
lookup. Original iOpenPod used the publisher GUID when available.

Use the GUID to derive each Episode identity when a feed repeats an Enclosure
URL and every Episode in that group has a GUID unique within the feed. Ordinary
enclosure-derived identities remain compatible with existing Listening History.
A shared enclosure without unique GUID evidence still fails refresh, preserving
the show's existing media during automatic Sync.

Catalog reconciliation uses GUIDs when the catalog, Listening History, or
retained Tracks establish a shared enclosure. Existing identities can be retained
through a unique GUID match. Sync permits a shared enclosure with retained Tracks
when they are already matched to distinct Episodes by GUID. Unresolved matches
and repeated GUIDs continue to block unsafe automatic changes.
