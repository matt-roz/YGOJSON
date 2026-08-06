# Wave 1 — stop the column-offset corruption in the Yugipedia importer

**Base branch:** `feature/various-pipeline-fixes`

Implements issues #14, #4 and #1 from the [2026-08-06 warning audit](https://github.com/matt-roz/YGOJSON/issues/20).
This PRD does not replace those issues; it records what a design interview settled that they left open,
and corrects two of their claims that turned out to be wrong when checked against the live wiki and the
published database.

## Problem Statement

The published YGOJSON database contains silently wrong data, and the build that produced it was green.

Someone building a deck-builder against `v1/individual` sees `Duel Royale Deck Set EX` as a 103-card
product where every card appears exactly once. The actual product contains two copies of Blue-Eyes
White Dragon, three of Manju of the Ten Thousand Hands, and eleven other duplicates. Nothing in the
data says otherwise and nothing in the build said anything at all — this defect produces **zero** log
lines.

Someone browsing set galleries sees cards named `UR`, `ScR` and `Secret Rare` in `Starter Deck 2018`
and `Memories of the Duel King`, while the real cards on those rows — *Kanan the Swordmistress*,
*Crush Card Virus*, *Obelisk the Tormentor* — are missing entirely. Roughly half of those rows also
produce no warning.

The 2026-08-05 run emitted 2137 warnings and shipped anyway. The warnings that fired were a poor guide
to what was actually broken: the defect responsible for 176 of them corrupts nothing in the published
output, while the defect corrupting real published quantities is silent. A third defect, never yet
executed, will abort an import job outright the first time a wiki editor writes a particular
combination of template parameters.

## Solution

Correct the column arithmetic in both Yugipedia row parsers, so that the importer reads the same
columns Yugipedia's own templates define, and record the print-status value it currently discards.

Concretely, from a consumer's perspective:

- Preconstructed decks report the true number of copies of each card.
- Set galleries contain real cards, not cards named after rarities, and the cards that were being
  dropped come back.
- A printing can say whether the wiki recorded it as a new print or a reprint.
- An import job cannot be killed by a wiki edit that exercises a dead code path.
- The number of gallery images the importer fails to resolve becomes a visible figure instead of an
  invisible one, so the follow-up work can be scoped from data rather than guesses.

The behaviour is defined by two Yugipedia template documentation pages, `Template:Set list` and
`Template:Set gallery`, which were read during design and which resolve the research question the
audit flagged as blocking. Their rules are:

- For `Set list`, a `print` or `qty` parameter that is **present** adds a column to every row. The
  parameter's *value* is only the default for rows that leave that column blank. Presence and
  truthiness are different things, and only presence determines the column layout.
- For `Set gallery`, an abbreviation supplied for a row — whether from the template-level parameter or
  from a row-level entry option — means that row has **no card-number column**, and its first value is
  the card name.

## User Stories

