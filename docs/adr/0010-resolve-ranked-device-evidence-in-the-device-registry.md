# ADR-0010: Resolve ranked Device Evidence in the Device Registry

- Status: Accepted
- Date: 2026-08-28

## Context

Identifying an iPod requires evidence from several places. A Host may observe USB
identifiers and serials, while an iPod Volume may contain SysInfo metadata with a
model number, product serial, firmware version, and cached USB information. Those
sources can be incomplete, coarse, stale, or contradictory. A USB Product ID often
identifies only a family or generation, and recovery-mode Product IDs must not be
treated as normal operating connections.

The Original iOpenPod contains valuable model, serial-suffix, USB Product ID, and
capability research. Its device scanner also combines platform probing, filesystem
reads, mutable global Active iPod state, identity resolution, and capability
selection in one subsystem. Reusing that structure would violate the Storage and
Device Registry boundary accepted in ADR-0002.

Product serial numbers and USB or FireWire transport serials are different
identifiers. Confusing them can select an incorrect model or use the wrong value for
database signing. A Device Profile also describes a marketed hardware variant; its
advertised capacity is not proof of the Physical Device's current storage capacity,
which may have been upgraded.

## Decision

Device Registry is a pure, immutable evidence-resolution module:

- Storage discovers Physical Devices and Volumes and obtains current Host hardware
  observations. Device Registry performs no Host probing, mounting, path access, or
  filesystem reads.
- The Application Layer supplies a `DeviceEvidence` value containing typed Device
  Identifiers, provenance, and one of three evidence authorities: current hardware,
  device metadata, or derived evidence.
- Current hardware evidence outranks device metadata, which outranks derived
  evidence. Higher-authority exact evidence may resolve a disagreement with stale
  lower-authority evidence and must retain a structured issue describing that
  disagreement. Equally authoritative exact identifiers that disagree produce a
  conflicting result; Device Registry does not guess.
- Product serials and transport serials remain separate typed collections. Only a
  product serial participates in serial-suffix model lookup.
- USB identity is the pair of Vendor ID and Product ID. Product ID alone is not
  globally meaningful. Normal-mode USB identifiers constrain or corroborate exact
  evidence and otherwise produce a bounded set of candidates. Recovery-mode USB
  identifiers produce a recovery result and never a normal exact result.
- `DeviceRegistry.identify()` returns an immutable `IdentificationResult` containing
  a status, connection mode, optional exact Device Profile, bounded candidates, and
  structured issues.
- A Device Profile owns grouped Display, Audio, Artwork, Video, and Database
  Capabilities. Built-in catalog data is translated from the Original iOpenPod's
  research for release-target full-size iPod generations 1 through 5.5, iPod
  Classic, iPod Mini, and iPod Nano families. Original iOpenPod remains neither an
  import nor a runtime dependency.
- Parsers such as `parse_sysinfo()` accept bytes or text already obtained by an
  authorized caller and return Device Evidence. They do not accept Host paths.
- An Identification Result describes identity only. It does not authorize device
  I/O, establish a Filesystem Session, or prove that a connection is safe for
  mutation.

## Consequences

Identity and capability behavior can be tested with captured values and synthetic
evidence without connecting a physical iPod. Platform-specific Storage adapters can
evolve independently and feed the same interface on Windows, macOS, and Linux.

Callers must retain the distinction between current and cached evidence and must not
manufacture current-hardware authority for persisted values. Application and
Storage safety checks remain necessary after exact identification.

Catalog expansion and corrected device facts are localized data changes. Additional
identifier adapters, including SysInfoExtended and platform hardware observations,
can be added without changing the primary registry interface.
