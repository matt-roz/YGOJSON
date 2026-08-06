# An empty `|print=` parameter makes the set-list parser read the print status as the quantity

**Date:** 2026-08-06
**Source:** GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) (Generate/Upload Database)
**Symptom in log:** `[WARNING] Got strange quantity in Set Card Lists:...: New` / `: Reprint`
**Occurrences:** 176 (126 × `Reprint`, 50 × `New`)
**Severity:** high — silently wrong card quantities in shipped data

> **Read this first.** Everything below was derived on 2026-08-06 by reading the run log, the
> importer source, and live Yugipedia wikitext. Wiki pages change and line numbers drift. You
> **must** re-verify each claim yourself — re-fetch the cited pages, re-read the code at the cited
> locations, and reproduce the warning locally — before writing a fix. The proposed fix below is a
> starting hypothesis, not a specification.

## The issue

Yugipedia's `{{Set list}}` template takes a `|print=` parameter. When it is present, each row
carries an extra print-status column between the rarity and the quantity. Yugipedia writes it
**present but empty** when the per-row values differ:

```
{{Set list|region=KR|rarities=C|print=|qty=1|
RD/SD0B-KR001; Elemental HERO Flame Wingman (Rush Duel); UR; New
RD/SD0B-KR007; Elemental HERO Burstinatrix (Rush Duel);; New; 2
RD/SD0B-KR015; Yamiruler the Dark Delayer - Supreme Soldier Spear;; Reprint
}}
```

Our parser tests `|print=` for *truthiness*, so an empty value reads as "no print column". It then
reads the print status (`New` / `Reprint`) where the quantity should be, fails to `int()` it, warns,
and leaves the real quantity unread.

## Where it happens

`src/ygojson/importers/yugipedia.py`, inside `parse_tcg_ocg_set` → the set-list handler.

Two sites:

**Line ~1931** — the flag is captured as a raw string:

```python
raw_default_reprint_status = get_table_entry(setlist, "print")
```

`get_table_entry` (line ~331) returns `arg.value` when the parameter exists and `default` (here
`None`) when it does not. For `|print=` it returns `""`.

**Lines ~2003-2016** — the flag is used to decide whether to skip a column:

```python
if raw_default_reprint_status:      # <-- "" is falsy; column is NOT skipped
    col_index += 1

qty = None
if default_qty is not None and len(cols) > col_index:
    raw_qty = cols[col_index]
    if raw_qty:
        try:
            qty = int(raw_qty)
        except ValueError:
            logging.warn(
                f"Got strange quantity in {listpagename}, in row {name}: {raw_qty}"
            )
        col_index += 1
```

## Why it happens

Presence of a template parameter and truthiness of its value are different things, and the code
conflates them. `get_table_entry(setlist, "print")` returns `None` when absent and `""` when
present-and-empty — the distinction is available, it is just not used.

Note the warning only fires when `|qty=` is also set (otherwise `default_qty is None` and the
quantity block is skipped entirely), which is why only a handful of sets show it. Sets with
`|print=` and no `|qty=` are silently mis-columned in the same way but produce no warning — worth
checking whether anything downstream reads those columns.

## What it leads to

**Quantities in preconstructed decks are wrong.** In the example above,
`RD/SD0B-KR007; ...;; New; 2` should record 2 copies. Instead `raw_qty` is `"New"`, the `int()`
fails, `qty` stays `None`, and the code falls back to `default_qty` (1). We ship "1 copy" for a
card the deck contains twice.

Affected in this run:

- `Set Card Lists:Structure Deck: Birth of Hero (OCG-JP)`
- `Set Card Lists:Structure Deck: Birth of Hero (OCG-KR)`
- `Set Card Lists:Structure Deck R: Lost Sanctuary (OCG-JP)`
- `Set Card Lists:Structure Deck R: Lost Sanctuary (OCG-KR)`

Also worth checking: because `col_index` is not advanced past the print column, anything read
*after* the quantity column (if the parser is ever extended) inherits the same offset.

## How we might fix it

Sketch only — **investigate before implementing**:

- Change the presence test to `get_table_entry(setlist, "print") is not None`, or capture a
  separate boolean `has_print_column = any(x.name.strip() == "print" for x in setlist.arguments)`.
- **Verify the semantics against `Template:Set list` on Yugipedia** before committing to that.
  In the same page we also see `{{Set list|region=KR|rarities=SR|print=New|` where rows have only
  three columns — i.e. a *non-empty* `print=` acts as a default and the rows have no print column.
  If that is the actual rule, then presence alone is the wrong test and you need to handle
  "non-empty print= means default, empty print= means per-row column". Confirm which it is; the
  current code and the proposed fix disagree about the non-empty case.
- Consider parsing the print status into the model rather than discarding it — `New`/`Reprint` is
  real information, and `CardPrinting` already has a `replica` concept nearby (line ~2461).

## How to verify

- Re-fetch:
  `https://yugipedia.com/api.php?action=parse&page=Set%20Card%20Lists:Structure%20Deck:%20Birth%20of%20Hero%20(OCG-KR)&prop=wikitext&format=json`
- Import that one set and assert `RD/SD0B-KR007` and `RD/SD0B-KR008` come out with `qty == 2`
  while their neighbours come out with `qty == 1`.
- Sweep for `|print=` with no `|qty=` and confirm nothing else is being mis-columned silently.