1. As a deck-builder app developer, I want preconstructed deck contents to report the real number of copies of each card, so that a deck I import from YGOJSON is actually legal and complete.
2. As a deck-builder app developer, I want a card that appears twice in a Structure Deck to say so in the data, so that I do not have to hand-maintain a correction list for products I know are wrong.
3. As a collection-tracker developer, I want quantities to be right, so that a user marking a sealed product as owned gets the correct card counts added to their collection.
4. As a data consumer, I want the absence of a quantity field to reliably mean "one copy", so that I can treat the default as trustworthy rather than as "one copy, or possibly the importer failed to read it".
5. As a data consumer, I want set galleries to contain only real cards, so that I do not have to filter out entries named after rarities before using the data.
6. As a data consumer, I want the cards currently being dropped from galleries to be present, so that set contents are complete.
7. As a price-tracking developer, I want gallery rows for oversized, replica and illegal cards to resolve to the right card, so that I do not attach prices to a nonexistent card called `UR`.
8. As a data consumer, I want to know whether a printing was recorded as new or a reprint, so that I can identify a card's debut set without inferring it from release dates.
9. As a Yu-Gi-Oh! player, I want to search for *Kanan the Swordmistress* and find its `Starter Deck 2018` printing, so that the database reflects the product I own.
10. As a maintainer, I want a wiki edit adding a particular template parameter combination to be incapable of crashing an import job, so that a run does not fail for reasons unrelated to any change we made.
11. As a maintainer, I want an import failure in one partition not to abandon the remaining partitions because of an unhandled exception in a parser branch, so that a full run's cost is not wasted.
12. As a maintainer, I want the parser to agree with what Yugipedia's own templates render, so that a disagreement between our output and the wiki is a bug we can act on rather than an intentional divergence nobody documented.
13. As a maintainer, I want the number of gallery images that fail to resolve to be reported at the end of a run, so that a silent loss class becomes a number I can watch across runs.
14. As a maintainer, I want that number broken down by cause, so that images Yugipedia refuses to serve for licensing reasons do not mask images we failed to name correctly.
15. As a maintainer, I want the print-status column parsed rather than discarded, so that information the wiki already provides is not thrown away on every run.
16. As a maintainer, I want dead code that has never executed removed rather than repaired, so that the codebase does not accumulate branches that implement syntax no template supports.
17. As a contributor picking up one of these issues, I want the template semantics stated and cited, so that I do not re-derive the same research from scratch or reach a different conclusion.
18. As a contributor, I want to know which claims in the original issues were checked and found wrong, so that I do not verify against an assertion that no longer holds.
19. As a contributor, I want an exact reproduction command, so that I can confirm a fix without running the full multi-hour pipeline.
20. As a contributor, I want to know that narrowing a run requires set page titles rather than set list page titles, so that I do not run a command that imports nothing and reports success.
21. As a reviewer, I want the fix's scope stated in rows and pages rather than in warning counts, so that I can tell whether the verification actually covers the affected data.
22. As a reviewer, I want the schema addition to be additive and optional, so that existing consumers of the v1 schema are unaffected.
23. As a pipeline operator, I want this change not to alter behaviour for the thousands of set lists that parse correctly today, so that a fix for 13 templates does not risk the other several thousand.
24. As a pipeline operator, I want the change to avoid clearing the Yugipedia page cache during verification, so that confirming a fix does not cost a full refetch of the wiki.
25. As a future maintainer, I want the reason this class of bug occurred — conflating a parameter's presence with its truthiness — named in the code, so that the same mistake is not reintroduced next to it.

## Implementation Decisions

### Scope

- Wave 1 implements issues #14, #4 and #1, plus an image-miss counter, plus a `printStatus` field.
- Two findings surfaced during design are **not** implemented here and get their own issues: gallery
  image filenames built from page names rather than card names, and the total absence of Rush Duel
  cards from the database.
- Delivered as a single pull request off `feature/various-pipeline-fixes`.

### Set-list row parser (issues #14 and #1)

- The `print` and `qty` template parameters are tested for **presence**, not truthiness. Column layout
  is decided by whether the parameter exists; the parameter's value is used only as the default for
  rows that leave the column blank. These are two separate concerns and are represented by two
  separate values rather than one overloaded one.
- This fixes two defects of identical shape: an empty `print` parameter causing the print status to be
  read where the quantity belongs, and an empty `qty` parameter causing the quantity column never to
  be read at all.
- The row-level `abbr::` branch is **deleted**, not repaired. `Template:Set list` does not define
  `abbr::` as an entry option, and a scan of every page transcluding the template found zero
  occurrences of the string anywhere. The existing fallback for the `noabbr` option is already correct
  and is retained.

### Gallery row parser (issue #4)

- An abbreviation from either source — the template-level parameter or a row-level entry option —
  means the row has no card-number column. The row-level abbreviation must therefore be resolved
  *before* the first column is consumed, not after.
- This is a per-row decision, not a per-template one: rows with and without card numbers occur inside
  the same template on the live wiki.
- No additional discriminator (such as column count) is needed. Of the 33 `abbr::` rows on the wiki,
  **none** combines a row-level abbreviation with a template-level one, and none has four columns —
  the count a row carrying both a number and an abbreviation would produce. Observed column counts are
  one, two and three only.

### Image-miss accounting

- The batcher counts image lookups that fail, separated by cause: the file page not existing, a
  metadata page existing without a file, and files the wiki declines to serve for licensing reasons.
- Reported as a single summary line at the end of the Yugipedia import. Per-miss logging is explicitly
  rejected — two such log statements already exist in the code, commented out, and the batch's stated
  goal is to reduce warning volume, not add to it.
- The counter cannot distinguish "we generated the wrong filename" from "the wiki has no such image".
  It is a tripwire for tracking the number across runs, not a scoping tool.

