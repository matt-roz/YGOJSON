# The schema holds one image per printing, so ~1288 variant images are discarded

**Date:** 2026-08-06
**Source:** GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) (Generate/Upload Database)
**Symptom in log:** `[WARNING] Found multiple images for the same card ... : ['', 'Reprint']`
**Occurrences:** 1480 warnings over 1288 distinct (card, rarity, set) keys
**Severity:** design decision — currently the largest single category of dropped data

> **Read this first.** Everything below was derived on 2026-08-06 from the run log and the source.
> This is a **schema change proposal**, not a bug fix — it changes the public JSON contract and
> affects every consumer. Do not implement it on the strength of this document. Establish that the
> data is wanted, check what `schema/` commits us to, and get agreement before writing code.
>
> There is a separate, unambiguous bug in the same code path — see
> `2026-08-06-nondeterministic-image-selection.md`. **Fix that first regardless of what is decided
> here.** It is independent and much smaller.

## The issue

A printing can have several images within one edition. The schema has room for one.

```python
# src/ygojson/database.py, line ~1766
card_images: typing.Dict[SetEdition, typing.Dict[CardPrinting, str]]
```

The importer collects all of them into `RawPrinting.image`
(`typing.Dict[ImageLocator, str]`, where `ImageLocator = (edition, altinfo)`), warns that there are
several, keeps the first, and throws the rest away.

What is being thrown away, by alt-info tag:

```
~840  Reprint / Reprint2        different print runs within one set
~330  AA / AA2 / AA3 / AA4/AA5  alternate artwork
  80  Emblazoned
  66  ClassicStyle
  37  EA
  35  Silver
  25  OriginalLayout
  32  Logo / S1                 stamped (tournament / promo) variants
   5  numbered 2 / 3
        plus CT, GC, B, C, D, Red, Misprint, and one-offs
```

Worst-affected sets: Legend of Blue Eyes White Dragon (202), Quarter Century Art Collection (125),
Metal Raiders (108), EX Starter Box (85), Limited Pack World Championship 2025 (80), Prismatic Art
Collection (65), Vol.1 and Vol.4-7 (~240 combined), Labyrinth of Nightmare (37), Pharaonic Guardian
(35).

## Where it happens

`src/ygojson/importers/yugipedia.py`, **lines ~2469-2481**:

```python
ils = [il for il in rc.image if il.edition == edition]
if len(ils) > 1:
    logging.warn(f"Found multiple images for the same card ...")
if ils:
    il = ils[0]
    locale.card_images[edition][...] = rc.image[il]
```

Related structures: `ImageLocator` (line ~1716), `RawPrinting` (line ~1731), `COLORFUL_RARES`
(line ~1772). Serialisation lives in `src/ygojson/database.py` around lines ~1820-1850, and the
public schema in `schema/`.

## Why it happens

`card_images` was modelled as one image per printing per edition. The alt-info dimension exists in
the importer's intermediate representation but has nowhere to go in the output.

Note there is a partial precedent for handling variants: `COLORFUL_RARES` (line ~1772) promotes
certain `(rarity, alt)` pairs into distinct rarities — `(ULTRA, "Blue") → ULTRA_BLUE` — and clears
the alt. So the codebase already has one strategy for "this variant is really a different thing".
The open question is whether `Reprint` / `AA` / `Emblazoned` deserve the same treatment, a new
dimension, or nothing.

## What it leads to

- ~1288 printings ship with one image where several exist. For alternate-art-heavy products
  (Quarter Century Art Collection, Prismatic Art Collection, the Rarity Collections) that is a
  substantial fraction of what makes the set interesting.
- Combined with the nondeterministic selection bug, *which* single image survives is arbitrary and
  changes between runs.
- 1480 warning lines per run that are, under the current design, not actionable — they describe
  intended behaviour. That is 69% of the entire warning volume.

## How we might fix it

Options to evaluate — **this needs a decision before any code**:

1. **Do nothing to the schema; fix the selection and downgrade the warning.** Legitimate outcome.
   The data is on Yugipedia; we simply do not carry it. If this is the decision, record it, and
   drop the message to DEBUG or an aggregate count so it stops masking real problems.
2. **Add a variants map alongside the canonical image**, e.g. keep `card_images` as-is for
   compatibility and add an optional per-printing `{altinfo: url}` map. Additive, so existing
   consumers keep working.
3. **Promote some alt-infos to first-class concepts.** `Reprint`/`Reprint2` arguably describe a
   distinct *printing*, not a distinct image — the set was reprinted with a different card code or
   layout. `AA` is arguably a distinct artwork of the same printing. These may want different
   treatment from each other; lumping them together as "variant images" may be the wrong shape.
4. **Extend `COLORFUL_RARES`-style promotion** where the variant really is a rarity distinction.

Before choosing, work out what the alt-info tags actually *mean* on Yugipedia — `EA`, `Emblazoned`,
`ClassicStyle`, `OriginalLayout`, `S1`, `GC`, `CT` are set-specific conventions and I did not
establish their semantics. That research is the real work here.

Two entries look like wiki errors rather than legitimate variants and should be checked separately:

- `Legendary Collection: 25th Anniversary Edition` — Blue-Eyes White Dragon, Dark Magician and
  Red-Eyes Black Dragon each carry `['Italian', 'German']`, i.e. two *locales* filed under one
  printing.
- `OTS Tournament Pack 9` — Mecha Phantom Beast Token carries
  `['Harrliard', 'Megaraptor', 'Dracossack']`, three artwork variants under one entry.

## How to verify

- Whatever is decided, the check is the same: pick five printings from the list above, compare our
  output against the Yugipedia gallery, and confirm we carry what we claim to carry.
- If the schema changes, `schema/` and the README's format documentation must change with it, and
  existing consumers need a migration note.

## Related

- `2026-08-06-nondeterministic-image-selection.md` — the independent bug in the same lines. Fix
  first.
- `2026-08-06-warning-observability.md` — this bucket is 69% of the warning volume.
