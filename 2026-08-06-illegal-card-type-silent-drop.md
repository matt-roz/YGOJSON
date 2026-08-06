# 16 cards are dropped for an unrecognised card type, and the log does not say which

**Date:** 2026-08-06
**Source:** GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) (Generate/Upload Database)
**Symptom in log:** `[WARNING] Found card with illegal card type: counter / token` (15) and `: counter/  token` (1)
**Occurrences:** 16
**Severity:** medium — cards silently excluded, and currently un-diagnosable

> **Read this first.** Everything below was derived on 2026-08-06 from the run log and the importer
> source. I was **not** able to identify which 16 pages these are (see below) — that is the first
> piece of work. You **must** determine the affected pages and confirm the actual `card_type`
> values before deciding how to handle them.

## The issue

The card parser rejects any `card_type` it does not recognise and returns without importing the
card. In this run 16 cards were rejected with the values `counter / token` and `counter/  token`
(note the doubled space in the second — the raw wiki values are inconsistent).

Because the warning does not include the page title, **there is no way to tell which cards were
dropped.** The log line has no other identifying information, and the surrounding tqdm progress
output only gives a counter position.

## Where it happens

`src/ygojson/importers/yugipedia.py`, **lines ~3040-3054**:

```python
ct = (
    get_table_entry(cardtable, "card_type", "monster")
    .strip()
    .lower()
)
if (
    ct == "counter"
    or batcher.namesToIDs.get(CAT_TOKENS) in categories
):
    ct = "token"
if batcher.namesToIDs.get(CAT_SKILLS) in categories:
    ct = "skill"
if ct not in CardType._value2member_map_:
    logging.warn(f"Found card with illegal card type: {ct}")
    return                      # <-- card dropped entirely
```

`CardType` (in `src/ygojson/database.py`, lines ~109-116) has exactly five members: `monster`,
`spell`, `trap`, `token`, `skill`.

## Why it happens

`ct == "counter"` is an exact-equality test against a free-text wiki field. Pages that write
`card_type = Counter / Token` (a compound value) do not match, fall through to the membership
check, fail it, and are dropped.

Confirmed for reference: `Spell Counter (card)` on Yugipedia uses the plain `card_type = Counter`
and *is* handled correctly. The compound-value pages are a different set, which I could not
enumerate — Yugipedia's `insource:` search returned no results for every query I tried, so the
search index appears unavailable to us.

The doubled-space variant (`counter/  token`) shows the wiki values are not even internally
consistent, which is an argument for tokenising rather than string-matching.

## What it leads to

16 cards absent from the published database, with no record of which. There is no way to assess the
impact from the log alone — they could be obscure counter cards or something consumers care about.

The deeper problem is the pattern: **a warning that reports a value but not a subject.** Any
`logging.warn` in the card path that omits the page title produces an unfixable report. This one is
the clearest example but probably not the only one.

## How we might fix it

Sketch only — **investigate before implementing**:

1. **First, make the warning identify the card.** The page title is available (`batcher.idsToNames`
   is used for this elsewhere, e.g. line ~3036 `Found card without card table: {…idsToNames[pageid]}`).
   Do this before anything else — you cannot evaluate the rest without knowing the inputs.
2. Re-run (or run the importer locally over the card list) to get the 16 titles.
3. Then decide how to handle compound `card_type` values. Splitting on `/`, stripping, and checking
   whether any component is recognised is one approach — but work out what
   `Counter / Token` actually *means* on those pages first. It may indicate a card that is both,
   in which case picking one is a modelling decision, not a parsing one.
4. Audit the rest of the importer for warnings that omit the subject. `grep -n 'logging.warn' `
   and check each one has enough context to act on.

## How to verify

- After step 1, confirm the log names the pages.
- Fetch each page and inspect its `card_type`, categories, and whether it is an official card at
  all — some may be joke or unofficial pages that *should* be excluded, in which case the current
  behaviour is right and only the logging needs fixing.
- Confirm the imported card count increases by exactly the number you intended to rescue.

## Related

- `2026-08-06-warning-observability.md` — the general version of this problem.
- `2026-08-06-yugipedia-upstream-data-issues.md` — other card-page data oddities.
