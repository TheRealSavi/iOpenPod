# ADR-0189: Protect GitHub release credentials

- Status: Accepted
- Date: 2026-10-25
- Amends: ADR-0104, ADR-0109, and ADR-0112

## Context

The owner requested repository security hardening while preserving version-tag and
manual releases, and explicitly chose approval before publication and signing.
Application-code review alone does not cover workflows, build scripts, dependencies,
or upstream Actions. The update-signing key must continue matching installed clients.

## Decision

Keep the existing build matrix, artifacts, version checks, and release triggers.
Use protected environments `github-release`, `pypi`, and `release-signing` for the
corresponding publication jobs. Each requires `TheRealSavi` approval, permits only
branch `main` and tags `v*`, and disables administrator approval bypass. Allow
self-review because there is only one maintainer. Keep PyPI's existing workflow
filename and environment identity. Health remains manual under ADR-0106.

Move the existing private signing seed into the `release-signing` environment;
remove its repository-level copy only after the environment-aware workflow is live.
Keep the public trust configuration unchanged. Pass only the named secret to the
reusable workflow, which selects its protected environment. Signing does not restore
dependency caches. Publish jobs independently reject PR events and unrelated refs.

Pin external Actions to verified upstream commit SHAs without changing their major
versions. Use Dependabot to propose Action updates. Disable checkout credential
persistence and scope explicit release-token environment variables to their API steps.
Enable dependency alerts, security updates, and CodeQL scanning without making them
new release prerequisites.

Protect `main` against force pushes and deletion, dismiss stale PR approvals, and
require review with code ownership for automation, dependencies, packaging, and update
code. Retain the named owner's PR bypass because the sole maintainer cannot approve
their own PR. Do not impose PR requirements on `update-feed` or prohibit creating
version tags: the existing release jobs need those writes.

## Consequences

Releases pause for explicit deployment approvals. Fork PR candidates remain separate
from publication. GitHub settings and workflow files jointly implement the boundary;
an approval must cover the exact commit, build inputs, and workflow being released.
Administrator account compromise remains outside these protections.

Older tagged workflows without the signing environment cannot sign after removal of
the repository secret. Renew or repair a published feed through the current `main`
workflow using the existing version. Do not restore the broad secret or rotate the
trust key to rerun an old workflow. Existing released downloads remain unchanged.
