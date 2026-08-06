# The rarity vocabulary: one canonical table, and every lookup derived from it.
#
# The authority for what a rarity is called is Yugipedia's Lua module
# ``Module:Data/static/rarity/data``
# (https://yugipedia.com/wiki/Module:Data/static/rarity/data), which is what
# ``Template:Rarity`` and the set list and gallery templates render through. It
# publishes a ``normalize`` table of aliases and a ``main`` table of
# ``{abbr, full}`` per rarity; ``RARITIES`` below mirrors ``main``, section for
# section, so that a rarity the wiki adds is one row here.
import collections
import logging
import re
import typing

from .database import CardRarity


class Rarity(typing.NamedTuple):
    """One rarity in the vocabulary, and every way a wiki page spells it.

    ``key`` is Yugipedia's canonical key for the rarity, ``abbreviation`` is the
    official abbreviation it publishes, ``card_rarity`` is the schema member the
    rarity maps onto, and ``spellings`` is every *other* accepted spelling — the
    abbreviation is always accepted and is never repeated there.

    ``card_rarity`` is ``None`` for a rarity the schema has no member for. Such
    a row still resolves its abbreviation, which is what gallery image filenames
    are built from, so dropping it would rename images.
    """

    key: str
    abbreviation: str
    card_rarity: typing.Optional[CardRarity]
    spellings: typing.Tuple[str, ...] = ()


