# YGOJSON

YGOJSON aims to be the ultimate Yugioh database - a set of machine-readable [JSON](https://www.json.org/json-en.html) files detailing:

* Cards, including tokens and skill cards
* Sets, including Duel Links and Master Duel sets
* Archetypes and series information
* Pack odds
* Sealed products, such as tin contents

# Data Sources

We gather our data from the following sources:

* [YGOPRODECK](https://ygoprodeck.com/)
* [Yaml Yugi](https://github.com/DawnbrandBots/yaml-yugi)
* [Yugipedia](https://yugipedia.com/)

Special thanks goes out to [YGO Prog](https://www.ygoprog.com/) for their tireless work on discovering pack odds.

# Using the Database

There are several methods of consuming the database. To get the files, you can either:

* Download a ZIP file [here](https://github.com/matt-roz/YGOJSON/releases/latest)
* Download the raw JSON files on the [indiviual](https://github.com/matt-roz/YGOJSON/tree/v1/individual) and [aggregate](https://github.com/matt-roz/YGOJSON/tree/v1/aggregate) branches

To get the ZIP files in an automated fashion, fetch the following URLs:

* For a individualized ZIP file: https://github.com/matt-roz/YGOJSON/releases/download/v1/individual.zip
* For a aggregated ZIP file: https://github.com/matt-roz/YGOJSON/releases/download/v1/aggregate.zip

If you don't want everything, or don't want to unzip things, just fetch the following URLs for indiviudal things, with `cards` replaced by the type of things you want, and the UUID replaced with your UUID:

* For individual card JSON files: https://raw.githubusercontent.com/matt-roz/YGOJSON/v1/individual/cards/00045021-f0d3-4473-8bbc-8aa6504d3562.json
* For a list of all card UUIDs: https://raw.githubusercontent.com/matt-roz/YGOJSON/v1/individual/cards.json
* For all information for all cards: https://raw.githubusercontent.com/matt-roz/YGOJSON/v1/aggregate/cards.json ***(NOTE: These files are currently BROKEN and OUT OF DATE due to GitHub file size limits. Use the individuals or download the aggregates ZIP file instead!)***

You may have noticed the two different ways of getting the data: individual and aggregate. The differences between the two are as follows:

* `individual`: Each card, set, etc. is in its own JSON file, whose filename is its UUID.
* `aggregate`: Every card, set, etc. is in one JSON file.

Within each folder should be the data you need. Check out the [JSON schema](https://json-schema.org/) for all this data [here](schema/v1/).

We have the following things available for you:

* `cards`: Yugioh cards. This includes tokens, Speed Duel skill cards and Rush Duel cards. Rush Duel cards carry the stats they share with every other card; their Rush-only properties (Requirement/Condition, MAXIMUM ATK, Legend status) are not modelled. This does NOT include video-game exclusive cards.
* `sets`: Yugioh products such as booster packs, decks, and sets of promotional cards.
* `series`: Information about archetypes and series.
* `sealedProducts`: Sealed products are things like booster boxes, tins, and other things that consist of a mix of packs.
* `distributions`: Pack odds information for sets. You can use this to figure out how to make random packs of sets accurately.

The data is regenerated from our sources every day at midnight. So if you don't see the latest new cards in the database yet, wait a bit!

## Viewing YGOJSON Interactively

If you want to explore the YGOJSON dataset interactively and visually, we have an application that runs in your web browser, [YJViewer](https://github.com/iconmaster5326/YJViewer).

| ![YJViewer's front page.](yjv1.jpg) | ![YJViewer searching for cards.](yjv2.jpg) | ![YJViewer at a card page.](yjv3.jpg) |
| - | - | - |

Check it out if you want to look at what we have!

## Using the YGOJSON API

The API we use to make the database has facilities for you to load any YGOJSON database and manipulate it using a convientient [Python](https://www.python.org/) API. To get our API from [PyPI](https://pypi.org), you can simply do the following:

```bash
python3 -m pip install ygojson
```

From there, you can write Python code to load the database and have fun with it:

```python
# you'll need to specify where the database goes on your filesystem
INDIVIDUALS_DIR = "path/to/unzipped/individuals/dir"
AGGREGATES_DIR = "path/to/unzipped/aggregates/dir"

# import only the code that deals with the database schema
import ygojson.database as ygodb

# construct the database; you can omit one if you don't have both downloaded
# (there is also load_from_file if you already have the files)
db = ygodb.load_from_internet(individuals_dir=INDIVIDUALS_DIR, aggregates_dir=AGGREGATES_DIR)

# print the name of every card
for card in db.cards:
    print(card.text[ygodb.Language.ENGLISH].name)
```

# Generating the Database

You'll need a modern version of Python, at least 3.8, to run this code. To install YGOJSON:

```bash
python3 -m pip install -e .
```

Then you can run the database generator via the `ygojson` command, or by `python3 -m ygojson`. Here are the command-line arguments I usually pass when testing:

```bash
ygojson --download --individuals "" --no-individuals
```

Try `-h` or `--help` for more command-line options.

By default, it will place the generated JSON files in the `data` folder. It will also create a `temp` folder, containing things like the Yugipedia cache. (Yugipedia takes several hours to download from a fresh cache, and hammers their servers a bit more than I'd like, so only delete that cache when absolutely necesary!)

The [`manual-data`](manual-data) folder contains all the things that aren't covered nicely by any of our data sources. This includes things like pack odds and sealed products, as well as some set information.

# Contributing

The biggest thing you can do is report bad data. Something we have in our database incorrect? Tell us via our issue tracker! Before you do, though, please look at our data sources if you can, to see if the problem lies with their data or not. If it's with them, bring it up with them!

Another thing you can do is submit additions to [`manual-data`](manual-data) when new things come out. That's also extremly helpful. Check out the READMEs in the subdirectories for more details.

If you want to contribute code changes or test your manual fixup changes, you can install YGOJSON for editing and testing like so:

```bash
python3 -m pip install -e .[dev,test]
pre-commit install
```

From there, you can run YGOJSON as you will, and there are some tests you can run before making your pull requests like so:

```bash
python3 test/validate_data.py # runs a JSON schema validator against everything in the data/ folder
```

# Schema Changelog

## v1

Initial release.

### Unreleased additions

All of the below are additive: no field changed meaning, no published value was renamed, and
everything new is optional. Note, though, that **adding values to an enum can break a consumer that
validates strictly** against a cached copy of the schema. If you do that, re-fetch `schema/v1` before
reading a database built after these landed.

* **`rarity.json` gained 12 values**, bringing it to 73. Every rarity Yugipedia's own data module
  defines is now representable: `grandmaster`, `holofoil`, `secretultra`, `ultra-red`, the Rush Duel
  family (`rush`, `goldrush`, `overrush`, `fulloverrush`, `rush-red`, `overrush-black`), and the two
  Quarter Century variants (`25thsecret-special`, `25thsecret-tokyodome`). `ultra-blue` already
  existed but could not previously be produced from a rarity name.

  A CI check now fails the build if Yugipedia introduces a rarity we do not model, so this list should
  not silently fall behind again. Rarities Yugipedia has since dropped — `parallel`,
  `commonparallel`, `dtpc` and the Kaiba Corporation secret — are deliberately retained.

* **`imageVariant.json` is new.** A small vocabulary — `alternate-art`, `official-proxy`,
  `official-website` — for classifying the variant images below.

* **`cardInfo` entries in `set.json` gained an optional `variants` array.** A printing can have
  several images in one edition: alternate artworks, different print runs, stamped promo variants.
  Previously we kept one and discarded the rest. Each entry is `{code, image, variant?}`, where
  `code` is Yugipedia's own tag verbatim, and `variant` is present only where the tag's meaning is
  established. **Most entries have no `variant`** — that is deliberate, not an omission. Yugipedia's
  `Reprint` tag in particular means a print run on some pages and a Magic-to-Spell text change on
  others, so classifying it would be asserting something untrue about roughly two thirds of the
  cases.

* **Alternate artworks now appear in a card's `images` array.** That array previously held only
  YGOPRODECK-sourced artworks, so **a card's artwork count may go up**. Variant entries tagged
  `alternate-art` carry an `imageID` pointing at the treatment they depict.

* **`printing.json` gained an optional `printNote`.** Yugipedia's set lists write far more in their
  `print` column than the two words `printStatus` can hold — `Speed Duel debut`, `New artwork`,
  `Functional errata`, `Reprint (renamed)` — and we previously published no `printStatus` at all for
  those rows, which the schema documents as "the source did not say". They now resolve (all 23
  measured phrases mean `reprint`) and carry the phrase verbatim in `printNote`. **`printNote` is
  present only when the source said something other than literally `new` or `reprint`**, so its
  presence tells you `printStatus` lost information; it is not on every printing. It may also appear
  *without* a `printStatus`, which means the phrase is one we do not classify — you get the wiki's
  words even where we decline to interpret them. **`printStatus` itself is unchanged**: same two
  values, same meaning, just present on many more printings than before.

* **`meta.json` gained an optional `runID`.** The CI run that produced the database — the GitHub
  Actions run ID, which resolves at `<repository>/actions/runs/<runID>` — so a published snapshot can
  be tied to the run that built it. **Absence means no run was recorded**, such as a database built
  locally; it does not mean the run is unknown.

* **Two schema definitions were silently vacuous and are now enforced.** `set.json`'s `locales` and
  `sealedProduct.json`'s `locales` both used `remainingProperties`, which is not a JSON Schema
  keyword — so nothing under either was validated at all. Data already conformed; if you generated
  your own database against the old schema and it passed, it may not now.

* **`card.json`'s `attribute` and `type` each gained one value** - `laugh` and `charisma`. Both exist
  for a single real printed OCG card, `Charisma Token`, whose `attribute = LAUGH` and
  `types = Charisma` were previously parsed, found unmodellable and dropped. Yugipedia tracks it in
  `Category:Cards with odd Attributes` and `Category:Cards with odd Types`. **That card gains two
  fields**; nothing else changes. The other odd values in those categories belong to anime-only cards
  we do not import and are deliberately not modelled.

* **`format.json` gained `rushduel`**, and so did `set.json`'s deprecated `contents.formats` enum.
  Rush Duel is a separate game, and its sets are Japanese or Korean, so they were previously
  published as `ocg` — as though playable in the OCG. **A set that used to report `ocg` may now
  report `rushduel`**, which is a value change for existing sets even though the enum addition is
  additive. Rush Duel *cards* are new to the database entirely (see below); their Rush-only
  properties — Requirement/Condition, MAXIMUM ATK, Legend status — are **not** modelled, so those
  cards publish with the stats they share with every other card and nothing more.

### Unreleased behaviour changes

Not schema changes, but visible in the data:

* **The database is now reproducible.** Two runs over the same Yugipedia content produce
  byte-identical files, whether the page cache is cold or warm. Previously the key ordering inside
  every set file churned on every run, printings in Master Duel and Duel Links sets were assigned
  **new UUIDs on every cold run**, and which image a printing published depended on which network
  request finished first. If you diff published snapshots, that diff now means something.

* **An unrecognised rarity is no longer replaced with Common.** A printing whose rarity cannot be
  determined carries no rarity, so absence now means "unknown" rather than "unknown, or Common".

* **`meta.json`'s `increment` now advances once per run, not once per job.** It is documented as
  incrementing each time YGOJSON is updated, but the generator writes the database once per job and a
  run has ten jobs, so a run advanced it by ten. The field was corrected rather than the description.
  **A published `increment` therefore rises by roughly one tenth of what it used to per run**, and
  compares across that change only as an ordering, not as a count. Where no run identifier is
  available — a local run, for instance — each write still counts as its own update.

* **`increment` can no longer go backwards.** It was seeded from whichever ZIP the run downloaded,
  and the individual and aggregate artifacts drift, so the published counter went 2351 → 2350 once.
  A save now continues from the highest of what it loaded and what the output already publishes.

* **A one-time consolidation of 6,184 printing UUIDs happened in the 2026-08-07 publish.** No
  printing disappeared: card entries went *up* by 1,702 while distinct printing UUIDs fell by 4,042,
  because printings that used to get a separate UUID in each locale block now share one across the
  blocks they appear in, which is the shape a set is supposed to have. **Identifiers held from a
  snapshot before 2026-08-07 may no longer resolve.** This is a correction, not the recurring churn
  that the reproducibility fix above addressed, and it is not expected to repeat.

* **Many more sets publish their printings.** A set's card-list and gallery pages are named after
  the set, and we built those names from the Yugipedia *page title* — so every set with a
  disambiguated title (`Premium Pack 2 (TCG)`, `Metal Raiders (Japanese)`) looked for a page that
  does not exist and published an empty card list, silently. 73 locale entries across 49 sets were
  affected. Separately, `Legacy Pack` (4,057 printings) and `Promotional Pack` (50) keep their lists
  in shapes we did not read, and now publish.

* **Sets that shared a Konami set ID no longer collapse onto one another.** 153 Konami set IDs are
  declared by more than one Yugipedia page — a booster and its `+1 Bonus Pack`, `Wave 1` and
  `Wave 2` — and one ID in common was enough for one page to take the other's set object, leaving
  that set absent from the database and its UUID naming something else. **Sets absent for this
  reason reappear, with new UUIDs**, and a set already published keeps the UUID it had.

* **101 set pages are enumerated that never were.** Set discovery walks category trees downward
  only, and twenty categories on Yugipedia have no parent category at all, so nothing in them was
  ever fetched. Rush Duel's five such categories (331 pages) are still excluded deliberately.

* **Rush Duel cards are in the database.** 3,151 cards that were in neither `Category:TCG cards` nor
  `Category:OCG cards` and so were never imported. Rush Duel sets consequently stop publishing empty
  card lists, and 1,234 Duel Links set-list rows that resolved to nothing now resolve.

# Python API Changelog

## 0.6.0

* Added schema for card prices and for the Genesys format.
* Added Yugipedia importing of Genesys point and legality data.
* Bugfixes for database generation.

## 0.5.1

* Added support for the new red and blue foil secret rares, and improved support for the purple foil ultra rares.
* Bugfixes for database generation.

## 0.5.0

* Replaced some common strings with enumeration values. Expanded `Format`, and added `Language` and `Locale`.
* Fixed bug with YGOPRODECK importing of DEF values.
* Deduplicated spurious booster box additions.

## 0.4.0

* Changed how booster boxes work; the properties for them on sets are deprecated, and instead sealed products represent booster boxes now. Booster boxes indicate what packs they are boxes of.
* Other minor bugfixes.

## 0.3.3

* Fix for pack distributions not being able to be loaded properly.

## 0.3.2

* Fix for pack distribution card-type filtering in slots, adding new "quota" mechanism, to properly model early TCG reprint packs.
* Other small fixes in output of manually fixed up models.

## 0.3.1

* Minor fix for YGOPRODECK importer.
* Fixes for manual fixups.
* Added ability to look up sets by Yugipedia page title.

## 0.3.0

* Added support for per-locale editions and formats.
* Completely revamped the Yugipedia set import process. It should be more accurate now.
* Minor fixes for other importers.

## 0.2.0

* Added options for downloading the data from the `database` module.
* Fixed bugs with running on a PyPI installation.
* Added documentation to the `database` module.
* More robust YGOPRODECK support. (Sometimes their API bugs out.)

## 0.1.0

Initial release.
