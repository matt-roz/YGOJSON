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
import atexit
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

EXPECTED_CONDITIONS = logging.getLogger("ygojson.expected-conditions")
"""The logger for warnings that describe the parser working *correctly*.

Two call sites are most of the raw log and none of its signal: pages correctly
rejected as not being sets, and gallery lines correctly rejected as not being
cards. Records sent here reach the bucketing handler and nothing else, so they
are counted into the histogram and never printed. That is what makes silencing
them safe — a bucket that is 90% noise is still 10% signal, and a count answers
it: if the bucket triples, the histogram says so even though nothing printed.

Deliberately a logger of its own rather than a lower root level. Two places in
the Yugipedia importer log ``response.text`` when the *root* logger is at
debug, so dropping the root level to make these countable would put the body of
every HTTP response of a day-long run into the log.

Route a warning here only after re-deriving the bucket from a real run and
confirming the condition is one the parser is right about. Anything that could
be a real set or a real card row belongs in the printed log; silencing one of
those is worse than every line this suppresses.
"""

# Nothing printed: the root logger's handlers are where printing happens.
EXPECTED_CONDITIONS.propagate = False
# Counted whatever the root level is, so that `--logging ERROR` cannot stop
# these records before they are bucketed and quietly shorten the histogram.
EXPECTED_CONDITIONS.setLevel(logging.WARNING)
# A logger that neither propagates nor has a handler falls back to
# `logging.lastResort`, which prints to stderr. Without this, a process that
# never called `install_warning_buckets` would print the lines this suppresses.
EXPECTED_CONDITIONS.addHandler(logging.NullHandler())

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

_SAVED = False
"""Whether this process has already written its counts.

Read by the exit hook, which writes them only for a run that never reached the
end and said so itself. The end-of-run save deliberately happens *before* the
histogram is logged — those lines are warnings too — so a second, later write
would fold the summary into the counts the run's sum adds up.
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


def _sorted_rows(
    rows: typing.List[typing.Tuple[str, int, str]]
) -> typing.List[typing.Tuple[str, int, str]]:
    """Orders ``(location, count, example)`` rows largest first.

    Largest first because the biggest problem should be the first thing read.
    Ties break on location, so that the same run twice renders the same table —
    and so that one job's histogram and the run's sum of ten of them order
    their shared rows the same way.
    """
    return sorted(rows, key=lambda row: (-row[1], row[0]))


def _bucket_rows() -> typing.List[typing.Tuple[str, int, str]]:
    """This process's buckets as ``(location, count, example)``, largest first."""
    return _sorted_rows(
        [
            (_location(pathname, lineno), count, WARNING_EXAMPLES[(pathname, lineno)])
            for (pathname, lineno), count in WARNING_BUCKETS.items()
        ]
    )


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

    The same handler goes on :data:`EXPECTED_CONDITIONS` as well as the root
    logger, because that one does not propagate: it is the only way its records
    reach the counts at all, and skipping it would drop two of the largest
    buckets out of the histogram rather than merely out of the log.
    """
    handler = _WarningBucketer()
    handler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(handler)
    EXPECTED_CONDITIONS.addHandler(handler)
    atexit.register(_save_warning_buckets_at_exit)


def save_warning_buckets() -> None:
    """Writes this process's buckets to :data:`WARNING_BUCKETS_PATH`.

    Machine-readable, so that summing the ten jobs of a run is addition rather
    than a regex over a megabyte of log text. Written even when nothing warned,
    so that a job with no warnings is distinguishable from a job that died
    before it could say.
    """
    global _SAVED
    buckets = {
        location: {"count": count, "example": example}
        for location, count, example in _bucket_rows()
    }
    with open(WARNING_BUCKETS_PATH, "w", encoding="utf-8") as file:
        json.dump(buckets, file, indent=2)
    _SAVED = True


def _save_warning_buckets_at_exit() -> None:
    """Writes the counts of a process that stopped before it could report them.

    An unhandled exception is how this pipeline actually stops early — every
    Yugipedia API error the importer does not retry aborts the import — and
    those runs are the ones worth reading. Without this the job's whole share
    of the run's warnings would be missing from the sum, silently and in the
    direction that makes a broken run look quiet.

    It does not cover a process killed outright, by a cancelled job or a runner
    timeout; nothing inside the process can. That gap is why the cross-job
    summary states how many jobs it summed rather than letting a short sum read
    as the run's total.
    """
    if not _SAVED:
        save_warning_buckets()


def merge_warning_buckets(
    contributions: typing.Iterable[typing.Dict[str, typing.Dict[str, typing.Any]]]
) -> typing.List[typing.Tuple[str, int, str]]:
    """Sums the saved buckets of several processes into one table of rows.

    A run is ten pipeline processes and partition assignment is an unseeded
    shuffle, so which pages a given job saw is different every run and its own
    figure is comparable to nothing. The sum over the run is the comparable
    one: the page list is rebuilt every run, so the same corpus is behind it
    each time.

    Locations are the key because that is what :func:`save_warning_buckets`
    wrote them under, already relative to the checkout so that ten different
    working directories still agree. Each bucket keeps the example of the first
    contribution to carry it, in the order the caller passes them, so that the
    same artifacts render the same table.
    """
    counts: typing.Counter[str] = collections.Counter()
    examples: typing.Dict[str, str] = {}
    for buckets in contributions:
        for location, bucket in buckets.items():
            counts[location] += bucket["count"]
            examples.setdefault(location, bucket["example"])
    return _sorted_rows(
        [(location, count, examples[location]) for location, count in counts.items()]
    )


def render_warning_buckets(
    rows: typing.List[typing.Tuple[str, int, str]],
    contributors: typing.Sequence[str],
    expected: typing.Optional[int] = None,
) -> typing.List[str]:
    """The summed histogram as lines, headed by how much of the run it covers.

    Coverage is stated before any figure, because a sum missing a job's counts
    is a lower bound and otherwise reads exactly like a complete one — which is
    the failure this whole instrument exists to prevent. ``expected`` is how
    many jobs were meant to contribute; ``None`` says the caller does not know,
    which is honest for a hand-assembled sum and still refuses to claim
    completeness.
    """
    lines = []
    if expected is None:
        lines.append(f"Summed the warning counts of {len(contributors)} job(s).")
    elif len(contributors) == expected:
        lines.append(f"Summed the warning counts of all {expected} jobs of the run.")
    else:
        lines.append(
            f"INCOMPLETE: summed {len(contributors)} of the run's {expected} jobs. "
            "This is a partial sum, not the run's total."
        )
    if contributors:
        lines.append("Contributing jobs: " + ", ".join(contributors))
    lines.append("")
    if not rows:
        lines.append("No warnings were counted.")
        return lines
    total = sum(count for _, count, _ in rows)
    lines.append(f"{total} warnings from {len(rows)} call sites:")
    for location, count, example in rows:
        lines.append(f"\t{count} x {location}: {example}")
    return lines


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
