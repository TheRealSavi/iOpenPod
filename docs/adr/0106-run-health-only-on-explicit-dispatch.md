# ADR-0106: Run Health only on explicit dispatch

- Status: Accepted
- Date: 2026-10-03
- Amends: ADR-0104's automatic Health execution and publication gate

## Context

The owner requested that Health never run automatically. Previously, pushes and
pull requests triggered it directly, and release and Flatpak workflows called it.

## Decision

Health exposes only `workflow_dispatch`. Remove its push, pull request, and reusable
workflow triggers, together with release and Flatpak calls and dependencies.
Maintainers explicitly dispatch Health when they want its checks.

## Consequences

Health retains all existing checks, but publication and Flatpak candidate builds
no longer require a successful Health run. Native build validation, frozen smoke
tests, and release assembly remain required by their respective workflows.
This supersedes only ADR-0104's Health execution and gating policy; its other
publication requirements remain in effect.
