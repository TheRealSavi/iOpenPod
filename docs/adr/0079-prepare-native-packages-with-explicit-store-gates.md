# ADR-0079: Prepare native packages with explicit store gates

- Status: Accepted
- Date: 2026-09-25
- Extends: ADR-0001 and ADR-0007
- External media-helper bundling requirement superseded by ADR-0081.
- Candidate-only GitHub publication policy amended by ADR-0104.

## Context

iOpenPod targets the Mac App Store, Microsoft Store, and common Linux stores. The
inherited release workflows referenced Original iOpenPod modules and absent build
files, selected Python 3.13, and published before the rebuilt app had working native
packaging. Native compilation does not establish sandbox or store compatibility.

## Decision

Keep one versioned Python distribution containing all four boundaries. Package its
shared installed entry point into per-platform PyInstaller directory bundles with
the Original iOpenPod icon, runtime resources, native dependencies, and notices.
The executable entry module retains the existing developer CLI and its database
diagnostics outside the Application Layer. Application consumers still use only
the public `iPodDB.library` contract.
UV locks build-only tooling in a separate dependency group. Windows uses MSIX
staging; macOS uses an app bundle; Linux shares desktop metadata between Flatpak
and Snap candidates. Candidates are verified and retained without automatic public
publication while store requirements remain unresolved.

Store sandbox adaptation must preserve Storage's identity-bound Filesystem Sessions,
safe mutation, disconnect invalidation, and truthful eject results. Configuration
alone cannot authorize remembered paths. In particular, Mac App Store release stays
blocked until persistent user-granted file access and native operations work in the
signed sandbox. Package definitions must not weaken those invariants to pass a
build. See [the packaging guide](../packaging.md) for platform gates and evidence.

## Consequences

Builds use the project's Python 3.12 line, retain package metadata and non-Python
resources, and can be tested away from the source checkout. The optional GPU extra
is excluded from the native baseline. The original requirement to bundle reviewed
media helpers is superseded by [ADR-0081](0081-require-user-installed-media-tools.md):
users install the command-line tools, while bundled libraries retain their notice
and source requirements. Store
accounts, identity ownership, signing, native acceptance, and submission remain
separate from compiling a candidate.
