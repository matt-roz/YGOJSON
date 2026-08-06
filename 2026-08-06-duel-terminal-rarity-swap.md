# `DTRPR` and `DTPSP` are swapped in the full-name rarity map

**Date:** 2026-08-06
**Source:** code review prompted by GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603)
**Symptom in log:** none — this is silent
**Severity:** medium — silently wrong rarity on Duel Terminal printings

> **Read this first.** This was found on 2026-08-06 by reading the source, not from a warning. It
> is an inference from the two maps disagreeing; it has **not** been confirmed against real output.
> You **must** verify the correct mapping against Yugipedia's rarity template and against actual
> Duel Terminal set data before changing anything — it is possible the *short* map is the wrong one.

## The issue

There are two rarity lookup tables in the Yugipedia importer: `RARITY_STR_TO_ENUM` (short codes)
and `FULL_RARITY_STR_TO_ENUM` (full English names). For the two Duel Terminal parallel rarities
they disagree with each other.

`RARITY_STR_TO_ENUM`, lines ~955-956:

```python
"dnrpr": CardRarity.DTPSP,
"drpr":  CardRarity.DTRPR,
```

`FULL_RARITY_STR_TO_ENUM`, lines ~1534-1535:

```python
"duel terminal rare parallel rare":        CardRarity.DTPSP,   # drpr
"duel terminal normal rare parallel rare": CardRarity.DTRPR,   # dnrpr
```

The trailing comments name `drpr` and `dnrpr` respectively, so the *intent* matches the short map,
but the enum values are the other way round.

The enum docstrings in `src/ygojson/database.py` (lines ~527-531) back the short map:

```python
DTPSP = "dtpsp"
"""Duel Terminal Parallel Short Print or Duel Terminal Normal Rare Parallel Rare."""
DTRPR = "dtrpr"
"""Duel Terminal Rare Parallel Rare."""
```

So `FULL_RARITY_STR_TO_ENUM` looks wrong: "Duel Terminal Rare Parallel Rare" should be `DTRPR`,
and "Duel Terminal Normal Rare Parallel Rare" should be `DTPSP`.

## Where it happens

`src/ygojson/importers/yugipedia.py`, lines ~1534-1535, inside `FULL_RARITY_STR_TO_ENUM`.

Both maps are consulted at every rarity lookup site — set lists (~line 1992), gallery default
rarity (~line 2103), gallery per-row rarity (~line 2163), subgalleries (~line 2232) — always as
`RARITY_STR_TO_ENUM.get(x) or FULL_RARITY_STR_TO_ENUM.get(x)`. The short map is tried first, so the
bug only bites when a page spells the rarity out in full.

## Why it happens

Almost certainly a transcription slip when the full-name table was written. The two entries are
adjacent and their names differ by one word.

## What it leads to

Any Duel Terminal set list or gallery that writes the rarity as a full English name rather than the
`DRPR`/`DNRPR` abbreviation gets the wrong rarity recorded, with no warning. Consumers see
`dtrpr` where `dtpsp` belongs and vice versa.

The blast radius is unknown — it depends entirely on how many Duel Terminal pages spell the rarity
out. Establishing that number is part of the work.

## How we might fix it

Sketch only — **investigate before implementing**:

- Swap the two enum values in `FULL_RARITY_STR_TO_ENUM` so they match their own comments, the
  short map, and the enum docstrings.
- **First** confirm which side is authoritative. Check Yugipedia's rarity template (the commented
  block at lines ~845-925 of `yugipedia.py` is a copy of it) and a real Duel Terminal card page.
  `DNRPR` and `DRPR` are distinct rarities; make sure the enum docstrings themselves are right
  before treating them as ground truth.
- Note `DTPSP`'s docstring conflates "Duel Terminal Parallel Short Print" and "Duel Terminal Normal
  Rare Parallel Rare". Check whether that conflation is deliberate.
- Consider deriving one map from the other (via `_RARITY_FTS_RAW` / `RAIRTY_FULL_TO_SHORT`, lines
  ~994-1507) so the two can never drift again. That is the durable fix; the swap is the patch.

## How to verify

- Add a unit test asserting `RARITY_STR_TO_ENUM["drpr"] is FULL_RARITY_STR_TO_ENUM["duel terminal
  rare parallel rare"]`, and the same for the `dnrpr` pair. Generalise it: for every entry in
  `_RARITY_FTS_RAW`, assert the short code and every full name resolve to the same enum member.
  That test would have caught this and will catch the next one.
- Grep the imported database for `dtrpr` / `dtpsp` printings before and after and eyeball a few
  against Yugipedia.
