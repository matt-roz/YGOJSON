# Working in this repository

Orientation for agents. Humans want `README.md`.

**This is a data pipeline, and almost nothing here fails loudly.** A wrong parse does not crash — it
publishes a card with a missing printing, or drops a set, to branches other people consume. A lost
cache does not error — it refetches the whole wiki at one request per 1.1 seconds. A run takes the
better part of a day and only fires on a cron, so the gap between a mistake and its first signal is
measured in days. Almost every rule below exists because something silently produced wrong data.

There is **no CI on pushes or pull requests** (see [CI](#ci)). Locally, `pre-commit run --all-files`
is the only gate you get, and it checks formatting — nothing else. Read carefully rather than
leaning on a pipeline to catch you.

## First command

```sh
python -m pip install -e '.[dev,test]'
pre-commit install
```

**CI runs Python 3.8; you are almost certainly on something much newer.** `setup.py` declares
`>=3.8, <4`, both workflows pin 3.8, and there is no `from __future__ import annotations` anywhere.
So `list[str]`, `dict[str, int]` and `X | None` in annotations run fine on your interpreter and
raise `TypeError` at import time on 3.8. Nothing local catches it — black parses them happily. The
codebase uses `typing.Optional`, `typing.List`, `typing.Dict` throughout; keep writing those.

## Tasks

There is no task runner and no `pyproject.toml`. These are the only commands.


| Command                        | What it does                                                      | Needs generated data | CI                | Agent loop                     |
| ------------------------------ | ----------------------------------------------------------------- | -------------------- | ----------------- | ------------------------------ |
| `pre-commit run --all-files`   | black, isort (line length 88), JSON pretty-format, merge-conflict | no                   | **Yes** (`lint`)  | **Yes — loop closer**          |
| `python -m ygojson --help`     | Smoke check that the package still imports and the CLI parses     | no                   | No                | **Yes** — cheapest real signal |
| `python test/validate_data.py` | Validates everything under `data/` against `schema/v1`            | **yes**              | **Yes** (final)   | Only if you have a `data/` dir |
| `ygojson [flags]`              | The pipeline itself — see below                                   | no                   | **Yes** (the job) | Only with narrow flags         |


`pre-commit` **rewrites files** (black, isort and the JSON formatter all autofix), so run it before
reading a diff, not after.

**There is no unit test suite, no test runner and no type checker.** `test/validate_data.py` is a
schema validator over generated output, not a test — it can only run after a pipeline run has
produced `data/`, and it says nothing about whether the values are *correct*, only that they are
*shaped* right. No importer has a test of any kind. When you change a parser, the honest
verification is a narrow real run (below) and reading the JSON it produces.

### Running the pipeline narrowly

A full run is not something to do casually. Scope it instead:

```sh
ygojson --no-ygoprodeck --no-yamlyugi --yugipedia-pages 'Pot of Greed' --no-manual --no-aggregates
```

`--yugipedia-pages` takes page titles or numeric IDs and confines the Yugipedia import to them,
which is the fastest way to exercise a parser change against real wikitext. Pair it with `--no-*`
flags for the sources and stages you are not touching. `--fresh` resets the last-read timestamps so
sources are re-examined; it does **not** delete database contents.

## The pipeline

`src/ygojson/__main__.py` runs one ordered sequence over a single in-memory `Database`, then saves
once at the end:

```
load (file or --download) → ygoprodeck → yamlyugi → yugipedia
  → regenerate backlinks → manual fixups (distros, sets, products) → deduplicate → save
```

Every stage has a `--no-*` flag. The three importers live in `src/ygojson/importers/`; everything
else — the schema dataclasses, loading, saving, fixups, dedup — is `database.py` (~3.6k lines).

Four things here fail silently and have each already cost a run:

- `temp/` **is the Yugipedia page cache, and it is load-bearing.** Not a scratch directory. Losing
it means refetching the wiki at `RATE_LIMIT = 1.1` seconds per request.
- `--download` **seeds** `last_yugipedia_read` **from the ZIPs at** `REPOSITORY`**.** Point it at a
repository that stopped publishing more than `TIME_TO_JUST_REDOWNLOAD_ALL_PAGES` (30 days) ago and
every run discards its page cache and refetches everything. **This is a fork**, so `REPOSITORY`
defaults to `matt-roz/YGOJSON` releases — the repo that actually publishes these runs — not
upstream. Override with `YGOJSON_REPOSITORY`.
- `USER_AGENT` **must carry working contact information.** Yugipedia's API policy requires the
service name *and* a way to reach whoever is making the requests, and blocks without warning. Set
`YGOJSON_USER_AGENT` if you run this yourself, so the wiki reaches you.
- `--production` **is what gates Yugipedia cache clears.** CI passes it on every job. Omitting it
locally is the safe direction; adding it is not.

Yugipedia is retried on `maxlag` and `readonly` (`MAX_TRIES = 10`, exponential backoff to
`MAX_RETRY_DELAY = 300`). Other API errors still abort the import.

## Data and schema

- `data/` **and** `temp/` **are generated and gitignored.** `manual-data/` is committed source.
- Output comes in two shapes, both written by the same `save()`: `data/individual/` (one JSON per
object, named by UUID, plus a list file) and `data/aggregate/` (one JSON per type). CI publishes
them to the `v1/individual` and `v1/aggregate` branches and attaches ZIPs to the latest release.
- `SCHEMA_VERSION = 1`, with the JSON Schema in `schema/v1/`. **The version appears in four places
that do not move together**: the constant, the `schema/vN/` directory, the two publish branch
names in `db.yml` (which carry a `# update this when we have new schema versions` comment), and
the default `REPOSITORY` URL. A schema bump means editing all four.
- Aggregates currently exceed GitHub's file size limit — the aggregate push step is
`continue-on-error: true` with a TODO about git-lfs. A green run does not mean aggregates landed.



## Manual data

`manual-data/{sets,distributions,sealed-products}` holds everything no source provides — pack odds,
sealed product contents, set corrections. Read `manual-data/README.md` before editing: references
use **Manual Fixup Identifiers** (`name`, `konamiID`, `yugipediaName`, set/locale/edition/rarity/code
for printings), not raw UUIDs, so a fixup can name something that does not exist yet.

A fixup naming an object that never matches is not an error — it silently does nothing. Verify a new
fixup by running the pipeline with `--no-ygoprodeck --no-yamlyugi --no-yugipedia` and checking the
object actually changed.

`manual-data/**/test*.json` is gitignored, so a file named that way is a scratch file.

## CI

Two workflows, and **neither triggers on a push or a pull request**:

- `db.yml` — cron `0 0 */2 * *` plus manual dispatch. Concurrency group `db`,
`cancel-in-progress: false`, because a full run takes the better part of a day and every job
shares the same `temp`/`data` caches.
- `pypi.yml` — manual dispatch only. Lints, builds, uploads to PyPI.

The database run is one strictly sequential chain: `lint` → `pre-yugipedia` (splits the work into 8
partition files under `temp/part*.json`) → `yugipedia-1` … `yugipedia-8`, each `needs` the last →
`post-yugipedia` (manual fixups, `validate_data.py`, publish). State moves between jobs **only**
through the `temp` and `data` GitHub caches, restored by `.github/actions/setup` and saved by
`.github/actions/teardown` under `temp-<run_id>-<job>` / `data-<run_id>-<job>`.

Two consequences worth holding onto: a failure in `yugipedia-4` abandons the remaining half of the
run, and every cache step is `continue-on-error: true`, so a cache that fails to save produces a
**successful** job that quietly hands the next one stale state.

## Fork and branches

`origin` is `matt-roz/YGOJSON` (this fork, and what publishes the data); `upstream` is
`iconmaster5326/YGOJSON`. Work happens on `fix/`, `perf/` and `feature/` branches merged into an
integration branch.

**Commit subjects follow the log, not a linter.** There is no commitlint here, and the log has two
registers: code changes read as plain imperative sentences matching upstream's style
(`Fix set lists dropping cards that repeat at another code`), while repo/tooling changes use
conventional prefixes (`chore(skills): agent skills for handoffs`). `/git-commit` will push you
toward conventional commits for everything — that is the skill's convention, not this repository's.
Code changes that could go upstream should read like upstream's.

## What is not decided

Reaching for any of these is a real decision, not a cleanup. Raise it first.

- **No test framework.** No pytest, no unit tests, no fixtures. Adding one is worth doing and is not
a side quest inside another change.
- **No type checker.** No mypy, no config for one, and the codebase is annotated well enough that
turning one on would be a large, separate diff.
- **No linter beyond black and isort.** No flake8, no ruff.
- **No** `pyproject.toml`**.** Packaging is `setup.py` with setuptools, and the 3.8 floor is load-bearing
for CI.
- **No CI on branches or PRs.** Adding one means deciding what it could even run, given the above.



## Conventions

- **Private helpers are** `_`**-prefixed** (`_load_card`, `_save_set`, `_deduplicate`). Public API is
what `src/ygojson/__init__.py` re-exports.
- **Vocabularies are** `enum.Enum`, with a `*_STR_TO_ENUM` dict mapping source strings onto them.
A new rarity or locale from a source is a new enum member plus a mapping entry — never a bare
string threaded through.
- **Constants carry a docstring** stating what breaks if they are wrong. Follow that when adding one;
several of the traps above are documented exactly there and nowhere else.
- Formatting is black plus isort at line length 88. Do not hand-format.



## Naming

- **Name in project vocabulary**, the words a Yugioh player would search: *printing*, *set contents*,
*locale*, *pack distribution*, *sealed product*. Those are the domain's terms and the schema's.
- **No filler words** — `data`, `helper`, `values`, `misc`, `util` say nothing about a file that
parses set lists.
- **Understanding at a glance has very high value**; avoid very long names, which create clutter.

## Behaviour

### 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them—don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.
- Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it—don't delete it.

When your changes create orphans:

- Remove imports, variables, or functions that **your** changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.