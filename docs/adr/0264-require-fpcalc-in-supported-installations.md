# ADR-0264: Require fpcalc in supported installations

- Status: Accepted
- Date: 2026-11-13
- Amends: ADR-0081, ADR-0084 and ADR-0103's treatment of fpcalc as an optional dependency

## Context

The owner explicitly requires fpcalc. The immutable Linux and Flatpak research
incorrectly recommended keeping it optional because earlier decisions and current
code permit reduced operation without it. That recommendation does not meet the
owner's requirement.

## Decision

FFmpeg, FFprobe and Chromaprint's fpcalc are required application dependencies.
Every supported installation channel must provide a working installation and
execution route for all three while preserving the requirement that their
executables remain outside the iOpenPod distribution. Acoustic Fingerprint
support is part of the required functionality.

A packaging proposal that supplies only FFmpeg and FFprobe is incomplete.
Resolve fpcalc installation, runtime compatibility, discovery, execution and
updates as part of Linux and Flatpak support. Do not use missing-tool fallback
behavior as a reason to classify fpcalc as optional or omit it from acceptance.

## Consequences

Current code still permits explicit Adds and previously proven Sync relationships
without fpcalc under ADR-0084. This is an implementation discrepancy to address
in behavior work; this research correction does not change executable code or
define new startup or per-operation gates. Existing handling of individual
unfingerprintable files and retained matching data remains a separate concern.

Older ADRs remain historical evidence. This decision governs the dependency
requirement when their optional-dependency wording conflicts with it.
