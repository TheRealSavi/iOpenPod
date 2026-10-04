# ADR-0112: Publish Python distributions with GitHub Releases

- Status: Accepted
- Date: 2026-10-04
- Amends: ADR-0104's deferred PyPI publication

## Context

The owner requested that Build and release also update PyPI. Native builds already
produce Python distributions, and release assembly selects the checked Windows
wheel and sdist for the same version and commit as the native downloads.

## Decision

After successful GitHub publication, publish those assembled distributions to PyPI
through a separate job in `release.yml`. Transfer only the wheel and sdist in a
dedicated Actions artifact. Use UV Trusted Publishing through the `pypi` environment,
with `id-token: write` limited to that job and no stored PyPI token or source rebuild.
Candidate-only runs do not publish. GitHub Release assets remain governed by
ADR-0107 and ADR-0110; the signed update feed remains independent of PyPI.

## Consequences

The maintainer must register this repository, workflow, and environment as a PyPI
Trusted Publisher. PyPI can fail after the GitHub Release is already public; retry
only the failed job against the retained artifact. UV skips identical published
files and rejects conflicting contents, preserving immutable versioned releases.
See [the packaging guide](../packaging.md#pypi-setup-and-recovery) for setup and
recovery instructions.
