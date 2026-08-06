# Latent `IndexError` in the set-list `abbr::` override

**Date:** 2026-08-06
**Source:** code review prompted by GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603)
**Symptom in log:** none — the branch was not reached in this run
**Severity:** low probability, high impact (uncaught exception aborts the import)

> **Read this first.** This was found on 2026-08-06 by reading the source. It did **not** fire in
> the referenced run. You **must** confirm the branch is reachable and reproduce the crash before
> deciding how to fix it — it is possible the branch is dead code that should be deleted instead.

## The issue

The set-list parser's `abbr::` handling calls `.group(1)` on a regex that has no capture group.
If the branch is ever entered with a matching comment, it raises `IndexError: no such group`.

```python
>>> import re
>>> re.match(r"abbr::[^\s;]+", "abbr::LPG2").group(1)
IndexError: no such group
```

## Where it happens

`src/ygojson/importers/yugipedia.py`, set-list row parsing, **lines ~1965-1973**:

```python
if not noabbr:
    code = cols[col_index]
    col_index += 1
else:
    abbr_override = re.match(r"abbr::[^\s;]+", post_comment)   # no capture group
    if abbr_override:
        code = str(abbr_override.group(1))                      # IndexError
    else:
        code = ""
```

The gallery parser has the correct form of the same idea at **line ~2127**:

```python
abbr_override = re.search(r"abbr::\s*([^\s;]+)", post_comment)
```

Note three differences: `search` vs `match`, `\s*` after `::`, and an actual capture group.

## Why it happens

`noabbr` is set from `"noabbr" in raw_options.lower()` (line ~1944), where `raw_options` comes from
the template's `|options=` parameter. For the exception to fire you need a set-list template with
`options=noabbr` **and** a row whose post-`//` comment starts with `abbr::`. That combination did
not occur in the 407 sets processed in this run, so the code path has apparently never executed
with a match — which is why an obvious bug survived.

The `re.match` (anchored at position 0) also means it only fires when the comment begins with
`abbr::`, narrowing it further. Yugipedia comments in the wild are often `// abbr::LPG2` with a
leading space, which `post_comment` strips — so the anchoring may not save us.

## What it leads to

An unhandled `IndexError` inside the batcher callback. Depending on how the batcher handles
exceptions this either kills the whole import job or corrupts that set's data. Either way it will
happen without warning the first time someone adds `options=noabbr` plus a row-level `abbr::` to a
Yugipedia page — i.e. at an arbitrary future time, in CI, for reasons unrelated to any change we
made.

## How we might fix it

Sketch only — **investigate before implementing**:

- Align it with the gallery version: `re.search(r"abbr::\s*([^\s;]+)", post_comment)` and keep the
  `.group(1)`.
- Better: factor the `abbr::` extraction into one helper used by both parsers, so they cannot
  diverge again. Check first whether the two really do want identical semantics — the set-list side
  gates on `noabbr` while the gallery side does not, so they may be intentionally different.
- While you are there, consider whether `file::` and `extension::` (lines ~2130-2135) deserve the
  same treatment.
- Consider whether an exception in a batcher callback should be caught and logged rather than
  propagating. That is a broader question than this bug, but this bug is a good argument for it.

## How to verify

- Unit-test the extraction helper directly with `"abbr::LPG2"`, `"abbr:: LPG2"`,
  `"foo // abbr::LPG2"`, and `""`.
- Construct a synthetic `{{Set list|options=noabbr|...}}` fixture with a row carrying an `abbr::`
  comment, run it through the parser, and confirm it produces the right code instead of raising.
- Search Yugipedia for set-list pages using `options=noabbr` to find out whether any real page is
  one edit away from triggering this.

## Related

- `2026-08-06-gallery-abbr-column-shift.md` — the gallery side of `abbr::` handling has a
  different, active bug.