### Schema

- `printing` gains an optional `printStatus` enum with values for new and reprint, populated from the
  print column that the set-list parser now reads correctly instead of discarding.
- Purely additive: the printing schema requires only two properties and does not forbid additional
  ones, so no schema version bump is required and existing consumers are unaffected.
- Accepted limitation: roughly two-thirds of set-list templates do not use the `print` parameter, so
  the field will be absent for most printings. Absence means "not recorded", not "new" — consumers
  cannot distinguish the two.

### Not extracted

The two row parsers remain where they are. They are loops that mutate importer state and invoke
batcher callbacks rather than deep modules waiting to be freed; extracting them would mean threading
several captured values through a new signature for no present caller. Revisit when Wave 2 introduces
a test framework, at which point the extraction has somewhere to be used.

## Testing Decisions

### What makes a good test here

There is no test framework in this repository, no unit tests and no type checker, and adding one is
explicitly a separate decision rather than a side quest inside another change. The honest verification
for a parser change is a narrow real run against live wikitext followed by reading the JSON it
produces — that is what this PRD specifies. Assertions are made about **published output** (does this
printing carry this quantity, is this card present, is this phantom card gone), never about internal
parser state.

### Prior art

`test/validate_data.py` is the only thing resembling a test. It validates generated output against the
v1 JSON schema and can only run after a pipeline run has produced data. It says nothing about whether
values are correct, only that they are shaped correctly. It should still be run after the verification
runs, because this PRD changes the schema.

### Verification

The pipeline is narrowed with the flag that confines the Yugipedia import to specific pages. This flag
filters the enumerated page list by ID — it does **not** fetch arbitrary pages. It must be given **set
page** identifiers; giving it set list or gallery page titles matches nothing and produces a
successful run that imports nothing. Numeric page IDs are used to avoid title normalisation surprises.
The production flag is omitted, so the Yugipedia page cache is never cleared.

Assertions, all against emitted JSON:

- **Quantity, the case that is actually wrong today.** In `Duel Royale Deck Set EX (OCG-JP)`, thirteen
  printings currently publish with no quantity field (meaning one copy) where the wiki gives two or
  three — including Blue-Eyes White Dragon at two and Manju of the Ten Thousand Hands at three. After
  the fix these carry their true quantities. Same check for `Structure Deck: Egyptian Gods' Advent
  (OCG-SC)` and one printing in `Structure Deck R: Machiners Command (OCG-JP)`.
- **Quantity, the case the original issue named.** `Structure Deck R: Lost Sanctuary` must be
  unchanged — every card is genuinely one copy, so the current output is already correct and the fix
  must not alter it. This is a regression check, not a corrections check.
- **Galleries.** Across the twelve affected gallery pages, no printing exists whose card name is a
  rarity, and the real cards on those rows are present. This must be checked on all twelve pages, not
  only on the ones that emitted warnings — roughly half the affected rows are silent, and verifying by
  warning disappearance alone would leave those unverified.
- **No regression at scale.** The presence-based column test must not change behaviour for the
  thousands of templates that supply a non-empty `print` value, which parse correctly today. Verified
  by importing a sample of such sets and confirming their output is byte-identical before and after.
- **Schema.** The full schema validator passes with the new optional field present on some printings
  and absent on others.
- **Crash path.** The deleted branch is confirmed unreachable by the wiki scan described above rather
  than by a test, since no live page can reach it.

## Out of Scope

- **Gallery image filenames built from page names** — filed as #22. Fixing the column shift restores
  the printing but not its image, and also leaves the `replica` flag false. Affects rows that parse
  correctly today, so it has a much larger blast radius than #4.
- **Rush Duel cards missing from the database** — filed as #21. All 3,147 of them. This is why
  `Structure Deck: Birth of Hero` publishes with an empty card list, and why that set cannot be used
  to verify the quantity fix.
- **Published `$schema` URLs pointing at upstream** — filed as #23. Relevant to this PRD because
  `printStatus` is the first field this fork's schema will have that upstream's does not. Worth a
  decision before this PR merges, though it does not block it.
- **`--yugipedia-pages` silently importing nothing** — filed as #24. The verification plan below works
  around it by passing set page IDs; the flag itself is not fixed here.
