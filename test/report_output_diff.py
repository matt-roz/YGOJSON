# Reports what a run changed in the individual JSON it published.
#
# Every other signal in this pipeline reports the code paths that chose to
# report. The three largest defects found in the first two waves of the warning
# audit chose nothing: quantities corrupted by an empty parameter, a serializer
# that rewrote all 3,376 set files on every run, and old-printing deletion that
# rebuilt whole sets under fresh printing UUIDs - the stable handle consumers
# key on. Not one of them emitted a line. All three are plainly visible as a
# count of published files that differ on disk.
#
# So this compares the artifact instead of asking the code what it did.
# In-process accounting of objects added, updated and deleted would have
# described the serializer defect as "three sets updated", accurately and
# uselessly, on the run where 1,415 files changed.
#
# It reports; it never fails a build. Differences are the normal case - a run
# that changes nothing is the surprising one - so there is no exit status for
# "found differences", only one for "could not compare".
import argparse
import collections
import hashlib
import json
import pathlib
import sys
import typing

EXIT_COULD_NOT_COMPARE = 2
"""One side could not be indexed, so no comparison happened.

Kept distinct from a clean exit, and given the same value as
:data:`validate_rarity_coverage.EXIT_CHECK_DID_NOT_RUN`, so that a baseline
that failed to download reads as a missing baseline rather than as a run that
changed nothing. Those two want completely different responses and are
otherwise indistinguishable: both print no differences.
"""

SETS_DIRNAME = "sets"
"""The sub-directory of published individual JSON holding sets.

Printings are defined in set files and nowhere else - every other object type
refers to them by UUID - so this is the only directory parsed. A snapshot
without it is reported as one that could not be compared, because a printing
count of zero would otherwise read as a database that lost every printing it
had. Rename this directory in the database module and this constant must move
with it.
"""

EXAMPLES_SHOWN = 10
"""How many reassigned printings, or unreadable files, are listed by name.

Reassignment happens to whole sets at a time, so listing every one would bury
the run somebody is trying to read under thousands of lines. The counts are
the figures; these are for hand-checking them.
"""


class PrintingIdentity(typing.NamedTuple):
    """What names a printing when its UUID is the thing in question.

    The fields a Yugioh player would name a printing by - which set, which
    card, which locales, which code, which rarity - and deliberately not the
    edition or format of the contents blocks it sits in, which are the parts a
    re-import moves around most. Measured against the published database, this
    is unique: no two of its 133,354 printings share one.
    """

    set_id: str
    card: str
    locales: typing.Tuple[str, ...]
    suffixes: typing.Tuple[str, ...]
    rarities: typing.Tuple[str, ...]


class Appearance(typing.NamedTuple):
    """One printing as it is written into one contents block of one set."""

    set_id: str
    card: str
    locales: typing.Tuple[str, ...]
    suffix: typing.Optional[str]
    rarity: typing.Optional[str]


class Snapshot(typing.NamedTuple):
    """One directory of published individual JSON, indexed for comparison."""

    files: typing.Dict[str, str]
    """Path relative to the snapshot root, to a digest of that file's bytes."""

    printings: typing.Dict[str, PrintingIdentity]
    """Printing UUID, to what identifies that printing without its UUID."""

    unreadable: typing.Tuple[str, ...]
    """Set files that are not readable JSON, so contributed no printings."""


class FileCounts(typing.NamedTuple):
    """How one object type's published files fared between two snapshots."""

    unchanged: int
    added: int
    removed: int
    modified: int


class Reassignment(typing.NamedTuple):
    """One printing published under a new UUID, having kept its identity."""

    identity: PrintingIdentity
    was: str
    now: str


