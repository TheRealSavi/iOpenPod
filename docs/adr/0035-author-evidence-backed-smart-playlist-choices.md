# ADR-0035: Author evidence-backed Smart Playlist choices

- Status: Accepted
- Date: 2026-09-12
- Extends: ADR-0022

## Context

The Smart Playlist editor can already author recursive text, numeric, boolean, and
date conditions, but four conditions supported by the Original iOpenPod remain
read-only: Playlist membership, Purchased, Media Kind, and Location. Treating raw
Playlist IDs and native media masks as ordinary integers would leak iTunesDB details
through the common Library contract and make draft identity allocation unsafe.

Other known iTunes fields, including cloud status, favorites, Work, Movement, and
album/video ratings, still have no trustworthy value in the common Track contract.
Making those conditions editable would let iOpenPod calculate incorrect saved
membership.

## Decision

Represent Playlist targets, media choices, and location choices with distinct typed
semantic values. Purchased remains a boolean condition. iPodDB privately translates
those values to and from the evidenced native field, action, and value codes.

The Application Layer evaluates a Playlist-reference condition against saved
membership. A referenced Smart Playlist is not reevaluated as a consequence. A
Playlist Folder contributes the union of its descendants' saved membership. Missing
references fail explicitly, and a Smart Playlist cannot reference itself. References
to new Playlist drafts are translated through the same allocated identity mapping
used for Playlist headers and folder relationships.

Every Track in the loaded iPod Library is local for the legacy Location rule, matching
the Original iOpenPod evaluator. Purchased uses the retained iPod observation when
available and otherwise evaluates false. Media Kind is resolved from the common
semantic Media Types rather than exposing the native bit mask.

Known conditions without a trustworthy semantic Track value remain explicitly
unsupported, read-only, and byte-preserved.

## Consequences

The editor reaches parity with the Original iOpenPod's evidence-backed authorable
condition set without weakening the source-neutral Library boundary. Playlist
dependencies are validated and remapped instead of becoming dangling native IDs.
The evaluator remains deterministic and does not cascade reevaluation through Smart
Playlist dependencies. Additional iTunes fields require new format evidence and a
typed common value before they can become authorable.
