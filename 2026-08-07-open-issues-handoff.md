# Handoff — YGOJSON, the 27 open issues

**Date:** 2026-08-07 · **Repo:** `/home/matt/Workspace/YGOJSON` (github: `matt-roz/YGOJSON`)
**Your task:** work the 27 open issues one at a time. **Do not create new issues.**

Read `CLAUDE.md` first. It overrides your defaults and it is accurate.

---

## Where things stand

The 2026-08-06 warning audit ([#20](https://github.com/matt-roz/YGOJSON/issues/20), now closed) ran
four waves and closed all nineteen of its findings. Each wave was a PRD → PR: #25→#31, #33→#53,
#54→#69, #73→#95. The closing comment on #20 has the full table and the batch's conclusions — read it
before starting, it is the cheapest context available.

**The 27 issues you are working are not from that audit.** They accumulated underneath it, one wave at
a time, and eleven are marked `data-loss`. No tracking issue covers them and none carries a wave label.

### One thing to raise with the user before anything else

**`main` does not have Wave 4.** `origin/main` is at `eb7bdaf22` (Wave 3's merge); the integration
branch `feature/various-pipeline-fixes` is 10 commits ahead at `9975d8b4f`. `db.yml` runs on a cron
against the default branch, so **the next scheduled run will not test Wave 4** — the same situation
Wave 3's outcome documented, where a run was dispatched and turned out to sit on an older commit.

Wave 4's definition-of-done item (warning count down from 6884, predicted ~275 over ~20 rows) cannot be
evaluated until `main` is fast-forwarded. That is a decision for the user, not for you.

---

## Ground rules for this session

- **Create no new issues.** When work surfaces something new — and it will, see "the pattern" below —
  record it as a **comment on the closest existing issue** and surface it in your report to the user.
  Do not silently drop a finding, and do not open a ticket for it.
- **One issue at a time**, merged or reported before starting the next.
- **`feature/various-pipeline-fixes` is HEAD and is where you work from.** It is already checked out at
  `9975d8b4f`, clean and fast-forwarded, 10 commits ahead of `main`, with `pre-commit` exiting 0.
  Branch from it — never from `main`, which does not have Wave 4. Work branches here are `fix/`,
  `perf/` or `feature/`; PRs target `feature/various-pipeline-fixes`.
- **Never merge a PR.** Create it and stop.

---

## Environment — three traps that will cost you an hour each

**1. There is no `pip` and no `pre-commit` on the system Python.** `python3 -m pip` does not exist.
`ensurepip` and `venv` do. A working venv already exists — use it rather than building another:

```
~/.cache/ygojson-prd73-orchestrator/bin/pre-commit run --all-files
~/.cache/ygojson-prd73-orchestrator/bin/python test/validate_data.py
```

To build a fresh one, put it **outside the repository** — `.venv` is *not* in `.gitignore`, so an
in-repo venv gets staged:

```
python3 -m venv "$HOME/.cache/ygojson-work" && "$HOME/.cache/ygojson-work/bin/pip" install -q -e '.[dev,test]'
```

**2. If you work in a git worktree, you cannot `git checkout` a branch that is checked out elsewhere.**
Use `git checkout -B <new> origin/<base>` instead.

**3. Do not write a shell wait-loop that greps for the process it is waiting on.**
`until ! pgrep -f "ygojson --no-ygoprodeck"; do sleep 20; done` never terminates: `pgrep -f` matches
the polling shell's own command line. Two of these were left spinning for 36 minutes during Wave 4.

---

## Repo rules that actually bite

- **CI runs Python 3.8.** `typing.Optional`/`List`/`Dict` only. `list[str]`, `dict[str,int]` and
  `X | None` in annotations import fine for you and crash on 3.8. There is no
  `from __future__ import annotations` anywhere and black will not warn you.
- **`pre-commit run --all-files` is the only gate**, and it rewrites files — run it *before* reading a
  diff, not after. It is also the `lint` job that gates the entire sequential database chain.
- **Never pass `--production` or `--download`** to `ygojson`. `--production` gates Yugipedia cache
  clears; `--download` can discard the page cache and trigger a full refetch at 1.1s/request.
- **`temp/` is the Yugipedia page cache and is load-bearing.** Copy it into any worktree
  (`cp -r /home/matt/Workspace/YGOJSON/temp .`) rather than refetching.
- **Commit subjects follow the log, not a linter.** Code changes read as plain imperative sentences
  matching upstream (`Fix set lists dropping cards that repeat at another code`). Only repo/tooling
  changes use conventional prefixes. `/git-commit` will push you toward conventional commits for
  everything — that is the skill's convention, not this repository's.
- **No test framework, no type checker, no linter beyond black/isort.** Adding one is an explicit
  decision to raise with the user, not a side quest. `test/` holds standalone scripts; follow that
  shape — `test/validate_print_status.py` is the newest example and runs offline in `lint`.

---

## Analysis traps — every one of these produced a wrong answer during Wave 4

- **The local `data/` directory is not a clean snapshot.** It is a pre-Wave-1 downloaded baseline
  (`increment: 2351`) with two sets overwritten by a local run (`Structure Deck R: Lost Sanctuary`,
  `Structure Deck: Egyptian Gods' Advent`). It is fine for "does X publish at all" and **wrong for any
  load-bearing claim** — a Wave 4 claim about `Collectible Tins 2006 Wave 2` was drawn from it and was
  false. For real figures, measure against the `individual.zip`/`aggregate.zip` published by run
  31142489208 (release assets, `runID` in `meta.json`).
- **`locales.<lc>.cardInfo` is not a printing count.** It holds per-locale image/price entries only.
  Printings live in `contents[].cards`; count entries whose `contents[].locales` includes your locale.
  Using `cardInfo` reports a main booster as having 1 card.
- **Card names contain colons** (`Number 39: Utopia`). A non-greedy regex splitting a log line on
  `in row (.*?): ` splits in the wrong place and invents values.
- **Per-job histogram lines truncate with `...`.** They match the same regexes as real warning lines
  and become phantom entries. Filter them.
- **Summary warnings are per-job, not per-row.** `rarity.py`'s `Could not resolve N rarities` fires
  once per job; counting it as per-row inflated a Wave 4 figure by 2×.
- **A count from a warning bucket is a floor.** Buckets measure only the paths that chose to warn.

---

## Investigation techniques that work here

- **Yugipedia template error-tracking categories answer corpus questions in one request.**
  `Category:((Set gallery)) transclusions to be checked` contained exactly the three stub pages of #11.
  Try this *before* fetching pages in bulk. This was the single best discovery of Wave 4.
- **Yugipedia has no CirrusSearch.** `insource:` returns zero for everything, including strings that
  certainly exist. A zero is not evidence of absence.
- **Batch API queries:** `action=query&titles=A|B|C` takes 50 titles at once. Add `&redirects`.
  A full-corpus fetch takes ~6 minutes, not hours — the importer batches 50 pages per XML export.
- **Set `YGOJSON_USER_AGENT`** to something carrying the maintainer's real contact details before any
  wiki access. Yugipedia's policy requires it and they block without warning. (The value used during
  Wave 4 contained the maintainer's personal email — ask the user rather than guessing one.)
- **Warning data for a real run** comes from its job logs, e.g. run 31142489208:
  `gh api repos/matt-roz/YGOJSON/actions/jobs/<id>/logs`. The `warning-summary` job holds the
  22-row histogram. Note that some buckets are routed to `EXPECTED_CONDITIONS` and are counted but
  never printed, so their per-page lines are *not* in the logs.

### Narrow verification run

```
export YGOJSON_USER_AGENT="…"          # ask the user
ygojson --no-ygoprodeck --no-yamlyugi --no-manual --no-aggregates --yugipedia-pages 'Some Set'
```

Copy `temp/` and `data/` in first so card lookups resolve against real data. **#24 is live**:
`--yugipedia-pages` silently imports nothing when given a page that is not a discovered set, and a run
against an empty database publishes zero printings because nothing resolves — both look exactly like a
parse failure. Say which one you hit rather than concluding the parser broke.

---

## The pattern you should expect

Across four waves, **the largest finding of each wave was in no issue on the list** — a serializer
reshuffling all 3,376 set files, `deloldprints()` minting fresh printing UUIDs on every production run,
a `lint` job that could never pass, and #91's 32 silently empty sets. In Wave 4, **four of six issues
were wrong about what they described.**

So: **re-measure before implementing.** An issue's stated cause is a hypothesis and its count is a
floor. When an issue turns out to be wrong, say so plainly in the PR and in a comment on the issue —
that is the most valuable output this workflow produces, and it is why you must not silently
re-scope.

---

## Suggested order

These are grouped by coupling, not by priority alone. **#91 and #94 must be scoped together** — both
change how a set is identified and both touch `add_set`; working them separately risks one
invalidating the other's measurements.

| # | Issues | Why together |
|---|---|---|
| 1 | **#91 + #94 + #93** | Set identity and discovery. #91: list-page name built from the disambiguated page title, 32 sets publish zero printings, silent. #94: 146 Konami IDs claimed by >1 set, winner alternates run to run. #93: `SET_CATS` walks downward only and two categories have no parents. All three decide which sets exist and what they contain. |
| 2 | **#85 + #87 + #89 + #86 + #88** | The unissued histogram buckets. #85 correlates exactly with the only 8 sets of 3384 that publish no `contents`. #89 is 1 of **38** empty Duel Links sets — 37 warn nothing, so the bucket badly understates it. #88 demonstrates *no* loss and may just close. |
| 3 | **#21 → #84** | Rush Duel cards never import (3,147 of them). #84's odd-value cards were checked and are **anime**, not Rush Duel — so #21 does *not* unblock it; verify before assuming either way. |
| 4 | **#46 + #48** | Rarity family. #46 is `needs-decision` and its fix churns printing UUIDs — that consequence is why it is still open. |
| 5 | **#22 + #51 + #52 + #65** | Images and printing identity. #22 also suppresses `replica`. #52 is a schema field populated by nothing. |
| 6 | **#32 + #24 + #66 + #71 + #72** | Tooling and metadata. #32's premise needs revising — see the Wave 4 comment on it; the early `return` republishes the previous run's copy rather than skipping the product. #72 is documentation-only. |
| 7 | **#47** | Ordering nobody chose; one path silently drops legality history. |
| 8 | **#83, #92, #90, #49, #50** | **Wiki-side, not code.** These need a Yugipedia account and editorial judgement. You cannot close them by writing Python — check with the user before spending time here. |

Start with group 1. It is the largest measured data loss on the board and nothing else depends on it.

---

## Suggested skills

- **`/gh-cli`** — all issue reading, commenting and PR creation.
- **`/git-commit`** — but override its conventional-commit default for code changes; see the commit
  convention above.
- **`/code-review`** — before opening a PR on anything touching set identity (group 1). This codebase
  fails silently; a review pass is cheaper than a bad publish.
- **`/security-review`** — not relevant to this work; skip it.
- **Do not** reach for `/write-a-prd`, `/prd-to-issues` or `/orchestrate-prd` — they create issues,
  which the user has ruled out for this session.

---

## Reference

| | |
|---|---|
| Closed audit tracker, with all four wave outcomes | [#20](https://github.com/matt-roz/YGOJSON/issues/20) |
| Wave 4 PRD, with corrections appended | [#73](https://github.com/matt-roz/YGOJSON/issues/73) |
| Wave 4 PR | [#95](https://github.com/matt-roz/YGOJSON/pull/95) |
| PRD documents on disk | `.agents/prds/` |
| Last real pipeline run (all figures come from it) | run `31142489208` |
| Integration branch | `feature/various-pipeline-fixes` @ `9975d8b4f` |

The pipeline is `load → ygoprodeck → yamlyugi → yugipedia → backlinks → manual fixups → dedupe → save`,
all in `src/ygojson/__main__.py`. Three importers in `src/ygojson/importers/`; everything else —
schema dataclasses, loading, saving, fixups, dedup — is `database.py` (~3.6k lines).