RARITIES: typing.Tuple[Rarity, ...] = (
    # Standard non-foil
    Rarity("c", "C", CardRarity.COMMON, ("common",)),
    Rarity("nr", "NR", CardRarity.SHORTPRINT, ("normal", "Normal Rare")),
    Rarity("sp", "SP", CardRarity.SHORTPRINT, ("short print",)),
    Rarity("ssp", "SSP", CardRarity.SHORTPRINT, ("super short print",)),
    Rarity("r", "R", CardRarity.RARE, ("rare",)),
    # Standard foil
    Rarity("sr", "SR", CardRarity.SUPER, ("super", "Super Rare")),
    Rarity(
        "ur",
        "UR",
        CardRarity.ULTRA,
        (
            "ultra",
            "Ultra Rare",
            # not official, but typos were made in a few galleries (?)
            "rar",
        ),
    ),
    Rarity("utr", "UtR", CardRarity.ULTIMATE, ("ultimate", "Ultimate Rare")),
    Rarity("gr", "GR", CardRarity.GHOST, ("ghost", "Ghost Rare")),
    Rarity("hgr", "HGR", CardRarity.GHOST, ("hr", "holographic", "Holographic Rare")),
    # Secret
    Rarity("scr", "ScR", CardRarity.SECRET, ("se", "secret", "Secret Rare")),
    Rarity(
        "pscr",
        "PScR",
        CardRarity.PRISMATICSECRET,
        ("prismatic secret", "Prismatic Secret Rare"),
    ),
    Rarity(
        "uscr", "UScR", CardRarity.ULTRASECRET, ("ultra secret", "Ultra Secret Rare")
    ),
    Rarity(
        "scur", "ScUR", CardRarity.SECRETULTRA, ("secret ultra", "Secret Ultra Rare")
    ),
    Rarity(
        "escr", "EScR", CardRarity.EXTRASECRET, ("extra secret", "Extra Secret Rare")
    ),
    Rarity(
        "20scr", "20ScR", CardRarity.TWENTITHSECRET, ("20th secret", "20th Secret Rare")
    ),
    Rarity(
        "10000scr",
        "10000ScR",
        CardRarity.TENTHOUSANDSECRET,
        ("10000 secret", "10000 Secret Rare"),
    ),
    Rarity(
        "qcscr",
        "QCScR",
        CardRarity.TWENTYFIFTHSECRET,
        ("quarter century secret", "Quarter Century Secret Rare"),
    ),
    Rarity(
        "str",
        "StR",
        CardRarity.STARLIGHT,
        ("starlight", "Starlight Rare", "alt", "altr", "alternate", "Alternate Rare"),
    ),
    Rarity("gmr", "GMR", CardRarity.GRANDMASTER, ("grand master", "Grand Master Rare")),
    # Precious
    Rarity("gur", "GUR", CardRarity.GOLD, ("gold", "Gold Rare")),
    Rarity("gscr", "GScR", CardRarity.GOLDSECRET, ("gold secret", "Gold Secret Rare")),
    Rarity("ggr", "GGR", CardRarity.GOLDGHOST, ("ghost/gold", "Ghost/Gold Rare")),
    Rarity("pgr", "PGR", CardRarity.PREMIUMGOLD, ("premium gold", "Premium Gold Rare")),
    Rarity("plr", "PlR", CardRarity.PLATINUM, ("platinum", "Platinum Rare")),
    Rarity(
        "plscr",
        "PlScR",
        CardRarity.PLATINUMSECRET,
        ("platinum secret", "Platinum Secret Rare"),
    ),
    # Millennium
    Rarity("mlr", "MLR", CardRarity.MILLENIUM, ("mr", "millennium", "Millennium Rare")),
    Rarity(
        "mlsr",
        "MLSR",
        CardRarity.MILLENIUMSUPER,
        ("millennium super", "Millennium Super Rare"),
    ),
    Rarity(
        "mlur",
        "MLUR",
        CardRarity.MILLENIUMULTRA,
        ("millennium ultra", "Millennium Ultra Rare"),
    ),
    Rarity(
        "mlscr",
        "MLScR",
        CardRarity.MILLENIUMSECRET,
        ("millennium secret", "Millennium Secret Rare"),
    ),
    Rarity(
        "mlgr",
        "MLGR",
        CardRarity.MILLENIUMGOLD,
        ("millennium gold", "Millennium Gold Rare"),
    ),
    # Parallel
    Rarity(
        "npr",
        "NPR",
        CardRarity.COMMONPARALLEL,
        ("normal parallel", "Normal Parallel Rare"),
    ),
    Rarity(
        "rpr", "RPR", CardRarity.RAREPARALLEL, ("rare parallel", "Rare Parallel Rare")
    ),
    Rarity(
        "spr",
        "SPR",
        CardRarity.SUPERPARALLEL,
        ("super parallel", "Super Parallel Rare"),
    ),
    Rarity(
        "upr",
        "UPR",
        CardRarity.ULTRAPARALLEL,
        ("ultra parallel", "Ultra Parallel Rare"),
    ),
    Rarity(
        "scpr",
        "ScPR",
        CardRarity.SECRETPARALLEL,
        ("secret parallel", "Secret Parallel Rare"),
    ),
    Rarity(
        "escpr",
        "EScPR",
        CardRarity.EXTRASECRETPARALLEL,
        ("extra secret parallel", "Extra Secret Parallel Rare"),
    ),
    Rarity(
        "hgpr",
        "HGPR",
        CardRarity.GHOSTPARALLEL,
        ("holographic parallel", "Holographic Parallel Rare"),
    ),
    # Duel Terminal
    Rarity("dnpr", "DNPR", CardRarity.DTPC, ("Duel Terminal Normal Parallel Rare",)),
    Rarity(
        "dnrpr",
        "DNRPR",
        CardRarity.DTPSP,
        ("Duel Terminal Normal Rare Parallel Rare",),
    ),
    Rarity(
        "drpr",
        "DRPR",
        CardRarity.DTRPR,
        ("duel terminal parallel", "Duel Terminal Rare Parallel Rare"),
    ),
    Rarity(
        "dspr",
        "DSPR",
        CardRarity.DTSPR,
        ("duel terminal super parallel", "Duel Terminal Super Parallel Rare"),
    ),
    Rarity(
        "dupr",
        "DUPR",
        CardRarity.DTUPR,
        ("duel terminal ultra parallel", "Duel Terminal Ultra Parallel Rare"),
    ),
    Rarity(
        "dscpr",
        "DScPR",
        CardRarity.DTSCPR,
        ("duel terminal secret parallel", "Duel Terminal Secret Parallel Rare"),
    ),
    # Kaiba Corporation
    Rarity(
        "kcc",
        "KCC",
        CardRarity.KCCOMMON,
        ("kcn", "kaiba corporation common", "kaiba corporation normal"),
    ),
    Rarity(
        "kcr", "KCR", CardRarity.KCRARE, ("kaiba corporation", "Kaiba Corporation Rare")
    ),
    Rarity(
        "kcsr",
        "KCSR",
        CardRarity.KCSUPER,
        ("kaiba corporation super", "Kaiba Corporation Super Rare"),
    ),
    Rarity(
        "kcur",
        "KCUR",
        CardRarity.KCULTRA,
        ("kaiba corporation ultra", "Kaiba Corporation Ultra Rare"),
    ),
    # Rush Duel
    Rarity("rr", "RR", CardRarity.RUSH, ("rush", "Rush Rare")),
    Rarity("grr", "GRR", CardRarity.GOLDRUSH, ("gold rush", "Gold Rush Rare")),
    Rarity("orr", "ORR", CardRarity.OVERRUSH, ("over rush", "Over Rush Rare")),
    Rarity(
        "forr",
        "FORR",
        CardRarity.FULLOVERRUSH,
        ("full over rush", "Full Over Rush Rare"),
    ),
    # Colourful
    Rarity(
        "urblue",
        "URBlue",
        CardRarity.ULTRA_BLUE,
        ("Ultra Rare (Special Blue Version)",),
    ),
    Rarity(
        "urpurple",
        "URPurple",
        CardRarity.ULTRA_PURPLE,
        ("Ultra Rare (Special Purple Version)",),
    ),
    Rarity(
        "urred",
        "URRed",
        CardRarity.ULTRA_RED,
        ("Ultra Rare (Special Red Version)",),
    ),
    Rarity(
        "scrblue",
        "ScRBlue",
        CardRarity.SECRET_BLUE,
        ("Secret Rare (Special Blue Version)",),
    ),
    Rarity(
        "scrred",
        "ScRRed",
        CardRarity.SECRET_RED,
        ("Secret Rare (Special Red Version)",),
    ),
    Rarity(
        "rrred",
        "RRRed",
        CardRarity.RUSH_RED,
        ("Rush Rare (Special Red Version)",),
    ),
    Rarity(
        "orrblack",
        "ORRBlack",
        CardRarity.OVERRUSH_BLACK,
        ("Over Rush Rare (Premium Black Version)",),
    ),
    Rarity(
        "qcscrtdgreen",
        "QCScRTDGreen",
        CardRarity.TWENTYFIFTHSECRET_TOKYODOME,
        ("Quarter Century Secret Rare Tokyo Dome Green Version",),
    ),
    Rarity(
        "qcscrsv",
        "QCScRSV",
        CardRarity.TWENTYFIFTHSECRET_SPECIAL,
        ("Quarter Century Secret Rare (Special Version)",),
    ),
    # Other
    Rarity("hfr", "HFR", CardRarity.HOLOFOIL, ("holofoil", "Holofoil Rare")),
    Rarity("sfr", "SFR", CardRarity.STARFOIL, ("starfoil", "Starfoil Rare")),
    Rarity("msr", "MSR", CardRarity.MOSAIC, ("mosaic", "Mosaic Rare")),
    Rarity("shr", "SHR", CardRarity.SHATTERFOIL, ("shatterfoil", "Shatterfoil Rare")),
    Rarity(
        "cr",
        "CR",
        CardRarity.COLLECTORS,
        ("collectors", "Collectors Rare", "Collector's Rare"),
    ),
    Rarity(
        "urpr",
        "URPR",
        CardRarity.PHARAOHS,
        ("ultra pharaohs", "pharaohs", "Ultra Rare (Pharaoh's Rare)"),
    ),
    # Rarities Yugipedia's module no longer publishes, kept because set lists
    # and galleries written against older templates still spell them
    Rarity("pr", "PR", CardRarity.PARALLEL, ("parallel", "Parallel Rare")),
    Rarity("pc", "PC", CardRarity.COMMONPARALLEL, ("parallel common",)),
    Rarity("dpc", "DPC", CardRarity.DTPC, ("duel terminal parallel common",)),
    Rarity(
        "kcscr",
        "KCScR",
        CardRarity.KCSECRET,
        ("kaiba corporation secret", "Kaiba Corporation Secret Rare"),
    ),
    Rarity("h", "H", None, ("hobby", "Hobby Rare")),
)
"""Every rarity a Yugipedia set list or gallery may name.

This is the only place a rarity is written down: the lookups below are derived
from it, so two of them cannot drift apart the way the importer's four
hand-maintained tables did. Get a row wrong and every printing that spells its
rarity that way is published at the wrong rarity, or dropped outright.
"""


