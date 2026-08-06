# Sums the warning counts every job of a run uploaded, for the run summary.
#
# A run is ten pipeline processes - a pre-stage, eight partition jobs and a
# post-stage - so the per-process histogram prints ten times, each covering a
# tenth of the corpus. Partition assignment is an unseeded shuffle, so a job's
# own figure is not even comparable to the same job's figure last run. The sum
# over the run is.
#
# The counts travel as workflow artifacts, not through the `temp`/`data`
# caches: every cache step in the workflow is failure-tolerant by design, so a
# cache that failed to save would hand on stale counts in silence, and a sum
# quietly short by one job's warnings is worse than no sum at all because it
# presents as a measurement. This script therefore says how many jobs it found
# whenever that is not all of them.
#
# It reports; it never fails a build. The exit status distinguishes a partial
# sum from a complete one so the workflow can raise an annotation, and the
# workflow treats neither as a failure.
import argparse
import json
import os
import os.path
import sys
import typing

from ygojson.warnings import merge_warning_buckets, render_warning_buckets

EXIT_INCOMPLETE = 2
"""Fewer jobs' counts were summed than the run expected, or one was unreadable.

Kept distinct from a clean exit, and given the same value as
:data:`report_output_diff.EXIT_COULD_NOT_COMPARE`, so that the workflow can
annotate a partial sum. A partial sum is still printed and still worth reading;
what must never happen is it being read as the run's total.
"""

COUNTS_FILENAME = "warning-buckets.json"
"""The name each job's counts file carries inside its artifact.

Change ``WARNING_BUCKETS_PATH`` in the warnings module and this constant must
move with it. Nothing would notice if they drifted: a file this does not match
is simply not found, and the run would report a sum short by that job's
warnings rather than failing.
"""

ARTIFACT_PREFIX = "warning-buckets-"
"""What every uploading job's artifact name starts with in the workflow.

Stripped so that a contributor reads as ``yugipedia-3`` rather than as the
artifact it arrived in. Only presentational - a downloaded artifact whose name
lost this prefix is still summed, under its directory name.
"""


def read_counts(
    directory: str,
) -> typing.Tuple[
    typing.List[typing.Tuple[str, typing.Dict[str, typing.Dict[str, typing.Any]]]],
    typing.List[str],
]:
    """Reads every job's counts under ``directory`` as ``(job, buckets)`` pairs.

    ``actions/download-artifact`` puts each artifact in its own directory, so
    the directory holding a counts file names the job that uploaded it. Sorted
    by that name, because the walk order is arbitrary and the merge takes each
    bucket's example from the first contribution to carry it.

    A counts file that cannot be read is returned separately rather than
    skipped: a process killed part-way through writing one leaves exactly that,
    and the job it came from must be reported missing rather than counted.
    """
    contributions = []
    unreadable = []
    for root, _, filenames in os.walk(directory):
        if COUNTS_FILENAME not in filenames:
            continue
        job = os.path.basename(root)
        if job.startswith(ARTIFACT_PREFIX):
            job = job[len(ARTIFACT_PREFIX) :]
        try:
            with open(os.path.join(root, COUNTS_FILENAME), encoding="utf-8") as file:
                contributions.append((job, json.load(file)))
        except (OSError, ValueError) as error:
            unreadable.append(f"{job} ({type(error).__name__}: {error})")
    return sorted(contributions, key=lambda pair: pair[0]), sorted(unreadable)


def main(argv: typing.List[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Sum the warning counts uploaded by every job of a run."
    )
    parser.add_argument(
        "directory",
        metavar="DIRECTORY",
        help="Where the jobs' counts artifacts were downloaded",
    )
    parser.add_argument(
        "--expected",
        type=int,
        default=None,
        metavar="N",
        help="How many jobs were meant to upload counts, so that a sum short "
        "of that says so instead of reading as the run's total",
    )
    args = parser.parse_args(argv[1:])

    contributions, unreadable = read_counts(args.directory)
    rows = merge_warning_buckets(buckets for _, buckets in contributions)
    for line in render_warning_buckets(
        rows, [job for job, _ in contributions], args.expected
    ):
        print(line)
    for job in unreadable:
        print(f"Counts from {job} could not be read, and are not in the sum above.")

    if unreadable:
        return EXIT_INCOMPLETE
    if args.expected is not None and len(contributions) < args.expected:
        return EXIT_INCOMPLETE
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
