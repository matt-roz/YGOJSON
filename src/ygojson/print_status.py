# The print status vocabulary: what a set list's ``print`` column may say.
#
# Unlike rarity, there is no upstream list to sync against.
# ``Template:Set list/doc`` documents ``print`` as prose - "Used to indicate if
# a card was introduced in a set or reprinted from an earlier set" - and
# ``Module:Card collection/modules/Set list`` validates nothing, so every value
# below was measured from the corpus rather than read off a wiki module. The
# classification is ours and will always have a tail.
import typing

from .database import PrintStatus

PRINT_STATUS_SPELLINGS: typing.Dict[PrintStatus, typing.Tuple[str, ...]] = {
    PrintStatus.NEW: ("new",),
    PrintStatus.REPRINT: (
        "reprint",
        # Debuts: the card existed elsewhere first, which is what a reprint is.
        # The wiki settles these itself - `Reprint (European Debut)` and
        # `Reprint (EU Debut)` are written on its own pages, which makes the
        # bare debut spellings flavours of reprint rather than of new.
        "Speed Duel debut",
        "European debut",
        "European & Oceanian debut",
        "European English debut",
        "North American debut",
        "Oceanian debut",
        "TCG legal debut",
        "Reprint (European Debut)",
        "Reprint (EU Debut)",
        "Reprint (NA Debut)",
        # A reprint whose image changed. `New art` and `New artwork` are a real
        # spelling difference, not a case difference, so both are written down.
        "New art",
        "New artwork",
        "New artwork (renamed)",
        "New extension",
        "International artwork",
        "Japanese artwork",
        "Reprint (New Art)",
        "Reprint (new artwork)",
        # A reprint whose card text or name changed.
        "Functional errata",
        "Functional erratum",
        "Reprint (functional errata)",
        "Reprint (renamed)",
    ),
}
"""Every spelling a set list's ``print`` column is known to use, and its status.

The 22 spellings beyond the two bare words were measured across every row of
the corpus, and **all of them mean reprint**: read against
:class:`~ygojson.database.PrintStatus`'s own definition, none of them says
"first printing anywhere". A spelling missing here is a printing published with
no ``printStatus`` at all, which the schema documents as "the source did not
say" - so getting a row wrong asserts silence where the wiki spoke.
"""


def _check_unambiguous() -> None:
    """Refuses to import if two rows claim the same spelling.

    :data:`PRINT_STATUS_STR_TO_ENUM` is a dict, so a spelling written twice is
    silently won by whichever row is written second. Every measured spelling but
    one means ``reprint``, so the likely mistake is not two statuses fighting
    over a phrase but one phrase added twice - which hides that the second
    writer meant it to say something the first did not.
    """
    claimed: typing.Dict[str, PrintStatus] = {}
    for status, spellings in PRINT_STATUS_SPELLINGS.items():
        for spelling in spellings:
            key = spelling.strip().lower()
            if key in claimed:
                raise ValueError(
                    f"Print status {claimed[key].value!r} and {status.value!r} "
                    f"both spell themselves {spelling!r}; one would silently win."
                )
            claimed[key] = status


_check_unambiguous()

PRINT_STATUS_STR_TO_ENUM = {
    spelling.strip().lower(): status
    for status, spellings in PRINT_STATUS_SPELLINGS.items()
    for spelling in spellings
}
"""Every accepted spelling, lowercased, to the schema member it names.

Derived from :data:`PRINT_STATUS_SPELLINGS` rather than written out, so that
adding a spelling is one row in one place."""

_BARE_SPELLINGS = frozenset(status.value for status in PrintStatus)
"""The two words that are their own status, and so are never worth a note.

Taken from :class:`~ygojson.database.PrintStatus` itself rather than written
out, because these are exactly the values ``printStatus`` publishes: a note
repeating one of them would be on every print-bearing printing and say nothing.
"""


def resolve_print_status(raw: str) -> typing.Optional[PrintStatus]:
    """Returns the status a set list's ``print`` value names, or None if unknown.

    Case-insensitive, because the corpus spells the same phrase two ways -
    ``New artwork`` and ``New Artwork`` - and they are one entry here.

    A value nothing claims returns None and the printing publishes no
    ``printStatus``, as an unresolved rarity publishes no rarity. Guessing would
    be worse than silence: the two members mean opposite things.
    """
    return PRINT_STATUS_STR_TO_ENUM.get(raw.strip().lower())


def print_status_note(raw: str) -> typing.Optional[str]:
    """Returns the ``print`` value verbatim, or None if it said only new/reprint.

    This is what ``printNote`` publishes: the phrase the set list used, so that
    a consumer can tell ``New artwork`` from a plain reprint without re-scraping
    the wiki, and so that a value we decline to classify still reaches them.

    The rule is a property of the source and not of :data:`PRINT_STATUS_SPELLINGS`
    - a note appears whenever the wiki said more than one of the two bare words
    :class:`~ygojson.database.PrintStatus` publishes. It therefore does not
    change meaning as the table grows, and it is absent on the roughly 65,000
    printings whose set list said nothing more than ``new`` or ``reprint``.
    """
    note = raw.strip()
    if not note or note.lower() in _BARE_SPELLINGS:
        return None
    return note
