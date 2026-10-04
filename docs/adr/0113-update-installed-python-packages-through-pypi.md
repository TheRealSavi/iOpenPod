# ADR-0113: Update installed Python packages through PyPI

- Status: Accepted
- Date: 2026-10-04
- Extends: ADR-0105 and ADR-0112

## Context

The owner requested update checks and automatic installation for PyPI users,
choosing the existing **Update now** and restart flow. The Original iOpenPod's
updater distinguished source, pip, UV tool and pipx installations and directed
tool-managed environments to their owner. ADR-0112 publishes Python distributions
with each GitHub Release, but those packages need their own update provider.

## Decision

Add a PyPI Update Backend behind the existing typed provider and staged controller
flow. Select non-yanked stable wheels from the public Simple JSON index using
`packaging` for PEP 440, Requires-Python and wheel compatibility. Add `packaging` as
an explicit runtime dependency rather than duplicating its format rules or relying
on its incidental presence through another dependency.

Installation evidence must connect the running module to this interpreter's
distribution RECORD, metadata, package directory and pip/UV installer. Reject
editable, local archive and VCS origins. Index installations do not record their
original index, so the Install Channel label states that PyPI provides updates,
without claiming original download provenance. Direct official PyPI wheel origins
remain eligible after an update.

Only explicit user actions download and install. Stage a hash-verified wheel and
perform dependency resolution before taking the Library Draft/work guard. After
acknowledged handoff and authorized process exit, a separate Python helper takes
an exclusive Storage Host installation lease. Every participating GUI launch holds
a shared lease. Revalidate the current installation and selected wheel, install
the exact public URL with its SHA-256, then verify the installed version and
device-free runtime before relaunching with the same interpreter.

Use an existing UV executable or the deployed interpreter's pip, with explicit
interpreter and index selection and ambient configuration removed. Preserve pip
user-site scope. Repository tooling remains UV-only; the pip adapter serves
deployed users whose environments supply pip. No package manager is installed by
this feature. Tool-manager receipts, Conda, recognized project lockfiles, external
management, linked paths and read-only installations require their owning manager.
For the standard UV tool installation recommended in the README, use UV's tool
upgrade with receipt-bound tool and executable directories. Preserve its original
unpinned requirement, and accept the known public-index options written by this
updater. Customized or pinned tool receipts and pipx remain manual. Do not elevate
or bypass those restrictions.

## Consequences

The PyPI trust boundary is its HTTPS metadata and wheel hashes, independently of
GitHub's signed update feed. Package installation may download dependencies after
shutdown. A package-manager failure is not transactional rollback: retain logs,
attempt relaunch, and report the failure on the next successful launch. An unusable
environment may require manual package repair. Settings and device contents are
outside replacement. This does not adopt the standalone frozen health-commit and
rollback protocol.

Automated tests include real disposable UV package and tool environments, installation-use locks,
release selection and the controller's guarded restart. Published A-to-B GUI
acceptance on Windows, macOS and Linux remains required before release claims.
See [Application updates](../app-updates.md#python-packages-and-pypi).
