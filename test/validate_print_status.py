# Fails the build when the print status vocabulary or its reporting misbehaves.
#
# Unlike ``validate_rarity_coverage.py``, this makes **no network calls**. There
# is no upstream list of print values to sync against - ``Template:Set list``
# documents the column as prose and validates nothing - so a check that fetched
# the wiki could only detect that an editor had typed a new phrase into a
# free-text column. That is a change detector, and it would sit in `lint`, which
# gates a day-long sequential run. This checks the only thing that is ours: that
# the table still resolves what it is written to resolve.
#
# Every spelling below was measured across the corpus, with the row counts that
# make it worth having: 6591 rows in 23 spellings, of which `Speed Duel debut`
# alone is 5113.
import logging
import sys
import typing

from ygojson.database import PrintStatus
from ygojson.print_status import (
    PRINT_STATUS_SPELLINGS,
    UNKNOWN_PRINT_STATUSES,
    log_unknown_print_statuses,
    print_status_note,
    report_unknown_print_status,
    resolve_print_status,
)
from ygojson.warnings import EXPECTED_CONDITIONS

MEASURED_REPRINTS = (
    "Speed Duel debut",
    "New artwork",
    "European debut",
    "New Artwork",
    "Reprint (renamed)",
    "New extension",
    "New art",
    "Reprint (functional errata)",
    "Functional errata",
    "Functional erratum",
    "European & Oceanian debut",
    "International artwork",
    "Reprint (New Art)",
    "Japanese artwork",
    "Reprint (European Debut)",
    "New artwork (renamed)",
    "Reprint (NA Debut)",
    "North American debut",
    "Reprint (new artwork)",
    "TCG legal debut",
    "Reprint (EU Debut)",
    "Oceanian debut",
    "European English debut",
)
"""Every print value the corpus spells that is not `new` or `reprint`.

Written out here, separately from the table, on purpose: a check that read the
table would only prove the table equals itself. ``New artwork`` and
``New Artwork`` are both here and are one row there, which is what makes
case-insensitivity worth asserting rather than assuming.
"""

UNSEEN = "Martian debut"
"""A value the table has never seen, standing in for the 24th spelling.

Whatever a wiki editor types next has to publish its note and no status; that is
the behaviour, and it needs a value nothing claims to demonstrate it.
"""

OTHER_UNSEEN = "Venusian debut"
"""A second value the table has never seen, standing in for the 25th spelling.

Two unresolved spellings must cost two lines and two summary rows; one is what
the counting collapses, not two."""

SET_LIST_PAGE = "Set Card Lists:Martian Invasion (TCG-EN)"
"""The page a reported value is said to have come from.

Named rather than passed inline because the printed line is only actionable if
it carries the page and the row, and that is what is asserted about it."""

ROW = "row Pot of Greed"
"""The row a reported value is said to have come from, spelled as the importer
spells it - the set list parse site passes ``f"row {name}"``."""

INHERITED_ROWS = 200
"""How many rows one template-level ``print=`` default is worth, for the check.

A conservative stand-in: the measured worst case is ``Speed Duel debut`` at 5113
rows across ~53 pages, all of them inheriting one parameter. The whole point of
the reporting is that this number changes the summary's count and nothing else,
so the check would still be meaningful at 5113 and is faster at 200."""

EXIT_TABLE_REGRESSED = 1
"""The vocabulary no longer does what it is written to do."""


def check() -> typing.List[str]:
    """Returns one line per way the vocabulary misbehaves, empty when it does not."""
    failures = []

    for spelling in MEASURED_REPRINTS:
        status = resolve_print_status(spelling)
        if status is not PrintStatus.REPRINT:
            got = repr(status.value) if status else "nothing"
            failures.append(f"{spelling!r} resolves to {got}, not 'reprint'")

    for spelling, expected in (
        ("new", PrintStatus.NEW),
        ("reprint", PrintStatus.REPRINT),
    ):
        for written in (spelling, spelling.upper(), spelling.capitalize()):
            if resolve_print_status(written) is not expected:
                failures.append(f"{written!r} no longer resolves to {expected.value!r}")

    for spelling in MEASURED_REPRINTS:
        for written in (spelling.lower(), spelling.upper(), f"  {spelling}  "):
            if resolve_print_status(written) is not PrintStatus.REPRINT:
                failures.append(f"{written!r} resolves differently from {spelling!r}")

    # The note's presence is a property of what the wiki said, not of what we
    # classify, so it is asserted over the unclassified value too.
    for spelling in MEASURED_REPRINTS + (UNSEEN,):
        if print_status_note(spelling) != spelling:
            failures.append(
                f"{spelling!r} produces the note "
                f"{print_status_note(spelling)!r} rather than itself"
            )
    for bare in ("new", "reprint", "New", "REPRINT", "  reprint  ", "", "   "):
        if print_status_note(bare) is not None:
            failures.append(
                f"{bare!r} produces the note {print_status_note(bare)!r}, "
                "but says nothing the enum does not"
            )

    if resolve_print_status(UNSEEN) is not None:
        failures.append(f"{UNSEEN!r} resolves to something; the table knows too much")

    claimed: typing.Dict[str, PrintStatus] = {}
    for status, spellings in PRINT_STATUS_SPELLINGS.items():
        for spelling in spellings:
            key = spelling.strip().lower()
            if key in claimed:
                failures.append(
                    f"{spelling!r} is claimed by both {claimed[key].value!r} "
                    f"and {status.value!r}"
                )
            claimed[key] = status

    return failures


