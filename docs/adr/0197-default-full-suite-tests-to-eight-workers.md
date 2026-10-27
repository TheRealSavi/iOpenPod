# ADR-0197: Default full-suite tests to eight workers

- Status: Accepted
- Date: 2026-10-26

## Context

The full suite has grown large enough that serial execution slows routine
validation. The user requested a permanent eight-worker default. Focused debugging
and collection should retain their low-overhead, single-process behavior, and
the same full-suite command should work locally, in CI and from VS Code.

## Decision

Use `pytest-xdist` with eight workers for ordinary full-suite invocations:
`uv run pytest`, `uv run pytest tests`, and `uv run pytest .` from the repository
root. Use whole-file scheduling (`loadfile`) so tests within one module remain
together, preserving module-scoped fixture reuse and reducing disruption to GUI
test state. The fixed count makes this policy predictable across machines;
automatic CPU-count selection is not the default.

Focused paths or node IDs, `-k` and `-m` filtering, last-failed selection (`--lf`),
and collection-only invocations use a serial default. `-n8` can parallelize a
focused run. `-n0` is a diagnostic override, not the normal full-suite validation
command. Explicit numeric worker options take precedence over automatic selection.

The [Pytest configuration](../../pyproject.toml) owns the worker count and
whole-file scheduling default. The [repository hook](../../conftest.py) determines
whether an invocation selects the full suite before workers start. CI and VS Code
invoke Pytest without carrying their own copies of the worker count.
`pytest-xdist` belongs to the development dependency groups: `dev` for ordinary checks and
`packaging-checks` for the macOS packaging test environment. It is not an
application runtime dependency. UV owns both declarations and the lockfile.

The [test fixture](../../tests/conftest.py) gives each test process or worker a
private default writer-lock directory because unrelated tests reuse synthetic
volume and host-resource identities. Explicit lock directories and real operating
system lock acquisition remain intact; [subprocess tests](../../tests/test_storage_lock_isolation.py)
verify exclusion against a competing process. The Synesthesia temporary-copy
cleanup assertion uses its own test directory so another worker's temporary files
cannot affect its result. These changes isolate test resources without changing
the application's locking or temporary-file behavior.

## Consequences and validation

Workers use more memory and can contend for CPU or filesystem resources. Grouping
by file preserves local ordering and fixtures within that file; it does not make
shared external resources safe or establish independence between test modules.
Cross-file ordering must not become part of a test's contract.

Acceptance requires [tests of command selection and explicit overrides](../../tests/test_pytest_execution.py),
followed by a complete run under the default eight-worker policy. A successful serial
diagnostic run alone does not validate parallel execution. Native platform tests
retain their existing prerequisites and skip conditions; this decision does not
claim a measured speedup or cross-platform acceptance before those checks run.
