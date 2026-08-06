# 17 manual set fixups point at Yugipedia names that no longer resolve

**Date:** 2026-08-06
**Source:** GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) (Generate/Upload Database)
**Symptom in log:** `[WARNING] Unknown set to fixup: {"yugipediaName": "..."}`
**Occurrences:** 17 distinct names (25 warning lines)
**Severity:** low — but these are *our* files, and they are silently doing nothing

> **Read this first.** Everything below was derived on 2026-08-06 from the run log and the contents
> of `manual-data/`. You **must** check each name against Yugipedia yourself before deleting or
> rewriting anything — a name that failed to resolve in this run may be a page that was renamed
> (in which case update it) rather than one that never existed (in which case remove it).

## The issue

`manual-data/` contains hand-written fixups keyed by Yugipedia set name. At import time each key is
looked up; when the lookup fails we warn and skip. 17 keys currently fail, meaning those fixups have
no effect at all.

The failing names:

```
2015 Value Box                          Master Hyperion Value Box
Collectible Tins 2006 Wave 1            Next-Gen Dueling Kit
Dragunity Blast                         Poseidra Value Box
Duel Disk - Yusei Version               Premium Pack 2
Jump Pack 2014 Issue 1 promotional card Shadow Samurai Value Box
Jump Pack 2014 Issue 2 promotional card Shonen Jump Scholastic Edition Vol. 9, Issue 1 promotional card
Jump Pack 2014 Issue 3 promotional card Utopia Value Box
WSJ Jump Pack Fall 2016 promotional card
WSJ Jump Pack Spring 2016 promotional card
WSJ Jump Pack Spring 2017 promotional card
```

Most come from `manual-data/sets/TCG Promo Cards.json`; `Premium Pack 2` comes from
`manual-data/sets/TCG Premium Packs.json`. Several also appear under
`manual-data/sealed-products/` (e.g. `Dragunity Blast.json`, `Utopia Value Box.json`,
`Next-Gen Dueling Kit.json`) — check whether those are affected too or use a different lookup.

## Where it happens

`src/ygojson/database.py`, `Database.manually_fixup_sets`, **lines ~2445-2470**:

```python
for i, mfi in enumerate(ManualFixupIdentifier(x) for x in in_json["sets"]):
    set_ = self.lookup_set(mfi)
    if not set_:
        logging.warn(f"Unknown set to fixup: {mfi}")
```

Data lives under `manual-data/sets/` and `manual-data/sealed-products/`.

## Why it happens

Three plausible causes, and you need to determine which applies per name:

1. **Page renamed on Yugipedia.** Very likely for the promo-card entries — Yugipedia periodically
   reorganises promotional card set naming.
2. **Set never imported.** If the set page exists but our importer skips it (no set table, wrong
   namespace, video-game-only product), the fixup can never match. Several of these are boxed
   products ("Value Box", "Dueling Kit", "Duel Disk") which overlaps with the
   `Found set without set navigation table` bucket.
3. **Typo or stale name that was never correct.**

The lookup is by exact Yugipedia name, so any drift upstream silently disconnects the fixup.

## What it leads to

Whatever those 17 fixups were meant to correct is not being corrected. Since the fixups exist,
someone found the automatic import wrong for these sets — so the published data is presumably
wrong for them today, and has been since the names drifted, with only a log line to show for it.

The sealed-product entries are worth particular attention: if `manual-data/sealed-products/` uses
the same identifiers, sealed product data for those boxes may be orphaned as well.

## How we might fix it

Sketch only — **investigate before implementing**:

- For each name, check Yugipedia for a page with that title or a redirect from it. Update the key
  where the page moved; delete the entry where the set genuinely does not exist.
- Where the set exists on Yugipedia but we never import it, the fixup is not the bug — find out why
  the set is skipped. Cross-reference `2026-08-06-sets-without-set-table.md` and the
  `Found set without set navigation table` warnings from the same run.
- Consider making unresolved fixups **fail the build** rather than warn. These are files we control;
  a fixup that silently does nothing is worse than one that breaks loudly. Weigh that against how
  often Yugipedia renames pages — if it is frequent, a warning that is actually visible (see the
  observability handoff) may be the better trade.
- Consider keying fixups by Yugipedia page ID rather than name, since IDs survive renames.
  `ManualFixupIdentifier` may already support this — check before proposing it.

## How to verify

- For each name: `https://yugipedia.com/api.php?action=query&titles=<name>&redirects&format=json`
  and see whether it resolves, redirects, or is missing.
- After updating, confirm the warnings are gone *and* that the fixups now change the output —
  a fixup that resolves but changes nothing is still dead.

## Related

- `2026-08-06-sets-without-set-table.md`
- `2026-08-06-warning-observability.md`
