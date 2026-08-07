# Fails the build when the print status vocabulary stops behaving.
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
import sys
import typing

from ygojson.database import PrintStatus
from ygojson.print_status import (
    PRINT_STATUS_SPELLINGS,
    print_status_note,
    resolve_print_status,
)

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


def main(argv: typing.List[str]) -> int:
    failures = check()
    if failures:
        print("The print status vocabulary in src/ygojson/print_status.py regressed:")
        for failure in failures:
            print(f"\t{failure}")
        return EXIT_TABLE_REGRESSED

    print(
        f"All {len(MEASURED_REPRINTS)} measured print values resolve to 'reprint', "
        f"case-insensitively, out of {len(PRINT_STATUS_SPELLINGS[PrintStatus.REPRINT])} "
        "written down; 'new' and 'reprint' produce no note and everything else does."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