- **A test framework.** Deferred to Wave 2, where the tracking issue's dependency graph already calls
  for a cross-table consistency test.
- **Extracting the row parsers into testable modules.** Deferred with the test framework.
- **Everything in Waves 2, 3 and 4**, including all rarity table work, image-selection determinism,
  and the warning histogram.
- **The multiple-images-per-printing schema question**, which is a separate decision track.
- **Parsing the additional custom columns** that the set list template supports after the quantity
  column.

## Further Notes

### Corrections to the source issues

Two claims in the audit did not survive verification, and the issues should be updated:

- **Issue #14's research blocker is resolved, and its alternative hypothesis is wrong.** The issue
  suggests a non-empty `print` value might mean rows have no print column. The template documentation
  says the opposite, and a single live page uses both forms — a non-empty `print` with three-column
  rows and an empty `print` with five-column rows — which only a presence test parses correctly.
- **The severity assessment is inverted.** The tracking issue leads with wrong quantities in four
  Structure Decks from the `print` defect. Those four sets are unaffected in published output: two are
  Rush Duel products that publish no cards at all, and two have no card with a quantity other than
  one, so the fallback is coincidentally correct. The defect that actually corrupts published
  quantities is the empty `qty` parameter, which emits no warnings and is not mentioned in the audit.
  The batch definition-of-done should assert against `Duel Royale Deck Set EX` rather than the sets it
  currently names.

### Scope corrections

- **Issue #4 is larger than its warning count.** The issue documents 15 warnings across 6 galleries.
  The wiki has **33 affected rows across 12 galleries**, of which only **14 warn**. The three-column
  rows are the ones that warn, because the shifted alt-info lands in the rarity position and fails to
  decipher. The 17 two-column rows silently fall back to the template's default rarity and publish a
  phantom card; the 2 single-column rows are silently discarded. `Starter Deck 2018 (OCG-JP)` and
  `Terminal World (OCG-JP)` are affected and appear nowhere in the warning audit.

### Wiki usage figures

Measured 2026-08-06 by fetching every transcluding page and parsing with the same library the importer
uses.

| Set list — 8,869 templates / 11,058 pages | | Set gallery — 9,955 templates / 6,812 pages | |
| --- | ---: | --- | ---: |
| `print` present | 2,738 | template-level `abbr=` | 96 |
| ↳ non-empty (correct today) | 2,599 | rows with `abbr::` | 33 |
| ↳ empty — the defect | 139 | ↳ across pages | 12 |
| `qty` present | 964 | ↳ also having template `abbr=` | 0 |
| ↳ empty — the silent defect | 13 | ↳ 3 columns (warns) | 14 |
| `print=` empty *and* `qty` present | 13 | ↳ 2 columns (silent) | 17 |
| `options=noabbr` | 406 | ↳ 1 column (silent) | 2 |
| rows using `abbr::` | 0 | | |

The 139 empty-`print` templates split into 13 that also have a `qty` column — which produce all 176
warnings — and 126 that do not, which are mis-columned but harmless, because nothing is read past the
rarity column when no quantity column exists.

### Environment

The package is not currently installed in the working environment; verification runs require an
editable install first. A stale branch exists whose content is behind `main` and whose commits are
already in `main` by another route; it is unrelated to this work and is left alone.

### Method

Template semantics were taken from Yugipedia's own documentation pages rather than inferred from
observed data. Usage figures come from fetching every page transcluding each template and parsing it
with the same library the importer uses; a second, independent pass using a hand-written regex agreed
to within one template, so the counts are not an artefact of either method.

Two measurement traps are worth recording, because both produced confident wrong answers before being
caught:

- **Yugipedia has no source-search extension.** `insource:` queries return zero hits for *everything*,
  including strings that certainly exist. A zero result from `insource:` is not evidence of absence.
  The claim that no set-list row uses `abbr::` therefore rests on fetching all 11,058 transcluding
  pages and testing for the substring directly, not on a search query.
- **Counting pages containing `{{Set list` overcounts templates.** Set pages carry
  `{{Set list tabs}}`, a different template whose name shares that prefix and which transcludes
  `Template:Set list`. Comparing that page count against a template count suggests a large parsing
  gap that does not exist.

Yugipedia also runs a MediaWiki old enough that the revisions API does not support content slots;
revision text must be read from the legacy field, and requesting slots yields a warning and no
content rather than an error.
