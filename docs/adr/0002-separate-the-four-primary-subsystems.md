# ADR-0002: Separate the four primary subsystems

- Status: Accepted
- Date: 2026-08-20

## Context

iOpenPod must combine platform-specific removable-media access, iPod hardware
knowledge, binary database formats, application workflows, and a Qt GUI. Mixing
these responsibilities would make destructive filesystem behavior difficult to
audit and database logic difficult to test independently.

The architecture draft identifies four distinct kinds of knowledge that should
cooperate without collapsing into one package.

## Decision

The system has four primary architectural boundaries:

- **Storage** owns generic, safe host filesystem and removable-media operations.
- **Device Registry** owns iPod identification and capability descriptions.
- **iPodDB** owns iPod database representation, parsing, validation, and
  serialization.
- **iOpenPod** owns application orchestration, state, services, and GUI behavior.

iOpenPod may depend on the other three boundaries. Storage, Device Registry, and
iPodDB must not depend on iOpenPod. iPodDB works with data, bytes, and generic
streams; actual device persistence goes through Storage under Application Layer
coordination.

This ADR establishes responsibilities and dependency direction, not final Python
package names or distribution boundaries.

## Consequences

- Platform-specific code remains inside Storage.
- iPod-specific conditions do not leak into generic filesystem operations.
- Database parsers and writers can be tested without mounting a device.
- GUI components call application services instead of manipulating databases or
  device files directly.
- Cross-boundary interfaces must use explicit data and errors.
- New work that crosses these boundaries requires design review and may require a
  superseding ADR.
- Existing exploratory code may require later restructuring to conform to the
  decision.
