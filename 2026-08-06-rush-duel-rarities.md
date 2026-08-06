# Rush Duel rarities (RR / GRR / ORR) are half-wired

**Date:** 2026-08-06
**Source:** GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) (Generate/Upload Database)
**Symptom in log:** `Got strange rarity in Set Card Lists:...: ORR` / `: Over Rush Rare`
**Occurrences:** 18 (16 × `ORR`, 2 × `Over Rush Rare`)
**Severity:** medium — Rush Duel printings dropped

> **Read this first.** Everything below was derived on 2026-08-06 by reading the run log and the
> importer source. You **must** re-verify — confirm the official names and abbreviations against
> Yugipedia, and check which other Rush Duel rarities exist — before adding enum members. A
> `CardRarity` member is a public API commitment.

## The issue

Three Rush Duel rarities — Rush Rare (`RR`), Gold Rush Rare (`GRR`) and Over Rush Rare (`ORR`) —
are documented in the importer and present in the full-name→short-code table, but are **missing
from both enum lookup tables and from `CardRarity` itself**. Rows using them are dropped.

The importer even carries Yugipedia's own rarity template as a comment (lines ~923-925):

```
#   | rr    | rush       = ... | Rush Rare      | RR    |
#   | grr   | gold rush  = ... | Gold Rush Rare | GRR   |
#   | orr   | over rush  = ... | Over Rush Rare | ORR   |
```

and `_RARITY_FTS_RAW` has entries for all three (lines ~1475-1490 and ~1505):

```python
(["rr",  "rush",      "Rush Rare"],      "RR"),
(["grr", "gold rush", "Gold Rush Rare"], "GRR"),
(["orr", "over rush", "Over Rush Rare"], "ORR"),
```

But `RARITY_STR_TO_ENUM` (line ~927) and `FULL_RARITY_STR_TO_ENUM` (line ~1509) have none of them,
and `CardRarity` in `src/ygojson/database.py` has no corresponding members.

Seen in this run on `Set Card Lists:Structure Deck: Birth of Hero` (OCG-JP and OCG-KR):

```
RD/SD0B-KRS01; Elemental HERO Flame Wingman (Rush Duel); ORR
RD/SD0B-KRS02; Elemental HERO Burst Wingman; ORR
```

## Where it happens

- Enum: `src/ygojson/database.py`, `CardRarity`, lines ~465-592 — no `RR`/`GRR`/`ORR` members.
- `src/ygojson/importers/yugipedia.py` line ~927 `RARITY_STR_TO_ENUM` — no `"rr"`, `"grr"`, `"orr"`.
- `src/ygojson/importers/yugipedia.py` line ~1509 `FULL_RARITY_STR_TO_ENUM` — no
  `"rush rare"`, `"gold rush rare"`, `"over rush rare"`.
- Failure surfaces at the set-list lookup, lines ~1991-2000.

## Why it happens

`_RARITY_FTS_RAW` exists to build `RAIRTY_FULL_TO_SHORT` for *image filename construction*, and it
was extended with the Rush entries. The enum maps serve a different purpose (parsing rarity into
the model) and were not. The three tables are maintained by hand and independently, so they drift.

Note the asymmetry this produces: because `RAIRTY_FULL_TO_SHORT` knows `ORR`, the image filename
comes out correct; but because the enum maps do not, the printing itself is dropped. We generate a
right-looking URL for a printing that does not exist.

## What it leads to

18 rarity assignments discarded across Structure Deck: Birth of Hero (JP/KR) and Structure Deck R:
Lost Sanctuary. Those rows fall back to the set list's `default_rarities`, so the cards are recorded
at the wrong rarity rather than being absent — arguably worse, since it is invisible downstream.

Broader concern: Rush Duel coverage generally. `ORR` is the only one that appeared in this run, but
`RR` and `GRR` are equally unmapped and will fail the same way the moment a set using them is
imported.

## How we might fix it

Sketch only — **investigate before implementing**:

- Add `CardRarity` members for Rush Rare, Gold Rush Rare and Over Rush Rare, then add short-code
  and full-name entries to both maps.
- **First** check what the complete Rush Duel rarity list is. Yugipedia's rarity template is the
  source of truth; the copy at lines ~845-925 of `yugipedia.py` may itself be stale. There may be
  more Rush rarities than these three.
- Consider whether Rush Duel rarities should be distinguishable from OCG/TCG ones in the schema at
  all, or whether consumers care. That is a design call, not a mechanical one.
- Strongly consider deriving `RARITY_STR_TO_ENUM` and `FULL_RARITY_STR_TO_ENUM` from a single
  table (`_RARITY_FTS_RAW` is nearly that already). The whole class of bug here is three tables
  that must agree and do not.

## How to verify

- Re-fetch:
  `https://yugipedia.com/api.php?action=parse&page=Set%20Card%20Lists:Structure%20Deck:%20Birth%20of%20Hero%20(OCG-KR)&prop=wikitext&format=json`
- Import that set; `RD/SD0B-KRS01` and `RD/SD0B-KRS02` must come out as Over Rush Rare, not the
  list default.
- Add the consistency test described in `2026-08-06-duel-terminal-rarity-swap.md` — for every entry
  in `_RARITY_FTS_RAW`, assert both maps resolve it, and to the same member. That test fails today
  on exactly these three entries.

## Related

- `2026-08-06-grand-master-rare.md`, `2026-08-06-ultra-rare-special-blue.md`,
  `2026-08-06-rarity-string-normalization.md`, `2026-08-06-duel-terminal-rarity-swap.md`
