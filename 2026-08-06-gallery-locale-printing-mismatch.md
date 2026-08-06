# `Printing in gallery not found in locale` — 48 gallery/list disagreements, undiagnosed

**Date:** 2026-08-06
**Source:** GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) (Generate/Upload Database)
**Symptom in log:** `[WARNING] Printing in gallery <gallery> not found in locale: <card> / <rarity> -- Available in [...]`
**Occurrences:** 48
**Severity:** unknown — needs triage

> **Read this first, and note this one is different from the others in this batch.** I did **not**
> diagnose this bucket. What follows is the shape of the data and where the code lives, nothing
> more. There is no root-cause claim here to verify — the first task is establishing what is
> actually going on. Do not assume any of the hypotheses below is correct.

## The issue

For each gallery row, the importer resolves the card and looks for a matching printing that the
*set list* already registered for that locale. When no printing matches the row's rarity, it warns
and drops the image.

48 rows failed this way. They split into two distinct shapes, which are probably two different
problems:

**Shape A — the card has no printing in that locale at all (23 rows).** `Available in []`:

```
Set Card Galleries:Yugi's Legendary Decks (TCG-PT-LE)
    The Winged Dragon of Ra / ultra    -- Available in []
    Slifer the Sky Dragon / ultra      -- Available in []
    Obelisk the Tormentor / ultra      -- Available in []
Set Card Galleries:Tournament Pack <N> Vol.<N> (OCG-JP)
    Karbonala Warrior / common         -- Available in []
    Inferno Tempest / common           -- Available in []
    Darkfire Dragon / common           -- Available in []
Set Card Galleries:Structure Deck: Master of Pendulum (OCG-JP)
    Metaphys Armed Dragon / common     -- Available in []
Set Card Galleries:V Jump promotional cards (OCG-JP)
    Speedroid CarTurbo / ultra         -- Available in []
Set Card Galleries:Sneak Peek Participation Cards (TCG-PT-LE)
    Token Collector / ultra            -- Available in []
```

**Shape B — the card is present but at a different rarity (25 rows).** For example:

```
Goblin's Secret Remedy / common       -- Available in ['rare']
Kelbek / rare                         -- Available in ['common']
Barrel Dragon / secret                -- Available in ['ultra']
Battlestorm / ultra                   -- Available in ['super']
Rainbow Neos / secret                 -- Available in ['ultra', 'ultimate', 'ghost']
Obelisk the Tormentor (original) / prismaticsecret -- Available in ['secret']
Marauding Captain / parallel          -- Available in ['common', 'commonparallel']
    (12 rows of this last shape, all in World Ranking Promos: Series <N> (OCG-JP))
```

## Where it happens

`src/ygojson/importers/yugipedia.py`, inside `get_gallery_data` → `add_card_image` → `onGetCard`,
**lines ~2063-2085**:

```python
rcs = [rc for rc in raw_locale.cards.values()
       if rc.card == card and rc.rarity == card_rarity]
if code and any(rc.code == code for rc in rcs):
    rcs = [rc for rc in rcs if rc.code == code]
if not rcs:
    if rarity == card_rarity and card_rarity in FALLBACK_RARITIES:
        onGetCard(card, FALLBACK_RARITIES[card_rarity])     # one retry
    elif not alt:
        logging.warn(f"Printing in gallery {galleryname} not found in locale: ...")
else:
    for rc in rcs:
        rc.image[ImageLocator(edition, alt)] = url
```

`FALLBACK_RARITIES` is at line ~1787 and covers only common↔shortprint plus the `COLORFUL_RARES`
reverse mapping.

## Why it happens

**Unknown.** Candidate explanations, none verified:

- The gallery and the set list genuinely disagree on Yugipedia (a wiki inconsistency to report
  upstream) — plausible for the Shape B rarity mismatches.
- The set list page failed to parse, so the locale has no printings to match against — this would
  produce Shape A. Worth cross-referencing against the run's
  `Found set navigation in <set> with gallery but no list for locale <lc>` warnings (6 in this run)
  and `Found set list page without set list template` (1, Mattel Action Figure promotional cards).
- The `FALLBACK_RARITIES` retry is too narrow. The 12 `parallel` → `['common', 'commonparallel']`
  rows in World Ranking Promos all have the same shape and might be one missing fallback rule.
- Column-shift or rarity-lookup bugs elsewhere in this batch feeding bad rarities in. Note
  `Obelisk the Tormentor (original)` appears both here and in
  `2026-08-06-gallery-abbr-column-shift.md` — **fix that one first and re-measure**, this bucket
  may shrink on its own.

## What it leads to

48 gallery images dropped. Whether that matters depends on the shape: for Shape B the card is in
the set at a different rarity and merely loses an image; for Shape A the card may be missing from
the set entirely, which is worse. That distinction has not been established.

## How we might approach it

There is no fix to propose yet. Suggested sequence:

1. Fix `2026-08-06-gallery-abbr-column-shift.md`, `2026-08-06-grand-master-rare.md`,
   `2026-08-06-rush-duel-rarities.md` and `2026-08-06-ultra-rare-special-blue.md` first, then
   re-run and re-measure this bucket. Several of these warnings are likely downstream of those.
2. Split the remainder into Shape A and Shape B and handle them separately.
3. For Shape A, check whether the set list page parsed at all for that locale — that is a different
   bug class from a rarity mismatch.
4. For Shape B, open the gallery and the list page side by side for two or three examples and
   determine which one is right. If the wiki is inconsistent, fix it upstream; if we are
   mis-parsing one of them, that is our bug.
5. Only then consider whether `FALLBACK_RARITIES` needs extending — do not widen it speculatively,
   since a too-permissive fallback attaches images to the wrong printing silently.

## How to verify

Whatever the eventual fix, verification is per-example: pick a row, open both the
`Set Card Lists:` and `Set Card Galleries:` pages for that set and locale, and confirm our output
matches what the wiki actually says.

## Related

- `2026-08-06-gallery-abbr-column-shift.md` — probable upstream cause of some of these.
- `2026-08-06-warning-observability.md` — this bucket sat unexamined behind 1480 lines of noise.
