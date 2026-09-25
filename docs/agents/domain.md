# Domain Documentation

This is a single-context repository. Engineering workflows should use the same
system-wide context and language before exploring or changing code.

## Read before substantial work

1. `CONTEXT.md` for purpose, boundaries, current stage, and unresolved questions.
2. `GLOSSARY.md` for canonical domain terms and flagged ambiguities.
3. `docs/source_architecture.md` for the detailed target architecture.
4. Relevant records under `docs/adr/` for accepted decisions.

For behavior already present in the Original iOpenPod, inspect that project before
inventing a new answer. Treat it as the compatibility and research baseline, then
translate the relevant behavior into iOpenPod 2.0 documentation, fixtures, and tests.
It is not a runtime dependency and its source layout is not automatically the target
architecture.

The source architecture describes a target. The source tree contains exploratory
implementation. If they disagree, report the difference instead of silently
assuming either one is authoritative about present behavior.

## Use the glossary

Use terms as defined in `GLOSSARY.md` in work-item titles, hypotheses, tests, code,
and documentation. Do not introduce a synonym merely because it fits a class or
module name better.

If a needed concept is absent, determine whether the new word reflects a real domain
concept. Add it to `GLOSSARY.md` when it does; otherwise use existing language.

## Respect ADRs

Surface a conflict with an accepted ADR explicitly. Do not silently override it.
Propose a new ADR when a durable decision must change, and mark the old ADR as
superseded only after the new one is accepted.

## Documentation layout

```text
/
├── AGENTS.md
├── CONTEXT.md
├── GLOSSARY.md
└── docs/
    ├── README.md
    ├── source_architecture.md
    ├── adr/
    └── agents/
```
