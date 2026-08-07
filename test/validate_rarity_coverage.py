# Fails the build when Yugipedia defines a rarity we cannot resolve.
#
# Yugipedia grows rarities. Every one it grows that ``RARITIES`` has no row for
# costs every printing that names it: the rarity resolves to nothing, so the
# row contributes no printing and its gallery image is looked up under a
# filename built from the raw string. That is invisible in a run's output and
# was last found months later, in a log.
#
# This lives here, next to the schema validator, and not in the importer,
# because the database job is one strictly sequential chain in which a failure
# abandons the rest of a day-long run. It fails in seconds on the condition
# that matters — the wiki knows a rarity we do not — before any importing,
# rather than on the accident of whether a set using that rarity happened to be
# imported that night. The importer still publishes such a printing without a
# rarity and warns; see :func:`ygojson.rarity.report_unknown_rarity`.
import re
import sys
import typing

from ygojson.importers.yugipedia import make_request
from ygojson.rarity import RARITIES, resolve_abbreviation, resolve_rarity

MODULE_PAGE = "Module:Data/static/rarity/data"
"""The Lua module that is the authority on what rarities Yugipedia has.

``Template:Rarity`` and the set list and gallery templates all render through
this module; the template itself holds no data. Check anything else and a
rarity can be added here without the check noticing.
"""

EXIT_UNMODELLED_RARITY = 1
"""Yugipedia defines a rarity ``RARITIES`` has no row for. A real coverage gap."""

EXIT_CHECK_DID_NOT_RUN = 2
"""The module could not be fetched or read, so nothing was compared.

Kept distinct from :data:`EXIT_UNMODELLED_RARITY` so that a wiki outage or a
restructured module cannot be mistaken for a missing rarity — the two want
completely different responses.
"""

EXIT_UNRESOLVED_SPELLING = 3
"""Yugipedia accepts a spelling of a modelled rarity that we do not.

Distinct from :data:`EXIT_UNMODELLED_RARITY` because it costs less and is fixed
differently: the rarity is modelled and every other spelling of it still works,
so only the printings written that particular way lose their rarity, and the
repair is a string in an existing row rather than a new one."""

MAIN_TABLE = re.compile(r"\blocal main = \{(.*?)\n\}", re.DOTALL)
"""The module's ``main`` table, which is one entry per rarity."""

NORMALIZE_TABLE = re.compile(r"\blocal normalize = \{(.*?)\n\}", re.DOTALL)
"""The module's ``normalize`` table, which is one entry per accepted spelling.

This is how the wiki's own templates accept what editors actually type, so it
is the list of strings a set list or gallery can legitimately contain. We read
wikitext rather than rendered output, so a spelling here that we do not accept
is a printing published without its rarity - and normalization cannot rescue
it, because `duelterminalnormalparallel` and `duelterminalnormalparallelrare`
differ by a word, not by punctuation."""

ALIAS_ROW = re.compile(r"\['(?P<alias>[^']+)'\]\s*=\s*'(?P<key>[^']+)'")
"""One ``['alias'] = 'key'`` entry of the ``normalize`` table."""

RARITY_ROW = re.compile(r"\['(?P<key>[^']+)'\]\s*=\s*\{(?P<body>[^}]*)\}")
"""One ``['key'] = { abbr = 'X', full = 'Y' }`` entry of the ``main`` table."""

ROW_KEY = re.compile(r"\['[^']+'\]\s*=")
"""Just the left-hand side of an entry, to count what :data:`RARITY_ROW` must find.

A regex that reads only some of the table would otherwise pass this check
while comparing nothing."""


class WikiRarity(typing.NamedTuple):
    """One rarity Yugipedia defines, and the two ways its module names it."""

    key: str
    abbreviation: str
    name: str


def fetch_module() -> str:
    """Returns the wikitext of :data:`MODULE_PAGE`.

    Goes through the importer's :func:`make_request` so this obeys the same
    rate limit, retries the same transient API errors, and sends the same
    ``User-Agent`` — which Yugipedia's API policy requires to carry contact
    information, on pain of being blocked without warning.
    """
    response = make_request(
        {"action": "parse", "page": MODULE_PAGE, "prop": "wikitext"}
    )
    return response.json()["parse"]["wikitext"]


def _field(body: str, name: str) -> str:
    """Returns a ``name = 'value'`` field of a ``main`` entry. Lua quotes either way."""
    match = re.search(name + r"\s*=\s*(?:'([^']*)'|\"([^\"]*)\")", body)
    if not match:
        raise ValueError(f"entry has no {name}: {body!r}")
    return match.group(1) if match.group(1) is not None else match.group(2)


def parse_rarities(wikitext: str) -> typing.Tuple[WikiRarity, ...]:
    """Returns every rarity the module's ``main`` table defines.

    Raises if the table cannot be found or cannot be read whole, so that a
    module someone restructured is reported as an unreadable module rather than
    as rarities nobody models.
    """
    table = MAIN_TABLE.search(wikitext)
    if not table:
        raise ValueError("no 'local main = {...}' table")
    body = table.group(1)
    rarities = tuple(
        WikiRarity(
            key=row.group("key"),
            abbreviation=_field(row.group("body"), "abbr"),
            name=_field(row.group("body"), "full"),
        )
        for row in RARITY_ROW.finditer(body)
    )
    entries = len(ROW_KEY.findall(body))
    if len(rarities) != entries:
        raise ValueError(f"read {len(rarities)} of the table's {entries} entries")
    return rarities


