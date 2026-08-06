# New rarity: Grand Master Rare is unrecognised

**Date:** 2026-08-06
**Source:** GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) (Generate/Upload Database)
**Symptom in log:** `Got strange rarity in ...: Grand Master Rare`, `Could not decipher rarity code for ...: Grand Master Rare`, `Could not determine default rarity of ...: Grand Master Rare`
**Occurrences:** 179 (141 set-list + 36 gallery + 2 gallery-default)
**Severity:** medium-high — printings dropped, and whole galleries silently downgraded to Common

> **Read this first.** Everything below was derived on 2026-08-06 by reading the run log, the
> importer source, and live Yugipedia wikitext. Wiki pages change. You **must** re-verify — in
> particular, confirm the official English name, the official abbreviation, and which sets actually
> use it — before adding anything to the schema. A `CardRarity` member is a public API commitment.

## The issue

"Grand Master Rare" is a rarity that exists on Yugipedia but not in our `CardRarity` enum or either
lookup table, so every printing at that rarity is dropped and every gallery that uses it as the
default rarity falls back to Common.

Sets using it in this run:

```
Set Card Lists:Limit Over Collection: The Heroes  (OCG-JP, OCG-KR, OCG-SC)
Set Card Lists:Limit Over Collection: The Rivals  (OCG-JP, OCG-KR, OCG-SC)
Set Card Lists:Magnificent Maestros               (TCG-EN)
Set Card Lists:Magnificent Monsters               (TCG-EN)
Set Card Lists:Original Artwork Collection        (OCG-JP)
Set Card Galleries:Limit Over Collection: The Heroes (OCG-JP)
Set Card Galleries:Limit Over Collection: The Rivals (OCG-JP)
```

The galleries use it as a template default, e.g.:

```
{{Set gallery|rarity=Grand Master Rare|
LOCH-JP001; Dark Magician, the Pharaoh's Servant
...
}}
```

## Where it happens

Three code paths, all in `src/ygojson/importers/yugipedia.py`:

1. **Set-list row rarity**, lines ~1991-2000. Lookup fails → warning → the rarity is *omitted from
   the row's rarity list*. If the row had no other rarity, `rarities` is empty and the row falls
   back to `default_rarities`.
2. **Gallery row rarity**, lines ~2159-2170 (lookup fails, `rarity` silently stays at the default)
   and lines ~2193-2203 (`RAIRTY_FULL_TO_SHORT` lookup fails → the raw string is pasted into the
   generated image filename and a warning is emitted).
3. **Gallery default rarity**, lines ~2094-2110:

```python
default_rarity = RARITY_STR_TO_ENUM.get(...) or FULL_RARITY_STR_TO_ENUM.get(...)
if not default_rarity:
    logging.warn(f"Could not determine default rarity of {galleryname}: {raw_default_rarity}")
    default_rarity = CardRarity.COMMON       # <-- everything in the gallery becomes Common
```

The data that needs updating:

- `CardRarity` in `src/ygojson/database.py` (lines ~465-592) — new member
- `RARITY_STR_TO_ENUM` (line ~927) — short code
- `_RARITY_FTS_RAW` (line ~994) — full names → short code, used to build `RAIRTY_FULL_TO_SHORT`
  (line ~1507), which is what generates image filenames
- `FULL_RARITY_STR_TO_ENUM` (line ~1509) — full name → enum

## Why it happens

The rarity is newer than the tables. Our rarity handling is three hand-maintained parallel maps
plus an enum, with no mechanism to notice when Yugipedia introduces a rarity we do not know.

## What it leads to

- **Printings lost.** 141 set-list rows at this rarity contribute nothing.
- **Whole galleries mis-rarified.** Limit Over Collection: The Heroes / The Rivals (OCG-JP)
  galleries default to Grand Master Rare; with the fallback to Common, *every card in those
  galleries* is recorded as Common. That is worse than dropping the rows.
- **Broken image filenames.** The generated name gets `-Grand Master Rare` appended (with spaces),
  which cannot resolve.

## How we might fix it

Sketch only — **investigate before implementing**:

- Add a `CardRarity` member (something like `GRANDMASTER = "grandmaster"`) and wire it into all
  three maps plus `_RARITY_FTS_RAW`.
- **Find the official abbreviation first.** Check Yugipedia's rarity template (mirrored as a
  comment at lines ~845-925 of `yugipedia.py`) for the canonical short code — do not invent one.
  `RAIRTY_FULL_TO_SHORT` feeds image filename construction, so a wrong code means every image URL
  for those sets is wrong.
- Check whether Yugipedia has *other* rarities we do not know about. This document covers the one
  that showed up in one run; a systematic diff of their rarity template against
  `RARITY_STR_TO_ENUM` would be more useful than fixing them one at a time.
- Consider whether the "could not determine default rarity → Common" fallback at line ~2110 is
  right. Silently marking an entire gallery Common is arguably worse than skipping it. At minimum
  the warning should be loud enough not to be lost among 2000 others.

## How to verify

- Re-fetch:
  `https://yugipedia.com/api.php?action=parse&page=Set%20Card%20Galleries:Limit%20Over%20Collection:%20The%20Heroes%20(OCG-JP)&prop=wikitext&format=json`
- Import Limit Over Collection: The Heroes and confirm the base-set cards come out at the new
  rarity rather than Common, and that their image URLs resolve.
- Confirm the 179 warnings are gone from a fresh run.

## Related

- `2026-08-06-rush-duel-rarities.md`, `2026-08-06-ultra-rare-special-blue.md`,
  `2026-08-06-rarity-string-normalization.md` — same tables, different gaps.
