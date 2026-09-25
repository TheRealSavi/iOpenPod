# ADR-0003: Share quality configuration between CLI and VS Code

- Status: Accepted
- Date: 2026-08-20

## Context

The project uses terminal commands, VS Code, and Codex Desktop on multiple machines.
Duplicating lint, formatting, type-checking, or test settings in editor preferences
would allow local diagnostics to disagree with the locked command-line tools.

The original Markdownlint extension also required a JavaScript command-line tool to
provide editor and terminal parity. Adding Node and npm solely for documentation
checks would conflict with the accepted Python 3.12 and UV development environment.

## Decision

- Keep Ruff, Mypy, Pytest, and Rumdl as UV-managed development dependencies locked
  in `uv.lock`.
- Keep their authoritative project settings in `pyproject.toml`.
- Use Rumdl for Markdown checking because its CLI and VS Code language server use
  the same executable and configuration without adding another package manager.
- Keep portable editor rules in `.editorconfig` and normalize repository text files
  with `.gitattributes`.
- Commit `.python-version`, `pyproject.toml`, `uv.lock`, `.editorconfig`,
  `.gitattributes`, and the recommended VS Code extensions, settings, and tasks
  under `.vscode/`.
- Configure VS Code extensions to use the workspace environment and filesystem
  configuration instead of copying rule selections into editor settings.
- Keep Pylance type checking disabled so Mypy remains the sole authoritative Python
  type checker; Pylance remains available for navigation and completion.

## Consequences

- `uv sync --locked` installs the same tool versions on every development machine.
- The terminal, VS Code Problems panel, and VS Code tasks resolve the same rule and
  path configuration.
- Changing a quality rule requires one reviewed change to `pyproject.toml` rather
  than coordinated edits to personal editor settings.
- Markdownlint is disabled for this workspace to prevent duplicate diagnostics when
  it is installed globally; Rumdl is the supported Markdown tool.
- VS Code extension releases are recommended rather than version-pinned, but the
  executables that determine project results remain locked by UV.
