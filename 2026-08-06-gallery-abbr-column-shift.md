# Set gallery rows using `abbr::` shift every column one to the left

**Date:** 2026-08-06
**Source:** GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) (Generate/Upload Database)
**Symptom in log:** `[WARNING] Could not decipher rarity code for <X> in Set Card Galleries:...: <Y>`
**Occurrences:** 15 (14 × `RP`, 1 × `Illegal`)
**Severity:** high — imports phantom cards, drops real printings

> **Read this first.** Everything below was derived on 2026-08-06 by reading the run log, the
> importer source, and live Yugipedia wikitext. Wiki pages change and line numbers drift. You
> **must** re-verify each claim yourself — re-fetch the cited pages, re-read the code at the cited
> locations, and reproduce the warning locally — before writing a fix. The proposed fix below is a
> starting hypothesis, not a specification.

## The issue

Yugipedia's `{{Set gallery}}` rows normally look like `<card number>; <name>; <rarity>; <alt>`.
Some rows omit the card-number column and instead supply the set abbreviation in a trailing
comment, e.g. `//abbr::15AY`. Our gallery parser does not account for the missing column: it
unconditionally eats the first column as the card number, so name, rarity and alt-info all slide
one position to the left.

Observed on `Set Card Galleries:Memories of the Duel King: Battle City Arc (OCG-JP)`:

```
 Obelisk the Tormentor (original); UR; RP //abbr::15AY
 Duelist Kingdom (card); UR; RP //abbr::15AY
```

parses as `code="Obelisk the Tormentor (original)"` (then overwritten with `15AY`),
`name="UR"`, `rarity="RP"`, `alt=""`.

And on `Set Card Galleries:Limited Pack GX: Ra Yellow (OCG-JP)`:

```
Hamon, Lord of Striking Thunder (illegal); Secret Rare; Illegal // abbr::LPG2
```

parses as `name="Secret Rare"`, `rarity="Illegal"`.

## Where it happens

`src/ygojson/importers/yugipedia.py`, inside `parse_tcg_ocg_set` → `get_gallery_data` → `do` →
`onGetList`, around **lines 2142-2155**:

```python
col_index = 0

code = default_abbr if default_abbr else None
if not default_abbr and len(cols) > col_index:
    code = cols[col_index]          # <-- consumed unconditionally
    col_index += 1
if abbr_override:
    code = str(abbr_override.group(1))   # <-- too late; the column is already gone

if len(cols) > col_index:
    name = cols[col_index]
    col_index += 1
else:
    continue
```

Contrast with the **set-list** parser in the same file (~lines 1963-1973), which gets this right
via the `noabbr` option:

```python
if not noabbr:
    code = cols[col_index]
    col_index += 1
else:
    abbr_override = re.match(...)
    ...
```

The warning itself is emitted further down, at **line ~2201**, from the image-filename builder —
it is a *downstream* symptom, not the bug site.

## Why it happens

`abbr_override` is computed at line ~2127 but only applied *after* `cols[0]` has already been
consumed. The gallery parser has no equivalent of the set-list parser's `noabbr` handling, and it
never considers that a row supplying `abbr::` is signalling "this row has no number column".

## What it leads to

1. **Phantom cards.** `add_card_image(name, ...)` is called with `name="UR"`, `"Ultra Rare"` or
   `"Secret Rare"`. Those go through `get_card(name)`, so we attempt to resolve card pages that
   are rarity names.
2. **Lost printings.** The real cards on those rows — *Obelisk the Tormentor (original)*,
   *Duelist Kingdom (card)*, *Hamon, Lord of Striking Thunder (illegal)*, and the equivalents in
   the KR-UE and Yugi's Uncut Card Sheet galleries — get no image and quite possibly no printing.
3. **Garbage image filenames.** The generated filename gets `-RP`/`-Illegal` appended, which can
   never resolve.
4. Log noise that masks other problems.

Affected galleries seen in this run: Memories of the Duel King (Battle City / Ceremonial Battle /
Duelist Kingdom Arc, OCG-JP and OCG-KR-UE), Yugi's Uncut Card Sheet promotion (OCG-KR-UE),
Limited Pack GX: Ra Yellow (OCG-JP).

## How we might fix it

Sketch only — **investigate before implementing**:

- When `abbr_override` is present, do not consume `cols[0]` as the card number; treat it as the
  name. Something like: compute `abbr_override` first, then
  `if abbr_override: code = abbr_override.group(1)` **without** advancing `col_index`.
- Check whether `default_abbr` (`|abbr=` on the template) interacts with this — the current code
  already skips the number column when `default_abbr` is set, which suggests the intended
  semantics are "an abbreviation from anywhere means the row has no number column". Confirm that
  against Yugipedia's `Template:Set gallery` documentation rather than assuming.
- Consider whether the leading whitespace on those rows is also a signal, and whether a row can
  legitimately have *both* a number column and an `abbr::` comment. If it can, the heuristic above
  is wrong and you need a different discriminator (e.g. column count).

## How to verify

- Re-fetch the wikitext:
  `https://yugipedia.com/api.php?action=parse&page=Set%20Card%20Galleries:Memories%20of%20the%20Duel%20King:%20Battle%20City%20Arc%20(OCG-JP)&prop=wikitext&format=json`
- Run the Yugipedia importer against just that set and confirm the warning disappears and that
  *Obelisk the Tormentor (original)* gets an image.
- Grep the run log for `Could not decipher rarity code` and confirm all 15 `RP`/`Illegal` lines
  are gone; the `Grand Master Rare` / `Ultra Rare (Special Blue Version)` lines are a *different*
  issue (see the rarity handoffs) and should still be there until those are fixed too.

## Related

- `2026-08-06-abbr-override-regex-index-error.md` — the set-list side has a latent crash in its
  own `abbr::` handling.
- `2026-08-06-placeholder-gallery-rows.md` — another class of gallery row we mis-parse into a
  phantom card.