def _normalize(spelling: str) -> str:
    """Reduces a spelling to what Yugipedia's ``normalize`` table is keyed on.

    Case, spaces, punctuation and the word breaks around them are the ways one
    rarity gets written two ways; nothing else in a rarity name is decorative.
    """
    return re.sub(r"[^0-9a-z]", "", spelling.lower())


def _spellings(row: Rarity) -> typing.Tuple[str, ...]:
    """Every string that names this rarity, abbreviation included."""
    return (row.abbreviation,) + row.spellings


def _check_unambiguous() -> None:
    """Refuses to import if two rows normalize to the same spelling.

    The lookups below are dicts, so a spelling two rows both claim would be
    silently won by whichever row is written second, and the other rarity would
    quietly stop resolving for that spelling.
    """
    claimed: typing.Dict[str, str] = {}
    for row in RARITIES:
        for spelling in _spellings(row):
            normal = _normalize(spelling)
            if claimed.setdefault(normal, row.key) != row.key:
                raise ValueError(
                    f"Rarities {claimed[normal]!r} and {row.key!r} both spell "
                    f"themselves {spelling!r}; one of them would silently win."
                )


_check_unambiguous()

RARITY_STR_TO_ENUM = {
    spelling.lower(): row.card_rarity
    for row in RARITIES
    if row.card_rarity is not None
    for spelling in _spellings(row)
}
"""Every accepted spelling, lowercased, to the schema member it names.

This is what every rarity on every set list and gallery page is read through; a
spelling missing here is a printing published at its set's default rarity."""