class _Captured(logging.Handler):
    """Keeps every message logged to it, and prints none of them."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: typing.List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _capture(
    work: typing.Callable[[], None]
) -> typing.Tuple[typing.List[str], typing.List[str]]:
    """Runs ``work``, returning what it logged to the printed log and to the quiet one.

    Handlers rather than a patched ``logging.warning``, because routing is part
    of what is under test: ``EXPECTED_CONDITIONS`` does not propagate, so a
    record sent there lands in the second list and never in the first. That
    separation is the assertion that a dropped print status still prints.

    Attaching a handler to the root logger also stops ``logging.warning`` from
    calling ``basicConfig``, so this check emits nothing to stderr of its own.
    """
    printed = _Captured()
    quiet = _Captured()
    root = logging.getLogger()
    root.addHandler(printed)
    EXPECTED_CONDITIONS.addHandler(quiet)
    try:
        work()
    finally:
        root.removeHandler(printed)
        EXPECTED_CONDITIONS.removeHandler(quiet)
    return printed.messages, quiet.messages


def check_reporting() -> typing.List[str]:
    """Returns one line per way reporting an unresolved value misbehaves."""
    failures = []

    def report_inherited_rows() -> None:
        for _ in range(INHERITED_ROWS):
            report_unknown_print_status(SET_LIST_PAGE, UNSEEN, ROW)

    UNKNOWN_PRINT_STATUSES.clear()
    printed, quiet = _capture(report_inherited_rows)

    if len(printed) != 1:
        failures.append(
            f"{INHERITED_ROWS} rows carrying {UNSEEN!r} printed {len(printed)} "
            "warnings, not 1"
        )
    for named in (SET_LIST_PAGE, ROW, UNSEEN):
        if not any(named in message for message in printed):
            failures.append(f"no printed warning names {named!r}")
    if quiet:
        failures.append(
            f"{len(quiet)} warnings went to the quiet logger, which its own "
            "docstring forbids for a real card row"
        )
    if UNKNOWN_PRINT_STATUSES[UNSEEN.lower()] != INHERITED_ROWS:
        failures.append(
            f"{UNKNOWN_PRINT_STATUSES[UNSEEN.lower()]} of {INHERITED_ROWS} "
            f"occurrences of {UNSEEN!r} were counted"
        )

    summary, quiet_summary = _capture(log_unknown_print_statuses)
    if len(summary) != 2:
        failures.append(
            f"the summary of one unresolved spelling is {len(summary)} lines, "
            "not a header and one row"
        )
    elif summary[1] != f"\t{INHERITED_ROWS} x {UNSEEN.lower()}":
        failures.append(f"the summary's only row is {summary[1]!r}")
    if summary and str(INHERITED_ROWS) not in summary[0]:
        failures.append(
            f"the summary header {summary[0]!r} does not say how often the "
            "spelling appeared"
        )
    if quiet_summary:
        failures.append("the summary went to the quiet logger")

    def report_two_spellings() -> None:
        for written in (UNSEEN, UNSEEN.upper(), f"  {UNSEEN}  "):
            report_unknown_print_status(SET_LIST_PAGE, written, ROW)
        report_unknown_print_status(SET_LIST_PAGE, OTHER_UNSEEN, ROW)

    UNKNOWN_PRINT_STATUSES.clear()
    printed, _ = _capture(report_two_spellings)
    if len(printed) != 2:
        failures.append(
            f"two unresolved spellings printed {len(printed)} warnings, not 2"
        )
    # Resolution is case-insensitive, so the three ways of writing `UNSEEN` are
    # the one table row it would take to fix them, and one line about it.
    counted = dict(UNKNOWN_PRINT_STATUSES)
    if counted != {UNSEEN.lower(): 3, OTHER_UNSEEN.lower(): 1}:
        failures.append(f"the counts are {counted}, not one entry per spelling")

    UNKNOWN_PRINT_STATUSES.clear()
    printed, _ = _capture(log_unknown_print_statuses)
    if printed:
        failures.append(f"a run that resolved everything still logged {printed}")

    return failures


def main(argv: typing.List[str]) -> int:
    failures = check() + check_reporting()
    if failures:
        print("src/ygojson/print_status.py regressed:")
        for failure in failures:
            print(f"\t{failure}")
        return EXIT_TABLE_REGRESSED

    print(
        f"All {len(MEASURED_REPRINTS)} measured print values resolve to 'reprint', "
        f"case-insensitively, out of {len(PRINT_STATUS_SPELLINGS[PrintStatus.REPRINT])} "
        "written down; 'new' and 'reprint' produce no note and everything else does."
    )
    print(
        "A value the table has never seen prints 1 warning naming its page and "
        f"row across {INHERITED_ROWS} rows, and one summary row counting all "
        f"{INHERITED_ROWS}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
