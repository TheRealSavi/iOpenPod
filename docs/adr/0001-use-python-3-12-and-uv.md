# ADR-0001: Use Python 3.12 and UV

- Status: Accepted
- Date: 2026-08-20

## Context

iOpenPod 2.0 is beginning from a clean development foundation. Multiple Python
versions, environment managers, dependency tools, and overlapping quality tools
would introduce avoidable variability before the architecture is stable.

The project needs one reproducible local environment shared by VS Code, Codex
Desktop, terminal commands, and future automation.

## Decision

- Develop and test exclusively on the Python 3.12 release line.
- Pin the local interpreter with `.python-version` and constrain project metadata to
  `>=3.12,<3.13`.
- Use UV to manage Python, `.venv`, dependencies, `uv.lock`, and command execution.
- Keep developer-only dependencies in the standard `dependency-groups.dev` group.
- Use Ruff for formatting and linting, Mypy for static type checking, and Pytest for
  tests.
- Keep tool configuration in `pyproject.toml` and portable workspace behavior under
  `.vscode/`.

## Consequences

- `uv sync --locked` reproduces the project environment from committed metadata.
- Commands run through `uv run`; contributors do not need to activate `.venv`.
- Pip, Poetry, Pipenv, Conda, Black, Flake8, and alternate test runners are outside
  the supported development workflow.
- Supporting Python 3.13 or another tool requires an explicit future decision and
  verification, not an incidental local change.
- The lockfile and tool configuration become reviewed project artifacts.
