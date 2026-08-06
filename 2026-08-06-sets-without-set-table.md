# `Found set without set table` fires 61 times, almost all on series and index pages

**Date:** 2026-08-06
**Source:** GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) (Generate/Upload Database)
**Symptom in log:** `[WARNING] Found set without set table: <page>`
**Occurrences:** 61 (plus 36 of the related `Found set without set navigation table`)
**Severity:** low — noise, but it is hiding the small number of real cases

> **Read this first.** Everything below was derived on 2026-08-06 from the run log and the importer
> source. The classification of which pages are "series pages" vs "real sets we are failing to
> parse" is my reading of the titles, not something I verified page by page. You **must** check the
> actual pages before filtering anything out — silencing a real set is worse than the noise.

## The issue

The set importer warns when a page it decided to treat as a set turns out to have no set table. The
overwhelming majority of the 61 hits are pages that are not sets at all — they are series index
pages, portal pages, and disambiguation-style hubs:

```
Structure Deck                    Starter Deck              Battle Pack
Structure Deck R                  Star Pack                 Astral Pack
Legendary Collection (series)     Turbo Pack                Champion Pack
Legendary Duelists (series)       Booster SP                Collectors Pack
Limited Edition (series)          Mega Pack (series)        Deck-Build Pack
Entry Pack (series)               Extra Pack (series)       V Jump Edition (series)
Portal:Yu-Gi-Oh! Master Duel sets ...
```

Mixed in are pages that are plausibly real products we are failing to parse, and those are the ones
worth attention:

```
+1 Bonus Pack                     Enhancement Pack          Promotion Pack 3
60 Card Set                       Go Rush Deck              Power-Up Pack
2009 Event Token Promos           Selection BOX             World Premiere Pack
Duel Disk promotional cards       Tactical-Try Deck         Animation Chronicle
Yu-Gi-Oh! <various> manga promotional cards
```

Separately, `Found set without set navigation table` (36 hits) is dominated by video-game decks
(`Initial Deck (Tag Force 1-6)`, `Initial Deck (World Championship 2007-2011)`, `Initial Deck (DM5)`,
`Starter Deck (Duel Transer)`) and boxed products (`Gold - Premium Pack Kit`,
`Super Starter: Power Box`, `Duelist Pack Collection Tin 2007`). Those are likely legitimate — such
products genuinely have no locale navigation — but they are worth a look because several of the same
names appear in `2026-08-06-dead-manual-set-fixups.md`.

## Where it happens

`src/ygojson/importers/yugipedia.py`, **line ~3241**:

```python
if not settables and not md_settables and not dl_settables:

    @batcher.getPageID(pageid)
    def onGetName(pageid: int, title: str):
        logging.warn(f"Found set without set table: {title}")

    return
```

and **line ~2360** for the navigation-table variant.

## Why it happens

The list of pages fed to the set importer is broader than the set of actual sets. Yugipedia's series
pages live in the same categories/namespaces as the sets they group, and we do not distinguish them
before attempting to parse.

`Portal:Yu-Gi-Oh! Master Duel sets` in the list is a useful tell — a `Portal:` namespace page is
definitively not a set, which suggests the page-collection step is not filtering by namespace at
all.

## What it leads to

No data loss from the series pages — they correctly produce nothing. The cost is:

- ~50 lines of pure noise per run, in a log where the signal-to-noise ratio is already the main
  obstacle to finding real bugs (see `2026-08-06-warning-observability.md`).
- The ~11 genuinely-questionable entries are invisible inside that noise. Nobody has looked at
  `Enhancement Pack` or `Animation Chronicle` because they read as more of the same.
- Wasted requests fetching and parsing pages we will always reject.

## How we might fix it

Sketch only — **investigate before implementing**:

- Work out where the candidate page list comes from and filter non-article namespaces (`Portal:` at
  minimum) before parsing.
- Series pages are harder. Check whether Yugipedia has a category or template that marks them
  (`Template:Set series`?, `Category:Set series`?) — filtering on a positive marker is much safer
  than a title heuristic like "ends in `(series)`", which would miss `Structure Deck` and
  `Starter Deck` anyway.
- **Triage the ~11 ambiguous entries individually before filtering.** For each, open the page and
  determine whether it is a series hub or a real product we are failing to parse. Anything in the
  second category is a separate bug and should get its own handoff.
- If a page is legitimately a series hub, consider whether we want to *model* series rather than
  merely skip them. Note the run also emitted `Found series without series table: Archetype` and
  `: Series`, which suggests there is already a series code path with its own problems.

## How to verify

- After filtering, the warning count should drop to only the pages you deliberately left in, and
  each remaining one should be a real, investigable case.
- Confirm no set disappears from the output. Diff the set list before and after — it must be
  identical, since series pages contributed nothing.

## Related

- `2026-08-06-warning-observability.md`
- `2026-08-06-dead-manual-set-fixups.md` — overlapping product names.
- `2026-08-06-subgallery-noise.md` — the other big noise bucket.
