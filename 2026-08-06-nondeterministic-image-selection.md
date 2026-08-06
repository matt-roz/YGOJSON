# Which image a printing gets is nondeterministic across runs

**Date:** 2026-08-06
**Source:** GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) (Generate/Upload Database)
**Symptom in log:** `[WARNING] Found multiple images for the same card <X> / <rarity>, in <set>: [...]`
**Occurrences:** 1480 warnings across 1288 distinct (card, rarity, set) keys
**Severity:** medium-high — unstable output, wrong image chosen

> **Read this first.** Everything below was derived on 2026-08-06 by reading the run log and the
> importer source. Line numbers drift. You **must** re-verify each claim yourself — re-read the
> code at the cited locations and reproduce the behaviour locally — before writing a fix. The
> proposed fix below is a starting hypothesis, not a specification.

## The issue

A printing can legitimately have several images in one edition (base art, `Reprint`, `AA`
alternate art, `Emblazoned`, …). `Locale.card_images` only has room for one, so we pick
`ils[0]` — the first key in a plain `dict` — and drop the rest.

Dict order here is *insertion* order, and insertion order is the order in which asynchronous
Yugipedia image lookups complete. It is not stable. Nine printings in this single run were
reported with genuinely different orderings of the *same* image set:

```
Eldlich the Golden Lord / COLLECTORS, Rarity Collection Quarter Century Edition
    ['', 'AA']   and   ['AA', '']
Dark Magical Circle / ULTRA, Legendary Duelists: Season 3
    ['', 'Red']  and   ['Red', '']
Blue-Eyes White Dragon / COMMON, Legendary Decks II
    ['', '2', '3']   and   ['3', '2', '']
Mecha Phantom Beast Token / SUPER, OTS Tournament Pack 9
    ['Harrliard', 'Megaraptor', 'Dracossack']
    ['Megaraptor', 'Dracossack', 'Harrliard']
    ['Megaraptor', 'Harrliard', 'Dracossack']
Harpie Lady Sisters / SUPER, Metal Raiders
    ['', 'Reprint', 'Reprint2']  and  ['', 'Reprint2', 'Reprint']
Polymerization / SUPER, Legend of Blue Eyes White Dragon      (same pattern)
Goblin's Secret Remedy / RARE, Legend of Blue Eyes White Dragon
Final Flame / RARE, Legend of Blue Eyes White Dragon
Swords of Revealing Light / SUPER, Legend of Blue Eyes White Dragon
```

Whenever the non-empty alt-info sorts first, we export the *alternate* art as the printing's
canonical image.

## Where it happens

`src/ygojson/importers/yugipedia.py`, end of `parse_tcg_ocg_set`, **lines ~2469-2481**:

```python
for edition in raw_locale.editions:
    locale.card_images.setdefault(edition, {})
    for rc in raw_locale.cards.values():
        ils = [il for il in rc.image if il.edition == edition]
        if len(ils) > 1:
            logging.warn(
                f"Found multiple images for the same card ... {[il.altinfo for il in ils]}"
            )
        if ils:
            il = ils[0]                       # <-- arbitrary
            locale.card_images[edition][
                raw_printings_to_printings[content][suffix_locator(rc)]
            ] = rc.image[il]
```

`rc.image` is `typing.Dict[ImageLocator, str]` where `ImageLocator = (edition, altinfo)` — see
`RawPrinting` at line ~1731 and `ImageLocator` at line ~1716. Insertion happens in the
`onGetImage` / `onGetCard` callbacks at line ~2085, driven by the batcher.

## Why it happens

Two independent causes, both real:

1. **No tie-break.** `ils[0]` expresses no preference. Even with stable input order it would be
   luck-of-the-draw whether the base art or a variant wins.
2. **Unstable input order.** Images are populated from batched, asynchronous page/image lookups.
   The completion order varies run to run, which is why the same key shows different orderings
   within one workflow run.

## What it leads to

- **Churn.** The published database can differ between runs with no upstream change, producing
  meaningless diffs and cache invalidation for consumers.
- **Wrong image.** For `['AA', '']`, `['Red', '']`, `['3', '2', '']`, `['Reprint', '']` and
  `['Misprint', '']` we ship the variant rather than the base art.
- **Data loss.** ~1288 printings have extra images we discard entirely. See the separate schema
  handoff — that is the deeper problem; this document is about the *selection* being unstable.

Worst-affected sets by warning count: Legend of Blue Eyes White Dragon (202), Quarter Century Art
Collection (125), Metal Raiders (108), EX Starter Box (85), Limited Pack World Championship 2025
(80), Prismatic Art Collection (65), Vol.4-7 (~200 combined).

## How we might fix it

Sketch only — **investigate before implementing**:

- Sort `ils` with an explicit, total key before taking `[0]` — e.g. prefer `altinfo == ""`, then
  fall back to lexicographic `altinfo`, so the choice is both deterministic and semantically
  "the plain printing".
- Check whether an empty-alt image is *always* the right canonical choice. `OTS Tournament Pack 9`
  has no empty-alt entry at all (`['Harrliard', 'Megaraptor', 'Dracossack']`), so the fallback
  matters. Likewise `['Italian', 'German']` in Legendary Collection: 25th Anniversary Edition —
  neither is obviously canonical, and that one may be a wiki error worth reporting upstream.
- Audit for *other* order-dependent reads of `rc.image`. Line ~2461 does
  `replica=any(il.altinfo.lower() == "rp" for il in rc.image)` — that one is order-independent, but
  check the rest.
- Once ordering is deterministic, decide whether the warning should stay at WARNING level. If the
  schema keeps one image per printing by design, ~1288 lines of "we dropped extras" per run is not
  actionable and should probably be DEBUG or an aggregated count.

## How to verify

- Run the importer twice over the same cached Yugipedia snapshot and diff the output. Today the
  `card_images` entries for the printings listed above should differ; after the fix they must not.
- Assert directly: for `Eldlich the Golden Lord` (Collector's Rare, Rarity Collection Quarter
  Century Edition) the exported image must be the empty-alt one, not `AA`.

## Related

- `2026-08-06-multiple-images-per-printing-schema.md` — whether we should be keeping the extra
  images at all.
