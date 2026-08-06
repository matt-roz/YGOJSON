# 2137 warnings per run with no summary, so real bugs stay invisible

**Date:** 2026-08-06
**Source:** GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) (Generate/Upload Database)
**Symptom:** the run is green; the log contains two instances of outright data corruption
**Occurrences:** 2137 warning lines across 10 jobs
**Severity:** medium — this is the reason the other issues in this batch went unnoticed

> **Read this first.** The numbers below are from one run on 2026-08-06 and will drift. Re-derive
> them before designing anything. More importantly: this handoff proposes process/tooling changes,
> which are opinionated. Treat the specific proposals as options to evaluate, not decisions taken.

## The issue

A successful run emits 2137 warnings. There is no summary, no grouping, and no signal when a *new
kind* of warning appears. The distribution:

```
1480  Found multiple images for the same card
 176  Got strange quantity in Set Card Lists:...
 175  Got strange rarity in Set Card Lists:...
  65  Could not decipher rarity code
  61  Found set without set table
  48  Printing in gallery ... not found in locale
  44  Found strange subgallery line
  36  Found set without set navigation table
  17  Unknown set to fixup
  16  Found card with illegal card type
  19  misc one-offs
```

Two of those buckets are silently corrupting data — the 176 "strange quantity" lines mean card
quantities are wrong in four Structure Decks, and 15 of the 65 "could not decipher rarity" lines
mean gallery rows are being parsed with every column shifted. Both had been happening for an
unknown number of runs. They were only found because someone read the whole log by hand.

Meanwhile the three genuinely rare, genuinely actionable one-offs (`Bad password 'None'`,
`bad ATK: None`, `Monster typeline bit unknown`) are three lines out of 2137.

## Where it happens

Warnings are emitted via bare `logging.warn` from ~73 call sites across
`src/ygojson/importers/yugipedia.py`, `ygoprodeck.py`, `yamlyugi.py` and `database.py`. There is no
aggregation layer and nothing in `.github/workflows/` inspects the output.

## Why it happens

The warnings were added incrementally, each one reasonable in isolation. Nothing ever asked "what
does the total look like?" The high-volume buckets are mostly expected conditions
(`multiple images`, `strange subgallery line`, `set without set table`) that were never downgraded,
and they drown everything else.

There is also no per-warning identity: several messages omit the subject entirely (see
`2026-08-06-illegal-card-type-silent-drop.md`), so even when you find them you cannot act.

## What it leads to

- Real data corruption ships, repeatedly, in green builds.
- New failure modes are indistinguishable from the existing background noise, so they are never
  noticed on the run where they first appear.
- Investigating requires downloading and hand-parsing ~1 MB of logs across 10 jobs.

## How we might fix it

Options to evaluate — **investigate and choose; do not implement all of these**:

1. **Warning histogram at end of run.** Group by message template (strip the variable parts), print
   counts sorted descending. Cheapest change with the largest immediate payoff — it turns "read
   2137 lines" into "read 11 lines".
2. **Fail or annotate on a new warning kind.** Keep a checked-in baseline of known message
   templates with expected counts; surface anything unrecognised as a GH Actions annotation, or
   fail the job. This is what would have caught `Grand Master Rare` on the run it first appeared.
   Weigh how noisy this gets given Yugipedia changes constantly.
3. **Severity triage.** Split "expected condition we chose not to model" (DEBUG) from "we lost
   data" (WARNING) from "we imported something wrong" (ERROR). Doing this properly requires going
   through all 73 sites; doing it for the top three buckets covers 82% of the volume.
4. **Subject in every message.** Every warning should name the page it came from. Audit all 73.
5. **Named loggers per module** so importer warnings can be filtered independently — see
   `2026-08-06-logging-warn-deprecation.md`, which touches the same lines.

Suggested order if you take this on: (1) first, because it is nearly free and makes the rest
measurable; then (4); then (3); then decide about (2) with real numbers in hand.

## How to verify

- After (1): the job summary shows the histogram, and the top buckets match a manual
  `grep | sort | uniq -c` of the raw log.
- After (3): total WARNING-level lines drop by roughly the `multiple images` +
  `strange subgallery` + `set without set table` volume (~1585), and everything remaining is
  something a person could act on.
- After (2): deliberately introduce an unknown rarity in a test fixture and confirm the run flags
  it.

## Related

Every other handoff in this batch. This one is arguably the highest-leverage of them, because it
determines whether the next batch gets found in one run or in eighteen months.
