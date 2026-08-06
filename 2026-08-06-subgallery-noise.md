# `Found strange subgallery line` fires on non-card gallery images

**Date:** 2026-08-06
**Source:** GH Actions run [30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) (Generate/Upload Database)
**Symptom in log:** `[WARNING] Found strange subgallery line in Set Card Galleries:...: <line>`
**Occurrences:** 44
**Severity:** low — expected condition logged at the wrong level

> **Read this first.** Everything below was derived on 2026-08-06 from the run log and the importer
> source. Before downgrading or suppressing anything, **confirm that none of the 44 lines represent
> a real card we are failing to import.** A warning that is 90% noise is still 10% signal; find the
> 10% first.

## The issue

Old OCG Booster galleries contain `<gallery>` blocks that mix card images with non-card images —
rule inserts, FAQ cards, deck-construction guides, and the backs of those inserts. Our subgallery
parser requires three wikilinks per line (code, rarity, name); anything else warns.

Representative lines:

```
Set Card Galleries:Booster 1-7 (OCG-JP)
    FAQCard1-B01-JP-C.jpg | FAQ Card #1
    JuniorRuleIntroductionVol1-B01-JP.png   | [[Junior Rule Introduction Vol. 1]]
    NewExpertRule1-B01-JP.png      | "[[Spell Speed 1]]"
    NewExpertRule-B01-JP-Back1.png | New Expert Rule backing (1)
    CertainVictoryComboCollection-B01-JP-Back1.png | Certain Victory Combo backing (1)
Set Card Galleries:Booster 3 (OCG-JP)
    DeckConstructionCard1-B03-JP.jpg | Understanding the Role of Cards
    DeckConstructionCard2-B03-JP.png | Decide on a Deck Theme
    DeckConstructionCard3-B03-JP.jpg | Start by Choosing the Best Monsters...
```

None of these are cards. The parser is behaving correctly by skipping them; it just says so at
WARNING level.

## Where it happens

`src/ygojson/importers/yugipedia.py`, **lines ~2216-2245**:

```python
for subgallery in subgallery_htmls:
    lines = [x.strip() for x in subgallery.split("\n") if x.strip()]
    for line in lines:
        parsed_line = wikitextparser.parse(line)
        if len(parsed_line.wikilinks) < 3:
            logging.warn(
                f"Found strange subgallery line in {galleryname}: {line}"
            )
        else:
            ...
```

## Why it happens

`<gallery>` on MediaWiki is a generic image-list construct. Yugipedia uses it for card galleries
*and* for whatever else belongs on the page. The three-wikilink shape is a convention of card rows
only, so every non-card image in the same block trips the check.

The `< 3 wikilinks` heuristic is doing exactly what it should — the problem is purely that "this
line is not a card row" is treated as anomalous rather than routine.

## What it leads to

No data loss. 44 lines of log per run that no one can act on, in a log where noise is the primary
obstacle to spotting real problems.

There is a second-order cost: because this bucket is known-noisy, a *genuinely* malformed card row
appearing here would be ignored. That is the reason to triage before suppressing.

## How we might fix it

Sketch only — **investigate before implementing**:

- **First**, read all 44 lines and confirm every one is a non-card image. Extract them with
  something like `grep 'strange subgallery line' <log> | sort -u`. If any is a real card row, that
  is a separate bug and needs its own fix.
- Then downgrade the message to `debug`, or keep it at warning only when the line looks like it was
  *meant* to be a card row (e.g. it has 1-2 wikilinks rather than 0, or the filename matches the
  set's card-code pattern). The second option preserves signal; the first is simpler.
- Consider whether these non-card images are worth capturing at all — rule inserts and FAQ cards
  were physically included in those boosters. That is a schema question, not a logging one, and
  probably out of scope here.

## How to verify

- Re-fetch a sample:
  `https://yugipedia.com/api.php?action=parse&page=Set%20Card%20Galleries:Booster%203%20(OCG-JP)&prop=wikitext&format=json`
- Confirm the card rows in those galleries still import correctly after the change — the risk of
  loosening or relocating this check is skipping a real row.

## Related

- `2026-08-06-warning-observability.md`
- `2026-08-06-sets-without-set-table.md` — the other large low-signal bucket.