NORMALIZED_RARITY_STR_TO_ENUM = {
    _normalize(spelling): row.card_rarity
    for row in RARITIES
    if row.card_rarity is not None
    for spelling in _spellings(row)
}
"""The same, keyed on :func:`_normalize` instead — the table's unambiguous index.

:func:`_check_unambiguous` proves no two rarities share a key here, which is
what makes it safe to fall back to when a page spells a rarity in a way nobody
has written down."""

RARITY_STR_TO_ABBREVIATION = {
    spelling.lower(): row.abbreviation
    for row in RARITIES
    for spelling in _spellings(row)
}
"""Every accepted spelling, lowercased, to Yugipedia's official abbreviation.

Gallery image filenames carry the abbreviation, so a rarity missing here is a
printing whose image is looked up under a filename the wiki does not use.
Rarities with no schema member appear here and nowhere else."""

NORMALIZED_RARITY_STR_TO_ABBREVIATION = {
    _normalize(spelling): row.abbreviation
    for row in RARITIES
    for spelling in _spellings(row)
}
"""The same, keyed on :func:`_normalize` — what a punctuated spelling falls back to.

Without this a rarity only the normalized lookup recognises resolves its schema
member but not its abbreviation, and the gallery pastes the raw string into the
image filename instead."""


def resolve_rarity(raw: str) -> typing.Optional[CardRarity]:
    """Returns the rarity a wiki page's rarity string names, or None if unknown.

    Every rarity call site goes through here, so that a spelling means the same
    thing whether the page put it in a template parameter or in a table row.

    The written-down spelling is tried first and the normalized one only if that
    misses, so making lookup forgiving can rescue a spelling that used to fail
    but can never move one that already worked.
    """
    spelling = raw.strip()
    exact = RARITY_STR_TO_ENUM.get(spelling.lower())
    if exact is not None:
        return exact
    return NORMALIZED_RARITY_STR_TO_ENUM.get(_normalize(spelling))


def resolve_abbreviation(raw: str) -> typing.Optional[str]:
    """Returns Yugipedia's official abbreviation for a rarity string, or None.

    Gallery image filenames carry the abbreviation, so a wrong answer here does
    not produce a wrong rarity — it produces a printing with no image.

    Exact before normalized, for the same reason as :func:`resolve_rarity`.
    """
    spelling = raw.strip()
    exact = RARITY_STR_TO_ABBREVIATION.get(spelling.lower())
    if exact is not None:
        return exact
    return NORMALIZED_RARITY_STR_TO_ABBREVIATION.get(_normalize(spelling))


UNKNOWN_RARITIES: typing.Counter[str] = collections.Counter()
"""Every rarity string a run could not resolve, and how often it appeared.

Two things land here: a spelling no row in :data:`RARITIES` claims, and a
rarity Yugipedia names that the schema has no member for. Both come out the
same way — the printing is published carrying no rarity rather than a guess —
so both are worth seeing, and neither is findable among a day-long run's
warnings unless something counts it."""


def report_unknown_rarity(page: str, raw: str, where: str) -> None:
    """Warns that a rarity string did not resolve, and counts it for the summary.

    Every rarity call site reports through here rather than logging its own
    warning, so that an unresolved rarity is both actionable on the spot — the
    warning names the page and the string — and present in
    :func:`log_unknown_rarities`. A site that logged its own warning would be
    missing from the summary, which is how the gallery row path stayed invisible.
    """
    UNKNOWN_RARITIES[raw] += 1
    logging.warning(f"Unknown rarity in {page} ({where}): {raw}")


def log_unknown_rarities() -> None:
    """Logs each rarity string this run could not resolve, and how often.

    Deliberately counts rarity strings and nothing else: a run drops thousands
    of warnings and the handful of spellings worth adding to :data:`RARITIES`
    are not findable among them.
    """
    if not UNKNOWN_RARITIES:
        return
    logging.warning(
        f"Could not resolve {sum(UNKNOWN_RARITIES.values())} rarities, "
        f"in {len(UNKNOWN_RARITIES)} distinct spellings:"
    )
    for raw, count in sorted(UNKNOWN_RARITIES.items(), key=lambda kv: (-kv[1], kv[0])):
        logging.warning(f"\t{count} x {raw}")
