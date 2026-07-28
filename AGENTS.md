# Agent guide

Use **uv** for every Python command in this repo. Do not use bare `python`, `pip`, `poetry`, or `conda`.

## Setup

```bash
uv sync
uv run pre-commit install
uv run python scripts/dev.py doctor   # verify everything is wired up
```

Human-oriented guide: `docs/DEV.md`. Cursor settings template: `.vscode/settings.json.example`.

## Dev commands (canonical)

All lint, format, typecheck, test, and architecture checks go through one script:

```bash
uv run python scripts/dev.py check          # full gate (lint + types + test + arch)
uv run python scripts/dev.py lint           # ruff check
uv run python scripts/dev.py fmt            # ruff format (opt-in; not in check gate yet)
uv run python scripts/dev.py fmt-check      # verify formatting only
uv run python scripts/dev.py types          # mypy
uv run python scripts/dev.py test           # full pytest suite
uv run python scripts/dev.py test tests/test_foo.py -k pattern
uv run python scripts/dev.py arch           # architecture guardrails
uv run python scripts/dev.py doctor         # what's installed / misconfigured
```

Run the app:

```bash
uv run iopenpod
```

Build (release tooling):

```bash
uv run pyinstaller iOpenPod.spec
```

## Linting: ruff only

This project uses **ruff** for lint and format. Do **not** run flake8, black, isort, or pylint — ruff covers those roles and is what CI runs.

Config lives in `pyproject.toml` under `[tool.ruff]` and `[tool.mypy]`.

## Before finishing a change

1. `uv run python scripts/dev.py lint`
2. `uv run python scripts/dev.py test` (or a targeted test file)
3. For cross-layer changes: `uv run python scripts/dev.py arch`

For large changes, run `uv run python scripts/dev.py check`.

## Safety

- Tests must use `tmp_path` and `create_virtual_ipod()` — never write to a real iPod mount.
- Device capabilities: use `capabilities_for_family_gen()` from `ipod_models.py`; do not hardcode generation logic elsewhere.
- GUI work must stay off the main thread (`ThreadPoolSingleton` + workers).

## Architecture map

See `CLAUDE.md` (local) or browse by area:

| Area | Path |
| ------ | ------ |
| Binary DB parsers/writers | `src/iopenpod/itunesdb_*`, `src/iopenpod/artworkdb_*` |
| Sync engine | `src/iopenpod/sync/` |
| GUI | `src/iopenpod/gui/` |
| Device model / virtual iPod | `src/iopenpod/device/`, `ipod_models.py` |
| ADRs | `docs/adr/` |

## Issues

GitHub issues via `gh`. Label fully specified agent work `ready-for-agent`. See `docs/agents/issue-tracker.md`.
