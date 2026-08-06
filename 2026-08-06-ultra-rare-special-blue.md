# `Ultra Rare (Special Blue Version)` is unreachable although the enum member exists

**Date:** 2026-08-06
**Source:** GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) (Generate/Upload Database)
**Symptom in log:** `Got strange rarity in ...: Ultra Rare (Special Blue Version)` and `Could not decipher rarity code for ...: Ultra Rare (Special Blue Version)`
**Occurrences:** 20 (10 set-list + 10 gallery)
**Severity:** medium — 10 printings dropped; the fix is a couple of dictionary entries

> **Read this first.** Everything below was derived on 2026-08-06 by reading the run log, the
> importer source, and live Yugipedia wikitext. You **must** re-verify the wikitext and the code
> before implementing — in particular check whether the colourful-rare mechanism (below) is the
> intended path for these rarities rather than a direct name mapping.

## The issue

`CardRarity.ULTRA_BLUE` and `CardRarity.ULTRA_GREEN` exist in the schema, but neither
`RARITY_STR_TO_ENUM` nor `FULL_RARITY_STR_TO_ENUM` can produce them. They are reachable **only**
through `COLORFUL_RARES`, which requires the rarity column to say plain "Ultra Rare" and a
*separate* alt column to say "Blue".

Yugipedia does not always write it that way. `Set Card Lists:Limited Pack GX: Ra Yellow (OCG-JP)`
puts the full name in the rarity column:

```
{{Set list|region=JP|rarities=Ultra Rare, Secret Rare, Prismatic Secret Rare|print=Reprint|
LPG2-JP019; Destiny HERO - Doom Lord; Ultra Rare, Ultra Rare (Special Blue Version)
LPG2-JP021; Destiny HERO - Diamond Dude; Ultra Rare, Ultra Rare (Special Blue Version), Secret Rare
...
}}
```

The lookup fails, the rarity is dropped from that row's rarity list, and the corresponding gallery
entry then also fails to build an image filename.

Note the contrast: `"secret rare (special blue version)"` **is** in `FULL_RARITY_STR_TO_ENUM`
(line ~1520) and `"scrblue"` is in `RARITY_STR_TO_ENUM` (line ~941). The Ultra equivalents were
simply never added.

## Where it happens

- `src/ygojson/importers/yugipedia.py` line ~1509 `FULL_RARITY_STR_TO_ENUM` — has
  `"ultra rare (special purple version)"` but not the blue or green variants.
- `src/ygojson/importers/yugipedia.py` line ~927 `RARITY_STR_TO_ENUM` — has `"urpurple"` (with a
  comment noting Yugipedia does not actually use it) but no `"urblue"` / `"urgreen"`.
- `_RARITY_FTS_RAW` (line ~994) has no entry either, so `RAIRTY_FULL_TO_SHORT` cannot produce a
  short code and the image filename gets the raw string appended (line ~2200).
- `COLORFUL_RARES` at line ~1772 does map `(CardRarity.ULTRA, "Blue") → CardRarity.ULTRA_BLUE`,
  which is the only working route today.

A quick audit shows eight enum members reachable from neither map — `RARE_BLUE`, `RARE_COPPER`,
`RARE_GREEN`, `RARE_PURPLE`, `RARE_RED`, `RARE_WEDGEWOOD`, `ULTRA_BLUE`, `ULTRA_GREEN` — all
`COLORFUL_RARES`-only. For the `RARE_*` family that is probably correct by design; for the
`ULTRA_*` family it demonstrably is not, because Yugipedia writes the full name.

## Why it happens

Two ways of expressing the same rarity (rarity column vs rarity + alt column) and two mechanisms to
parse them, with no guarantee that both mechanisms cover the same set of rarities. The Secret Rare
variants got both; the Ultra Rare variants got one.

## What it leads to

- 10 printings in Limited Pack GX: Ra Yellow lose their Special Blue rarity. Those rows do have a
  plain "Ultra Rare" alongside, so the card is not lost outright — but the blue variant is.
- 10 gallery rows produce image filenames with `-Ultra Rare (Special Blue Version)` appended, which
  cannot resolve.
- Also seen: 2 × `Secret Rare Special Blue Version` (no parentheses) — see the normalization
  handoff.

## How we might fix it

Sketch only — **investigate before implementing**:

- Add `"ultra rare (special blue version)" → CardRarity.ULTRA_BLUE` and the green equivalent to
  `FULL_RARITY_STR_TO_ENUM`, plus `_RARITY_FTS_RAW` entries so a short code exists for filename
  construction.
- **Work out what the short code should be.** `RARITY_STR_TO_ENUM` uses the invented `"urpurple"`
  and admits so in a comment. If Yugipedia has no official abbreviation, whatever you pick will end
  up in generated image filenames — check what the actual `File:` names look like on the wiki for
  these cards before choosing.
- Decide whether `COLORFUL_RARES` and the name maps should be generated from one table so this
  class of gap closes permanently. See `2026-08-06-rarity-string-normalization.md`.
- Check the `RARE_*` family too — confirm those really are alt-column-only on Yugipedia and not
  just undiscovered.

## How to verify

- Re-fetch:
  `https://yugipedia.com/api.php?action=parse&page=Set%20Card%20Lists:Limited%20Pack%20GX:%20Ra%20Yellow%20(OCG-JP)&prop=wikitext&format=json`
- Import Limited Pack GX: Ra Yellow; `LPG2-JP019` through `LPG2-JP028` must each carry both an
  Ultra Rare and an Ultra Rare (Special Blue Version) printing, and the blue one must have a
  resolvable image.

## Related

- `2026-08-06-rarity-string-normalization.md`, `2026-08-06-grand-master-rare.md`,
  `2026-08-06-rush-duel-rarities.md`, `2026-08-06-duel-terminal-rarity-swap.md`
