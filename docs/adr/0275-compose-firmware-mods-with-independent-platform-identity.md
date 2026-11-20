# ADR-0275: Compose Firmware Mods with independent platform identity

- Status: Accepted
- Date: 2026-11-17
- Extends: ADR-0230

## Context

The requested product is a firmware modding ecosystem inside iOpenPod, reached
through Device Summary. Users select mods and build a custom firmware, and the
iPod itself lists its installed mods. Apple Firmware version fields must remain
distinct from our Mod Platform Version. The earlier Parachute stock-only route
has been superseded by the user's choice of custom firmware.

Apple's release number does not uniquely identify an input image. Classic update
branches also differ: a later number for one updater family is not permission to
install it on every Classic. Existing lab work proves selected patches and native
imports, but does not establish a complete installable mod platform for every
model. The pinned RepriseOS code is useful evidence and a potential build
foundation, not a product runtime dependency on a sibling checkout.

## Decision

Keep the ecosystem in iOpenPod. Device Summary owns the selection/review
presentation; the Application Layer owns the mod catalog, dependency resolution,
build composition, and installation workflow. Device Registry continues to own
hardware/firmware identification. Storage owns all device mutations, including
any future firmware transport. iPodDB does not gain a firmware patcher.

Retain Apple Firmware identity, a separate Mod Platform Version, each Firmware
Mod's version, and a content-derived Firmware Build ID. Do not overload
`VisibleBuildID`, `BuildID`, or transport revisions with our platform identity.
The platform's development version starts at `0.1.0-dev`; `7.26.0` was a format
example, not a selected release number.

Every build starts with verified pristine Apple inputs. Resolve an explicitly
selected mod set into pinned dependencies, reject cycles, unsupported targets,
declared conflicts, shared exclusive hooks, and overlapping modifications.
Changing a selection rebuilds the composition; it does not reverse patches in
an unknown modified image. Declarative precompiled recipes are the intended
distribution format. Downloading a mod must not execute its arbitrary Host
Python or shell code. Shared hooks belong to the platform or a common dependency.

Generate the native Firmware Mod Registry from the exact resolved composition.
Its embedded data identifies the build and mod releases. A saved installation
record uses the same registry and adds the final image fingerprint; that
fingerprint cannot be embedded in the image it hashes. The registry is read-only
on the iPod initially. It must describe the built composition, not a separately
editable list of checkboxes. A disk-side record is not proof of currently running
firmware or a security credential.

Keep selected, built, installed, and boot-confirmed states separate. Device
Summary reads captured installed metadata through the existing device-load
workflow. Opening or retranslating the page does not probe or mutate the iPod.
Malformed optional metadata does not prevent Library loading; disconnects still
invalidate the session. A source/checksum match alone never enables installation.

The target workflow is identify, determine the latest Apple release for the exact
updater family, prepare any required official update, re-identify, choose mods,
build, review, install, verify, and confirm boot. Official update/restore and mod
installation are distinct operations with their own recovery and identity rules.
Do not automatically restore on connection. If the latest branch has no qualified
mod backend, explain that limitation rather than silently choosing another model's
firmware or downgrading the device.

## Consequences and implementation state

The user subsequently narrowed the active increment to stock firmware basics.
Device Summary now exposes only observed firmware identity and disabled Restore
and Update placeholders. The mod panel and device-load registry capture are
disconnected. The following prototype remains available for future evaluation,
but is not part of the current Device Summary workflow.

The experimental increment provides a standalone selection/review panel, strict registry
interchange, dependency/conflict planning, a checked pure byte-composition engine,
and generated native registry data. Built-in catalog entries deliberately have
no production recipes until their complete native build adapters are qualified.
No button claims to build or install working firmware yet.

Native registry-menu integration, compiled-mod packaging, authenticated catalog
updates, official Apple updating, complete boot bundles, journaled installation,
recovery, and physical Classic/Nano acceptance remain separate implementation
work. The platform is the continuing product scope; this first increment does not
reduce that scope to a Parachute patch.
