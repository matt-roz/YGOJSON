# One histogram of a run's warnings, bucketed by the code that emitted them.
#
# A run emits thousands of warning lines across ten jobs, and nothing in the log
# distinguishes one line repeated a thousand times from the one line that
# appeared for the first time last night. Reading a run therefore meant
# downloading every job's log and grouping it by hand, which is how two data
# corruptions shipped repeatedly in green builds.
#
# The identity a warning is bucketed by is its source location, because that is
# the one identity the logging module already knows exactly. Messages are
# f-strings, interpolated long before they reach a handler, so grouping by their
# text means inferring a template back out of ``Found set without set table:
# Duel Terminal`` — while ``record.pathname`` and ``record.lineno`` hand the
# same grouping over for free, and point at the code to fix. Nothing changes at
# the 73 warning call sites, so coverage is all of them on the first run rather
# than whichever ones somebody got around to migrating.
#
# This is a net under the two summaries that count *values* — unresolved rarity
# spellings in ``rarity.py``, image misses by cause in the Yugipedia importer —
# not a replacement for them. A source location cannot say which spelling.
import collections
import json
import logging
import os
import os.path
import typing

from .database import ROOT_DIR

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
"""The directory holding YGOJSON's own modules.

The handler sits on the root logger, so ``requests`` and ``urllib3`` reach it
too. This is the test for telling their records from ours; widen it and
somebody else's library can take the top row of a histogram about our pipeline.
"""

WARNING_BUCKETS_PATH = os.path.join(
    ROOT_DIR if os.access(ROOT_DIR, os.W_OK) else os.curdir, "warning-buckets.json"
)
"""Where a process writes its own warning counts, to be summed across a run.

Deliberately neither ``TEMP_DIR`` nor ``DATA_DIR``. Both are restored from a
shared cache at the start of every CI job, so counts written to either would
arrive in the next job already populated and be added to a second time — and
every cache step is failure-tolerant, so a doubled total would present as a
measurement with nothing saying otherwise. The checkout root is the one place
in the tree each job starts empty.
"""

MAX_EXAMPLE_LENGTH = 120
"""How much of a bucket's first message the histogram keeps.

Too short and the example stops saying what the bucket is about, which is the
only reason it is there. Too long and one warning carrying a page of wikitext
turns the histogram back into the log it exists to replace.
"""

WARNING_BUCKETS: typing.Counter[typing.Tuple[str, int]] = collections.Counter()
"""How many warning-or-worse records each source location in YGOJSON emitted.

Keyed by ``(pathname, lineno)``, so every one of the warning call sites is
counted without being touched, and each count names the code to go and read.
"""

WARNING_EXAMPLES: typing.Dict[typing.Tuple[str, int], str] = {}
"""The first message each bucket of :data:`WARNING_BUCKETS` produced.

One example rather than all of them, because the histogram is a table somebody
reads rather than the log again; the first rather than the last, so that a row
means the same thing however far into a run it is read.
"""

THIRD_PARTY_WARNINGS: typing.Counter[str] = collections.Counter()
"""Warning-or-worse records from outside YGOJSON, counted per logger.

Kept out of the histogram so that a library's retry chatter cannot outrank our
own biggest bucket, but counted rather than dropped: they still print in the
raw log, and a run where a dependency suddenly warns ten thousand times is
worth one line at the bottom of the summary.
"""


def _shorten(message: str) -> str:
    """Collapses a message to one bounded line, for use as a bucket's example."""
    line = " ".join(message.split())
    if len(line) > MAX_EXAMPLE_LENGTH:
        line = line[: MAX_EXAMPLE_LENGTH - 3] + "..."
    return line


def _location(pathname: str, lineno: int) -> str:
    """Names a source location the way both the histogram and the counts file do.

    Relative to the package's parent directory and always posix-separated: the
    counts of ten jobs get summed by their location, so a key that carried an
    absolute path would stop matching the moment a checkout moved.
    """
    module = os.path.relpath(pathname, os.path.dirname(PACKAGE_DIR))
    return "{}:{}".format(module.replace(os.sep, "/"), lineno)


def _bucket_rows() -> typing.List[typing.Tuple[str, int, str]]:
    """The buckets as ``(location, count, example)``, largest first.

    Largest first because the biggest problem should be the first thing read.
    Ties break on location, so that the same run twice renders the same table.
    """
    rows = [
        (_location(pathname, lineno), count, WARNING_EXAMPLES[(pathname, lineno)])
        for (pathname, lineno), count in WARNING_BUCKETS.items()
    ]
    rows.sort(key=lambda row: (-row[1], row[0]))
    return rows


class _WarningBucketer(logging.Handler):
    """Buckets warning-or-worse records by the source location that emitted them.

    ``record.pathname`` and ``record.lineno`` are the *caller's*, not the
    logging module's, even though every site here warns through the
    module-level ``logging.warning()`` function: the standard library skips its
    own frames when it walks the stack for a caller.
    """

    def emit(self, record: logging.LogRecord) -> None:
        pathname = os.path.abspath(record.pathname)
        if not pathname.startswith(PACKAGE_DIR + os.sep):
            THIRD_PARTY_WARNINGS[record.name] += 1
            return
        bucket = (pathname, record.lineno)
        WARNING_BUCKETS[bucket] += 1
        if bucket not in WARNING_EXAMPLES:
            WARNING_EXAMPLES[bucket] = _shorten(record.getMessage())


def install_warning_buckets() -> None:
    """Starts counting warnings, for the histogram at the end of the run.

    Called once from the entry point beside the logging configuration, because
    a handler installed any later silently misses everything that ran before
    it, and a histogram that is quietly short is worse than none — it presents
    as a measurement.
    """
    handler = _WarningBucketer()
    handler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(handler)


def save_warning_buckets() -> None:
    """Writes this process's buckets to :data:`WARNING_BUCKETS_PATH`.

    Machine-readable, so that summing the ten jobs of a run is addition rather
    than a regex over a megabyte of log text. Written even when nothing warned,
    so that a job with no warnings is distinguishable from a job that died
    before it could say.
    """
    buckets = {
        location: {"count": count, "example": example}
        for location, count, example in _bucket_rows()
    }
    with open(WARNING_BUCKETS_PATH, "w", encoding="utf-8") as file:
        json.dump(buckets, file, indent=2)


def log_warning_buckets() -> None:
    """Logs one row per source location that warned this run, largest first.

    Logged after :func:`save_warning_buckets`, so that the summary's own lines
    — warnings themselves, and counted like any other — cannot land in the
    counts a later job sums.
    """
    if not WARNING_BUCKETS and not THIRD_PARTY_WARNINGS:
        return
    rows = _bucket_rows()
    logging.warning(
        f"{sum(WARNING_BUCKETS.values())} warnings from {len(rows)} call sites:"
    )
    for location, count, example in rows:
        logging.warning(f"\t{count} x {location}: {example}")
    if THIRD_PARTY_WARNINGS:
        libraries = ", ".join(
            f"{count} x {logger}"
            for logger, count in sorted(
                THIRD_PARTY_WARNINGS.items(), key=lambda kv: (-kv[1], kv[0])
            )
        )
        logging.warning(f"\tand from outside YGOJSON: {libraries}")
