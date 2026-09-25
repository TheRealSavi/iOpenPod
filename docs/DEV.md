# Dev workflow (Python + uv + Cursor)

One rule: **everything goes through `uv`**. The project venv (`.venv`) holds all dev tools — you do not need global flake8, black, or mypy.

## First-time setup

```bash
git clone https://github.com/TheRealSavi/iOpenPod.git
cd iOpenPod
uv sync
uv run pre-commit install
```

Copy Cursor/VS Code settings (optional but recommended):

```powershell
# Windows
Copy-Item .vscode/settings.json.example .vscode/settings.json
```

Install the **Ruff** extension in Cursor (`charliermarsh.ruff`).

## Daily commands

| What | Command |
| ------ | --------- |
| Run the app | `uv run iopenpod` |
| Lint | `uv run python scripts/dev.py lint` |
| Typecheck | `uv run python scripts/dev.py types` |
| Test (all) | `uv run python scripts/dev.py test` |
| Test (one file) | `uv run python scripts/dev.py test tests/test_foo.py` |
| Full CI gate | `uv run python scripts/dev.py check` |
| Health audit | `uv run python scripts/dev.py doctor` |

## What's installed where

```css
uv (global)          → manages Python versions + creates .venv
.venv/               → ruff, mypy, pytest, pre-commit, pyqt6, …
scripts/dev.py       → single entry point for lint/types/test/arch
pyproject.toml       → config for ruff, mypy, pytest
.pre-commit-config   → runs lint + arch on git commit
AGENTS.md            → rules for AI agents (same commands)
.cursor/rules/       → Cursor auto-injects python-tooling rule
```

## Tool choices (intentional)

| Tool | Role | Do NOT also use |
| ------ | ------ | ----------------- |
| **uv** | install, run, sync | pip, poetry, conda |
| **ruff check** | lint (E/F/B/I/UP) | flake8, pylint |
| **ruff format** | formatter (opt-in) | black, isort |
| **mypy** | types (subset of files) | pyright in CI |
| **pytest** | tests | unittest runner directly |

Ruff replaces flake8/black/isort. Mypy is separate because it does type analysis, not style.

## Python version

Pinned to **3.11** via `.python-version`. uv reads this automatically.

You may have 3.12/3.13/3.14 installed globally — ignore them for this repo. Always use `.venv` (3.11).

## Pre-commit

After `uv run pre-commit install`, every `git commit` runs:

- `ruff check` (via `dev.py lint`)
- architecture guardrails (via `dev.py arch`)

Mypy and full pytest run in CI / when you explicitly call `dev.py check`.

## Cursor + AI agents

Agents should read `AGENTS.md`. The always-on Cursor rule in `.cursor/rules/python-tooling.mdc` repeats the same commands.

When prompting agents:

> Use uv only. Run `uv run python scripts/dev.py lint` and targeted tests before finishing.

## Troubleshooting

### "command not found" for ruff/mypy/pytest

```bash
uv sync
uv run python scripts/dev.py doctor
```

### Wrong Python version

```bash
uv python pin 3.11
uv sync --reinstall
```

### Pre-commit not running

```bash
uv run pre-commit install
```

### Not sure what's broken

```bash
uv run python scripts/dev.py doctor
```
