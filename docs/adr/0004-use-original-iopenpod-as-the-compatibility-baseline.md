# ADR-0004: Use Original iOpenPod as the compatibility baseline

- Status: Accepted
- Date: 2026-08-20

## Context

iOpenPod 2.0 is a deliberate rebuild, but the Original iOpenPod already contains
working product behavior, device knowledge, binary-format research, tests, fixtures,
and cross-platform experience. Defining a smaller replacement as the product target
would discard that knowledge and make architectural discussions repeat questions the
existing project already answers.

The new codebase still needs freedom to improve the architecture rather than inherit
the structure and coupling of the Original iOpenPod.

## Decision

- Treat the Original iOpenPod as the behavioral and research baseline for iOpenPod
  2.0.
- Develop incrementally toward feature parity and then beyond it. There is no reduced
  first usable version that permanently narrows the product target.
- Target Windows, macOS, and Linux for release.
- Target the filesystem-accessible iPod families supported by the Original iOpenPod:
  full-size iPod generations 1 through 5.5, iPod Classic, iPod Mini, and iPod Nano
  across their supported generations.
- Keep iPod touch and iPod shuffle outside the iOpenPod 2.0 release target.
- Use Original iOpenPod documentation, code, research, tests, captured databases, and
  virtual device behavior as evidence. Translate that evidence into iOpenPod 2.0
  documentation, fixtures, and tests.
- Do not make iOpenPod 2.0 depend on the Original iOpenPod at runtime, and do not copy
  its architecture without review.

## Consequences

- Missing behavior in an interim development build is unfinished migration, not an
  implicit product decision to remove the behavior.
- Architecture work begins by checking the Original iOpenPod before inventing new
  behavior for an already-solved workflow.
- Routine automated testing can use fixtures and virtual device volumes instead of
  writing to a physical iPod.
- Supporting the full compatibility target remains substantial work even though it
  may be delivered in small, verifiable increments.
