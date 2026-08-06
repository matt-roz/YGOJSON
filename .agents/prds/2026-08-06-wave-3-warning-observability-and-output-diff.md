# Wave 3 — a readable warning stream and a run-over-run output diff

**Base branch:** `feature/various-pipeline-fixes`

Implements issues #18, #7, #8, #15 and #16 from the
[2026-08-06 warning audit](https://github.com/matt-roz/YGOJSON/issues/20), and adds one workstream
that is in no issue: a report on what a run changed in published output. This PRD does not replace
those issues; it records what a design interview settled that they left open, and corrects several
of their claims that did not survive being measured.

Every count taken from run
[30985840603](https://github.com/matt-roz/YGOJSON/actions/runs/30985840603) is **stale** and is
marked as such. Waves 1 and 2 changed the parsers those counts describe, and until this PRD was
written no pipeline run had ever executed either wave. That is now fixed: `main` was fast-forwarded
to the integration branch and run
[31120463581](https://github.com/matt-roz/YGOJSON/actions/runs/31120463581) was dispatched against
it. Slices re-derive their numbers from that run.

## Problem Statement

**Nobody can read a run.** The last audited run emitted 2137 warning lines across ten jobs, with no
summary, no grouping, and nothing that distinguishes a line that has appeared every run for two years
from one that appeared for the first time last night. Finding out what a green build did requires
downloading roughly a megabyte of logs from ten separate jobs and grouping them by hand. That is how
two active data corruptions shipped repeatedly in successful builds, and it is why the audit
happened at all.

**The warning stream reports only the code paths that chose to warn, and the biggest defects chose
not to.** This is the finding both preceding waves ended on, and it is the reason this wave exists in
the shape it does. The three largest problems in the entire audit produced zero warnings between
them:

- An empty quantity parameter published `Duel Royale Deck Set EX (OCG-JP)` with 103 printings all at
  quantity 1, where thirteen should have been 2 or 3. No warning. Meanwhile the *sibling* defect,
  which produced 176 warnings, corrupted nothing at all.
- The serializer reshuffled card-info keys in all 3,376 set files on every single run. Two control
  runs on unpatched code differed in 1,415 files despite re-importing three sets. No warning.
- Old-printing deletion ran before any card lookup had answered, so every production run deleted and
  rebuilt whole sets with **fresh printing UUIDs** — the stable public handle consumers key on.
  `Vortex of Magic` had 35 of 45 printings replaced; `Age of Discovery` 40 of 40. No warning.

A histogram of warnings would not have surfaced one of them. Something has to watch the output.

**Sixteen real cards are dropped, and until this interview nobody could say which.** The card parser
rejects any card type it does not recognise and returns without importing. The warning it emits names
the offending value but not the page, so the log records that sixteen cards vanished and nothing more.
They are now enumerated, and the issue's hedge — that some might be joke or unofficial pages that
*should* be excluded — is wrong. All sixteen are legitimate printed cards with real set codes and
rarities: `Token (side:Unity)` is MP24-EN051 in *25th Anniversary Tin: Dueling Mirrors* at Prismatic
Secret Rare; `Emperor's Key` is SD42-JPTKN and SD42-KRTKN in *Structure Deck: Overlay Universe* at
Ultra Rare. Their printings are missing from those sets too.

**Roughly a hundred lines per run describe the parser working correctly.** Sixty-one pages are
reported as sets without a set table; they are series hub and index pages that correctly produce
nothing. Forty-four gallery lines are reported as strange; they are rule inserts, FAQ cards and
deck-construction guides that are correctly not treated as cards. Both buckets are pure noise, and
both are large enough to hide the small number of real cases inside them — which is exactly why
neither can simply be deleted.

**The warning stream is emitted through a deprecated function at 72 call sites.** It costs nothing
today; Python does not even surface the deprecation, because its default filter only reports
deprecations raised in `__main__` and every one of these lives in an importer. When the alias is
removed, every one becomes a crash at the moment the importer tries to warn about anything, in
production, on a Python upgrade.

**Two end-of-run summaries already exist, in two different shapes, and neither can count a whole
run.** Wave 1 added counters for unresolved image lookups; Wave 2 added a counter for unresolved
rarity spellings. One lives on an importer object and reports totals inline; the other is a
module-level counter with a reporting funnel and a summary function called from the entry point.
Neither knows the other exists, and a third bespoke counter would be the third pattern.

Worse, **both are per-process, and a CI run is ten processes.** The work is split across eight
partition jobs plus a pre- and post-stage, so each summary prints ten times per run, each covering a
fraction of the corpus, and nothing sums them. The partition assignment is an unseeded shuffle, so
which pages a given job sees is random each run — meaning a per-job figure cannot be compared to the
same job's figure from last run. Wave 1's counter describes itself as "a tripwire for watching the
figure across runs". Today there is no figure to watch.

## Solution

One number per warning kind per run, every warning naming its subject, the noise counted but not
printed, the sixteen cards back, and a report at the end of each run saying what actually changed in
the published data.

From a maintainer's perspective:

- Reading a run means reading one table of roughly fifteen rows in the run summary, sorted by
  volume, each row naming the code that produced it and showing an example. The raw logs remain, but
  nobody has to start there.
- That table covers the **whole run** — all ten jobs summed — and it is produced even when a job in
  the middle of the chain fails, which is when it is most worth reading.
- Every warning that prints names the page, set or card it is about. A warning that cannot be acted
  on does not print.
- Noise is *counted, not deleted*. The bucket for correctly-rejected hub pages still appears in the
  histogram with its count; it just stops printing a line per occurrence. If it triples, that is
  visible. This is what makes downgrading safe, and it is what both noise issues asked for without
  having a mechanism for it.
- Sixteen cards that Yugipedia describes as usable as either a Token or a Counter are imported as
  tokens, consistently with the five plain Counter cards that already are, and their printings appear
  in their sets.
- At the end of a run, a report states how many published files changed, broken down by object type,
  how many printings were gained or lost, how many printing UUIDs were reassigned — and how many
  pages Yugipedia's own changelog said had changed. The pair is the signal: three sets re-imported
  and 1,415 files different is the shape of a silent defect, and neither number alone looks wrong.

## User Stories

1. As a maintainer, I want a single histogram of warnings at the end of a run, so that I can tell what a run did without downloading ten job logs.
2. As a maintainer, I want that histogram summed across every job in the run, so that I read one number per warning kind rather than ten partial ones.
3. As a maintainer, I want each histogram row to identify the code that produced it, so that I can go straight to the emitting site instead of grepping for the message.
4. As a maintainer, I want each histogram row to carry an example message, so that I can tell what the bucket is about without reading the source.
5. As a maintainer, I want the histogram sorted by volume, so that the largest problems are the first thing I read.
6. As a maintainer, I want the histogram rendered into the workflow run summary, so that it is visible from the run page without opening a job.
7. As a maintainer, I want the histogram produced even when a job in the middle of the chain fails, so that a broken run is the one I can diagnose rather than the one I cannot.
8. As a maintainer, I want each job to keep printing its own histogram to its own log, so that a local narrow run gives me the same view without any CI involvement.
9. As a maintainer, I want the per-job counts persisted as machine-readable data, so that summing them does not depend on parsing log text.
10. As a maintainer, I want the cross-job counts carried by a channel that fails loudly, so that a summary is never quietly short by one job's worth of warnings.
11. As a maintainer, I want the two existing bespoke summaries left working, so that per-value breakdowns — which spelling, which cause — are not lost to a per-call-site view that cannot express them.
12. As a maintainer, I want warnings that describe expected conditions to be counted without printing, so that the raw log stops being 90% noise while the bucket stays watchable.
13. As a maintainer, I want a sudden jump in a suppressed bucket to be visible in the histogram, so that suppressing noise never means losing the signal inside it.
14. As a maintainer, I want the pages we correctly reject as not-a-set to stop printing a line each, so that the log stops implying something is wrong when nothing is.
15. As a maintainer, I want non-card gallery images to stop printing a line each, so that rule inserts and FAQ cards stop looking like parse failures.
16. As a maintainer, I want suppression implemented without lowering the root log level, so that turning it on does not start dumping every HTTP response body into the log.
17. As a consumer, I want the sixteen dual-purpose Token/Counter cards present in the database, so that cards I own and can find on the wiki are not simply absent.
18. As a consumer, I want those cards' printings present in their sets, so that *Structure Deck: Overlay Universe* and *25th Anniversary Tin: Dueling Mirrors* list what is actually in them.
19. As a consumer, I want those cards typed consistently with the plain Counter cards already published, so that two cards with the same lore do not carry different types.
20. As a maintainer, I want compound card-type values parsed by splitting and normalising rather than by exact string equality, so that a wiki editor's stray double space does not drop a card.
21. As a maintainer, I want a card that is still rejected to name its page in the warning, so that the next unrecognised value is diagnosable on the run it appears.
22. As a maintainer, I want the card-type resolution to live as one small function with an explicit vocabulary, so that it matches how rarities are already handled and can later be coverage-checked the same way.
23. As a maintainer, I want the deprecated logging call replaced everywhere, so that a future Python release cannot turn every warning site into a crash.
24. As a maintainer, I want a guard that prevents the deprecated call from being reintroduced, so that the rename does not quietly undo itself in the next slice.
25. As a maintainer, I want that guard to run in the existing lint job, so that it is enforced by the same gate everything else is.
26. As a maintainer, I want the guard implemented without adopting a new linter, so that a mechanical rename does not settle an explicitly-undecided tooling question as a side effect.
27. As a maintainer, I want a report at the end of a run of how many published files changed, so that a run that quietly rewrote the database is distinguishable from one that did not.
28. As a maintainer, I want that report broken down by object type, so that "every set file changed" and "three card files changed" do not look alike.
29. As a maintainer, I want printings gained and lost counted, so that a parser change that silently drops printings is visible on the run it lands.
30. As a maintainer, I want printing UUID reassignments counted, so that the class of defect that churns consumers' stable handles cannot happen unnoticed again.
31. As a maintainer, I want the number of changed output files reported next to the number of pages the wiki changelog reported, so that the ratio between them is the alarm rather than either number alone.
32. As a maintainer, I want that comparison made against the artifact consumers actually download, so that the report describes what shipped rather than what the code believed it did.
33. As a maintainer, I want the run identified in the published metadata, so that a baseline can be tied to the run that produced it.
34. As a maintainer, I want the increment field to mean what it says, so that a figure documented as "increments once per update" stops advancing ten times per run.
35. As a maintainer, I want nothing in this wave able to fail the build, so that a summary can never block the database from publishing.
36. As a maintainer, I want anything worth flagging surfaced as a workflow annotation, so that attention is drawn without a red run implying the data is bad.
37. As a maintainer, I want the design to leave the existing rarity coverage check as the model for catching new wiki vocabulary, so that we do not build a weaker warning-based proxy for a check that already works.
38. As a maintainer, I want every stale figure in the source issues explicitly marked as stale, so that nobody calibrates a new instrument against a measurement taken before two waves of parser changes.
39. As a maintainer, I want each slice to re-derive its own numbers from a real run, so that the wave's claims are measurements rather than inherited assertions.
40. As a maintainer, I want the wave's findings that contradict the audit recorded on the issues, so that the tracking issue stops propagating claims that have been disproven.

## Implementation Decisions

### Scope

Five issues from the audit — #18, #7, #8, #15, #16 — plus one workstream present in no issue: a
run-over-run output diff report. The sixth exists because both preceding waves ended by finding that
the defect doing the most damage emitted no warnings at all, and a wave devoted entirely to improving
the warning channel would optimise the one place that has now twice been shown to under-report.

### How a warning acquires its identity

A single logging handler buckets records by the source location that emitted them, holding a count
and a first-seen example message per bucket. Nothing changes at the 82 warning call sites, coverage
is complete on the first day rather than complete for whichever sites were migrated, and each
histogram row is directly navigable to the code that produced it.

Rejected: rewriting all 82 sites to report through an explicit funnel with stable codes. It is the
better identity in the abstract but costs 82 edits to buy something the handler gets for free, and
the capability that would justify stable codes — a checked-in baseline — is explicitly out of scope
(below). Also rejected: stripping variable parts out of the emitted message text to infer a template.
Messages are interpolated before they reach the logger, so this reverse-engineers structure the
handler already has exactly.

The two existing summaries stay as they are. A source-location key cannot express *which rarity
spelling* or *which cause of image miss*, and those breakdowns are the whole value of those two
counters. The new mechanism is a net under everything, not a replacement for them.

### Aggregation across the run

Each process writes its buckets as machine-readable data at the end of its run. Each job uploads that
as a workflow artifact. A final job — conditioned to run regardless of whether the chain succeeded —
downloads all of them, merges them, and renders the summed histogram into the run summary.

Artifacts rather than the shared cache: the cache steps are all failure-tolerant by design, so a
cache that fails to save produces a green job that hands the next one stale state. A histogram that
is silently short by one job's warnings is worse than none, because it presents as a measurement.
Building this wave's instrument on that channel would reproduce the audit's own headline finding
inside the tooling meant to prevent it.

A separate always-running job rather than the existing final job: a failure mid-chain abandons the
final job entirely, so aggregation living there is lost precisely on the runs worth reading.

Each process also keeps printing its own histogram to its own log, so a local narrow run gets the
same view with no CI involved.

### Suppressing noise without losing it

A dedicated logger, configured not to propagate and with the bucketing handler attached, receives the
warnings that describe expected conditions. They are counted into the histogram and never printed.

This is what makes downgrading safe. Both noise issues open with the same objection — a bucket that
is 90% noise is still 10% signal, and silencing a real set is worse than the noise. A counted-but-
unprinted bucket answers it: if the count triples, the histogram shows it even though nothing printed.

It must be a dedicated logger rather than simply lowering the root level. Two places in the Yugipedia
importer test the root logger's effective level and, when it is at debug, log the entire body of every
HTTP response. Lowering the root level to make debug records countable would turn a day-long run's log
into gigabytes.

This is a deliberate, narrow reversal of the decision to avoid named loggers (below): one logger for
one purpose, not a per-module refactor.

### The two noise buckets

Neither predicate changes. Both are already correct, and the fixes their issues propose do not work:

- Filtering by namespace catches exactly one page of sixty-one. The portal page cited in the issue is
  the only non-article page in the bucket; everything else sampled is a normal article.
- All twelve pages the issue lists as "plausibly real products we are failing to parse" are hub
  pages. They announce it structurally — archetype or miscellaneous infoboxes, pack navigation
  templates, and categories naming the product *line* — and none carries a set infobox. There is
  nothing to fix, only something to stop printing.
- Refining the gallery-line predicate does not separate cleanly. The tripping lines sampled carry
  zero wikilinks, but the issue's own examples include one-wikilink non-cards, so "one or two links
  means it was meant to be a card row" would keep warning on genuine rule inserts.

Both are routed to the quiet logger instead.

### Compound card types

Card-type resolution becomes one small function with an explicit vocabulary, mirroring how rarity
resolution already works: split the raw value on its separator, normalise case, spacing and
punctuation, and resolve. A value containing *counter* takes the existing path that already maps a
plain *Counter* to token.

Mapping to token is not a new modelling decision. The importer already maps a plain `Counter` to
token, and five cards publish that way today. The sixteen are dropped only because the test is exact
equality against a free-text wiki field.

Rejected: adding a distinct card type for counters. It is a public schema change that would also
reclassify five already-published cards, to settle a modelling question nobody has raised. If it is
worth doing it is a decision track of its own, as the multi-image question was in Wave 2.

The warning for a value that is still unrecognised gains the page title. The page title is available
at that point and is already used for the same purpose a few lines above.

This is the third instance of one defect shape in three waves: exact string equality against a
free-text wiki field. Wave 1 was parameter presence versus truthiness; Wave 2 was exact-match rarity
lookup, fixed with a normalisation fallback; this is card type. Naming the pattern is part of the
deliverable.

### The deprecated logging call

A mechanical rename of all 72 sites, landing in the same commit as a guard that prevents
reintroduction. The guard uses the pattern-matching hook language that the existing pre-commit
framework already provides, so it adds no tool and no dependency, and it runs inside the lint job
that already gates the chain.

Rejected: adopting a general-purpose linter to enforce it. The absence of one beyond the formatters
is an explicitly open decision in this repository, and settling it sideways inside a chore ticket is
the wrong way to make it.

Rejected: introducing per-module named loggers alongside the rename. The stated benefit — filtering
importer warnings independently — is already delivered by the handler, which carries each record's
source location. The issue itself asks for this to be decided separately, and folding it in would
turn a mechanical diff into one with behaviour in it.

This lands before the histogram work, so every later slice is written against the correct call from
the start.

### The output diff report

A reporter that indexes two directories of published individual files and compares them: files added,
removed and modified by object type; printings gained and lost; printing UUIDs reassigned. It runs in
the final job, where complete output exists — unlike the histogram, a half-imported run has nothing
meaningful to diff, and every difference would be noise.

The baseline is the previously published release archive, re-fetched at report time. That is the
artifact consumers actually receive, and the mechanism to fetch it already exists in the package.

Rejected: in-process accounting of objects added, updated and deleted. It can only report what the
code believes it did. The serializer defect would have been reported, accurately and uselessly, as
three sets updated, while 1,415 files changed on disk. The value is in comparing the artifact.

Rejected: snapshotting the starting state and carrying it forward — that routes a large payload
through the failure-tolerant cache channel already ruled out. Rejected: publishing with history so
that git provides the diff — the publish is squashed deliberately, and the aggregate publish is
already exceeding a size limit.

The headline figure is a **pair**: output files changed, alongside pages the wiki changelog reported
changed. Either alone looks unremarkable; the ratio is the alarm, and it is the exact signature by
which the serializer defect was eventually found. This makes the report a practical determinism check
without paying for a second full run.

### Schema changes

Both additive and optional, in the metadata object only:

- A run identifier, so a published database can be tied to the run that produced it. Wave 2 could not
  confirm which run its baseline came from, and that ambiguity is what this removes.
- The increment field is corrected to mean what it is documented to mean. It is described as
  advancing once per update but is written once per save, and a run saves ten times.

### Failure semantics

Nothing in this wave fails the build. The aggregation job runs after publishing has already happened,
so a red run there would be a notification rather than a gate, and a warning summary must never be
able to block the database from publishing. Anything worth flagging is surfaced as a workflow
annotation.

### Modules

- **A new warnings module in the package** (`src/ygojson/warnings.py`) holding the bucketing handler,
  the quiet logger, installation, and the reading and writing of per-job counts. Its pure core is the
  merge of several jobs' counts and the rendering of the merged result — plain data in, text out, with
  no logging, filesystem or network involvement.
- **A new output-diff reporter under the test directory** (`test/report_output_diff.py`), alongside
  the existing schema and rarity-coverage scripts, since that is where CI-invoked scripts already
  live. Its pure core is the comparison of two indexes, independent of how they were loaded.
- **Card-type resolution** as a small vocabulary-resolution function beside the card type enumeration
  itself, matching how rarity resolution is placed.
- **Modified:** the entry point installs the handler and writes counts; the Yugipedia importer gains
  the card-type fix, the subject in its warning, and the two noise routings; all importers and the
  database module take the rename; the database module and metadata schema take the run identifier and
  increment correction; the pre-commit configuration gains the guard; the workflow and its composite
  actions gain artifact upload, the aggregation job, and the diff step.

## Testing Decisions

**There is no test framework in this repository, and this wave does not add one.** Adding pytest is
listed among the decisions that must be raised on their own rather than made inside another change,
and doing it here would mean settling it as a side effect of an observability wave. That was
considered and declined during the interview.

Verification follows what Waves 1 and 2 did, which is the honest standard for this codebase: a narrow
real run against real wiki content, and reading the JSON it produces.

**What makes a good verification here.** It exercises external behaviour against real input and
checks a published value, not an internal call. It states a figure before and after. It includes at
least one case that must *not* change, so that a fix that over-reaches is caught as readily as one
that under-reaches — Wave 1's use of a set whose quantities were already correct is the model.

**Prior art in the repository.** `test/validate_data.py` validates generated output against the schema
and is run by CI after a full run. `test/validate_rarity_coverage.py` is a plain script with named
exit-code constants, human-readable output, and a distinct exit status for "the check could not run"
versus "the check failed" — no framework, no dependency, run from the lint job. New scripts follow
that shape.

**Per slice:**

- *Histogram and aggregation:* run narrowly with a partition file, confirm the per-process histogram
  matches a manual grouping of the same run's raw log. Confirm the merge of several jobs' counts sums
  correctly by running more than one partition. Confirm the aggregation job produces a summary when a
  mid-chain job fails, by failing one deliberately.
- *Quiet logger:* confirm the two buckets stop printing and continue to be counted, and confirm the
  root level is unchanged by checking that response bodies are still not logged.
- *Card types:* confirm all sixteen named pages import, that their printings appear in their sets,
  and that the five plain Counter cards are unchanged. Confirm the rejection warning names its page
  by feeding a value that is still unrecognised.
- *Rename and guard:* confirm no occurrences remain, and confirm the guard fails on a deliberately
  reintroduced call.
- *Output diff:* run the reporter against two known-different published snapshots and check the
  counts by hand. Run it against a snapshot and itself and confirm it reports no change.
- *Schema:* validate generated output, and confirm the previously published database still validates.

**Every slice re-derives its own figures from run 31120463581 or a later one.** No slice inherits a
count from the audit.

## Out of Scope

- **A baseline of known warning kinds, and failing or annotating on a new one.** The case the issue
  makes for it — that it would have caught a new rarity on the run it appeared — is already served,
  and served better, by the rarity coverage check that Wave 2 put in the lint job: a positive check
  against the wiki's own data, failing in seconds before the run starts. Every stable-key scheme for a
  baseline costs a mechanism this wave rejected twice.
- **Generalising that coverage check to other wiki vocabularies.** This is the right successor, and
  the card-type work hands it the evidence. It is not in this wave: each vocabulary needs its own
  answer to what the authoritative source on the wiki is, and for rarities that took Wave 2 a while to
  discover was a Lua data module rather than the template everyone assumed.
- **Per-module named loggers**, beyond the single quiet logger.
- **Adopting a linter beyond the existing formatters.**
- **Modelling series as first-class objects**, and filtering hub pages out of the page collection
  before fetching. The requests are cached, and inferring a filter from a partial sample is how a real
  set gets silenced.
- **A distinct card type for counters.**
- **The unseeded shuffle that distributes work across partition jobs.** It sits directly upstream of
  the four remaining order-dependent card paths tracked in #47 and is worth filing, but it is a
  determinism issue, not an observability one.
- **The aggregate publish exceeding GitHub's file size limit.**
- **The temporary tracker documents now on the default branch.**
- **Wave 4** — #2, #11, #19 and then #5, which should be re-measured before it is picked up.

## Further Notes

**The audit's numbers are not a baseline.** The largest bucket in the published distribution — 1480
lines, 69% of the total — describes a warning that no longer exists; Wave 2 deleted it when it made
variant images publish. Wave 2 measured total warnings falling from 431 to 98 over the sets it
touched. Designing this wave's instruments against the audited distribution would be calibrating a
ruler against a measurement two waves out of date.

**Five claims in the audit have already been disproven, and this interview disproved three more.**
Wave 1 established there were never any phantom cards and that the quantity defect named in the
tracking issue corrupted nothing. Wave 2 disproved five more, including that a set was publishing at
Common when it never had. This interview adds: the sixteen dropped cards are not joke pages; the
namespace filter proposed for the hub-page bucket catches one page in sixty-one; and none of the
twelve pages listed as "plausibly real products we are failing to parse" is a product. The pattern is
consistent enough to be a working assumption — **an audited count is a floor, and an audited
explanation is a hypothesis.**

**A count of warnings is a count of the paths that chose to warn.** Wave 2 found a rarity path that
emitted nothing at all, affecting 201 rows plus 696 more, against an audited estimate of about 39.
Every figure in the audit is an undercount of unknown size, and the diff workstream exists because of
it.

**State of the branch.** `main` was fast-forwarded to the integration branch at `be672394`, putting
Waves 1 and 2 on the default branch for the first time. The rarity coverage check was verified against
the live wiki beforehand — all 67 rarities the wiki defines resolve. Run 31120463581 was dispatched;
its first attempt failed during job setup on a GitHub Actions major outage, before any project step
ran, and the re-run is queued behind that outage. It is the first run that will exercise either wave,
and the first that can produce numbers this wave is entitled to use.
