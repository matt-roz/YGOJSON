# Rarity lookups are exact-match, so punctuation and spacing variants fail

**Date:** 2026-08-06
**Source:** GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) (Generate/Upload Database)
**Symptom in log:** `Could not decipher rarity code for ...: ScR-Blue`, `Got strange rarity in ...: Secret Rare Special Blue Version`
**Occurrences:** 3 directly (1 × `ScR-Blue`, 2 × `Secret Rare Special Blue Version`) — plus an unknown number prevented
**Severity:** low individually, medium as a class

> **Read this first.** Everything below was derived on 2026-08-06 by reading the run log, the
> importer source, and live Yugipedia wikitext. You **must** re-verify before implementing. A
> normalization change touches *every* rarity lookup in the importer, so the risk is not the three
> warnings it fixes — it is what else it might start matching. Test accordingly.

## The issue

Every rarity lookup does `dict.get(raw.lower())` against hand-written keys. The keys are written
without punctuation (`"scrblue"`) or with a specific punctuation (`"secret rare (special blue
version)"`), so any wiki page that spells the rarity slightly differently falls through.

Two variants observed in this run:

```
Set Card Galleries:Tournament Pack 2025 Vol.2 (OCG-JP)
    Isolde, Two Tales of the Noble Knights; ...; ScR-Blue
        → key is "scrblue"; "scr-blue" does not match

Set Card Lists:Structure Deck: Harpie Lady Sisters (OCG-JP and OCG-KR)
    Harpie Lady Sisters Triangle Beauty: Secret Rare Special Blue Version
        → key is "secret rare (special blue version)"; the parenthesis-free form does not match
```

Both refer to rarities we already model (`CardRarity.SECRET_BLUE`).

## Where it happens

`src/ygojson/importers/yugipedia.py`. The same `.get(x.lower())` pattern appears at every lookup
site:

- set-list row rarity, line ~1992
- gallery default rarity, lines ~2100-2105
- gallery row rarity, lines ~2163-2167
- gallery image-filename short code (`RAIRTY_FULL_TO_SHORT`), lines ~2194-2196
- subgallery rarity, lines ~2232-2236

The tables themselves: `RARITY_STR_TO_ENUM` (line ~927), `_RARITY_FTS_RAW` (line ~994),
`RAIRTY_FULL_TO_SHORT` (line ~1507), `FULL_RARITY_STR_TO_ENUM` (line ~1509).

## Why it happens

`.lower()` is the only normalization applied. Yugipedia is edited by many people and is not
internally consistent about hyphens, spaces, or parentheses in rarity strings — the wiki's own
template accepts several spellings, and editors type whatever renders correctly.

Note that the `ScR-Blue` case is also self-inconsistent on our side: `_RARITY_FTS_RAW` maps the
full name to the short code **`"ScRBlue"`** (line ~1503), so we *emit* the un-hyphenated form in
filenames while some wiki pages use the hyphenated one.

## What it leads to

Directly: 3 warnings, 1 broken image filename (`-ScR-Blue` appended), and 2 Structure Deck: Harpie
Lady Sisters rows losing their Secret Blue rarity.

Indirectly, and more importantly: this is a silent-failure mode with no lower bound. Every future
spelling variant an editor introduces costs us a printing, and we only find out by reading 2000
lines of log. The three we can see are the ones that happened to occur in the 407 sets this run
touched.

## How we might fix it

Sketch only — **investigate before implementing**:

- Normalize both the keys and the lookup input through one function — casefold plus strip of
  non-alphanumerics is the obvious candidate, and would resolve both observed cases
  (`"scr-blue"` → `"scrblue"`, `"secret rare special blue version"` →
  `"secretrarespecialblueversion"`, matching a normalized
  `"secret rare (special blue version)"`).
- **Check for collisions before doing this.** Aggressive normalization can make two distinct
  rarities collide. Write the normalizer, apply it to every key in all four tables, and assert the
  result has no duplicate keys mapping to different enum members. If it does, normalize less
  aggressively.
- Do it as a *fallback*, not a replacement: try the exact lookup first, then the normalized one.
  That way the change cannot alter any lookup that currently succeeds.
- Consider logging when the normalized path is what rescued a lookup, so we can see wiki
  inconsistencies without them being fatal.
- This is the natural place to also collapse the four tables into one source of truth. See the
  related handoffs — `2026-08-06-duel-terminal-rarity-swap.md` is a drift bug between two of them,
  and `2026-08-06-rush-duel-rarities.md` is a gap in two of them.

## How to verify

- Re-fetch:
  `https://yugipedia.com/api.php?action=parse&page=Set%20Card%20Galleries:Tournament%20Pack%202025%20Vol.2%20(OCG-JP)&prop=wikitext&format=json`
  and the two Structure Deck: Harpie Lady Sisters list pages.
- Property test: for every key in every rarity table, feed the parser variants with hyphens
  inserted, parentheses removed, and extra spaces, and assert the same enum member comes back.
- Regression guard: run a full import before and after and diff the set of `(printing, rarity)`
  pairs. The only differences should be the ones you intended.

## Related

- `2026-08-06-ultra-rare-special-blue.md`, `2026-08-06-grand-master-rare.md`,
  `2026-08-06-rush-duel-rarities.md`, `2026-08-06-duel-terminal-rarity-swap.md`