class Comparison(typing.NamedTuple):
    """What differs between two snapshots.

    Produced from two indexes and nothing else, so it can be built from any
    pair of snapshots however they were loaded.
    """

    files: typing.Dict[str, FileCounts]
    """Object type, to how its files fared."""

    baseline_printings: int
    current_printings: int

    gained: typing.Dict[str, PrintingIdentity]
    """Printings only the current snapshot has, reassignments excluded."""

    lost: typing.Dict[str, PrintingIdentity]
    """Printings only the baseline has, reassignments excluded."""

    reassigned: typing.Tuple[Reassignment, ...]
    ambiguous: int
    """Identities held by more than one lost or gained printing.

    Matching them would be guesswork, so they are left in the gained and lost
    figures and counted here instead of being silently resolved either way.
    """

    unreadable: typing.Tuple[str, ...]


def object_type(path: str) -> str:
    """Returns the label a published file is counted under.

    Files in a sub-directory count as that directory - ``sets/`` - and the list
    and metadata files at the root count as themselves, so that a run which
    rewrote every set file cannot read like one that rewrote three cards.
    """
    directory, slash, _ = path.partition("/")
    return directory + slash if slash else directory


def read_printings(
    set_json: typing.Any,
) -> typing.List[typing.Tuple[str, Appearance]]:
    """Returns every printing one set file publishes, with its UUID.

    A printing is written into one contents block per locale it covers, so the
    same UUID is normally returned several times over.
    """
    found = []
    for contents in set_json.get("contents", []):
        locales = tuple(sorted(contents.get("locales", [])))
        for printing in contents.get("cards", []):
            found.append(
                (
                    printing["id"],
                    Appearance(
                        set_id=set_json["id"],
                        card=printing["card"],
                        locales=locales,
                        suffix=printing.get("suffix"),
                        rarity=printing.get("rarity"),
                    ),
                )
            )
    return found


def identify(appearances: typing.List[Appearance]) -> PrintingIdentity:
    """Folds every appearance of one printing into the identity it matches on.

    The blocks a printing is written into do not always agree - 7,941 printings
    in the published database carry one suffix in one locale and another
    elsewhere - so every spelling it is published under goes into its identity,
    and one printing has one identity however many blocks hold it.
    """
    return PrintingIdentity(
        set_id=appearances[0].set_id,
        card=appearances[0].card,
        locales=tuple(sorted({locale for a in appearances for locale in a.locales})),
        suffixes=tuple(sorted({a.suffix for a in appearances if a.suffix is not None})),
        rarities=tuple(sorted({a.rarity for a in appearances if a.rarity is not None})),
    )


def index_snapshot(directory: str) -> Snapshot:
    """Indexes one directory of published individual JSON.

    Files are digested byte for byte rather than compared as parsed JSON: the
    serializer defect this exists to catch rewrote every set file without
    changing a single value, and normalising the JSON first would have called
    that run unchanged.

    Raises :class:`ValueError` if the directory is not published output, so
    that pointing this at the wrong place is reported as such rather than as a
    database that lost everything in it.
    """
    root = pathlib.Path(directory)
    if not root.is_dir():
        raise ValueError(f"{directory} is not a directory")

    files: typing.Dict[str, str] = {}
    appearances: typing.Dict[str, typing.List[Appearance]] = collections.defaultdict(
        list
    )
    unreadable: typing.List[str] = []
    sets_dirname = SETS_DIRNAME + "/"

    for path in sorted(root.rglob("*.json")):
        relative = path.relative_to(root).as_posix()
        content = path.read_bytes()
        files[relative] = hashlib.sha256(content).hexdigest()
        if object_type(relative) != sets_dirname:
            continue
        try:
            printings = read_printings(json.loads(content))
        except (ValueError, TypeError, KeyError, AttributeError):
            # Counted and reported, never skipped quietly: a set file nobody
            # can read is a set whose printings all look lost.
            unreadable.append(relative)
            continue
        for uuid, appearance in printings:
            appearances[uuid].append(appearance)

    if not files:
        raise ValueError(f"{directory} holds no JSON files")
    if not any(object_type(path) == sets_dirname for path in files):
        raise ValueError(f"{directory} has no {sets_dirname} directory")

    return Snapshot(
        files=files,
        printings={uuid: identify(a) for uuid, a in appearances.items()},
        unreadable=tuple(unreadable),
    )


