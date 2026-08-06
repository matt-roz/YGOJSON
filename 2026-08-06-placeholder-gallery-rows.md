# Empty Yugipedia gallery stubs are parsed as a card called "name"

**Date:** 2026-08-06
**Source:** GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) (Generate/Upload Database)
**Symptom in log:** `Could not decipher rarity code for name in Set Card Galleries:...: rarity`
**Occurrences:** 3
**Severity:** low volume, but we are importing junk

> **Read this first.** Everything below was derived on 2026-08-06 by reading the run log and live
> Yugipedia wikitext. Wiki pages change — these stubs may well have been filled in by the time you
> read this. You **must** re-fetch the cited pages and confirm the pattern still exists (and check
> whether it exists on *other* pages) before writing a guard.

## The issue

When a set has a gallery page created but not yet populated, Yugipedia leaves the template's
documentation line in place:

```
{{Set page header}}

{{Set gallery|
number; name; rarity // option::value
}}
```

Our gallery parser has no idea this is a placeholder. It parses the row literally:
`code="number"`, `name="name"`, `rarity="rarity"`, and then calls `add_card_image("name", ...)`,
which goes through `get_card("name")` and tries to build an image filename ending in `-rarity`.

Seen on:

```
Set Card Galleries:Rage of the Abyss (OCG-AE)
Set Card Galleries:Alliance Insight (OCG-AE)
Set Card Galleries:Deck-Build Pack: Tactical Masters (OCG-SC)
```

## Where it happens

`src/ygojson/importers/yugipedia.py`, gallery row loop, **lines ~2114-2214**. There is no
validation between splitting the row on `;` and using the pieces:

```python
cols = [x.strip() for x in pre_comment.split(";")]
if not cols:
    continue
...
name = cols[col_index]      # "name"
...
add_card_image(name, rarity, alt, image, code)
```

The warning surfaces at line ~2201 from the filename builder, which is incidental — the row should
never have got that far.

## Why it happens

The parser trusts that any row inside `{{Set gallery}}` describes a card. Yugipedia's convention of
leaving the parameter legend in the template body as a placeholder is not something the parser
knows about.

Note the `// option::value` half is also literal placeholder text, and the parser's
`abbr::` / `file::` / `extension::` searches (lines ~2127-2135) run against it harmlessly only by
luck.

## What it leads to

- Three attempts to resolve a Yugipedia card page named `name`. Depending on how `get_card`
  behaves on a miss, this either wastes requests or creates a bogus card entry — **worth checking
  which**, since a phantom card in the published database is much worse than a log line.
- Three unresolvable image filenames.
- Log noise in the same warning bucket as two real bugs
  (`2026-08-06-gallery-abbr-column-shift.md`), which is how they stayed hidden.

## How we might fix it

Sketch only — **investigate before implementing**:

- Skip rows that match the placeholder shape. The literal
  `number; name; rarity // option::value` is a fixed string; matching it exactly is the least
  risky guard. Matching loosely (e.g. "name is literally `name`") risks eating a real card.
- **First establish what `get_card("name")` currently does.** If it silently creates or matches
  something, that is the actual bug and the guard is secondary.
- Consider a broader sanity check on gallery rows — a row whose card number does not look like a
  set code is suspicious. That would also catch the `abbr::` column-shift rows from the related
  handoff. Design it carefully: promo galleries legitimately have rows with no number.
- Consider fixing the wiki. These are stub pages; if the sets have released, populating them
  upstream benefits everyone. If they have not, the stub is legitimate and the guard is the right
  answer.

## How to verify

- Re-fetch:
  `https://yugipedia.com/api.php?action=parse&page=Set%20Card%20Galleries:Rage%20of%20the%20Abyss%20(OCG-AE)&prop=wikitext&format=json`
- Search the imported database for a card named `name` and for any card whose Yugipedia title is
  `name`. Confirm before *and* after — if it is there today, the fix has to remove it.
- Confirm the 3 warnings are gone from a fresh run.

## Related

- `2026-08-06-gallery-abbr-column-shift.md` — the other way gallery rows turn into phantom cards.
