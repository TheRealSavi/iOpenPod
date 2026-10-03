# Publish validated tagged GitHub Releases

- Status: Accepted
- Date: 2026-10-01
- Amends: ADR-0079's candidate-only GitHub publication policy

The owner requested automatic public GitHub Releases on version tags. A pushed
`v<version>` tag must match `pyproject.toml`. The release workflow runs the reusable
Health workflow, builds and smoke-tests Windows x64, macOS arm64 and x86_64, and
Linux x64 bundles, verifies the complete artifact set and hashes, and uploads all
assets to a draft before making it public. Pull requests and manual branch builds
retain downloadable candidates. Manual runs on a version tag also publish.

Health runs the authoritative formatting, lint, and Mypy checks on Windows, whose
Qt bindings match the supported type-checking environment. Tests run independently
on all four native targets, using the controlled macOS environment from ADR-0094.
This preserves Mypy's project rules and keeps the known Mac stub limitation from
preventing Mac runtime tests. Native builds exclude development tooling.

GitHub downloads include the Python distributions, native archives, dependency
inventories, Mac compatibility reports, checksums, the application source, and
verified pinned third-party source archives. Existing public releases are never
overwritten. Failed uploads leave an unpublished draft for deliberate recovery.

This decision enables publication; it does not establish platform acceptance or
complete the outstanding native source audit. Tagging is the maintainer's release
decision. The documented licensing/source requirements still apply, including the
missing Mac-specific and Linux native evidence. Production signing, notarization,
Store submission, and PyPI publication remain separate work. GitHub release notes
must describe the unsigned downloads and acceptance limits truthfully.

The owner subsequently requested the same tag-driven flow plus a manual release
button. A manual dispatch on `main` can request publication of its checked-out
version. Native builds run alongside Health to retain candidate artifacts even
when tests fail; publication still requires both to pass. Only after release
assembly succeeds may the publication job create the matching tag at the built
commit. Existing tags are never moved. Publication stays in the same workflow
because tags created with `GITHUB_TOKEN` do not trigger another workflow run.