def _by_identity(
    printings: typing.Dict[str, PrintingIdentity]
) -> typing.Tuple[typing.Dict[PrintingIdentity, str], int]:
    """Inverts printings onto their identities, dropping the ambiguous ones.

    Returns the unambiguous half and a count of the printings dropped.
    """
    holders = collections.defaultdict(list)
    for uuid, identity in printings.items():
        holders[identity].append(uuid)
    unambiguous = {
        identity: uuids[0] for identity, uuids in holders.items() if len(uuids) == 1
    }
    ambiguous = sum(len(uuids) for uuids in holders.values() if len(uuids) > 1)
    return unambiguous, ambiguous


def compare(baseline: Snapshot, current: Snapshot) -> Comparison:
    """Compares two indexes, taking no account of how either was loaded."""
    added: typing.Counter[str] = collections.Counter()
    removed: typing.Counter[str] = collections.Counter()
    modified: typing.Counter[str] = collections.Counter()
    unchanged: typing.Counter[str] = collections.Counter()
    for path in set(baseline.files) | set(current.files):
        label = object_type(path)
        if path not in current.files:
            removed[label] += 1
        elif path not in baseline.files:
            added[label] += 1
        elif baseline.files[path] != current.files[path]:
            modified[label] += 1
        else:
            unchanged[label] += 1

    lost = {
        uuid: identity
        for uuid, identity in baseline.printings.items()
        if uuid not in current.printings
    }
    gained = {
        uuid: identity
        for uuid, identity in current.printings.items()
        if uuid not in baseline.printings
    }
    # Only printings that vanished are matched against printings that
    # appeared, which is what keeps an ordinary edit out of this entirely: a
    # printing whose rarity or code was corrected under the same UUID is in
    # neither pool and can never pair with anything.
    was, ambiguous_lost = _by_identity(lost)
    now, ambiguous_gained = _by_identity(gained)
    reassigned = tuple(
        Reassignment(identity=identity, was=was[identity], now=now[identity])
        for identity in sorted(set(was) & set(now))
    )

    return Comparison(
        files={
            label: FileCounts(
                unchanged=unchanged[label],
                added=added[label],
                removed=removed[label],
                modified=modified[label],
            )
            for label in sorted(
                set(added) | set(removed) | set(modified) | set(unchanged)
            )
        },
        baseline_printings=len(baseline.printings),
        current_printings=len(current.printings),
        gained={
            uuid: identity
            for uuid, identity in gained.items()
            if uuid not in {r.now for r in reassigned}
        },
        lost={
            uuid: identity
            for uuid, identity in lost.items()
            if uuid not in {r.was for r in reassigned}
        },
        reassigned=reassigned,
        ambiguous=ambiguous_lost + ambiguous_gained,
        unreadable=tuple(sorted(set(baseline.unreadable) | set(current.unreadable))),
    )


def _spell(identity: PrintingIdentity) -> str:
    """Spells a printing identity as one line, for hand-checking a count."""
    return (
        f"set {identity.set_id} card {identity.card} "
        f"{'/'.join(identity.locales) or '(no locale)'} "
        f"{'/'.join(identity.suffixes) or '(no code)'} "
        f"{'/'.join(identity.rarities) or '(no rarity)'}"
    )


