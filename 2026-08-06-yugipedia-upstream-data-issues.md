# Individual bad values on Yugipedia card pages

**Date:** 2026-08-06
**Source:** GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) (Generate/Upload Database)
**Symptom in log:** `Bad password 'None' in card ...`, `Card ... has bad ATK: None`, `Monster typeline bit unknown in ...`
**Occurrences:** 3 (one each)
**Severity:** low — but two of them are cheap upstream fixes and one is a policy question

> **Read this first.** These were checked against live Yugipedia on 2026-08-06. Wiki pages change
> constantly and at least one of these has already moved. You **must** re-fetch each page and
> confirm the problem still exists before doing anything. Do not "fix" the importer for a wiki
> problem that has since been corrected upstream.

## The issues

### 1. `password = None` (literal string)

```
[WARNING] Bad password 'None' in card The Winged Dragon of Ra - Immortal Phoenix
```

The wikitext for that card contains, verbatim:

```
| password = None
```

An editor wrote the English word where the field should be empty. Our parser sees a non-empty
string that is not a number.

**This is a wiki fix.** The right action is to blank the field on Yugipedia. Whether we *also*
want the importer to treat `None` / `N/A` / `-` / `?` as absent is a separate judgement call —
being liberal here hides future editor mistakes rather than surfacing them.

### 2. `atk` reported as `None`

```
[WARNING] Card Ilios the Black Sun Dragon has bad ATK: None
```

As of 2026-08-06 the page reads `| atk = 1500`, so this appears to have been a transient — the
page was incomplete when the importer scraped it and has since been filled in. **Verify this is
still resolved.** If it recurs, the interesting question is whether newly-created card pages are
being imported before they are complete, and whether we should defer or retry rather than warn.

### 3. Unknown monster typeline bit

```
[WARNING] Monster typeline bit unknown in Charisma Token: Charisma
```

The page has `types = Charisma`, `attribute = LAUGH`, `card_type = Token`. `LAUGH` is not a real
Yu-Gi-Oh! attribute; this is a joke/unofficial page. We are attempting to parse it as a real card.

**This is a policy question, not a parse bug.** Options: exclude unofficial/joke pages by category,
accept them and model the odd values, or leave it warning. Find out first how Yugipedia categorises
these pages — if there is a reliable "unofficial" category we can filter on, this generalises
beyond one card.

## Where it happens

`src/ygojson/importers/yugipedia.py`, in the card parsing path (the block beginning around line
~3030 with the `CardTable2` handling). Grep for the exact warning strings — the password, ATK and
typeline handlers are separate sites.

## Why it happens

Yugipedia is a wiki. Fields are free text, pages get created before they are complete, and joke
pages exist alongside real ones. Our parser assumes well-formed values and warns when it does not
get them, which is the correct default — the question in each case is whether to tolerate,
exclude, or push the fix upstream.

## What it leads to

Minimal in isolation: one card missing a password, one missing an ATK (if it recurs), one joke card
with a garbled typeline. None of these break the import.

The real cost is that these three lines were buried in a 2137-line warning log. Genuinely rare,
genuinely actionable warnings are only useful if they are findable — see the observability handoff.

## How we might fix it

Sketch only — **investigate before implementing**:

- Fix `password = None` on Yugipedia directly. Consider whether the importer should also normalize
  obvious placeholder values, and argue the case either way rather than assuming.
- Re-check `Ilios the Black Sun Dragon`. If resolved, nothing to do; note it as an example of a
  transient and move on.
- Decide the policy on joke/unofficial pages and implement it once, not per-card. Look for a
  Yugipedia category to filter on.
- None of these justify code changes on their own. If you touch the importer here, do it because
  you have decided a *class* of value should be handled differently, not to silence three lines.

## How to verify

For each, re-fetch and check the field:

```
https://yugipedia.com/api.php?action=parse&page=The%20Winged%20Dragon%20of%20Ra%20-%20Immortal%20Phoenix&prop=wikitext&format=json
https://yugipedia.com/api.php?action=parse&page=Ilios%20the%20Black%20Sun%20Dragon&prop=wikitext&format=json
https://yugipedia.com/api.php?action=parse&page=Charisma%20Token&prop=wikitext&format=json
```

## Related

- `2026-08-06-warning-observability.md` — why these were hard to find.
- `2026-08-06-illegal-card-type-silent-drop.md` — a card-parsing warning that drops data outright.
