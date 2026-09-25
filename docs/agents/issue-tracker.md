# Issue Tracker: Private Local Markdown

Plans, PRDs, and work items for this repository live as private Markdown files under
`.scratch/`. The directory is ignored by Git and must not be committed or uploaded.

## Conventions

- Use one directory per feature or investigation: `.scratch/<work-slug>/`.
- Store an optional PRD at `.scratch/<work-slug>/PRD.md`.
- Store implementation items at
  `.scratch/<work-slug>/issues/<NN>-<short-slug>.md`, numbered from `01`.
- Record state as a `Status:` line near the top of an item file.
- Append discussion under a `## Comments` heading instead of replacing history.

## Publishing work

When an engineering workflow says to publish a PRD or issue, create the appropriate
private file under `.scratch/`. Do not create a public issue or send content to an
external service unless the user explicitly requests it.

## Fetching work

Read the path supplied by the user. If only a number or short name is provided,
search `.scratch/` locally and ask only when multiple items match.
