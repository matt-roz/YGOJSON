# `logging.warn` is deprecated and used at 73 call sites

**Date:** 2026-08-06
**Source:** code review prompted by GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603)
**Symptom:** `DeprecationWarning: The 'warn' function is deprecated, use 'warning' instead`
**Occurrences:** 73 call sites
**Severity:** low — mechanical, but it will eventually break

> **Read this first.** Counts and locations were taken on 2026-08-06. Re-run the grep before
> starting; the numbers will have moved. This is the most mechanical item in this batch — do not
> let it grow into a logging refactor unless that is a deliberate decision.

## The issue

The codebase calls `logging.warn(...)` throughout. `logging.warn` has been deprecated since Python
3.3 in favour of `logging.warning`, and emits a `DeprecationWarning`:

```console
$ python3 -W error::DeprecationWarning -c "import logging; logging.warn('x')"
DeprecationWarning: The 'warn' function is deprecated, use 'warning' instead
```

CI runs Python 3.13 today. The alias still exists but is a candidate for removal.

## Where it happens

```
src/ygojson/importers/yugipedia.py    60
src/ygojson/importers/ygoprodeck.py    8
src/ygojson/importers/yamlyugi.py      3
src/ygojson/database.py                2
```

Verify with: `grep -rc 'logging\.warn(' src/ygojson/ --include='*.py'`

## Why it happens

`logging.warn` predates the deprecation and nothing has forced the issue — the alias still works,
and no linter in `.pre-commit-config.yaml` currently flags it.

Note also that `logging.warn` / `logging.warning` at module level log through the **root** logger.
Whether that is intended is a separate question worth a moment's thought while you are in here — a
named logger per module would make it possible to filter importer warnings independently, which is
directly relevant to `2026-08-06-warning-observability.md`.

## What it leads to

Nothing today. When `logging.warn` is eventually removed, every one of these becomes an
`AttributeError` at call time — i.e. an importer that crashes the first time it tries to warn about
anything, in production, on a Python upgrade.

## How we might fix it

Sketch only — **investigate before implementing**:

- Mechanical replacement of `logging.warn(` with `logging.warning(`. It is a pure rename; there is
  no behavioural difference.
- Add a lint rule so it cannot come back. Check what `.pre-commit-config.yaml` already runs and
  whether the existing linter has a rule for this (ruff's `G010`, for example) rather than adding a
  new tool.
- **Decide separately** whether to introduce module-level named loggers. That is a real change with
  real benefits, but it is not this ticket unless you choose to make it so. If you do, do it as a
  second commit so the mechanical rename stays reviewable.

## How to verify

- `grep -rn 'logging\.warn(' src/` returns nothing.
- Run the test suite with `-W error::DeprecationWarning` and confirm no logging-related failures.
- Run a short import and confirm warnings still appear in the output.
