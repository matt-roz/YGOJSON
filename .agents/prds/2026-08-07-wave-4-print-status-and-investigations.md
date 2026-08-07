# Wave 4 — the print status vocabulary, and four investigations that were mis-scoped

**Base branch:** `feature/various-pipeline-fixes`

Implements issue #70 and issues #2, #11, #19, #5 and #68 from the
[2026-08-06 warning audit](https://github.com/matt-roz/YGOJSON/issues/20).

Every figure in this PRD is measured from run
[31142489208](https://github.com/matt-roz/YGOJSON/actions/runs/31142489208) — all 12 jobs green,
52 minutes, the first successful run ever to contain Waves 1, 2 and 3 — or from live Yugipedia on
2026-08-07, or from the database that run published. **No count in this document is inherited from
the audit.** Where a re-measurement contradicts an issue, the issue is wrong and this PRD says so;
that has now happened in all six.

Wave 4 differs from its predecessors in one way worth stating up front. Waves 1–3 were code waves
that each discovered their largest finding outside the issues they were implementing. This wave
carries **one code workstream and four investigations**, and the investigations were re-derived
during the design interview rather than at implementation time. The result is that four of the six
issues turned out to describe something other than what they are named after, and one of them —
#2 — is roughly ten times larger than its title.

---

## Problem Statement

**Ninety-six percent of a run's warnings are one field that we throw away.** Run 31142489208 emitted
6884 warnings. 6591 of them — 96% — are `Got strange print status`, a single bucket that did not
exist when the audit was written. Yugipedia's set lists carry a `print` column saying whether a
printing debuted in its set or was reprinted from an earlier one; our lookup table has exactly two
entries, `new` and `reprint`, and discards everything else. Twenty-three other spellings appear in
the corpus, covering 6591 rows.

Those 6591 printings publish with **no** `printStatus`. The schema documents an absent `printStatus`
as *"the source did not say"* — so the published database currently asserts something false about
6591 printings, in exactly the places where the wiki did say. `Speed Duel debut` alone accounts for
5113 of them.

This is the fourth instance of one defect shape in three waves — exact string equality against a
free-text wiki field — and **Wave 1 introduced it in the very slice that fixed the first instance.**

**The remaining warnings are small, and four of the five issues describing them are wrong about
what they are.** Re-measuring each against the current run and live Yugipedia:

- **#2 is not seventeen stale names.** All seventeen pages exist on Yugipedia today, none is a
  redirect, and sixteen carry `Category:All sets`. Two of the seventeen are published in our own
  database and the fixup still fails to find them. The other fifteen are **absent from the database
  entirely** — fifteen real products missing, not fifteen dead strings.
- **#11 cannot create a phantom card.** Its stated risk — *"a phantom card in the published database
  is much worse than a log line"* — is false. `get_card` resolves against an index of already-imported
  cards and cannot create one; zero cards named `name`, `rarity` or `number` exist across all 14,821
  published card files. It is twelve log lines from three rows.
- **#5's deferral premise is dead.** The audit scheduled it last because its bucket was *"about to
  shrink"* behind Waves 1–2. It went from 48 to 47. Its leading hypothesis is also falsified.
- **#19 is wrong about two of its three findings.** The ATK warning is a **YGOPRODeck** value, not a
  healed Yugipedia transient, and it costs nothing. `Charisma Token` is a real `Category:OCG cards`
  card, not a joke page.

**One warning still does not name its subject.** `Could not decipher rarity code for name in …:
rarity` prints the literal placeholders `name` and `rarity`, because three Yugipedia gallery stubs
contain the template's own parameter legend where card rows go. This is the last outstanding item of
the batch's definition of done.

---

## Solution

**Read the `print` column properly, and carry what the enum cannot.** A new `print_status` module
resolves the 23 measured spellings, all of which mean *reprint*, and publishes a verbatim
`printNote` alongside `printStatus` wherever the source said something more specific than the two
bare words. A value we have never seen publishes its note, no enum, and one warning — not 212.

**Guard the three gallery stubs** so the one warning that names no subject stops being emitted, using
a predicate that survives an edit to Yugipedia's documentation rather than an exact string match.

**Repair what #2 actually is**: one fixup key pointing at a disambiguation page, one live lookup
failure, and a diagnosis of why fifteen catalogued Yugipedia sets never reach the database.

**Publish the triage that #5, #19 and #68 asked for and nobody had done**, so the next person to pick
them up starts from measurements rather than from hypotheses that have now been wrong three waves
running.

---

## User Stories

### The print status vocabulary (#70)

1. As a consumer of the published database, I want a printing whose set list said `Speed Duel debut`
   to carry `printStatus: "reprint"`, so that I am not told the source was silent when it was not.
2. As a consumer, I want the exact phrase the set list used available on the printing, so that I can
   distinguish a plain reprint from one with new artwork without re-scraping Yugipedia.
3. As a consumer, I want `printStatus` to keep its existing two values and its existing meaning, so
   that code I wrote against today's schema keeps working unchanged.
4. As a consumer, I want the verbatim note to be absent when the source said only `new` or `reprint`,
   so that its presence tells me the enum lost information rather than being noise on every printing.
5. As a consumer, I want the note's presence rule to depend on what the wiki said and not on which
   spellings we happen to classify, so that the field does not change meaning under me each time our
   table grows.
6. As a consumer, I want a printing whose print value we cannot classify to still carry the note, so
   that I get the information even when we decline to interpret it.
7. As a maintainer, I want a value the table has never seen to publish no `printStatus` rather than a
   guess, so that the importer reports and omits instead of substituting, as it already does for
   rarities.
8. As a maintainer, I want a new print value to cost the log **one** line naming its page and row plus
   one summary entry, so that a single template-level default cannot recreate a 96% bucket.
9. As a maintainer, I want every occurrence counted even though only the first prints, so that a
   bucket that triples is still visible.
10. As a maintainer, I want an end-of-run summary listing each unresolved spelling and its count, so
    that adding a spelling to the table is a five-minute job rather than a log-grepping exercise.
11. As a maintainer, I want the resolver to reject at import time two spellings that collide, so that
    a table edit cannot silently make one value win over another.
12. As a maintainer, I want the resolution to be case-insensitive, so that `New artwork` and
    `New Artwork` are one entry rather than two.
13. As a maintainer, I want the print-status table and its reporting to live in a module I can import
    and exercise without a wiki or a database, so that its behaviour is checkable in seconds.
14. As a maintainer, I want the two-entry `PRINT_STATUS_STR_TO_ENUM` deleted rather than left beside
    its replacement, so that there is one place a spelling can be added.
15. As a maintainer, I want no build gate on unknown print values, so that one editor typing a new
    phrase cannot cost a day-long run.
16. As a maintainer, I want a row that inherited its value from the template-level `print=` default to
    carry that default in its note, because per Yugipedia's own documentation the default *is* that
    row's rendered value.
17. As a data consumer, I want printing UUIDs unchanged by this work, so that nothing I key on is
    reassigned.

### The gallery placeholder guard (#11)

18. As a maintainer, I want a gallery row consisting only of the template's parameter legend skipped,
    so that a stub page does not produce four warnings naming nothing.
19. As a maintainer, I want the guard to key on the legend vocabulary rather than one exact byte
    string, so that an edit to Yugipedia's documentation does not silently return the noise.
20. As a maintainer, I want the guard narrow enough that a real card row cannot match it, so that
    silencing a stub never silences a printing.
21. As a maintainer, I want the three affected stub pages reported upstream, so that the fix is
    permanent where the sets have actually released.
22. As a maintainer, I want the vandalism found on two of those three pages reported, so that it is
    someone's problem rather than nobody's.

### The manual fixups and the missing sets (#2)

23. As a maintainer, I want the `Premium Pack 2` fixup to name a real set page rather than a
    disambiguation page, so that it does something.
24. As a maintainer, I want a decision recorded about which of the two `Premium Pack 2` sets that
    fixup was meant for, so that the repair is not a guess.
25. As a maintainer, I want to know why `Collectible Tins 2006 Wave 2` fails to resolve when it is
    published with exactly the name the fixup uses, because that failure mode can affect any fixup.
26. As a maintainer, I want the same name's sealed-product failure explained alongside it, since it
    fails in both paths.
27. As a maintainer, I want to know why fifteen sets catalogued in `Category:All sets` never reach the
    database, because that is fifteen missing products and not a manual-data problem at all.
28. As a maintainer, I want the fifteen-set finding filed as its own issue with the diagnosis attached,
    so that the fix is scoped from evidence rather than re-derived a second time.
29. As a maintainer, I want unresolved fixups to keep warning rather than failing the run, because the
    stage runs in the last job and failing there discards a completed day's work at the publish step.
30. As a maintainer, I want the sealed-product fixup's early `return` on an unknown set recorded, since
    it abandons that product file's entire fixup rather than skipping one pack.

### The gallery/locale mismatch triage (#5)

31. As a maintainer, I want the 47 rows split into their real shapes rather than the two the issue
    guessed, so that each is worked as the different problem it is.
32. As a maintainer, I want to know that Shape A's locales parsed correctly — 88 to 291 printings each
    — so that nobody spends a day looking for a parser bug that is not there.
33. As a maintainer, I want the `gallery but no list for locale` cross-reference recorded as falsified,
    so that the hypothesis is not tried a second time.
34. As a maintainer, I want the twelve `parallel` rows recognised as one systematic rule rather than
    twelve incidents, so that half the bucket has a single fix.
35. As a maintainer, I want that rule confirmed against the actual gallery and list pages before any
    fallback is widened, because a too-permissive fallback attaches images to the wrong printing
    silently.
36. As a maintainer, I want the remaining rows filed as one ticket with the full list attached, so that
    a Yugipedia editing session can work them without re-deriving anything.

### The individual bad values (#19)

37. As a maintainer, I want `password = None` fixed on Yugipedia rather than normalised in the
    importer, so that the next editor mistake still surfaces.
38. As a maintainer, I want it recorded that the importer already handles that value correctly, so that
    nobody writes code for it.
39. As a maintainer, I want the ATK warning correctly attributed to YGOPRODeck, so that nobody edits
    Yugipedia expecting it to stop.
40. As a maintainer, I want it recorded that Yugipedia's value already wins and the card publishes
    correctly, so that the warning is understood as cosmetic.
41. As a maintainer, I want `Charisma Token` recognised as a real OCG card rather than a joke page, so
    that we do not exclude a legitimate card for the third time in two waves.
42. As a maintainer, I want the seven cards in Yugipedia's odd-attribute category ticketed against the
    Rush Duel import issue, so that the decision is made once when it can actually be acted on.

### The unparsed product pages (#68)

43. As a maintainer, I want to know whether the cards on the eight banner-carrying pages are published
    under any set today, because that is the question the bucket cannot answer.
44. As a maintainer, I want the outcome to be either an upstream conversion request or a ticket for
    reading `{{Set list transclusion}}`, decided by that answer rather than in advance.
45. As a maintainer, I want the warning left routed to the quiet logger, because eight static pages do
    not need sixty-one printed lines a run.

### Verification

46. As a maintainer, I want the print-status table checked offline in the `lint` job, so that a
    regression in it is caught before a run starts.
47. As a maintainer, I want that check to make no network calls, so that it can never fail because
    Yugipedia changed.
48. As a maintainer, I want a narrow real run over a Speed Duel set and a `print=Reprint` set, so that
    the parse is verified against real wikitext and not only against the table.
49. As a maintainer, I want the published output diffed against the previous release, so that a change
    in printing counts or UUID assignment is visible before it ships.

---

## Implementation Decisions

### `printStatus` and `printNote` are siblings, not a nested object

`printStatus` keeps its two values, its meaning and its position. A **new optional string property**
carries the source phrase. Nesting the two into one object would break every consumer reading
`printStatus == "reprint"` today, and the established rule for this schema is that changes are
additive and optional.

The precedent being followed is Wave 2's image variants, where `variants[].code` is the required
verbatim source string and `variants[].variant` is the optional classification. The one deliberate
divergence: `variants[].code` is always present because variants are rare, whereas print values are
not. `printNote` is therefore present **only when the source string is not literally `new` or
`reprint`** — about 6,591 printings rather than roughly 65,000. That criterion is a property of the
source, not of our table, so it stays stable as the table grows.

Aggregate output already exceeds GitHub's file size limit and its push step is `continue-on-error`,
so a redundant string on every print-bearing printing is charged against a budget that is already
overdrawn, and a green run would not report that it failed to land.

### The vocabulary is ours, permanently

`Template:Set list/doc` documents `print` as prose — *"Used to indicate if a card was introduced in a
set or reprinted from an earlier set"* — with no enumerated values.
`Module:Card collection/modules/Set list` is a two-line delegation to a generic parser and validates
nothing; its own test fixtures use `Reprint` and `Speed Duel Debut` side by side. **Unlike rarity,
there is no upstream list to sync against.** Any classification is ours and will always have a tail.

### All 23 measured spellings resolve to `reprint`

Measured across every `Got strange print status` line of run 31142489208: **6591 rows, 23 distinct
spellings, 22 after case folding.**

| rows | pages | value | | rows | pages | value |
|---:|---:|---|---|---:|---:|---|
| 5113 | 53 | `Speed Duel debut` | | 6 | 2 | `International artwork` |
| 894 | 181 | `New artwork` | | 5 | 2 | `Reprint (New Art)` |
| 160 | 18 | `European debut` | | 5 | 1 | `Japanese artwork` |
| 83 | 4 | `New Artwork` | | 4 | 2 | `Reprint (European Debut)` |
| 82 | 8 | `Reprint (renamed)` | | 3 | 1 | `New artwork (renamed)` |
| 70 | 8 | `New extension` | | 2 | 1 | `Reprint (NA Debut)` |
| 66 | 6 | `New art` | | 2 | 1 | `North American debut` |
| 65 | 44 | `Reprint (functional errata)` | | 1 | 1 | `Reprint (new artwork)` |
| 14 | 13 | `Functional errata` | | 1 | 1 | `TCG legal debut` |
| 6 | 4 | `Functional erratum` | | 1 | 1 | `Reprint (EU Debut)` |
| 6 | 1 | `European & Oceanian debut` | | 1 | 1 | `Oceanian debut` |
| | | | | 1 | 1 | `European English debut` |

Read against the enum's own definition, **none of the 23 means "first printing anywhere."** Every
`… debut` describes a card that existed elsewhere first; every `New art*` and `… artwork` is a
reprint with a changed image; `Functional errata`/`erratum` and every `Reprint (…)` are explicit. The
wiki settles the ambiguous ones itself: `Reprint (European Debut)` and `Reprint (New Art)` exist,
which makes their bare siblings flavours of reprint.

The semantics were confirmed against real pages rather than inferred.
`Speed Duel: Battle City Box (TCG-EN)` carries `print=Speed Duel debut` as the **template-level
default** on all eleven `{{Set list}}` calls, with individual rows overriding to `New` (16, the
Speed Duel-exclusive Skill cards) and `Reprint` (16). `Brothers of Legend`,
`Battles of Legend: Glorious Gallery` and `Duelist Pack: Duelists of Brilliance` invert it: default
`print=Reprint`, with rows overriding to `New artwork` and `New extension` — the editor deliberately
distinguishing those from a plain reprint. That distinction is precisely what `printNote` preserves
and what the enum cannot.

**Consequence:** the enum half of this work is mechanical, and the note is the payload.

### Two claims in #70 do not survive

- **The `_normalize` remedy is already implemented.** The parse site already does
  `.strip().lower()` before lookup, so `New artwork` and `New Artwork` appearing as separate rows in
  #70's table is an artifact of the warning text printing the un-lowered string. They already
  collapse. Borrowing `rarity.py`'s `_normalize` would additionally strip punctuation, turning
  `Reprint (renamed)` into `reprintrenamed` — still not `reprint` — and would not touch
  `New art` versus `New artwork`, which is a real spelling difference.
- **The tail is not open-ended.** 23 values, not "a long tail". And **78% of the entire bucket is one
  template-level default on ~53 Speed Duel pages**, inherited by rows that said nothing — which is
  why a single new `print=` parameter is worth 212 log lines and why the warning must dedupe.

### A new `print_status` module

A top-level module mirroring `rarity.py`, holding the table, the resolution, the note policy, the
occurrence counting and the summary behind four functions:

- resolve a raw string to a `PrintStatus` or nothing — pure, case-insensitive
- produce the note for a raw string, or nothing when it is literally `new`/`reprint` — pure
- report an unresolved value: count it always, warn on the **first** sighting of that spelling only,
  naming its page and row
- log the end-of-run summary, in the shape `rarity.py` already uses

Resolution stays separate from reporting because `rarity.py` separates them and because it keeps the
pure half exercisable without capturing logs. An import-time check refuses to import if two spellings
collide, mirroring `rarity.py`'s existing guard. The summary is called from the same place the rarity
summary is called and re-exported from the package root alongside it.

The existing two-entry table in the Yugipedia importer is **deleted**, not left beside its
replacement.

### The warning is not routed to the quiet logger

`EXPECTED_CONDITIONS` forbids it in its own docstring: *"Anything that could be a real set or a real
card row belongs in the printed log."* A dropped print status is a real card row losing real data.

### There is no build gate on unknown print values

`test/validate_rarity_coverage.py` works because Yugipedia publishes a Lua module enumerating every
rarity — a closed list diffable in one request. `print` has no equivalent, so a coverage gate would
have to fetch every transcluding page and then assert that no editor had typed a new phrase into a
free-text column. That is a change detector, not a coverage property, and it would sit in `lint`,
which gates the entire sequential chain. Wave 2 put the rarity check there reasoning that *"one new
wiki rarity must not cost the whole night"*; a print check there would cost the whole night by
design. The 24th value costs one line in a 22-row table instead.

### Printing identity is untouched

`PrintingLocator` is `(card, rarity, code)` and UUIDs are restored from the previous run keyed on that
same locator. `print_status` is not part of it and neither is `print_note`, so **no printing UUID is
reassigned by this work** — relevant given #72 and #46.

### The gallery guard keys on legend vocabulary

The stub rows are byte-identical across all three pages today, so an exact string match would work.
It is rejected anyway: exact string equality against free-text wiki content is the defect shape #70
documents as having recurred four times in three waves, and writing instance five into the wave whose
headline item is instance four is indefensible. One edit to the documentation line and the guard
stops matching with no signal but returning noise.

Instead a row is skipped when **every one of its columns is a template-legend word** — the closed set
from `Template:Set list/doc`. A false positive requires a real card literally named `name`, at card
number `number`, at rarity `rarity`, in one row.

Traced behaviour confirming the guard is all that is needed: the placeholder row yields
`code="number"`, `name="name"`, `rarity="rarity"`, fails rarity resolution, falls back to the
gallery's truthy default rarity, survives to filename building, and dies at the card page lookup.
Four warnings, no object created.

### #2 is three different problems

- **`Premium Pack 2`** — the fixup names a **disambiguation page**. The real set pages are
  `Premium Pack 2 (TCG)` (id 48956) and `Premium Pack 2 (Japanese)` (id 48989), and both publish
  under the English name `Premium Pack 2`. The sole genuine stale key, and which set it meant must be
  decided rather than guessed.
- **`Collectible Tins 2006 Wave 2`** — publishes with `externalIDs.yugipedia.name` exactly equal to
  the fixup key (id 497848). The lookup should succeed and does not. Unexplained; it fails in both the
  set path and the sealed-product path. Because the set index is keyed on the Yugipedia name recorded
  at import and the fixup falls back no further when only `yugipediaName` is given, this failure mode
  can affect any fixup.
- **The other 15** — absent from the database entirely, though all sit in `Category:All sets`, none is
  a redirect, and **none appears in either printed set-rejection bucket** (zero overlap with the 36
  `set without set navigation table` pages). The cause is unknown and the diagnosis is this wave's
  deliverable; the fix is its own issue.

Unresolved fixups keep warning. The fixup stage runs in `post-yugipedia`, the last job, so failing
there discards a completed run at the publish step, and after this wave any surviving
`Unknown set to fixup` line is new by construction.

Recorded alongside: the sealed-product fixup **`return`s out of the whole file** on an unknown set
rather than skipping one pack, which is #32's neighbour and is what `Collectible Tins 2006 Wave 2`
currently triggers.

### #5's triage

| | rows | what it is |
|---|---:|---|
| **A1** | ~21 | The locale parsed fine — 88 to 291 printings — and the gallery names one or two cards the set list does not. `Ignition Assault` [kr] 102 printings, gallery adds `Ghostrick Fairy`; `Duelist Alliance` [kr] 88, gallery adds 3. **Wiki disagreement, not our bug.** |
| **A2** | 2 | The locale publishes zero printings — both `… Sneak Peek Participation Card` [sp] sets. |
| **B** | 24 | Rarity mismatches. **12 are one rule**: `parallel → ['common', 'commonparallel']`, all in `World Ranking Promos: Series 5` and `Series 6`. The other 12 are one-offs. |

The issue's leading hypothesis is falsified: the six `gallery but no list for locale` warnings name
`Shonen Jump promotional cards`, `Dark Duel Stories`, `Duelin' Monsters Giveaway`, `WC2004`,
`Demo Pack` and `Summoned Skull Sample` — **none of which appears in Shape A.**

Only the twelve-row rule is fixed in this wave, and only after opening the Series 5 gallery and list
side by side, because `Parallel Rare` and `Common Parallel Rare` are genuinely different rarities.

### #19 needs no code

- `password = None` is still on the Ra page verbatim. The card publishes with `password` absent, which
  is already correct: the importer omits and warns. **Wiki fix only**; normalising placeholder values
  in the importer is explicitly rejected, because being liberal hides the next editor mistake.
- `Ilios the Black Sun Dragon` reads `atk = 1500` on Yugipedia and publishes `atk=1500`. The warning
  comes from the **YGOPRODeck** importer, and Yugipedia's value already wins. **Cosmetic**, recurring,
  from a source we cannot edit.
- `Charisma Token` is in `Category:OCG cards`, `Monster Tokens` and Yugipedia's own
  `Cards with odd Attributes` / `Cards with odd Types`. It is a real card and it publishes with
  `attribute` and `type` both dropped — one card of real, small data loss.
  `Category:Cards with odd Attributes` has exactly seven members, and their names
  (`Charisma`, `The★Luke Division Manager`, `Masa on the Mic`) are Rush Duel vocabulary, which likely
  puts most of them behind #21. **Ticketed against #21, not modelled here** — a second additive enum
  change bought for seven cards that may not import is motion, not progress.

---

## Testing Decisions

**What makes a good test here.** This repository has no test framework, no test runner and no type
checker, and CLAUDE.md is explicit that adding one is a separate decision rather than a side quest.
`test/` holds four standalone scripts. A good test in this codebase is therefore an **offline,
dependency-free script asserting external behaviour** — what a function returns for a given input —
never how it computes it, and never requiring generated data or network access unless that is the
whole point of the script.

**The module under test is `print_status`, and it is the only one.** It is the one deep module this
wave produces: four functions, no I/O, no database, no wiki. Everything else in the wave is either a
predicate inside a 3.6k-line importer, a data edit, or an investigation.

**A new standalone script asserts:**

- every one of the 23 measured spellings resolves to `reprint`
- resolution is case-insensitive, so the two `New artwork` spellings are one entry
- `new` and `reprint` still resolve to their existing members
- a note is produced exactly when the raw string is not literally `new` or `reprint`
- an unseen value resolves to nothing, still produces a note, and is counted
- an unseen value warns once per distinct spelling however many times it occurs
- no two table spellings collide

**It runs in the `lint` job and makes no network calls.** That is what distinguishes it from the
wiki-fetching coverage gate rejected above: it can never fail because Yugipedia changed, only because
our table regressed.

**Prior art.** `test/validate_rarity_coverage.py` for the shape of a vocabulary check invoked from
`lint`; `rarity.py`'s import-time ambiguity guard for the collision check, which is reproduced rather
than shared; `test/validate_data.py` for a script that asserts and exits non-zero.

**Beyond the script**, verification is a narrow real run — `--no-ygoprodeck --no-yamlyugi --no-manual
--no-aggregates` over `Speed Duel: Battle City Box` (template default, 244 rows) and
`Battles of Legend: Glorious Gallery` (row-level overrides on a `Reprint` default) — reading the
produced JSON directly, followed by `test/validate_data.py` over that output and
`test/report_output_diff.py` against the previous release.

**Nothing else is tested**, and the reason is recorded rather than assumed: the gallery guard is three
lines inside a deeply nested loop with no seam, and extracting one to test it would be a refactor of
untouched code. It is verified by re-running the three stub pages.

---

## Out of Scope

- **Fixing the fifteen missing sets.** This wave diagnoses why they never import and files the finding.
  Committing to the fix before the cause is known is committing to an unknown.
- **Modelling odd Attributes and Types.** Ticketed against #21.
- **Normalising placeholder field values** (`None`, `N/A`, `-`, `?`) in the card parser. Explicitly
  rejected: it would hide the next editor mistake.
- **The ~35 individual gallery/list disagreements in #5.** Filed as one ticket with the list attached;
  each needs a human to decide whether the gallery or the list is right, which is a Yugipedia editing
  session.
- **Widening `FALLBACK_RARITIES` beyond the one confirmed rule.**
- **Adding a test framework.** CLAUDE.md flags this as its own decision; the standalone script above
  deliberately avoids making it.
- **Un-routing `Found set without set table` from the quiet logger.** #68's own "not to do".
- **The unissued histogram rows**, which become Wave 5: `set without set navigation table` ×36,
  `series without series table` ×2 (`Series` and `Archetype`, both concept pages),
  `Master Duel set without setlists` ×2, `Unknown locale in Spell Ruler: na (magic ruler)` ×1,
  `Unknown card in DL set Genesis Maximum: Thunder Spark` ×1, and
  `19302 image lookups did not resolve — 111 file pages that do not exist` ×8. Wave 4 files tickets
  for these from what the histogram already shows; it does not work them.

---

## Further Notes

**The local `data/` directory is contaminated.** It is a downloaded baseline (`increment: 2351`) with
exactly two sets overwritten by a local narrow run — `Structure Deck R: Lost Sanctuary` and
`Structure Deck: Egyptian Gods' Advent: Slifer the Sky Dragon & Obelisk the Tormentor`, the two
Wave 1 used for verification. They are the only two of 3,376 set files carrying `printStatus`.
Anything diffing this wave's output against that directory will see two sets that are not from the
baseline.

**Yugipedia has no CirrusSearch**, so `insource:` queries return zero for everything, including
strings that certainly exist. A zero from `insource:` is not evidence of absence. Corpus figures come
from fetching pages and testing directly; the importer batches 50 pages per XML export, so a full
corpus fetch takes about six minutes rather than the hours it looks like it should.

**Two of the three gallery stub pages are vandalised** — `Alliance Insight (OCG-AE)` carries a stray
`ṃ` and `mimkmkkp;`, `Deck-Build Pack: Tactical Masters (OCG-SC)` has `黑色花园` appended. Neither
affects parsing; both are worth reverting while the stubs are being reported.

**The pattern this batch keeps finding held again, six times out of six.** #70's remedy was already
implemented and its tail was a quarter of the claimed size; #11's phantom card cannot exist; #2's
title describes one of its seventeen cases; #5's bucket did not shrink and its leading hypothesis has
zero overlap with its data; #19 misattributed one finding to the wrong source and another to a joke
page that is a real OCG card; and #68 was the only one that survived intact. Three waves in, the rule
is settled and it is worth restating in the wave that will be read after this one: **an audited count
is a floor and an audited explanation is a hypothesis.** Every figure in this document was
re-measured, and the ones that came from a design interview rather than from a running slice deserve
the same suspicion when the next wave reads them.