def parse_aliases(wikitext: str) -> typing.Dict[str, str]:
    """Returns every spelling the module's ``normalize`` table accepts.

    Raises if the table cannot be found or cannot be read whole, for the same
    reason :func:`parse_rarities` does: a restructured module must report as
    unreadable rather than as a wiki that suddenly accepts no spellings.
    """
    table = NORMALIZE_TABLE.search(wikitext)
    if not table:
        raise ValueError("no 'local normalize = {...}' table")
    body = table.group(1)
    aliases = {row.group("alias"): row.group("key") for row in ALIAS_ROW.finditer(body)}
    entries = len(ROW_KEY.findall(body))
    if len(aliases) != entries:
        raise ValueError(f"read {len(aliases)} of the table's {entries} spellings")
    return aliases


def report_spelling_gaps(
    aliases: typing.Dict[str, str], rarities: typing.Tuple[WikiRarity, ...]
) -> typing.List[str]:
    """Returns one line per spelling Yugipedia accepts that we do not resolve.

    Compared against the rarity the module maps the spelling onto, not against
    each other, so a spelling that resolves to the *wrong* rarity is reported
    as loudly as one that resolves to nothing.

    Spellings whose canonical key is not in ``main`` are skipped rather than
    reported: that is a broken row of the wiki's own table, and
    :func:`report_gaps` is the check that owns the ``main`` table.
    """
    by_key = {rarity.key: rarity for rarity in rarities}
    gaps = []
    for alias, key in sorted(aliases.items()):
        rarity = by_key.get(key)
        if rarity is None:
            continue
        ours = resolve_abbreviation(alias)
        if ours is None:
            gaps.append(
                f"'{alias}' resolves to nothing; Yugipedia reads it as "
                f"{rarity.name} ({rarity.abbreviation})"
            )
        elif ours != rarity.abbreviation:
            gaps.append(
                f"'{alias}' resolves to '{ours}' for us and to "
                f"'{rarity.abbreviation}' ({rarity.name}) for Yugipedia"
            )
    return gaps


def report_gaps(rarities: typing.Tuple[WikiRarity, ...]) -> typing.List[str]:
    """Returns one line per rarity of the wiki's we do not resolve as it does.

    The comparison is deliberately one-way. ``RARITIES`` keeps rarities
    Yugipedia's module has dropped — Parallel Rare, Parallel Common, Hobby
    Rare, Kaiba Corporation Secret Rare, Duel Terminal Parallel Common — and
    ``ultra-green``, which it never had; removing them would break published
    data and old wikitext still spells them. Requiring the two tables to be
    equal would therefore fail forever.
    """
    gaps = []
    for rarity in rarities:
        members = {resolve_rarity(spelling) for spelling in (rarity.key, rarity.name)}
        if members == {None}:
            gaps.append(f"{rarity.name} ({rarity.abbreviation}) resolves to nothing")
        elif None in members:
            gaps.append(
                f"{rarity.name} ({rarity.abbreviation}) resolves under one of "
                f"'{rarity.key}' and '{rarity.name}' but not the other"
            )
        elif len(members) > 1:
            spelt = ", ".join(sorted(member.value for member in members))
            gaps.append(
                f"{rarity.name} ({rarity.abbreviation}) resolves to two "
                f"different rarities: {spelt}"
            )
        ours = resolve_abbreviation(rarity.name)
        # A name nothing resolves has no abbreviation of ours to disagree with,
        # and the line above already says so; don't say it twice.
        if ours is not None and ours != rarity.abbreviation:
            gaps.append(
                f"{rarity.name} is abbreviated '{ours}' by us and "
                f"'{rarity.abbreviation}' by Yugipedia"
            )
    return gaps


def main(argv: typing.List[str]) -> int:
    try:
        wikitext = fetch_module()
        rarities = parse_rarities(wikitext)
        aliases = parse_aliases(wikitext)
    except Exception as error:
        # Anything at all that goes wrong before there is a table to compare
        # means the check did not run. Saying so is the whole point: an outage
        # must never read as a rarity nobody models.
        print(f"Could not read {MODULE_PAGE}: {type(error).__name__}: {error}")
        print("Nothing was compared, so this is not a missing rarity.")
        return EXIT_CHECK_DID_NOT_RUN

    gaps = report_gaps(rarities)
    if gaps:
        print(f"Yugipedia defines rarities {MODULE_PAGE} and RARITIES disagree on:")
        for gap in gaps:
            print(f"\t{gap}")
        print(
            "Add or correct a row in src/ygojson/rarity.py for each, using "
            f"the abbreviation {MODULE_PAGE} publishes."
        )
        return EXIT_UNMODELLED_RARITY

    spelling_gaps = report_spelling_gaps(aliases, rarities)
    if spelling_gaps:
        print(f"Yugipedia accepts spellings in {MODULE_PAGE} that we do not:")
        for gap in spelling_gaps:
            print(f"\t{gap}")
        print(
            "Add each to the `spellings` tuple of the matching row in "
            "src/ygojson/rarity.py."
        )
        return EXIT_UNRESOLVED_SPELLING

    print(
        f"All {len(rarities)} rarities in {MODULE_PAGE} resolve, with "
        f"Yugipedia's abbreviation, and so do all {len(aliases)} spellings its "
        f"normalize table accepts. ({len(RARITIES)} rows in RARITIES; the "
        "rest are rarities Yugipedia has dropped, which is allowed.)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