def report(comparison: Comparison) -> typing.List[str]:
    """Renders a comparison as the lines to print."""
    baseline_files = sum(
        counts.unchanged + counts.modified + counts.removed
        for counts in comparison.files.values()
    )
    changed = sum(
        counts.added + counts.removed + counts.modified
        for counts in comparison.files.values()
    )
    lines = [
        f"{changed} of {baseline_files} published files changed.",
        "",
        "Files by object type:",
    ]

    width = max(len(label) for label in comparison.files) if comparison.files else 0
    width = max(width, len("object type"), len("total"))
    header = "  {:<{w}}  {:>8}  {:>8}  {:>8}  {:>8}  {:>8}".format(
        "object type", "baseline", "current", "added", "removed", "modified", w=width
    )
    lines.append(header)
    total = FileCounts(0, 0, 0, 0)
    for label, counts in comparison.files.items():
        lines.append(_file_row(label, counts, width))
        total = FileCounts(*(a + b for a, b in zip(total, counts)))
    lines.append(_file_row("total", total, width))

    lines.extend(
        [
            "",
            "Printings:",
            f"  {comparison.baseline_printings} in the baseline, "
            f"{comparison.current_printings} in the current snapshot",
            f"  {len(comparison.gained)} gained"
            f"{_across(comparison.gained.values())}",
            f"  {len(comparison.lost)} lost" f"{_across(comparison.lost.values())}",
            "  {} UUID{} reassigned{} - the same printing published under a "
            "new identifier".format(
                len(comparison.reassigned),
                "s" if len(comparison.reassigned) != 1 else "",
                _across(r.identity for r in comparison.reassigned),
            ),
        ]
    )

    if comparison.reassigned:
        shown = comparison.reassigned[:EXAMPLES_SHOWN]
        lines.append("")
        lines.append(
            f"Reassigned printings ({len(shown)} of {len(comparison.reassigned)}):"
        )
        for reassignment in shown:
            lines.append(f"  {_spell(reassignment.identity)}")
            lines.append(f"    was {reassignment.was}, now {reassignment.now}")

    if comparison.ambiguous:
        lines.append("")
        lines.append(
            f"{comparison.ambiguous} gained or lost printings share an identity "
            "with another, so they are counted as gained and lost rather than "
            "matched up as reassignments."
        )
    if comparison.unreadable:
        unreadable = len(comparison.unreadable)
        lines.append("")
        lines.append(
            "Not readable JSON in one snapshot or the other, so counting "
            "towards none of the printing figures above: "
            "{} set file{}".format(unreadable, "s" if unreadable != 1 else "")
        )
        for path in comparison.unreadable[:EXAMPLES_SHOWN]:
            lines.append(f"  {path}")

    lines.extend(
        [
            "",
            "This reports that published output changed, not that it changed",
            "for the worse: a file counted as modified may hold a fix, a",
            "regression, or a price that moved overnight. What is worth reading",
            "is the size of these figures against the size of the change that",
            "was expected.",
        ]
    )
    return lines


def _file_row(label: str, counts: FileCounts, width: int) -> str:
    """Renders one object type's row of the file table."""
    return "  {:<{w}}  {:>8}  {:>8}  {:>8}  {:>8}  {:>8}".format(
        label,
        counts.unchanged + counts.modified + counts.removed,
        counts.unchanged + counts.modified + counts.added,
        counts.added,
        counts.removed,
        counts.modified,
        w=width,
    )


def _across(identities: typing.Iterable[PrintingIdentity]) -> str:
    """Renders how many sets a group of printings falls across, if any do."""
    sets = len({identity.set_id for identity in identities})
    if not sets:
        return ""
    return ", across {} set{}".format(sets, "s" if sets > 1 else "")


def main(argv: typing.List[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Report what changed between two directories of published "
        "individual JSON."
    )
    parser.add_argument(
        "baseline",
        metavar="BASELINE",
        help="The individual JSON a run started from, as consumers received it",
    )
    parser.add_argument(
        "current",
        metavar="CURRENT",
        help="The individual JSON a run produced",
    )
    args = parser.parse_args(argv[1:])

    try:
        baseline = index_snapshot(args.baseline)
        current = index_snapshot(args.current)
    except (ValueError, OSError) as error:
        # Anything at all that goes wrong before there are two indexes means
        # nothing was compared. Saying so is the whole point: a baseline that
        # never arrived must never read as a run that changed nothing.
        print(f"Could not index both snapshots: {type(error).__name__}: {error}")
        print("Nothing was compared, so this is not a run that changed nothing.")
        return EXIT_COULD_NOT_COMPARE

    print(f"Baseline: {args.baseline}")
    print(f"Current:  {args.current}")
    print("")
    for line in report(compare(baseline, current)):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
