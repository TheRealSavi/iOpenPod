# iOpenPod Agent Guide

## Purpose

iOpenPod 2.0 is being rebuilt deliberately. Preserve clarity, safety, and explicit
decisions over implementation speed. The current source contains exploratory code;
do not mistake its presence for a settled architecture.

Use the Original iOpenPod project as the behavioral and research baseline. Translate
relevant behavior and knowledge into iOpenPod 2.0 documentation, fixtures, and tests;
do not make the new application depend on the Original iOpenPod at runtime or copy
its architecture without review.

## Start here

Before proposing or making a substantial change, read:

1. `CONTEXT.md` for the system boundaries and present development stage.
2. `GLOSSARY.md` for canonical domain terminology.
3. `docs/source_architecture.md` for the target source architecture.
4. Relevant records in `docs/adr/` for decisions already made.

If documentation and code disagree, surface the disagreement. Do not silently make
one conform to the other.

## Working agreements

- Work in small, reviewable increments.
- Separate investigation, decisions, and implementation.
- Do not add product behavior unless the requested scope includes it.
- Do not add or replace a dependency without explaining the need and tradeoff.
- Treat existing changes as user-owned and avoid unrelated edits.
- Add or update tests whenever behavior changes.
- Prefer explicit interfaces and typed data over loose dictionaries and globals.
- Use terms from `GLOSSARY.md` in documentation, code, tests, and conversation.
- Record durable architectural decisions as ADRs rather than burying them in code.

## Toolchain

- Python is pinned to the 3.12 release line by `.python-version` and
  `project.requires-python`.
- UV is the only Python version, environment, dependency, and command runner.
- Use `uv add` and `uv remove` for dependency changes; do not use `pip`, Poetry,
  Pipenv, or Conda for this repository.
- Ruff is the formatter and linter.
- Mypy is the authoritative static type checker; Pylance is for editor navigation
  and completion.
- Pytest is the test runner.
- Rumdl is the Markdown linter and formatter.
- `pyproject.toml` is the authoritative configuration for all four tools. VS Code
  invokes the locked environment tools and does not maintain duplicate rule lists.
- `.editorconfig` owns portable whitespace, indentation, line-ending, and final
  newline behavior for editors.

Set up the environment:

```shell
uv sync --locked
```

Run the checks:

```shell
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run rumdl check .
uv run mypy
uv run pytest
```

The VS Code task `Check: All` runs the same validation sequence.

Apply automatic formatting and safe fixes with the VS Code task `Format: All`, or
run the underlying commands explicitly:

```shell
uv run ruff format .
uv run ruff check --fix .
uv run rumdl fmt .
```

## Architectural boundaries

The four primary boundaries are:

- **Storage** safely interacts with host filesystems and removable media and knows
  nothing about iPods.
- **Device Registry** identifies known iPods and describes their capabilities; it
  does not discover, mount, or mutate devices.
- **iPodDB** parses, represents, validates, and serializes iPod database formats; it
  does not persist files directly.
- **iOpenPod** owns application workflows, dependency composition, state, and GUI
  behavior.

Dependencies point from iOpenPod toward the other three boundaries. Lower-level
boundaries must not import iOpenPod.

iOpenPod ships as one application and distribution. The other boundaries are
internal packages, not separately released products. Preserve established brand
spelling such as iOpenPod, iPodDB, iTunesDB, ArtworkDB, and iPod wherever practical.

## Device safety

- Direct device mutations belong only in Storage.
- Only one user-selected Active iPod is loaded at a time.
- Device-relative operations use validated relative paths, never arbitrary host
  paths.
- A filesystem session is tied to a device identity, volume identity, mount point,
  and connection generation; a disconnected session is never reused.
- Destructive workflows follow analyze, plan, validate, execute, verify, commit,
  and cleanup phases.
- Prefer staged writes, atomic replacement, journals, verification, and recoverable
  deletion.
- If an Active iPod disconnects, invalidate its Filesystem Session, stop further
  operations, and report that the interrupted work may be incomplete.
- Parsing and serializing an unchanged iPod database must reproduce the original
  bytes exactly, including Unknown Data.
- The shared iTunesDB Chunk definitions are the single source for known field
  offsets, binary types, sizes, defaults, and converters. Parsers and writers
  consume those definitions instead of repeating format knowledge locally.
- Backup Snapshots are user-controlled. Storage safety may not depend on the user
  enabling automatic pre-Sync backup.

## Documentation and decisions

- `CONTEXT.md` explains the system at a glance and distinguishes present state from
  target state.
- `GLOSSARY.md` defines the canonical language. Update it when domain understanding
  changes.
- `docs/source_architecture.md` is the detailed target design.
- `docs/adr/` records accepted architectural decisions and their consequences.
- `docs/agents/` tells engineering workflows how to find local planning and domain
  context.
- Private plans and work items live under `.scratch/` and must not be committed.

## Agent skills

### Issue tracker

Private work items live as ignored Markdown files under `.scratch/`. See
`docs/agents/issue-tracker.md`.

### Triage labels

Local work items use the project's five standard status names. See
`docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. Read `CONTEXT.md`, `GLOSSARY.md`,
`docs/source_architecture.md`, and relevant ADRs. See `docs/agents/domain.md`.

## Code review rules

- Flag dependency-direction violations between the four primary boundaries.
- Flag direct device-file mutation outside Storage.
- Flag destructive operations that lack validation, verification, or a recovery
  strategy.
- Flag new domain synonyms that conflict with `GLOSSARY.md`.
- Flag behavior changes without proportionate tests.
