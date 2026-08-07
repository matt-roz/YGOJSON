# Import data from Yugipedia (https://yugipedia.com).
import atexit
import datetime
import itertools
import json
import logging
import math
import os.path
import random
import re
import time
import typing
import uuid
import xml.etree.ElementTree

import requests
import tqdm
import wikitextparser

from ..database import *
from ..print_status import print_status_note, resolve_print_status
from ..rarity import report_unknown_rarity, resolve_abbreviation, resolve_rarity
from ..warnings import EXPECTED_CONDITIONS

API_URL = "https://yugipedia.com/api.php"
RATE_LIMIT = 1.1
REQUEST_TIMEOUT = 60
MAX_TRIES = 10
MAX_RETRY_DELAY = 300
TIME_TO_JUST_REDOWNLOAD_ALL_PAGES = 30 * 24 * 60 * 60  # 1 month-ish

CHANGELOG_PAGES_PATH = os.path.join(
    ROOT_DIR if os.access(ROOT_DIR, os.W_OK) else os.curdir, "changelog-pages.txt"
)
"""Where a run writes how many wiki pages its changelog reported changed.

Read by ``test/report_output_diff.py``, which is only worth reading as a pair:
1,415 published files changed is unremarkable beside 1,400 changed pages and is
a determinism defect beside three. The two figures are measured in different CI
jobs, so the count has to be written down rather than held in memory.

Deliberately neither ``TEMP_DIR`` nor ``DATA_DIR``, for the reason
:data:`ygojson.warnings.WARNING_BUCKETS_PATH` gives: both are restored from a
failure-tolerant cache, so a job that read no changelog would find a previous
run's count already sitting there and report it as its own. Absence means no
changelog was read at all - the first run against a database, or one whose
cache was older than ``TIME_TO_JUST_REDOWNLOAD_ALL_PAGES`` so every page was
re-read and a large diff is expected - and never that zero pages changed.
"""

# MediaWiki reports these with HTTP 200 and an error body, so they can't be
# spotted by status code alone. They're all transient server-side hiccups.
RETRYABLE_API_ERRORS = {"maxlag", "readonly"}

_last_access = time.time()
_session = requests.Session()


def _retryable_api_error(response: requests.Response) -> typing.Optional[str]:
    """Returns the error code if this is a transient MediaWiki API error, else None.

    Some queries (the XML page exports) don't return JSON at all, so we only
    look at bodies the server actually labelled as JSON.
    """
    if "json" not in response.headers.get("Content-Type", ""):
        return None
    if b'"error"' not in response.content:
        # cheap pre-filter, so we don't parse every response twice
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if not isinstance(error, dict):
        return None
    code = str(error.get("code", "")).lower()
    if code.startswith("internal_api_error") or code in RETRYABLE_API_ERRORS:
        return code
    return None


def make_request(rawparams: typing.Dict[str, str], n_tries=0) -> requests.Response:
    global _last_access

    delay = RATE_LIMIT - (time.time() - _last_access)
    if delay > 0:
        time.sleep(delay)
    _last_access = time.time()

    params = {
        "format": "json",
        "utf8": "1",
        "formatversion": "2",
        "redirects": "1",
    }
    params.update(rawparams)

    if logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
        logging.debug(f"Making request: {json.dumps(params)}")

    def retry(reason: str) -> requests.Response:
        if n_tries + 1 >= MAX_TRIES:
            raise RuntimeError(
                f"Yugipedia request failed {MAX_TRIES} times ({reason}); "
                f"query: {json.dumps(params)}"
            )
        # servers must be hammered; back off further each time
        backoff = min(RATE_LIMIT * 30 * 2**n_tries, MAX_RETRY_DELAY)
        logging.error(f"{reason}; waiting {backoff:.0f}s and retrying...")
        time.sleep(backoff)
        return make_request(rawparams, n_tries + 1)

    try:
        response = _session.get(
            API_URL,
            params=params,
            headers={
                "User-Agent": USER_AGENT,
            },
            timeout=REQUEST_TIMEOUT,
        )
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        return retry(f"{type(e).__name__} contacting Yugipedia")

    if logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
        logging.debug(
            f"Got response: {response.status_code} {response.reason} {response.text}"
        )
    if not response.ok:
        return retry(
            f"Yugipedia server returned {response.status_code}: {response.reason}"
        )
    api_error = _retryable_api_error(response)
    if api_error:
        return retry(f"Yugipedia API returned transient error {api_error}")
    return response


class WikiPage:
    id: int
    name: str

    def __init__(self, id: int, name: str) -> None:
        self.id = id
        self.name = name


class ChangeType(enum.Enum):
    CATEGORIZE = "categorize"
    EDIT = "edit"
    EXTERNAL = "external"
    LOG = "log"
    NEW = "new"


class ChangelogEntry(WikiPage):
    type: ChangeType

    def __init__(self, id: int, name: str, type: ChangeType) -> None:
        super().__init__(id, name)
        self.type = type


def paginate_query(query) -> typing.Iterable:
    query = query.copy()
    while True:
        in_json = make_request(query).json()
        if "query" not in in_json:
            raise ValueError(
                f"Got bad JSON: {json.dumps(in_json)} from query: {json.dumps(query)}"
            )
        yield in_json["query"]
        if "continue" in in_json:
            query.update(in_json["continue"])
        else:
            break


CAT_TCG_CARDS = "Category:TCG cards"
CAT_OCG_CARDS = "Category:OCG cards"
CAT_TOKENS = "Category:Tokens"
CAT_SKILLS = "Category:Skill Cards"
CAT_UNUSABLE = "Category:Unusable cards"
CAT_MD_UNCRAFTABLE = "Category:Yu-Gi-Oh! Master Duel cards that cannot be crafted"
CAT_ARCHETYPES = "Category:Archetypes"
CAT_SERIES = "Category:Series"

SET_CATS = [
    "Category:TCG sets",
    "Category:OCG sets",
    "Category:Yu-Gi-Oh! Master Duel sets",
    "Category:Yu-Gi-Oh! Duel Links sets",
    "Category:Preconstructed Decks",  # for specifically the Speed Duel box decks, because for some reason they have no format category in Yugipedia
]

BANLIST_CATS = {
    "tcg": "Category:TCG Advanced Format Forbidden & Limited Lists",
    "ocg": "Category:OCG Forbidden & Limited Lists",
    "ocg-kr": "Category:Korean OCG Forbidden & Limited Lists",
    # "ocg-ae": "Category:Asian-English OCG Forbidden & Limited Lists",
    # "ocg-tc": "Category:Traditional Chinese OCG Forbidden & Limited Lists",
    "ocg-sc": "Category:Simplified Chinese OCG Forbidden & Limited Lists",
    "speed": "Category:TCG Speed Duel Forbidden & Limited Lists",
    "masterduel": "Category:Yu-Gi-Oh! Master Duel Forbidden & Limited Lists",
    "duellinks": "Category:Yu-Gi-Oh! Duel Links Forbidden & Limited Lists",
}
CAT_BANLIST_GENESYS = "Category:Genesys Point Lists"

DBID_SUFFIX = "_database_id"
DBNAME_SUFFIX = "_name"
RELDATE_SUFFIX = "_release_date"

EXT_PREFIX = "extension::"
FILE_PREFIX = "file::"


def get_card_pages(batcher: "YugipediaBatcher") -> typing.Iterable[int]:
    with tqdm.tqdm(total=2, desc="Fetching Yugipedia card list") as progress_bar:
        result = []
        seen = set()

        @batcher.getCategoryMembers(CAT_TCG_CARDS)
        def catMem1(members: typing.List[int]):
            result.extend(x for x in members if x not in seen)
            seen.update(members)
            progress_bar.update(1)

        @batcher.getCategoryMembers(CAT_OCG_CARDS)
        def catMem2(members: typing.List[int]):
            result.extend(x for x in members if x not in seen)
            seen.update(members)
            progress_bar.update(1)

        return result


def get_set_pages(batcher: "YugipediaBatcher") -> typing.Iterable[int]:
    with tqdm.tqdm(
        total=len(SET_CATS), desc="Fetching Yugipedia set list"
    ) as progress_bar:
        result = []
        seen = set()

        for cat in SET_CATS:

            @batcher.getCategoryMembersRecursive(cat)
            def catMem(members: typing.List[int]):
                result.extend(x for x in members if x not in seen)
                seen.update(members)
                progress_bar.update(1)

        return result


def get_series_pages(batcher: "YugipediaBatcher") -> typing.Iterable[int]:
    with tqdm.tqdm(total=2, desc="Fetching Yugipedia series list") as progress_bar:
        result = []
        seen = set()

        @batcher.getCategoryMembers(CAT_ARCHETYPES)
        def catMem1(members: typing.List[int]):
            result.extend(x for x in members if x not in seen)
            seen.update(members)
            progress_bar.update(1)

        @batcher.getCategoryMembers(CAT_SERIES)
        def catMem2(members: typing.List[int]):
            result.extend(x for x in members if x not in seen)
            seen.update(members)
            progress_bar.update(1)

        return result


def get_changelog(
    batcher: "YugipediaBatcher", since: datetime.datetime
) -> typing.Iterable[ChangelogEntry]:
    query = {
        "action": "query",
        "list": "recentchanges",
        "rcend": since.isoformat(),
        "rclimit": "max",
    }

    for results in paginate_query(query):
        for result in results["recentchanges"]:
            batcher.removeFromCache(result["title"])
            batcher.removeFromCache(result["pageid"])
            yield ChangelogEntry(
                result["pageid"], result["title"], ChangeType(result["type"])
            )


def _record_changelog_pages(changelog: typing.Iterable[ChangelogEntry]) -> None:
    """Writes how many distinct pages the changelog reported, for the output diff.

    Distinct pages rather than changelog entries: a page edited five times in
    two days is one page whose parse could have moved, and counting it five
    times over would understate the ratio the diff report exists to show.
    """
    pages = len({entry.id for entry in changelog})
    logging.info(
        f"Yugipedia's changelog reports {pages} pages changed since the last read."
    )
    with open(CHANGELOG_PAGES_PATH, "w", encoding="utf-8") as file:
        file.write(f"{pages}\n")


def get_changes(
    batcher: "YugipediaBatcher",
    relevant_pages: typing.Iterable[int],
    relevant_cats: typing.Iterable[str],
    changelog: typing.Iterable[ChangelogEntry],
) -> typing.Iterable[int]:
    """
    Finds recent changes.
    Returns any cards changed or newly created.
    """
    changed_cards: typing.List[int] = []

    card_ids = set(relevant_pages)
    pages_to_catcheck: typing.List[ChangelogEntry] = []
    for change in changelog:
        if change.id in card_ids:
            changed_cards.append(change.id)
        elif (
            change.type == ChangeType.CATEGORIZE or change.type == ChangeType.NEW
        ) and not change.name.startswith("Category:"):
            pages_to_catcheck.append(change)

    new_cards: typing.Set[int] = {x for x in changed_cards}

    for entry in pages_to_catcheck:

        def do(entry: ChangelogEntry):
            @batcher.getPageCategories(entry.id)
            def onGetCats(cats: typing.List[int]):
                for cat in relevant_cats:
                    if batcher.namesToIDs[cat] in cats:
                        if all(
                            x.id != entry.id
                            for x in batcher.categoryMembersCache[
                                batcher.namesToIDs[cat]
                            ]
                        ):
                            batcher.categoryMembersCache[
                                batcher.namesToIDs[cat]
                            ].append(
                                CategoryMember(
                                    id=entry.id,
                                    name=entry.name,
                                    type=CategoryMemberType.PAGE,
                                )
                            )
                        new_cards.add(entry.id)

        do(entry)

    batcher.flushPendingOperations()
    return new_cards


T = typing.TypeVar("T")


def get_table_entry(
    table: wikitextparser.Template, key: str, default: T = None
) -> typing.Union[str, T]:
    try:
        arg = next(iter([x for x in table.arguments if x.name.strip() == key]))
        return arg.value
    except StopIteration:
        return default


LOCALES = {
    "": "en",
    "en": "en",
    "na": "en",
    "eu": "en",
    "oc": "en",
    "au": "en",
    "fr": "fr",
    "fc": "fr",
    "de": "de",
    "it": "it",
    "pt": "pt",
    "es": "es",
    "sp": "es",
    "jp": "ja",
    "ja": "ja",
    "ko": "ko",
    "kr": "ko",
    "tc": "zh-TW",
    "sc": "zh-CN",
    "ae": "ae",
}

LOCALES_FULL = {
    "English": "en",
    "French": "fr",
    "German": "de",
    "Italian": "it",
    "Portugese": "pt",
    "Spanish": "es",
    "Japanese": "ja",
    "Korean": "ko",
    "Traditional Chinese": "zh-TW",
    "Simplified Chinese": "zh-CN",
    "Asian English": "ae",
    "Asian-English": "ae",
}

MONSTER_CARD_TYPES = {
    "Ritual": MonsterCardType.RITUAL,
    "Fusion": MonsterCardType.FUSION,
    "Synchro": MonsterCardType.SYNCHRO,
    "Xyz": MonsterCardType.XYZ,
    "Pendulum": MonsterCardType.PENDULUM,
    "Link": MonsterCardType.LINK,
}
TYPES = {
    "Beast-Warrior": Race.BEASTWARRIOR,
    "Zombie": Race.ZOMBIE,
    "Fiend": Race.FIEND,
    "Dinosaur": Race.DINOSAUR,
    "Dragon": Race.DRAGON,
    "Beast": Race.BEAST,
    "Illusion": Race.ILLUSION,
    "Insect": Race.INSECT,
    "Winged Beast": Race.WINGEDBEAST,
    "Warrior": Race.WARRIOR,
    "Sea Serpent": Race.SEASERPENT,
    "Aqua": Race.AQUA,
    "Pyro": Race.PYRO,
    "Thunder": Race.THUNDER,
    "Spellcaster": Race.SPELLCASTER,
    "Plant": Race.PLANT,
    "Rock": Race.ROCK,
    "Reptile": Race.REPTILE,
    "Fairy": Race.FAIRY,
    "Fish": Race.FISH,
    "Machine": Race.MACHINE,
    "Divine-Beast": Race.DIVINEBEAST,
    "Psychic": Race.PSYCHIC,
    "Creator God": Race.CREATORGOD,
    "Wyrm": Race.WYRM,
    "Cyberse": Race.CYBERSE,
}
CLASSIFICATIONS = {
    "Normal": Classification.NORMAL,
    "Effect": Classification.EFFECT,
    "Pendulum": Classification.PENDULUM,
    "Tuner": Classification.TUNER,
    # specialsummon omitted
}
ABILITIES = {
    "Toon": Ability.TOON,
    "Spirit": Ability.SPIRIT,
    "Union": Ability.UNION,
    "Gemini": Ability.GEMINI,
    "Flip": Ability.FLIP,
}


MYSTERY_ATK_DEFS = {"?", "????", "X000"}


def _strip_markup(s: str) -> str:
    return "\n".join(
        wikitextparser.remove_markup(
            re.sub(
                r"\{\{[Rr]uby\|([^\|]*)\|(?:[^\}]*)?\}\}",
                r"\1",
                x.replace("<br />", "\n"),
            )
        )
        for x in s.split("\n")
    )


def parse_card(
    batcher: "YugipediaBatcher",
    page: int,
    card: Card,
    data: wikitextparser.WikiText,
    categories: typing.List[int],
    banlists: typing.Dict[str, typing.List["Banlist"]],
    series_members: typing.Dict[str, typing.Set[Card]],
    genesys_banlist: typing.Dict[datetime.date, typing.Dict[str, float]],
) -> bool:
    """
    Parse a card from a wiki page. Returns False if this is not actually a valid card
    for the database, and True otherwise.
    """

    for possibly_out_of_date_set in series_members.values():
        # we do this to ensure that we don't cache bad data when a series is removed from a card
        if card in possibly_out_of_date_set:
            possibly_out_of_date_set.remove(card)

    title = batcher.idsToNames.get(page)
    if title is None:
        logging.warning(f"Card page has no title: {page}")
        return False

    cardtable = next(
        iter([x for x in data.templates if x.name.strip().lower() == "cardtable2"])
    )

    card.text = {}
    for locale, key in LOCALES.items():
        lang = Language.normalize(key)

        value = get_table_entry(cardtable, locale + "_name" if locale else "name")
        if not locale and not value:
            value = title
        if value and value.strip():
            value = _strip_markup(value.strip())
            card.text[lang] = CardText(name=value)

        value = get_table_entry(
            cardtable,
            locale + "_lore" if locale else "lore",
            get_table_entry(cardtable, locale + "_text" if locale else "text"),
        )
        if value and value.strip():
            if lang not in card.text:
                # logging.warning(f"Card has no name in {key} but has effect: {title}")
                pass
            else:
                card.text[lang].effect = _strip_markup(value.strip())

        value = get_table_entry(
            cardtable, locale + "_pendulum_effect" if locale else "pendulum_effect"
        )
        if value and value.strip():
            if lang not in card.text:
                # logging.warning(f"Card has no name in {key} but has pend. effect: {title}")
                pass
            else:
                card.text[lang].pendulum_effect = _strip_markup(value.strip())

        if any(
            (
                t.name.strip() == "Unofficial name"
                or t.name.strip() == "Unofficial lore"
                or t.name.strip() == "Unofficial text"
            )
            and LOCALES_FULL.get(t.arguments[0].value.strip()) == key
            for t in data.templates
        ):
            if lang not in card.text:
                # logging.warning(f"Card has no name in {key} but is unofficial: {title}")
                pass
            else:
                card.text[lang].official = False

    if Language.ENGLISH not in card.text:
        card.text[Language.ENGLISH] = CardText(name=title, official=False)
    elif not card.text[Language.ENGLISH].name:
        card.text[Language.ENGLISH].name = title
        card.text[Language.ENGLISH].official = False

    if card.card_type in {
        CardType.MONSTER,
        CardType.TOKEN,
    }:  # parse monsterlike cards' common attributes
        typeline = get_table_entry(cardtable, "types")
        if not typeline:
            typeline = ""
            if card.card_type != CardType.TOKEN:
                logging.warning(f"Monster has no typeline: {title}")
                return False

        value = get_table_entry(cardtable, "attribute")
        if not value:
            # logging.warning(f"Monster has no attribute: {title}")
            pass  # some illegal-for-play monsters have no attribute
        else:
            value = value.strip().lower()
            if value == "???":
                pass  # attribute to be announced; omit it
            elif value not in Attribute._value2member_map_:
                if card.card_type != CardType.TOKEN:
                    logging.warning(f"Unknown attribute '{value.strip()}' in {title}")
            else:
                card.attribute = Attribute(value)

        typeline = [
            re.sub(r"<!--.*-->", r"", x).strip()
            for x in typeline.split("/")
            if x.strip()
        ]

        for x in typeline:
            if (
                x
                not in {
                    "",
                    "?",
                    "???",
                    "Token",
                    "Counter",
                }  # type to be announced or is token; omit it
                and x not in MONSTER_CARD_TYPES
                and x not in TYPES
                and x not in CLASSIFICATIONS
                and x not in ABILITIES
            ):
                logging.warning(f"Monster typeline bit unknown in {title}: {x}")

        if not card.monster_card_types:
            card.monster_card_types = []
        for k, v in MONSTER_CARD_TYPES.items():
            if k in typeline and v not in card.monster_card_types:
                card.monster_card_types.append(v)
        for k, v in TYPES.items():
            if k in typeline:
                card.type = v
        if not card.classifications:
            card.classifications = []
        for k, v in CLASSIFICATIONS.items():
            if k in typeline and v not in card.classifications:
                card.classifications.append(v)
        if not card.abilities:
            card.abilities = []
        for k, v in ABILITIES.items():
            if k in typeline and v not in card.abilities:
                card.abilities.append(v)
        # if not card.type and "???" not in typeline:
        #     # some illegal-for-play monsters have no type
        #     logging.warning(f"Monster has no type: {title}")

        value = get_table_entry(cardtable, "level")
        if value and value.strip() != "???":
            try:
                card.level = int(value)
            except ValueError:
                if card.card_type != CardType.TOKEN:
                    logging.warning(f"Unknown level '{value.strip()}' in {title}")
                    return False

        value = get_table_entry(cardtable, "atk")
        if value and value.strip() != "???":
            try:
                card.atk = "?" if value.strip() in MYSTERY_ATK_DEFS else int(value)
            except ValueError:
                logging.warning(f"Unknown ATK '{value.strip()}' in {title}")
                if card.card_type != CardType.TOKEN:
                    return False
        value = get_table_entry(cardtable, "def")
        if value and value.strip() != "???":
            try:
                card.def_ = "?" if value.strip() in MYSTERY_ATK_DEFS else int(value)
            except ValueError:
                logging.warning(f"Unknown DEF '{value.strip()}' in {title}")
                if card.card_type != CardType.TOKEN:
                    return False

    if card.card_type == CardType.MONSTER:
        value = get_table_entry(cardtable, "rank")
        if value and value.strip() != "???":
            try:
                card.rank = int(value)
            except ValueError:
                logging.warning(f"Unknown rank '{value.strip()}' in {title}")
                return False

        value = get_table_entry(cardtable, "pendulum_scale")
        if value and value.strip() != "???":
            try:
                card.scale = int(value)
            except ValueError:
                logging.warning(f"Unknown scale '{value.strip()}' in {title}")
                return False

        value = get_table_entry(cardtable, "link_arrows")
        if value:
            card.link_arrows = [
                LinkArrow(x.lower().replace("-", "").strip()) for x in value.split(",")
            ]
    elif card.card_type == CardType.SPELL or card.card_type == CardType.TRAP:
        value = get_table_entry(cardtable, "property")
        if not value:
            logging.warning(f"Spell/trap has no subcategory: {title}")
            return False
        card.subcategory = SubCategory(value.lower().replace("-", "").strip())
    elif card.card_type == CardType.TOKEN:
        pass
    elif card.card_type == CardType.SKILL:
        char = get_table_entry(cardtable, "character", "").strip()
        if char:
            card.character = char
        typeline = [
            x.strip()
            for x in get_table_entry(cardtable, "types", "").split("/")
            if x.strip()
        ]
        if len(typeline) == 3:
            card.skill_type = typeline[2]
        elif len(typeline) > 3:
            logging.warning(f"Found skill card {title} with weird typeline: {typeline}")
    else:
        logging.warning(f"Skipping {card.card_type} card: {title}")
        return False

    value = get_table_entry(cardtable, "password")
    if value:
        vmatch = re.match(r"^\d+", value.strip())
        if vmatch and value.strip() not in card.passwords:
            card.passwords.append(value.strip())
        if not vmatch and value.strip() and value.strip() != "none":
            logging.warning(f"Bad password '{value.strip()}' in card {title}")

    # generally, we want YGOProDeck to handle generic images
    # But if all else fails, we can add one!
    if all(
        (not image.card_art and not image.crop_art)
        or "yugipedia.com" in (image.card_art or "")
        for image in card.images
    ):
        in_images_raw = get_table_entry(cardtable, "image")
        if in_images_raw:
            in_images = [
                [x.strip() for x in x.split(";")]
                for x in in_images_raw.split("\n")
                if x.strip()
            ]

            def add_image(in_image: list, out_image: CardImage):
                if len(in_image) == 1:
                    image_name = in_image[0]
                elif len(in_image) == 2:
                    image_name = in_image[1]
                elif len(in_image) == 3:
                    image_name = in_image[1]
                else:
                    logging.warning(
                        f"Weird image string for {title}: {' ; '.join(in_image)}"
                    )
                    return

                @batcher.getImageURL("File:" + image_name)
                def onGetImage(url: str):
                    out_image.card_art = url

            for image in card.images:
                if len(in_images) == 0:
                    logging.warning(
                        f'mismatch between number of images known and found in "{title}"\'s page!'
                    )
                else:
                    in_image = in_images.pop(0)
                    add_image(in_image, image)
            for in_image in in_images:
                new_image = CardImage(id=uuid.uuid4())
                if len(card.passwords) == 1:
                    # we don't have the full ability to correspond passwords here
                    # but this will do for 99% of cards
                    new_image.password = card.passwords[0]
                add_image(in_image, new_image)
                card.images.append(new_image)

    md_title = title + MD_DISAMBIG_SUFFIX

    @batcher.getPageContents(md_title)
    def onGetMD(raw_vg_data: str):
        vg_data = wikitextparser.parse(raw_vg_data)
        for vg_table in [
            x for x in vg_data.templates if x.name.strip().lower() == "master duel card"
        ]:
            rarity = get_table_entry(vg_table, "rarity")
            if rarity and rarity.strip():
                rarity = rarity.strip().lower()
                if rarity in {"?", "???"}:
                    pass  # unknown rarity; this is fine
                elif rarity not in VideoGameRaity._value2member_map_:
                    logging.warning(
                        f"Found MD page for '{md_title}' with invalid rarity: {rarity}"
                    )
                else:
                    card.master_duel_rarity = VideoGameRaity(rarity)

        card.master_duel_craftable = True

        @batcher.getPageID(CAT_MD_UNCRAFTABLE)
        def onGetCatID(uncraftable_id: int, _: str):
            @batcher.getPageCategories(md_title)
            def onGetCats(cats: typing.List[int]):
                if uncraftable_id in cats:
                    card.master_duel_craftable = False

    dl_title = title + DL_DISAMBIG_SUFFIX

    @batcher.getPageContents(dl_title)
    def onGetDL(raw_vg_data: str):
        vg_data = wikitextparser.parse(raw_vg_data)
        for vg_table in [
            x for x in vg_data.templates if x.name.strip().lower() == "duel links card"
        ]:
            rarity = get_table_entry(vg_table, "rarity")
            if rarity and rarity.strip():
                rarity = rarity.strip().lower()
                if rarity in {"?", "???"}:
                    pass  # unknown rarity; this is fine
                elif rarity not in VideoGameRaity._value2member_map_:
                    logging.warning(
                        f"Found DL page for '{dl_title}' with invalid rarity: {rarity}"
                    )
                else:
                    card.duel_links_rarity = VideoGameRaity(rarity)

    limit_text = get_table_entry(cardtable, "limitation_text")
    if limit_text and limit_text.strip():
        card.illegal = True
        card.legality.clear()
    else:
        for rawformat, ban_history in banlists.items():
            if rawformat not in Format._value2member_map_:
                logging.warning(
                    f"Found unknown legality format in {title}: {rawformat}"
                )
                continue
            format = Format(rawformat)

            card_history = card.legality.get(format)
            if card_history:
                card_history.history.clear()

            for history_item in ban_history:
                if title in history_item.cards:
                    legality = history_item.cards[title]
                    if not card_history:
                        card.legality.setdefault(
                            format, CardLegality(legality=legality)
                        )
                        card_history = card.legality[format]
                    card_history.legality = legality
                    card_history.history.append(
                        LegalityPeriod(legality=legality, date=history_item.date)
                    )

        if any(
            f is Format.TCG
            and (
                h.legality is not Legality.UNKNOWN
                and h.legality is not Legality.UNRELEASED
            )
            for f, h in card.legality.items()
        ):
            genesys_info = CardLegality(points=0)
            last_points = 0
            for date, points in sorted(
                {
                    date: info[title]
                    for date, info in genesys_banlist.items()
                    if title in info
                }.items(),
                key=lambda kv: kv[0],
            ):
                if points != last_points:
                    genesys_info.history.append(
                        LegalityPeriod(points=points, date=date)
                    )
                last_points = points
            genesys_info.points = last_points
            card.legality[Format.GENESYS] = genesys_info

    for archseries in [
        x.strip()
        for x in get_table_entry(cardtable, "archseries", "")
        .replace("*", "")
        .split("\n")
        if x.strip()
    ]:
        series_members.setdefault(archseries.lower(), set())
        series_members[archseries.lower()].add(card)

    if not card.yugipedia_pages:
        card.yugipedia_pages = []
    for existing_page in card.yugipedia_pages or []:
        if not existing_page.name and existing_page.id == page:
            existing_page.name = title
        elif not existing_page.id and existing_page.name == title:
            existing_page.id = page
    if not any(x.id == page for x in card.yugipedia_pages):
        card.yugipedia_pages.append(ExternalIdPair(title, page))

    value = get_table_entry(cardtable, "database_id", "")
    vmatch = re.match(r"^\d+", value.strip())
    if vmatch:
        card.db_id = int(vmatch.group(0))

    # TODO: errata

    return True


CARD_GALLERY_NAMESPACE = "Set Card Galleries:"

GALLERY_LEGEND_WORDS = {
    "number",
    "card number",
    "name",
    "card name",
    "rarity",
    "card rarity",
    "rarities",
    "card rarities",
    "alt",
    "print",
    "quantity",
}
"""Every word ``Set gallery`` and ``Set list`` use to name a row's columns in
their own documentation.

A row whose columns are *all* from this vocabulary is that documentation line
left on a gallery nobody filled in - three of them carry ``number; name;
rarity`` verbatim - rather than a printing. Both templates' words are listed
because a stub is a pasted line and the row does not say which template it was
pasted from.

Matched as a vocabulary and not as one string on purpose: an exact match
against wiki free text stops matching the day somebody edits the line, and says
nothing when it does. Widening this is what costs a printing, and only barely -
every column must match, so a word here is dangerous only if a card is named it
*and* sits at a card number and a rarity that are legend words too. Narrowing
it only returns the noise.
"""

IMAGE_VARIANT_STR_TO_ENUM = {
    "AA": ImageVariant.ALTERNATE_ART,
    "AA2": ImageVariant.ALTERNATE_ART,
    "AA3": ImageVariant.ALTERNATE_ART,
    "AA4": ImageVariant.ALTERNATE_ART,
    "AA5": ImageVariant.ALTERNATE_ART,
    "AA6": ImageVariant.ALTERNATE_ART,
    "OP": ImageVariant.OFFICIAL_PROXY,
    "OW": ImageVariant.OFFICIAL_WEBSITE,
}
"""The gallery variant codes whose meaning is documented, and what they mean.
``OP`` and ``OW`` are defined by ``Yugipedia:Image policy``; the ``AA`` family is
alternate artwork, numbered where one printing has several of them - ``Quarter
Century Art Collection`` gets Dark Magician up to ``AA6``.

Listed one by one on purpose, including every number. A code absent here is
published with its raw spelling and no classification, which is the safe
direction: a code is only ever as reliable as the editor who wrote it in the
gallery row, and ``Reprint`` is already known to mean two different things on one
page. Matching loosely - by prefix, or case-insensitively - would classify codes
nobody has read, which is how ``Reprint`` came to be mistaken for a card-text
distinction in the first place.
"""

EDITION_STR_TO_ENUM = {
    "1E": SetEdition.FIRST,
    "UE": SetEdition.UNLIMTED,
    "REPRINT": SetEdition.UNLIMTED,
    "LE": SetEdition.LIMITED,
    "DT": SetEdition.LIMITED,
}

EDITIONS_IN_NAV = {
    "1e": SetEdition.FIRST,
    "ue": SetEdition.UNLIMTED,
    "le": SetEdition.LIMITED,
}

EDITIONS_IN_NAV_REVERSE = {v: k for k, v in EDITIONS_IN_NAV.items()}

FORMATS_IN_NAV = {
    "en": "TCG",
    "na": "TCG",
    "eu": "TCG",
    "au": "TCG",
    "oc": "TCG",
    "fr": "TCG",
    "fc": "TCG",
    "de": "TCG",
    "it": "TCG",
    "pt": "TCG",
    "es": "TCG",
    "sp": "TCG",
    "jp": "OCG",
    "ja": "OCG",
    "ko": "OCG",
    "kr": "OCG",
    "tc": "OCG",
    "sc": "OCG",
    "ae": "OCG",
}

FALLBACK_LOCALES = {
    "en": "",
    "na": "en",
    "eu": "en",
    "au": "en",
    "oc": "en",
    "fc": "fr",
    "jp": "ja",
    "ae": "jp",
    "sp": "es",
    "kr": "ko",
}

_LD_RARITIES = {
    CardRarity.ULTRA: [
        CardRarity.ULTRA,
        CardRarity.ULTRA_BLUE,
        CardRarity.ULTRA_GREEN,
        CardRarity.ULTRA_PURPLE,
    ]
}
_DL_RARITIES = {
    CardRarity.RARE: [
        CardRarity.RARE_PURPLE,
        CardRarity.RARE_RED,
        CardRarity.RARE_GREEN,
        CardRarity.RARE_BLUE,
    ]
}
MANUAL_RARITY_FIXUPS = {
    "Dragons of Legend: The Complete Series": _LD_RARITIES,
    "Legendary Duelists: Season 1": _LD_RARITIES,
    "Legendary Duelists: Season 2": _LD_RARITIES,
    "Duelist League 2010 participation cards": {
        CardRarity.RARE: [
            CardRarity.RARE_BLUE,
            CardRarity.RARE_GREEN,
            CardRarity.RARE_COPPER,
            CardRarity.RARE_WEDGEWOOD,
        ]
    },
    "Duelist League 2 participation cards": _DL_RARITIES,
    "Duelist League 3 participation cards": _DL_RARITIES,
    "Duelist League 13 participation cards": _DL_RARITIES,
    "Duelist League 14 participation cards": _DL_RARITIES,
    "Duelist League 15 participation cards": _DL_RARITIES,
    "Duelist League 16 participation cards": _DL_RARITIES,
    "Duelist League 17 participation cards": _DL_RARITIES,
    "Duelist League 18 participation cards": _DL_RARITIES,
}


def commonprefix(m: typing.Iterable[str]):
    "Given a list of strings, returns the longest common leading component"

    m = [*m]
    if not m:
        return ""
    s1 = min(m)
    s2 = max(m)
    for i, c in enumerate(s1):
        if c != s2[i]:
            return s1[:i]
    return s1


def _parse_month(m: str) -> int:
    try:
        return datetime.datetime.strptime(m, "%B").month
    except ValueError:
        try:
            return datetime.datetime.strptime(m, "%b").month
        except ValueError:
            return int(m)


def _parse_date(value: str) -> typing.Optional[datetime.date]:
    found_date = re.search(r"(\w+)\s+(\d+),\s*(\d+)", value)
    if found_date:
        (month, day, year) = found_date.groups()
    else:
        found_date = re.search(r"(\w+)\s+(\d+)", value)
        if found_date:
            (month, year) = found_date.groups()
            day = "1"
        else:
            found_date = re.search(r"(\d\d\d\d)", value)
            if found_date:
                (year,) = found_date.groups()
                month = "1"
                day = "1"
            else:
                return None

    try:
        return datetime.date(
            month=_parse_month(month),
            day=int(day),
            year=int(year),
        )
    except ValueError:
        return None


class ImageLocator(typing.NamedTuple):
    edition: SetEdition
    altinfo: str


class GalleryImage(typing.NamedTuple):
    position: typing.Tuple[int, int]
    """Where the gallery row that claimed this image sits: which gallery page,
    then which row of it."""
    url: str


class PrintingLocator(typing.NamedTuple):
    card: Card
    rarity: CardRarity
    # The card code, so that the same card at the same rarity may appear at
    # several codes in one set (common in Legendary Decks style products).
    # This is the full code in RawLocale.cards, and the code suffix when
    # locating CardPrintings.
    code: typing.Optional[str] = None


class RawPrinting:
    card: Card
    code: str
    rarity: CardRarity
    image: typing.Dict[ImageLocator, GalleryImage]
    qty: int
    noabbr: bool
    row: int
    """Which row of the set list page named this printing, counted where the row
    is parsed rather than where its card lookup answers. The answers arrive in
    fetch-completion order, so this is the only record of the order the wiki
    writes its set list in."""

    def __init__(
        self,
        card: Card,
        code: str,
        rarity: CardRarity,
        qty: int,
        noabbr: bool,
        row: int,
        print_status: typing.Optional[PrintStatus] = None,
        print_note: typing.Optional[str] = None,
    ) -> None:
        self.card = card
        self.code = code
        self.rarity = rarity
        self.image = {}
        self.qty = qty
        self.noabbr = noabbr
        self.row = row
        self.print_status = print_status
        self.print_note = print_note

    def locator(self) -> PrintingLocator:
        return PrintingLocator(self.card, self.rarity, self.code)


class RawLocale:
    key: str
    format: str
    editions: typing.List[SetEdition]
    """In ``EDITIONS_IN_NAV`` order. A set here would iterate in a different
    order every run, since enum members hash by name and Python randomizes
    string hashing per process."""
    cards: typing.Dict[PrintingLocator, RawPrinting]
    date: typing.Optional[datetime.date]
    images: typing.Dict[SetEdition, str]
    db_ids: typing.List[int]

    def __init__(self, key: str, format: str) -> None:
        self.key = key
        self.format = format
        self.editions = []
        self.cards = {}
        self.date = None
        self.images = {}
        self.db_ids = []


def _pack_image(raw_locale: RawLocale) -> typing.Optional[str]:
    """The pack image a locale publishes: the image of the first of its
    editions that has one, in ``EDITIONS_IN_NAV`` order. A locale whose
    editions carry distinct pack images therefore publishes its 1st Edition
    image, rather than whichever edition happened to be iterated first."""
    for edition in raw_locale.editions:
        if edition in raw_locale.images:
            return raw_locale.images[edition]
    return None


def _canonical_image(ils: typing.List[ImageLocator]) -> ImageLocator:
    """The one image a printing publishes for an edition, picked from the
    locators it carries there. The plain image, the one with no variant code,
    wins. Where a printing carries no plain image at all, as ``OTS Tournament
    Pack 9``'s Mecha Phantom Beast Token carries only ``Harrliard``,
    ``Megaraptor`` and ``Dracossack``, the alphabetically first code wins
    instead. The codes a printing carries in one edition are distinct, since
    they key the same dict, so this order is total: the pick does not depend
    on the order the asynchronous image lookups happened to complete in, and
    is the same on every run."""
    return min(ils, key=lambda il: (bool(il.altinfo), il.altinfo))


def _variant_image(
    art_treatments: typing.Dict[typing.Tuple[Card, str], CardImage],
    card: Card,
    il: ImageLocator,
    url: str,
) -> VariantImage:
    """One coded image of a printing, carrying the art treatment it depicts
    where the code says it depicts one.

    Only alternate artworks get a treatment. Their code is what the galleries
    number when a card has several of them, and the number is what tells two
    artworks apart: ``Quarter Century Art Collection`` gives Dark Magician
    ``AA`` through ``AA6``, six different artworks, and Yugipedia's own card
    page lists the same files as six separate artwork entries. So the code is
    the key, shared across the locales and rarities of one set - one artwork,
    one treatment, however many scans of it a set publishes - and not across
    sets, where nothing says two galleries numbered the same artwork alike.
    """
    variant = IMAGE_VARIANT_STR_TO_ENUM.get(il.altinfo)
    treatment = None
    if variant is ImageVariant.ALTERNATE_ART:
        treatment = art_treatments.setdefault(
            (card, il.altinfo), CardImage(id=uuid.uuid4())
        )
    return VariantImage(
        code=il.altinfo,
        image=url,
        variant=variant,
        art_treatment=treatment,
    )


def _record_image(
    images: typing.Dict[ImageLocator, GalleryImage],
    il: ImageLocator,
    position: typing.Tuple[int, int],
    url: str,
) -> None:
    """Record what one gallery row says a printing's image is for an edition and
    a variant code. Two rows can land on the same key. A set locale can carry
    both an edition's own gallery and an edition-agnostic one - sixty-one do -
    whose rows build file names differing only by the edition suffix; and
    ``COLORFUL_RARES`` clearing a row's variant code while ``FALLBACK_RARITIES``
    moves it onto the plain rarity's printing can fold two tables of one gallery
    onto the same key.

    The earlier row wins. ``position`` counts where the row is parsed - which
    gallery page, then which row of it - rather than when its image lookup
    answers, because the answers arrive in fetch-completion order: keeping the
    last write, as this used to, publishes whichever of the two the wiki
    answered for last, which differs between runs and between a warm and a cold
    page cache. The edition's own gallery is read before the edition-agnostic
    one, so an edition publishes its own scan wherever the wiki has one."""
    if il not in images or position < images[il].position:
        images[il] = GalleryImage(position, url)


COLORFUL_RARES = {
    (CardRarity.RARE, "Red"): CardRarity.RARE_RED,
    (CardRarity.RARE, "Bronze"): CardRarity.RARE_COPPER,
    (CardRarity.RARE, "Green"): CardRarity.RARE_GREEN,
    (CardRarity.RARE, "Silver"): CardRarity.RARE_WEDGEWOOD,
    (CardRarity.RARE, "Blue"): CardRarity.RARE_BLUE,
    (CardRarity.RARE, "Purple"): CardRarity.RARE_PURPLE,
    (CardRarity.ULTRA, "Green"): CardRarity.ULTRA_GREEN,
    (CardRarity.ULTRA, "Blue"): CardRarity.ULTRA_BLUE,
    (CardRarity.ULTRA, "Purple"): CardRarity.ULTRA_PURPLE,
    (CardRarity.SECRET, "Red"): CardRarity.SECRET_RED,
    (CardRarity.SECRET, "Blue"): CardRarity.SECRET_BLUE,
}


FALLBACK_RARITIES = {
    CardRarity.COMMON: CardRarity.SHORTPRINT,
    CardRarity.SHORTPRINT: CardRarity.COMMON,
    **{r2: r1 for (r1, alt), r2 in COLORFUL_RARES.items()},
}


def parse_tcg_ocg_set(
    db: Database,
    batcher: "YugipediaBatcher",
    pageid: int,
    set_: Set,
    data: wikitextparser.WikiText,
    raw_data: str,
    settable: wikitextparser.Template,
) -> bool:
    title = batcher.idsToNames[pageid]
    set_.yugipedia = ExternalIdPair(title, pageid)

    for lc, key in LOCALES.items():
        namearg = get_table_entry(settable, lc + "_name" if lc else "name")
        if not lc and not namearg:
            namearg = title
        if namearg and namearg.strip():
            namearg = _strip_markup(namearg.strip())
            set_.name[Language.normalize(key)] = namearg

    navs = [x for x in data.templates if x.name.strip().lower() == "set navigation"]
    if len(navs) > 1:
        logging.warning(f"Found set with multiple set navigation tables: {title}")

    raw_locales: typing.Dict[str, RawLocale] = {}
    # keyed by locale, or locale and edition; the int is which line of the set
    # page's pack image gallery the image came from
    packimages: typing.Dict[str, typing.Tuple[int, str]] = {}

    def get_card(name: str):
        # MediaWiki escapes "=" and "|" inside template arguments, so a card
        # name containing either arrives from a set list or gallery row still
        # wrapped in the escape ("Sky Striker Ace {{=}} Zero"). Expand them,
        # or the page lookup fails and the row is silently dropped.
        name = name.replace("{{=}}", "=").replace("{{!}}", "|")

        class GetCardDecorator:
            def __init__(self, callback: typing.Callable[[Card], None]) -> None:
                @batcher.getPageID(name)
                def getID(cardid: int, cardname: str):
                    if cardid not in db.cards_by_yugipedia_id:

                        @batcher.getPageID(name + " (card)")
                        def getID(cardid: int, cardname: str):
                            card = db.cards_by_yugipedia_id.get(cardid)
                            if not card:
                                logging.warning(
                                    f"Could not find card {cardname} (card) ({cardid})"
                                )
                                return
                            callback(card)

                        return
                    card = db.cards_by_yugipedia_id.get(cardid)
                    if not card:
                        logging.warning(f"Could not find card {cardname} ({cardid})")
                        return
                    callback(card)

        return GetCardDecorator

    def addcardlist(
        setname: str, raw_locale: RawLocale, editions: typing.List[SetEdition]
    ):
        listpagename = f"Set Card Lists:{setname} ({raw_locale.format.upper()}-{raw_locale.key.upper()})"

        @batcher.getPageContents(listpagename)
        def onGetList(raw_cardlist_data: str):
            cardlist_data = wikitextparser.parse(raw_cardlist_data)
            setlists = [
                x
                for x in cardlist_data.templates
                if x.name.lower().strip() == "set list"
            ]

            row_numbers = itertools.count()

            def add_card_to_cardlist(
                name: str,
                code: str,
                rarity: CardRarity,
                qty: typing.Optional[int],
                noabbr: bool,
                row: int,
                print_status: typing.Optional[PrintStatus] = None,
                print_note: typing.Optional[str] = None,
            ):
                @get_card(name)
                def onGetCard(card: Card):
                    rcs: typing.List[RawPrinting] = []
                    raw_rc = RawPrinting(
                        card,
                        code,
                        rarity,
                        qty or 1,
                        noabbr,
                        row,
                        print_status,
                        print_note,
                    )
                    if (
                        setname in MANUAL_RARITY_FIXUPS
                        and rarity in MANUAL_RARITY_FIXUPS[setname]
                    ):
                        for new_rarity in MANUAL_RARITY_FIXUPS[setname][rarity]:
                            rcs.append(
                                RawPrinting(
                                    raw_rc.card,
                                    raw_rc.code,
                                    new_rarity,
                                    raw_rc.qty,
                                    raw_rc.noabbr,
                                    raw_rc.row,
                                    raw_rc.print_status,
                                    raw_rc.print_note,
                                )
                            )
                    else:
                        rcs.append(raw_rc)

                    for rc in rcs:
                        rcl = rc.locator()
                        if rcl in raw_locale.cards:
                            # the same card at the same code and rarity listed
                            # twice (e.g. an alternate-artwork row); merge the
                            # quantities instead of dropping a row
                            raw_locale.cards[rcl].qty += rc.qty
                        else:
                            raw_locale.cards[rcl] = rc

            for setlist in setlists:
                raw_default_rarity = get_table_entry(setlist, "rarities", "C").strip()
                if not raw_default_rarity:
                    raw_default_rarity = "C"
                # An entry the vocabulary doesn't claim drops itself and leaves
                # the entries beside it alone. Dropping the whole list instead
                # sent every row that names no rarity of its own to Common, over
                # one unreadable entry.
                default_rarities: typing.List[CardRarity] = []
                for raw_default_entry in raw_default_rarity.split(","):
                    raw_default_entry = raw_default_entry.strip()
                    if not raw_default_entry:
                        continue
                    default_entry = resolve_rarity(raw_default_entry)
                    if not default_entry:
                        report_unknown_rarity(
                            listpagename, raw_default_entry, "default rarity list"
                        )
                    else:
                        default_rarities.append(default_entry)

                # A *present* `print` or `qty` parameter gives every row that column,
                # even when the parameter is empty; its value is only the default for
                # rows leaving the column blank. Column presence and column default
                # are therefore two separate things: test presence for the layout,
                # not truthiness of the default.
                raw_default_reprint_status = get_table_entry(setlist, "print")
                has_print_column = raw_default_reprint_status is not None

                raw_default_qty = get_table_entry(setlist, "qty")
                has_qty_column = raw_default_qty is not None
                default_qty = None
                if raw_default_qty is not None and raw_default_qty.strip():
                    try:
                        default_qty = int(raw_default_qty.strip())
                    except ValueError:
                        logging.warning(
                            f"Could not determine default quantity of {listpagename}: {raw_default_qty.strip()}"
                        )

                raw_options = get_table_entry(setlist, "options", "").strip()
                noabbr = "noabbr" in raw_options.lower()

                for arg in setlist.arguments:
                    if arg.positional:
                        rows = [x.strip() for x in arg.value.split("\n") if x.strip()]
                        for row in rows:
                            comment_parts = [
                                x.strip() for x in row.split("//") if x.strip()
                            ]
                            if not comment_parts:
                                continue
                            pre_comment = comment_parts[0]

                            cols = [x.strip() for x in pre_comment.split(";")]

                            if not cols:
                                continue

                            col_index = 0

                            if not noabbr:
                                code = cols[col_index]
                                col_index += 1
                            else:
                                code = ""

                            name = cols[col_index] if len(cols) > col_index else None
                            if not name:
                                continue
                            name = name.replace("#", "")
                            col_index += 1

                            raw_rarities = (
                                [
                                    x.strip()
                                    for x in cols[col_index].split(",")
                                    if x.strip()
                                ]
                                if len(cols) > col_index
                                else []
                            )
                            rarities: typing.List[CardRarity] = []
                            for raw_rarity in raw_rarities:
                                rarity = resolve_rarity(raw_rarity)
                                if not rarity:
                                    report_unknown_rarity(
                                        listpagename, raw_rarity, f"row {name}"
                                    )
                                else:
                                    rarities.append(rarity)
                            col_index += 1

                            print_status = None
                            print_note = None
                            if has_print_column:
                                raw_print_status = (
                                    cols[col_index] if len(cols) > col_index else ""
                                ) or raw_default_reprint_status
                                if raw_print_status and raw_print_status.strip():
                                    print_status = resolve_print_status(
                                        raw_print_status
                                    )
                                    # Published whether or not the status
                                    # resolved: a phrase we decline to classify
                                    # is exactly the one worth handing on whole.
                                    print_note = print_status_note(raw_print_status)
                                    if not print_status:
                                        logging.warning(
                                            f"Got strange print status in {listpagename}, in row {name}: {raw_print_status.strip()}"
                                        )
                                col_index += 1

                            qty = None
                            if has_qty_column and len(cols) > col_index:
                                raw_qty = cols[col_index]
                                if raw_qty:
                                    try:
                                        qty = int(raw_qty)
                                    except ValueError:
                                        logging.warning(
                                            f"Got strange quantity in {listpagename}, in row {name}: {raw_qty}"
                                        )
                                col_index += 1

                            for rarity in rarities or default_rarities:
                                add_card_to_cardlist(
                                    name,
                                    code,
                                    rarity,
                                    qty if qty is not None else default_qty,
                                    noabbr,
                                    next(row_numbers),
                                    print_status,
                                    print_note,
                                )

            if not setlists:
                logging.warning(
                    f"Found set list page without set list template: {listpagename}"
                )

            batcher.flushPendingOperations()
            for edition in editions:
                get_gallery_data(setname, raw_locale, edition, raw_locale.key)

    def get_gallery_data(
        setname: str, raw_locale: RawLocale, edition: SetEdition, locale_code: str
    ):
        if edition not in raw_locale.editions:
            raw_locale.editions.append(edition)

        def do(galleryname: str, gallery_rank: int):
            @batcher.getPageContents(galleryname)
            def onGetList(raw_gallery_data: str):
                gallery_data = wikitextparser.parse(raw_gallery_data)
                gallery_templates = [
                    x
                    for x in gallery_data.templates
                    if x.name.strip().lower() == "set gallery"
                ]
                subgallery_htmls = re.findall(
                    r"<gallery[^\n]*\n(.*?)\n</gallery>", raw_gallery_data, re.DOTALL
                )
                row_numbers = itertools.count()

                def add_card_image(
                    name: str,
                    rarity: CardRarity,
                    alt: str,
                    image: str,
                    row: int,
                    code: typing.Optional[str] = None,
                ):
                    @batcher.getImageURL(f"File:{image}")
                    def onGetImage(url: str):
                        def onGetCard(card: Card, card_rarity: CardRarity = rarity):
                            rcs = [
                                rc
                                for rc in raw_locale.cards.values()
                                if rc.card == card and rc.rarity == card_rarity
                            ]
                            if code and any(rc.code == code for rc in rcs):
                                rcs = [rc for rc in rcs if rc.code == code]
                            if not rcs:
                                if (
                                    rarity == card_rarity
                                    and card_rarity in FALLBACK_RARITIES
                                ):
                                    onGetCard(card, FALLBACK_RARITIES[card_rarity])
                                elif (
                                    not alt
                                ):  # some special cards, like oversized cards, should be ignored
                                    logging.warning(
                                        f"Printing in gallery {galleryname} not found in locale: {name} / {rarity.value} -- Available in {[rc.rarity.value for rc in raw_locale.cards.values() if rc.card == card]}"
                                    )
                            else:
                                for rc in rcs:
                                    _record_image(
                                        rc.image,
                                        ImageLocator(edition, alt),
                                        (gallery_rank, row),
                                        url,
                                    )

                        @get_card(name)
                        def do(card: Card):
                            onGetCard(card)

                for gallery in gallery_templates:
                    default_abbr = get_table_entry(gallery, "abbr", "").strip()

                    raw_default_rarity = (
                        get_table_entry(gallery, "rarities", "").strip()
                        or get_table_entry(gallery, "rarity", "").strip()
                    )
                    if not raw_default_rarity:
                        raw_default_rarity = "C"
                    # Left as None rather than Common: a gallery image is matched
                    # to a printing by rarity, so guessing here hangs the image
                    # off whichever printing happens to be Common.
                    default_rarity = resolve_rarity(raw_default_rarity)
                    if not default_rarity:
                        report_unknown_rarity(
                            galleryname, raw_default_rarity, "gallery default"
                        )

                    default_alt = get_table_entry(gallery, "alt", "").strip()

                    for arg in gallery.arguments:
                        if arg.positional:
                            rows = [
                                x.strip() for x in arg.value.split("\n") if x.strip()
                            ]
                            for row in rows:
                                comment_parts = [
                                    x.strip() for x in row.split("//") if x.strip()
                                ]
                                if not comment_parts:
                                    continue
                                pre_comment = comment_parts[0]
                                post_comment = " // ".join(comment_parts[1:])
                                abbr_override = re.search(
                                    r"abbr::\s*([^\s;]+)", post_comment
                                )
                                file_override = re.search(
                                    r"file::\s*([^\s;]+)", post_comment
                                )
                                ext_override = re.search(
                                    r"extension::\s*([^\s;]+)", post_comment
                                )

                                cols = [x.strip() for x in pre_comment.split(";")]

                                if not cols:
                                    continue

                                if all(
                                    col.lower() in GALLERY_LEGEND_WORDS for col in cols
                                ):
                                    # The template's own parameter legend, left
                                    # on a gallery nobody filled in. Not a card
                                    # row, and correctly skipped. It has to go
                                    # before the rarity column is resolved:
                                    # `rarity` is a legend word, so the row
                                    # otherwise warns once as an unknown rarity
                                    # and once as an undecipherable rarity code,
                                    # then spends an image lookup on a file
                                    # named after a card called `name`. Counted
                                    # rather than printed - see
                                    # `EXPECTED_CONDITIONS`.
                                    EXPECTED_CONDITIONS.warning(
                                        f"Found parameter legend where a gallery row should be in {galleryname}: {pre_comment}"
                                    )
                                    continue

                                col_index = 0

                                # An abbreviation from either source - the
                                # template-level parameter or the row-level entry
                                # option - means this row has no card-number
                                # column, so it must be resolved before the first
                                # column is consumed.
                                abbr = (
                                    str(abbr_override.group(1))
                                    if abbr_override
                                    else default_abbr
                                )

                                code = abbr if abbr else None
                                if not abbr and len(cols) > col_index:
                                    code = cols[col_index]
                                    col_index += 1

                                if len(cols) > col_index:
                                    name = cols[col_index]
                                    col_index += 1
                                else:
                                    continue

                                rarity = default_rarity
                                raw_rarity = raw_default_rarity
                                if len(cols) > col_index:
                                    col_rarity = cols[col_index]
                                    if col_rarity:
                                        raw_rarity = col_rarity
                                        rarity_override = resolve_rarity(raw_rarity)
                                        if rarity_override:
                                            rarity = rarity_override
                                        else:
                                            report_unknown_rarity(
                                                galleryname, raw_rarity, f"row {name}"
                                            )
                                    col_index += 1

                                if not rarity:
                                    # nothing this row or its gallery named is a
                                    # rarity we know, and add_card_image finds the
                                    # printing to attach to by rarity
                                    continue

                                raw_alt = default_alt or ""
                                if len(cols) > col_index:
                                    raw_alt = cols[col_index]
                                    col_index += 1

                                colorful_rare_selector = (rarity, raw_alt)
                                if colorful_rare_selector in COLORFUL_RARES:
                                    rarity = COLORFUL_RARES[colorful_rare_selector]
                                    alt = ""
                                else:
                                    alt = raw_alt

                                if file_override:
                                    image = file_override.group(1)
                                else:
                                    image = re.sub(r"\W", r"", name)
                                    if code:
                                        code_before_dash = re.match(r"[^\-]+", code)
                                        if code_before_dash:
                                            image += f"-{code_before_dash.group(0)}"
                                    image += f"-{raw_locale.key.upper()}"
                                    if raw_rarity:
                                        rarity_code = resolve_abbreviation(raw_rarity)
                                        if rarity_code:
                                            image += f"-{rarity_code}"
                                        else:
                                            image += f"-{raw_rarity}"
                                            logging.warning(
                                                f"Could not decipher rarity code for {name} in {galleryname}: {raw_rarity}"
                                            )
                                    ed_str = EDITIONS_IN_NAV_REVERSE[edition].upper()
                                    if "-" + ed_str in galleryname:
                                        image += f"-{ed_str}"
                                    if raw_alt:
                                        image += f"-{raw_alt}"
                                    if ext_override:
                                        image += f".{ext_override.group(1)}"
                                    else:
                                        image += ".png"

                                add_card_image(
                                    name, rarity, alt, image, next(row_numbers), code
                                )

                for subgallery in subgallery_htmls:
                    lines = [x.strip() for x in subgallery.split("\n") if x.strip()]
                    for line in lines:
                        parsed_line = wikitextparser.parse(line)
                        if len(parsed_line.wikilinks) < 3:
                            # Not a card row, and correctly skipped. A subgallery
                            # is every other gallery on the page: rule inserts,
                            # FAQ cards, coins, card backings. The page's actual
                            # printings are in its `Set gallery` template, which
                            # parses fine. Counted rather than printed — see
                            # `EXPECTED_CONDITIONS`.
                            EXPECTED_CONDITIONS.warning(
                                f"Found strange subgallery line in {galleryname}: {line}"
                            )
                        else:
                            raw_image = re.match(r"\s*([^\|\s]+)", line)
                            if raw_image:
                                image = str(raw_image.group(1))
                            else:
                                image = ""

                            (codelink, raritylink, namelink, *_) = parsed_line.wikilinks
                            rarity = resolve_rarity(raritylink.target)
                            if not rarity:
                                report_unknown_rarity(
                                    galleryname, raritylink.target, "subgallery row"
                                )
                                continue
                            name = namelink.target.strip()
                            add_card_image(
                                name,
                                rarity,
                                "",
                                image,
                                next(row_numbers),
                                codelink.target.strip(),
                            )

                if not gallery_templates and not subgallery_htmls:
                    logging.warning(f"No gallery tables found in {galleryname}!")

        # the edition's own gallery first, so that _record_image prefers its
        # scan over the edition-agnostic gallery's where a locale has both
        do(
            f"Set Card Galleries:{setname} ({raw_locale.format.upper()}-{raw_locale.key.upper()}-{EDITIONS_IN_NAV_REVERSE[edition].upper()})",
            0,
        )
        do(
            f"Set Card Galleries:{setname} ({raw_locale.format.upper()}-{raw_locale.key.upper()})",
            1,
        )

    def parse_packimage_line(line: str, row: int):
        imagename = re.match(r"\S+", line)
        if imagename:
            gallery_links = [
                link.target.strip()
                for link in wikitextparser.parse(line).wikilinks
                if link.target.strip().lower().startswith("set card galleries:")
            ]

            @batcher.getImageURL("File:" + imagename.group(0))
            def onImage(url: str):
                for gallery_link in gallery_links:
                    lc = re.search(r"\([^\-]+\-([^\)]+)\)", gallery_link)
                    if lc:
                        key = lc.group(1).lower()
                        # The earliest line wins. Five set pages, Toon Chaos
                        # among them, point several pack images at one locale
                        # key; keeping the last write published whichever image
                        # lookup answered last, which differs between runs.
                        if key not in packimages or row < packimages[key][0]:
                            packimages[key] = (row, url)

    for nav in navs:
        lists = [
            x.strip().lower()
            for x in get_table_entry(nav, "lists", "").split(",")
            if x.strip()
        ]
        galleries: typing.Dict[str, typing.List[str]] = {}
        setname = title

        for arg in nav.arguments:
            if arg.positional and arg.name == "0":
                # alternate set name
                setname = arg.value.strip()
            if arg.name.endswith("_galleries") and all(
                not arg.name.startswith(x) for x in EDITIONS_IN_NAV
            ):
                logging.warning(
                    f"Found gallery argument for unknown edition in {title}: {arg.name}"
                )

        for edition in EDITIONS_IN_NAV:
            galleries[edition] = [
                x.strip().lower()
                for x in get_table_entry(nav, f"{edition}_galleries", "").split(",")
                if x.strip()
            ]

        if not lists and not galleries:
            logging.warning(f"Found set without card lists or galleries: {title}")

        # deduplicated but kept in the order the set navigation names them:
        # this drives the published locale and set contents ordering, which a
        # set would reshuffle on every run
        all_lcs = list(
            dict.fromkeys([*lists, *[y for x in galleries.values() for y in x]])
        )
        release_dates = {
            locale: _parse_date(_strip_markup(arg.value.strip()))
            for arg in settable.arguments
            if arg.name.strip()[-(len(RELDATE_SUFFIX) - 1) :] == RELDATE_SUFFIX[1:]
            for locale in arg.name.strip()[: -len(RELDATE_SUFFIX)].split("/")
        }
        for lc in all_lcs:
            if lc not in FORMATS_IN_NAV:
                logging.warning(f"Unknown locale in {title}: {lc}")
            else:
                raw_locale = RawLocale(lc, FORMATS_IN_NAV[lc])
                raw_locales[lc] = raw_locale

                db_lc = lc
                while db_lc is not None:
                    dbarg = get_table_entry(
                        settable, db_lc + DBID_SUFFIX if db_lc else DBID_SUFFIX[1:]
                    )
                    if dbarg:
                        raw_ids = [
                            x.strip()
                            for x in dbarg.replace("*", "").split("\n")
                            if x.strip()
                        ]
                        for raw_id in raw_ids:
                            try:
                                raw_locale.db_ids.append(int(raw_id))
                            except ValueError:
                                if raw_id != "none":
                                    logging.warning(
                                        f"Found bad konami ID in {title}: {raw_id}"
                                    )
                        break
                    db_lc = FALLBACK_LOCALES.get(db_lc)

                date_lc = lc
                while date_lc is not None:
                    reldatearg = release_dates.get(date_lc)
                    if reldatearg:
                        raw_locale.date = reldatearg
                        break
                    date_lc = FALLBACK_LOCALES.get(date_lc)

                if not any(x.lower() == lc for x in lists):
                    logging.warning(
                        f"Found set navigation in {title} with gallery but no list for locale {lc}"
                    )
                    continue

                addcardlist(
                    setname,
                    raw_locale,
                    [EDITIONS_IN_NAV[ec] for ec, lcs in galleries.items() if lc in lcs],
                )

    if not navs:
        logging.warning(f"Found set without set navigation table: {title}")
        return False

    if not raw_locales:
        logging.warning(f"Found set without locales: {title}")
        return False

    packimages_html = re.search(
        r"<gallery[^\n]*\n(.*?)\n</gallery>", raw_data, re.DOTALL
    )
    if packimages_html:
        lines = [x.strip() for x in packimages_html.group(1).split("\n") if x.strip()]
        for row, line in enumerate(lines):
            parse_packimage_line(line, row)

    batcher.flushPendingOperations()

    for raw_locale in raw_locales.values():
        # The card lookups that filled this answered in fetch-completion order,
        # so its insertion order is decided by which pages the page cache
        # already held. Put it back into the order the set list page writes its
        # rows, which is what everything below reads it in: the published
        # `cards` list order, and the printing tuple that decides which locales
        # share one SetContents.
        raw_locale.cards = {
            rcl: rc
            for rcl, rc in sorted(
                raw_locale.cards.items(),
                key=lambda item: (item[1].row, item[0].rarity.value),
            )
        }

    old_printing_ids = {
        PrintingLocator(p.card, p.rarity or CardRarity.COMMON, p.suffix): p.id
        for c in set_.contents
        for p in c.cards
    }

    # The art treatments this set's alternate artworks resolved to last run,
    # keyed the way the gallery names them. Harvested before the clear below for
    # the same reason ``old_printing_ids`` is: the locales are rebuilt from
    # scratch, and a treatment that got a fresh UUID every run would be no use
    # to anyone linking to it.
    art_treatments: typing.Dict[typing.Tuple[Card, str], CardImage] = {
        (printing.card, variant.code): variant.art_treatment
        for locale in set_.locales.values()
        for printings in locale.card_image_variants.values()
        for printing, variants in printings.items()
        for variant in variants
        if variant.art_treatment
    }

    set_.locales.clear()
    set_.contents.clear()

    raw_printings_to_content: typing.Dict[
        typing.Tuple[PrintingLocator, ...], SetContents
    ] = {}
    raw_printings_to_printings: typing.Dict[
        SetContents, typing.Dict[PrintingLocator, CardPrinting]
    ] = {}

    for raw_locale in raw_locales.values():
        fmt = Format(raw_locale.format.lower())

        for edition in raw_locale.editions:
            image = packimages.get(
                f"{raw_locale.key}-{EDITIONS_IN_NAV_REVERSE[edition]}"
            ) or packimages.get(raw_locale.key)
            if image:
                raw_locale.images[edition] = image[1]

        prefix = commonprefix(c.code for c in raw_locale.cards.values())
        prefixfixer = re.match(r"[^\-]+\-\D*", prefix)
        if prefixfixer:
            prefix = prefixfixer.group(0)

        def suffix_locator(rc: RawPrinting) -> PrintingLocator:
            # locale-independent locator: the code suffix (e.g. "Y20") is the
            # same across locales, whereas the full code contains the
            # locale-specific prefix
            return PrintingLocator(
                rc.card, rc.rarity, None if rc.noabbr else rc.code[len(prefix) :]
            )

        locale = SetLocale(
            key=Locale.normalize(raw_locale.key),
            language=LOCALES.get(raw_locale.key, raw_locale.key),
            editions=[*raw_locale.editions],
            formats=[fmt],
            image=_pack_image(raw_locale),
            date=raw_locale.date,
            prefix=None
            if all(rc.noabbr for rc in raw_locale.cards.values())
            else prefix,
            db_ids=raw_locale.db_ids,
        )
        set_.locales[locale.key] = locale

        ptc_key = tuple(suffix_locator(rc) for rc in raw_locale.cards.values())
        if ptc_key in raw_printings_to_content:
            content = raw_printings_to_content[ptc_key]
            content.locales.append(locale)
            for edition in raw_locale.editions:
                if edition not in content.editions:
                    content.editions.append(edition)
            if fmt not in content.formats:
                content.formats.append(fmt)
        else:
            content = SetContents(
                locales=[locale],
                editions=[*raw_locale.editions],
                formats=[fmt],
                image=_pack_image(raw_locale),
            )
            raw_printings_to_printings[content] = {}
            for rc in raw_locale.cards.values():
                rcl = suffix_locator(rc)
                if rcl in raw_printings_to_printings[content]:
                    logging.warning(
                        f"Found mutliple printings with the same code and rarity in the same locale in {title}: {rcl.card.text[Language.ENGLISH].name} / {rcl.rarity.value}"
                    )
                    continue
                printing = CardPrinting(
                    id=old_printing_ids[rcl]
                    if rcl in old_printing_ids
                    else uuid.uuid4(),
                    card=rc.card,
                    rarity=rc.rarity,
                    suffix=rcl.code,
                    replica=any(il.altinfo.lower() == "rp" for il in rc.image),
                    qty=rc.qty,
                    print_status=rc.print_status,
                    print_note=rc.print_note,
                )
                raw_printings_to_printings[content][rcl] = printing
                content.cards.append(printing)

            set_.contents.append(content)

        for edition in raw_locale.editions:
            locale.card_images.setdefault(edition, {})
            for rc in raw_locale.cards.values():
                ils = [il for il in rc.image if il.edition == edition]
                if ils:
                    printing = raw_printings_to_printings[content][suffix_locator(rc)]
                    locale.card_images[edition][printing] = rc.image[
                        _canonical_image(ils)
                    ].url
                    # Every image the galleries tagged with a code, in code order:
                    # the codes a printing carries in one edition are distinct,
                    # since they key the same dict, so this order is total and the
                    # same on every run. The canonical image is among them wherever
                    # the printing has no plain scan at all.
                    variants = [
                        _variant_image(art_treatments, rc.card, il, rc.image[il].url)
                        for il in sorted(ils, key=lambda il: il.altinfo)
                        if il.altinfo
                    ]
                    if variants:
                        locale.card_image_variants.setdefault(edition, {})[
                            printing
                        ] = variants

    return True


MD_DISAMBIG_SUFFIX = " (Master Duel)"
DL_DISAMBIG_SUFFIX = " (Duel Links)"
ARCHETYPE_DISAMBIG_SUFFIX = " (archetype)"
SERIES_DISAMBIG_SUFFIX = " (series)"


def parse_md_set(
    db: Database,
    batcher: "YugipediaBatcher",
    pageid: int,
    set_: Set,
    data: wikitextparser.WikiText,
    raw_data: str,
    settable: wikitextparser.Template,
) -> bool:
    title = batcher.idsToNames[pageid]
    set_.name[Language.ENGLISH] = (
        title[: -len(MD_DISAMBIG_SUFFIX)]
        if title.endswith(MD_DISAMBIG_SUFFIX)
        else title
    )
    set_.yugipedia = ExternalIdPair(title, pageid)

    set_.date = _parse_date(
        _strip_markup(get_table_entry(settable, "release_date", "")).strip()
    )
    if set_.contents:
        contents = set_.contents[0]
    else:
        contents = SetContents(formats=[Format.MASTERDUEL])

    # the cards the set list names, and which of its rows first named them
    found_cards: typing.Dict[Card, int] = {}
    row_numbers = itertools.count()
    setlists = [
        x for x in data.templates if x.name.strip().lower() == "master duel set list"
    ]
    if not setlists:
        logging.warning(f"Found Master Duel set without setlists: {title}")
        return False

    raw_imagename = get_table_entry(settable, "image")
    if raw_imagename and raw_imagename.strip():
        raw_imagename = f"File:{raw_imagename.strip()}"
    else:
        raw_imagename = f"File:{title}-Pack-Master Duel.png"

    @batcher.getImageURL(raw_imagename)
    def onGetImage(url: str):
        contents.image = url

    for setlist in setlists:
        for arg in setlist.arguments:
            if not arg.positional:
                continue
            for row in [x.strip() for x in arg.value.split("\n") if x.strip()]:
                # first is card; second is rarity; third is (optional) quantity (in decks) or reprint status (in packs)
                parts = [x.strip() for x in row.split(";") if x.strip()]
                if not parts:
                    continue

                cardname = parts[0]
                if cardname.endswith(MD_DISAMBIG_SUFFIX):
                    cardname = cardname[: -len(MD_DISAMBIG_SUFFIX)]

                def add_card(card: Card, row: int):
                    found_cards.setdefault(card, row)
                    if card not in {p.card for p in contents.cards}:
                        contents.cards.append(CardPrinting(id=uuid.uuid4(), card=card))

                def do(cardname: str, row: int):
                    @batcher.getPageID(cardname)
                    def onGetID(cardid: int, _: str):
                        card = db.cards_by_yugipedia_id.get(cardid)
                        if not card:

                            @batcher.getPageID(cardname + " (card)")
                            def onGetID(cardid: int, _: str):
                                card = db.cards_by_yugipedia_id.get(cardid)
                                if not card:
                                    logging.warning(
                                        f"Unknown card in MD set {title}: {cardname}"
                                    )
                                else:
                                    add_card(card, row)

                        else:
                            add_card(card, row)

                do(cardname, next(row_numbers))

    def deloldprints():
        for i, printing in enumerate([*contents.cards]):
            if printing.card not in found_cards:
                del contents.cards[i]
                return deloldprints()
                # if printing.card not in {p.card for p in contents.removed_cards}:
                #     contents.removed_cards.append(printing)

    # Every card lookup above is asynchronous. Without this, a cold page cache
    # leaves `found_cards` empty here, `deloldprints` deletes the whole set as
    # unfound, and the answers then rebuild it with fresh printing UUIDs.
    batcher.flushPendingOperations()

    deloldprints()

    # The answers arrived in fetch-completion order, so anything appended above
    # sits in cache-hit order rather than set list order.
    contents.cards.sort(key=lambda printing: found_cards[printing.card])

    if contents not in set_.contents:
        set_.contents.append(contents)

    return True


def parse_dl_set(
    db: Database,
    batcher: "YugipediaBatcher",
    pageid: int,
    set_: Set,
    data: wikitextparser.WikiText,
    raw_data: str,
    settable: wikitextparser.Template,
) -> bool:
    title = batcher.idsToNames[pageid]
    set_.name[Language.ENGLISH] = (
        title[: -len(DL_DISAMBIG_SUFFIX)]
        if title.endswith(DL_DISAMBIG_SUFFIX)
        else title
    )
    set_.yugipedia = ExternalIdPair(title, pageid)

    set_.date = _parse_date(
        _strip_markup(get_table_entry(settable, "release_date", "")).strip()
    )
    if set_.contents:
        contents = set_.contents[0]
    else:
        contents = SetContents(formats=[Format.DUELLINKS])

    # the cards the set list names, and which of its rows first named them
    found_cards: typing.Dict[Card, int] = {}
    row_numbers = itertools.count()
    setlists = [x for x in data.templates if x.name.strip().lower() == "set list"]
    if not setlists:
        logging.warning(f"Found Duel Links set without setlists: {title}")
        return False

    raw_imagename = get_table_entry(settable, "image")
    if raw_imagename and raw_imagename.strip():

        @batcher.getImageURL(f"File:{raw_imagename.strip()}")
        def onGetImage(url: str):
            contents.image = url

    for setlist in setlists:
        for arg in setlist.arguments:
            if not arg.positional:
                continue
            for row in [x.strip() for x in arg.value.split("\n") if x.strip()]:
                # 1st is card; 2nd is rarity; 3rd is (optional) reprint status; 4th is (optional) quantity
                parts = [x.strip() for x in row.split(";") if x.strip()]
                if not parts:
                    continue

                cardname = parts[0]
                if cardname.endswith(DL_DISAMBIG_SUFFIX):
                    cardname = cardname[: -len(DL_DISAMBIG_SUFFIX)]

                def add_card(card: Card, row: int):
                    found_cards.setdefault(card, row)
                    if card not in {p.card for p in contents.cards}:
                        contents.cards.append(CardPrinting(id=uuid.uuid4(), card=card))

                def do(cardname: str, row: int):
                    @batcher.getPageID(cardname)
                    def onGetID(cardid: int, _: str):
                        card = db.cards_by_yugipedia_id.get(cardid)
                        if not card:

                            @batcher.getPageID(cardname + " (card)")
                            def onGetID(cardid: int, _: str):
                                card = db.cards_by_yugipedia_id.get(cardid)
                                if not card:
                                    logging.warning(
                                        f"Unknown card in DL set {title}: {cardname}"
                                    )
                                else:
                                    add_card(card, row)

                        else:
                            add_card(card, row)

                do(cardname, next(row_numbers))

    def deloldprints():
        for i, printing in enumerate([*contents.cards]):
            if printing.card not in found_cards:
                del contents.cards[i]
                return deloldprints()
                # if printing.card not in {p.card for p in contents.removed_cards}:
                #     contents.removed_cards.append(printing)

    # Every card lookup above is asynchronous. Without this, a cold page cache
    # leaves `found_cards` empty here, `deloldprints` deletes the whole set as
    # unfound, and the answers then rebuild it with fresh printing UUIDs.
    batcher.flushPendingOperations()

    deloldprints()

    # The answers arrived in fetch-completion order, so anything appended above
    # sits in cache-hit order rather than set list order.
    contents.cards.sort(key=lambda printing: found_cards[printing.card])

    if contents not in set_.contents:
        set_.contents.append(contents)

    return True


def parse_series(
    db: Database,
    batcher: "YugipediaBatcher",
    pageid: int,
    title: str,
    series: Series,
    data: wikitextparser.WikiText,
    seriestable: wikitextparser.Template,
    series_members: typing.Dict[str, typing.Set[Card]],
) -> bool:
    name = title
    if name.endswith(ARCHETYPE_DISAMBIG_SUFFIX):
        name = title[: -len(ARCHETYPE_DISAMBIG_SUFFIX)]
    if name.endswith(SERIES_DISAMBIG_SUFFIX):
        name = title[: -len(SERIES_DISAMBIG_SUFFIX)]

    for locale, key in LOCALES.items():
        value = get_table_entry(seriestable, locale + "_name" if locale else "name")
        if not locale and not value:
            value = name
        if value and value.strip():
            value = _strip_markup(value.strip())
            series.name[Language.normalize(key)] = value

    @batcher.getPageCategories(pageid)
    def onCatsGet(cats: typing.List[int]):
        if batcher.namesToIDs.get(CAT_ARCHETYPES) in cats:
            series.archetype = True
        elif batcher.namesToIDs.get(CAT_SERIES) in cats:
            series.archetype = False

    if name.lower() in series_members:
        series.members.update(series_members[name.lower()])
    if title.lower() in series_members:
        series.members.update(series_members[title.lower()])

    series.yugipedia = ExternalIdPair(title, pageid)
    return True


class Banlist:
    format: str
    date: datetime.date
    cards: typing.Dict[str, Legality]

    def __init__(
        self,
        *,
        format: str,
        date: datetime.date,
        cards: typing.Optional[typing.Dict[str, Legality]] = None,
    ) -> None:
        self.format = format
        self.date = date
        self.cards = cards or {}


BANLIST_STR_TO_LEGALITY = {
    "unlimited": Legality.UNLIMITED,
    "no_longer_on_list": Legality.UNLIMITED,
    "no-longer-on-list": Legality.UNLIMITED,
    "semi-limited": Legality.SEMILIMITED,
    "semi_limited": Legality.SEMILIMITED,
    "limited": Legality.LIMITED,
    "forbidden": Legality.FORBIDDEN,
    "did not exist": Legality.UNRELEASED,
    # speed duel legalities
    "limited_0": Legality.FORBIDDEN,
    "limited_1": Legality.LIMIT1,
    "limited_2": Legality.LIMIT2,
    "limited_3": Legality.LIMIT3,
}


def _parse_banlist(
    batcher: "YugipediaBatcher", pageid: int, format: str, raw_data: str
) -> typing.Optional[Banlist]:
    data = wikitextparser.parse(raw_data)

    limitlists = [
        x for x in data.templates if x.name.strip().lower() == "limitation list"
    ]
    md_limitlists = [
        x
        for x in data.templates
        if x.name.strip().lower() == "master duel limitation status list"
    ]
    if not limitlists and not md_limitlists:
        if (
            format != "masterduel"
        ):  # master duel has a lot of event banlists we want to ignore
            logging.warning(
                f"Found banlist without limitlist template: {batcher.idsToNames[pageid]}"
            )
        return None

    cards: typing.Dict[str, Legality] = {}
    raw_start_date = None

    for limitlist in limitlists:
        raw_start_date = _strip_markup(
            get_table_entry(limitlist, "start_date", "")
        ).strip()

        for arg in limitlist.arguments:
            if arg.name and arg.name.strip().lower() in BANLIST_STR_TO_LEGALITY:
                legality = BANLIST_STR_TO_LEGALITY[arg.name.strip().lower()]
                cardlist = [
                    x.split("//")[0].strip() for x in arg.value.split("\n") if x.strip()
                ]
                for card in cardlist:
                    if card.lower().endswith(DL_DISAMBIG_SUFFIX):
                        card = card[: -len(DL_DISAMBIG_SUFFIX)]
                    cards[card] = legality

    for limitlist in md_limitlists:
        raw_date = get_table_entry(limitlist, "date")
        if raw_date and raw_date.strip():
            raw_start_date = _strip_markup(raw_date).strip()

        for row in [
            x.split("//")[0].strip()
            for x in get_table_entry(limitlist, "cards", "").split("\n")
            if x.strip()
        ]:
            parts = [x.strip() for x in row.split(";")]
            if len(parts) == 2:
                (name, raw_legality) = parts
            elif len(parts) == 3:
                (name, _, raw_legality) = parts
            else:
                logging.warning(
                    f"Unparsable master duel banlist row in {batcher.idsToNames[pageid]}: {row}"
                )
                continue

            if raw_legality.lower() not in BANLIST_STR_TO_LEGALITY:
                logging.warning(
                    f"Unknown legality in master duel banlist row in {batcher.idsToNames[pageid]}: {raw_legality}"
                )
                continue

            cards[name] = BANLIST_STR_TO_LEGALITY[raw_legality.lower()]

    start_date = _parse_date(raw_start_date or "")
    if not start_date:
        logging.warning(
            f"Found invalid start date of {batcher.idsToNames[pageid]}: {raw_start_date}"
        )
        return None

    return Banlist(format=format, date=start_date, cards=cards)


def get_banlist_pages(
    batcher: "YugipediaBatcher",
) -> typing.Dict[str, typing.List[Banlist]]:
    with tqdm.tqdm(
        total=len(BANLIST_CATS), desc="Fetching Yugipedia banlists"
    ) as progress_bar:
        result: typing.Dict[str, typing.List["Banlist"]] = {}

        for format, catname in BANLIST_CATS.items():

            def do(format: str, catname: str):
                @batcher.getCategoryMembers(catname)
                def onGetBanlistCat(members: typing.List[int]):
                    for member in members:

                        def do(member: int):
                            @batcher.getPageID(member)
                            def onGetID(_pageid: int, _title: str):
                                @batcher.getPageContents(member)
                                def onGetContents(raw_data: str):
                                    banlist = _parse_banlist(
                                        batcher, member, format, raw_data
                                    )
                                    if banlist:
                                        result.setdefault(format, [])
                                        result[format].append(banlist)

                        do(member)
                    progress_bar.update(1)

            do(format, catname)

        batcher.flushPendingOperations()
        for format, banlists in result.items():
            banlists.sort(key=lambda b: b.date)
            running_totals: typing.Dict[str, Legality] = {}
            for banlist in banlists:
                for card, legality in {**banlist.cards}.items():
                    if card in running_totals and running_totals[card] == legality:
                        del banlist.cards[card]
                    else:
                        running_totals[card] = legality

        return result


def get_genesys_banlist(
    batcher: "YugipediaBatcher",
) -> typing.Dict[datetime.date, typing.Dict[str, float]]:
    with tqdm.tqdm(total=1, desc="Fetching Yugipedia pointlists") as progress_bar:
        result: typing.Dict[datetime.date, typing.Dict[str, float]] = {}

        @batcher.getCategoryMembers(CAT_BANLIST_GENESYS)
        def onGetGenesysBanlist(banlists: typing.List[int]):
            for banlist in banlists:

                def do(banlist):
                    @batcher.getPageContents(banlist)
                    def onGetBanlist(raw_data: str):
                        data = wikitextparser.parse(raw_data)

                        tables = [
                            x
                            for x in data.templates
                            if x.name.strip().lower() == "genesys point list"
                        ]
                        if len(tables) != 1:
                            logging.warning(
                                f"Genesys pointlist has odd number of tables: {batcher.idsToNames[banlist]}"
                            )
                            return
                        table = tables[0]

                        date = _parse_date(get_table_entry(table, "date", "").strip())
                        if date is None:
                            logging.warning(
                                f"Genesys pointlist has odd date: {repr(get_table_entry(table, 'date'))}"
                            )
                            return
                        result[date] = {}

                        for raw_card in (
                            get_table_entry(table, "cards", "").strip().split("\n")
                        ):
                            raw_fields = raw_card.strip().split(";")

                            if len(raw_fields) == 0:
                                continue
                            elif len(raw_fields) < 2:
                                logging.warning(
                                    f"Genesys pointlist entry has odd number of fields: '{raw_card.strip()}'"
                                )
                                continue
                            elif len(raw_fields) > 3:
                                logging.warning(
                                    f"Genesys pointlist entry has odd number of fields: '{raw_card.strip()}'"
                                )

                            name = raw_fields[0].strip()
                            points = float(raw_fields[1].strip())

                            result[date][name] = points

                do(banlist)

        batcher.flushPendingOperations()
        progress_bar.update()
        return result


def _attach_art_treatments(db: Database) -> None:
    """Puts every art treatment a gallery's alternate artworks resolved to into
    its card's list of them.

    Appends, like every other way this list is filled: an art treatment keeps
    the position it was first published at, since the card page's own image list
    is read against this one by position.

    What one run appends is sorted, though, because the gallery parse cannot
    offer a stable order to append in. A warm page cache answers a page lookup
    inside the call that asks for it, while a cold one answers it whenever the
    batch it landed in comes back, so which set's gallery is read first differs
    between two runs. Sorting on what the sets say, rather than leaving it to
    when they answered, is what makes a cold run and a warm one write the same
    file.
    """
    found: typing.Dict[Card, typing.List[typing.Tuple[str, str, str, CardImage]]] = {}
    for set_ in db.sets:
        name = set_.name.get(Language.ENGLISH, "")
        for locale in set_.locales.values():
            for printings in locale.card_image_variants.values():
                for printing, variants in printings.items():
                    for variant in variants:
                        if variant.art_treatment:
                            found.setdefault(printing.card, []).append(
                                (
                                    name,
                                    str(set_.id),
                                    variant.code,
                                    variant.art_treatment,
                                )
                            )

    n_new = 0
    for card, entries in found.items():
        # One artwork reaches a card once per locale, rarity and edition of the
        # set that published it, and again from every other set that did; the
        # list holds each treatment once, and already holds the ones a previous
        # run wrote to the card's own JSON.
        for *_, treatment in sorted(entries, key=lambda entry: entry[:3]):
            if treatment not in card.images:
                card.images.append(treatment)
                n_new += 1

    logging.info(
        f"{n_new} alternate artworks became new art treatments, "
        f"across {len(found)} cards."
    )


def import_from_yugipedia(
    db: Database,
    *,
    import_cards: bool = True,
    import_sets: bool = True,
    import_series: bool = True,
    production: bool = False,
    partition_filepath: typing.Optional[str] = None,
    specific_pages: typing.Sequence[typing.Union[int, str]] = (),
) -> typing.Tuple[int, int]:
    n_found = n_new = 0

    with YugipediaBatcher() as batcher:
        atexit.register(
            lambda: batcher.saveCachesToDisk()
        )  # to ensure we never lose cache data

        series_members: typing.Dict[str, typing.Set[Card]] = {}

        if partition_filepath is None:
            # process everything we can get our grubby mitts on
            cards, sets, series = _get_lists(
                db,
                batcher,
                import_cards=import_cards,
                import_sets=import_sets,
                import_series=import_series,
                production=production,
            )
        else:
            # only process what's given in the spec file
            with open(partition_filepath, encoding="utf-8") as file:
                things: typing.Dict[str, typing.List[int]] = json.load(file)
                cards = things.get("cards", [])
                sets = things.get("sets", [])
                series = things.get("series", [])

            # if we don't process every card before we process every series,
            # the series table will be all messed up. Fix that via DB lookup.
            for existing_series in db.series:
                if existing_series.yugipedia:
                    name = existing_series.yugipedia.name.lower()
                    series_members.setdefault(name, set())
                    for member in existing_series.members:
                        series_members[name].add(member)

        if len(specific_pages) > 0:
            specific_ids: typing.List[int] = []
            for page in specific_pages:

                def get_page_id(page: typing.Union[int, str]):
                    @batcher.getPageID(page)
                    def on_get_id(id: int, title: str):
                        specific_ids.append(id)

                get_page_id(page)
            batcher.flushPendingOperations()
            cards = [x for x in cards if x in specific_ids]
            sets = [x for x in sets if x in specific_ids]
            series = [x for x in series if x in specific_ids]

        if import_cards:
            banlists = get_banlist_pages(batcher)
            genesys_banlist = get_genesys_banlist(batcher)

            for pageid in tqdm.tqdm(cards, desc="Importing cards from Yugipedia"):

                def do(pageid: int):
                    @batcher.getPageCategories(pageid)
                    def onGetCats(categories: typing.List[int]):
                        @batcher.getPageContents(pageid)
                        def onGetData(raw_data: str):
                            nonlocal n_found, n_new

                            data = wikitextparser.parse(raw_data)
                            try:
                                cardtable = next(
                                    iter(
                                        [
                                            x
                                            for x in data.templates
                                            if x.name.strip().lower() == "cardtable2"
                                        ]
                                    )
                                )
                            except StopIteration:
                                logging.warning(
                                    f"Found card without card table: {batcher.idsToNames[pageid]}"
                                )
                                return

                            raw_ct = get_table_entry(
                                cardtable, "card_type", "monster"
                            ).strip()
                            ct = resolve_card_type(raw_ct)
                            if batcher.namesToIDs.get(CAT_TOKENS) in categories:
                                ct = CardType.TOKEN
                            if batcher.namesToIDs.get(CAT_SKILLS) in categories:
                                ct = CardType.SKILL
                            if ct is None:
                                logging.warning(
                                    f"Found card with illegal card type in "
                                    f"{batcher.idsToNames[pageid]}: {raw_ct}"
                                )
                                return

                            found = pageid in db.cards_by_yugipedia_id
                            card = db.cards_by_yugipedia_id.get(pageid)
                            if not card:
                                value = get_table_entry(cardtable, "database_id", "")
                                vmatch = re.match(r"^\d+", value.strip())
                                if vmatch:
                                    card = db.cards_by_konami_cid.get(
                                        int(vmatch.group(0))
                                    )
                            if not card:
                                value = get_table_entry(cardtable, "password", "")
                                vmatch = re.match(r"^\d+", value.strip())
                                if vmatch:
                                    card = db.cards_by_password.get(vmatch.group(0))
                            if not card and batcher.idsToNames[pageid] != "Token":
                                # find by english name except for Token, which has a lot of cards called exactly that
                                card = db.cards_by_en_name.get(
                                    batcher.idsToNames[pageid]
                                )
                            if not card:
                                card = Card(id=uuid.uuid4(), card_type=ct)

                            if parse_card(
                                batcher,
                                pageid,
                                card,
                                data,
                                categories,
                                banlists,
                                series_members,
                                genesys_banlist,
                            ):
                                db.add_card(card)
                                if found:
                                    n_found += 1
                                else:
                                    n_new += 1

                do(pageid)

            batcher.saveCachesToDisk()

        if import_sets:
            for setid in tqdm.tqdm(sets, desc="Importing sets from Yugipedia"):

                def do(pageid: int):
                    @batcher.getPageContents(pageid)
                    def onGetData(raw_data: str):
                        nonlocal n_found, n_new, cards

                        data = wikitextparser.parse(raw_data)

                        settables = [
                            x
                            for x in data.templates
                            if x.name.strip().lower() == "infobox set"
                        ]
                        for settable in settables:

                            def do(settable: wikitextparser.Template):
                                nonlocal cards

                                found = True
                                set_ = db.sets_by_yugipedia_id.get(pageid)
                                if not set_:
                                    for arg in settable.arguments:
                                        if arg.name and arg.name.strip().endswith(
                                            DBID_SUFFIX
                                        ):
                                            db_ids = [
                                                x.strip()
                                                for x in arg.value.replace(
                                                    "*", ""
                                                ).split("\n")
                                                if x.strip()
                                            ]
                                            try:
                                                for db_id in db_ids:
                                                    set_ = db.sets_by_konami_sid.get(
                                                        int(db_id)
                                                    )
                                                    if set_:
                                                        break
                                            except ValueError:
                                                if arg.value.strip() != "none":
                                                    logging.warning(
                                                        f'Unparsable konami set ID for {arg.name} in {batcher.idsToNames.get(pageid, pageid)}: "{arg.value}"'
                                                    )
                                if not set_:
                                    set_ = db.sets_by_en_name.get(
                                        get_table_entry(settable, "en_name", "")
                                    )
                                if not set_:
                                    set_ = Set(id=uuid.uuid4())
                                    found = False

                                cards = cards or [*get_card_pages(batcher)]

                                @batcher.getPageID(pageid)
                                def onGetID(pageid: int, title: str):
                                    nonlocal n_found, n_new

                                    if parse_tcg_ocg_set(
                                        db,
                                        batcher,
                                        pageid,
                                        set_,
                                        data,
                                        raw_data,
                                        settable,
                                    ):
                                        db.add_set(set_)
                                        if found:
                                            n_found += 1
                                        else:
                                            n_new += 1

                            do(settable)

                        md_settables = [
                            x
                            for x in data.templates
                            if x.name.strip().lower() == "infobox master duel set"
                        ]
                        for md_settable in md_settables:

                            @batcher.getPageID(pageid)
                            def onGetName(pageid: int, title: str):
                                found = True
                                set_ = db.sets_by_yugipedia_id.get(pageid)
                                if not set_:
                                    set_ = Set(id=uuid.uuid4())
                                    found = False

                                if parse_md_set(
                                    db,
                                    batcher,
                                    pageid,
                                    set_,
                                    data,
                                    raw_data,
                                    md_settable,
                                ):
                                    nonlocal n_found, n_new
                                    db.add_set(set_)
                                    if found:
                                        n_found += 1
                                    else:
                                        n_new += 1

                        dl_settables = [
                            x
                            for x in data.templates
                            if x.name.strip().lower() == "infobox duel links set"
                        ]
                        for dl_settable in dl_settables:

                            @batcher.getPageID(pageid)
                            def onGetName(pageid: int, title: str):
                                found = True
                                set_ = db.sets_by_yugipedia_id.get(pageid)
                                if not set_:
                                    set_ = Set(id=uuid.uuid4())
                                    found = False

                                if parse_dl_set(
                                    db,
                                    batcher,
                                    pageid,
                                    set_,
                                    data,
                                    raw_data,
                                    dl_settable,
                                ):
                                    nonlocal n_found, n_new
                                    db.add_set(set_)
                                    if found:
                                        n_found += 1
                                    else:
                                        n_new += 1

                        if not settables and not md_settables and not dl_settables:

                            @batcher.getPageID(pageid)
                            def onGetName(pageid: int, title: str):
                                # Not a set, and correctly rejected. These are
                                # hub pages naming a product *line* — series
                                # indexes, promo overviews, navigation — and
                                # none carries a set infobox, so there is
                                # nothing here to parse. Counted rather than
                                # printed — see `EXPECTED_CONDITIONS`.
                                EXPECTED_CONDITIONS.warning(
                                    f"Found set without set table: {title}"
                                )

                            return

                do(setid)

            batcher.saveCachesToDisk()

        if import_series:
            for seriesid in tqdm.tqdm(series, desc="Importing series from Yugipedia"):

                def do(pageid: int):
                    @batcher.getPageContents(pageid)
                    def onGetData(raw_data: str):
                        nonlocal n_found, n_new

                        title = batcher.idsToNames.get(pageid)
                        if title is None:
                            logging.warning(f"Found series ID without title: {pageid}")
                            return
                        data = wikitextparser.parse(raw_data)

                        seriestables = [
                            x
                            for x in data.templates
                            if x.name.strip().lower()
                            in {
                                "infobox archseries",
                                "infobox archetype",
                                "infobox series",
                            }
                        ]
                        for seriestable in seriestables:
                            series = db.series_by_yugipedia_id.get(pageid)
                            found = True
                            if not series and title.endswith(ARCHETYPE_DISAMBIG_SUFFIX):
                                series = db.series_by_en_name.get(
                                    title[: -len(ARCHETYPE_DISAMBIG_SUFFIX)]
                                )
                            if not series and title.endswith(SERIES_DISAMBIG_SUFFIX):
                                series = db.series_by_en_name.get(
                                    title[: -len(SERIES_DISAMBIG_SUFFIX)]
                                )
                            if not series:
                                series = db.series_by_en_name.get(title)
                            if not series:
                                series = Series(id=uuid.uuid4())
                                found = False

                            if parse_series(
                                db,
                                batcher,
                                pageid,
                                title,
                                series,
                                data,
                                seriestable,
                                series_members,
                            ):
                                db.add_series(series)
                                if found:
                                    n_found += 1
                                else:
                                    n_new += 1

                        if not seriestables:
                            logging.warning(
                                f"Found series without series table: {batcher.idsToNames[pageid]}"
                            )
                            return

                do(seriesid)

    # One line rather than one per miss: per-miss logging was tried and abandoned (the two
    # commented-out warnings in the batcher are what is left of it), and the point of this
    # figure is that somebody reads it. The first number cannot tell "we built the wrong
    # filename" from "the wiki genuinely has no such image" - it is a tripwire for watching
    # the figure across runs, not a way to scope which of the two is happening.
    unresolved_images = (
        batcher.missingFilePages
        + batcher.filePagesWithoutImage
        + batcher.licenseRestrictedImages
        + batcher.cachedMissingImages
    )
    logging.warning(
        f"{unresolved_images} image lookups did not resolve: "
        f"{batcher.missingFilePages} file pages that do not exist, "
        f"{batcher.filePagesWithoutImage} file pages carrying no image, "
        f"{batcher.licenseRestrictedImages} images Yugipedia won't serve for licensing reasons, "
        f"{batcher.cachedMissingImages} already known to be missing from a previous run."
    )

    _attach_art_treatments(db)

    return n_found, n_new


def _get_lists(
    db: Database,
    batcher: "YugipediaBatcher",
    *,
    import_cards: bool = True,
    import_sets: bool = True,
    import_series: bool = True,
    production: bool = False,
) -> typing.Tuple[typing.List[int], typing.List[int], typing.List[int]]:
    """Returns (cardIDs, setIDs, seriesIDs)."""

    last_access = db.last_yugipedia_read
    db.last_yugipedia_read = (
        datetime.datetime.now()
    )  # a conservative estimate of when we accessed, so we don't miss new changelog entries

    if last_access is not None:
        if (
            production
            and datetime.datetime.now().timestamp() - last_access.timestamp()
            > TIME_TO_JUST_REDOWNLOAD_ALL_PAGES
        ):
            # fetching the changelog would take too long; just blow up the cache
            batcher.clearCache()
        else:
            # clear the cache of any changed pages
            _record_changelog_pages([*get_changelog(batcher, last_access)])

    cards = []
    if import_cards:
        cards = [*get_card_pages(batcher)]

    sets = []
    if import_sets:
        sets = [*get_set_pages(batcher)]

    series = []
    if import_series:
        series = [*get_series_pages(batcher)]

    return (cards, sets, series)


def generate_yugipedia_partitions(
    db: Database,
    file_prefix: str,
    n_parts: int,
    *,
    import_cards: bool = True,
    import_sets: bool = True,
    import_series: bool = True,
    production: bool = False,
) -> int:
    """Generates ``n_parts`` partition files, each with the prefix of ``file_prefix``.
    For example, a prefix of "folder/file" would write to files "folder/file1.json", "folder/file2.json", etc.
    Returns the number of cards, sets, and series found.
    """

    with YugipediaBatcher() as batcher:
        cards, sets, series = _get_lists(
            db,
            batcher,
            import_cards=import_cards,
            import_sets=import_sets,
            import_series=import_series,
            production=production,
        )

    unwrapped = [
        *(("card", x) for x in cards),
        *(("set", x) for x in sets),
        *(("series", x) for x in series),
    ]
    random.shuffle(unwrapped)
    n_things = len(unwrapped)
    chunk_size = math.ceil(n_things / n_parts)

    for i in range(1, n_parts + 1):
        things = unwrapped[0:chunk_size]
        del unwrapped[0:chunk_size]

        part_cards = [x[1] for x in things if x[0] == "card"]
        part_sets = [x[1] for x in things if x[0] == "set"]
        part_series = [x[1] for x in things if x[0] == "series"]

        with open(f"{file_prefix}{i}.json", "w", encoding="utf-8") as file:
            json.dump(
                {
                    "cards": part_cards,
                    "sets": part_sets,
                    "series": part_series,
                },
                file,
            )

    return n_things


BATCH_MAX = 50

PAGES_FILENAME = "yugipedia_pages.json"
CONTENTS_FILENAME = "yugipedia_contents.json"
NAMESPACES = {"mw": "http://www.mediawiki.org/xml/export-0.10/"}
IMAGE_URLS_FILENAME = "yugipedia_images.json"
CAT_MEMBERS_FILENAME = "yugipedia_members.json"
PAGE_CATS_FILENAME = "yugipedia_categories.json"
MISSING_PAGES_FILENAME = "yugipedia_missing.json"


class CategoryMemberType(enum.Enum):
    PAGE = "page"
    SUBCAT = "subcat"
    FILE = "file"


class CategoryMember(WikiPage):
    def __init__(self, id: int, name: str, type: CategoryMemberType) -> None:
        super().__init__(id, name)
        self.type = type


class YugipediaBatcher:
    use_cache: bool
    missingPagesCache: typing.Set[str]

    def __init__(self) -> None:
        self.namesToIDs = {}
        self.idsToNames = {}
        self.use_cache = True
        self.missingPagesCache = set()

        self.pendingGetPageContents = {}
        self.pageContentsCache = {}

        self.pendingGetPageCategories = {}
        self.pageCategoriesCache = {}

        self.imagesCache = {}
        self.pendingImages = {}
        self.missingFilePages = 0
        self.filePagesWithoutImage = 0
        self.licenseRestrictedImages = 0
        self.cachedMissingImages = 0

        self.categoryMembersCache = {}

        self.pendingGetPageID = {}

        path = os.path.join(TEMP_DIR, PAGES_FILENAME)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as file:
                pages = json.load(file)
                self.namesToIDs = {page["name"]: page["id"] for page in pages}
                self.idsToNames = {page["id"]: page["name"] for page in pages}

        path = os.path.join(TEMP_DIR, MISSING_PAGES_FILENAME)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as file:
                self.missingPagesCache = {v for v in json.load(file)}

        path = os.path.join(TEMP_DIR, CONTENTS_FILENAME)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as file:
                self.pageContentsCache = {int(k): v for k, v in json.load(file).items()}

        path = os.path.join(TEMP_DIR, PAGE_CATS_FILENAME)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as file:
                self.pageCategoriesCache = {
                    int(k): v for k, v in json.load(file).items()
                }

        path = os.path.join(TEMP_DIR, CAT_MEMBERS_FILENAME)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as file:
                self.categoryMembersCache = {
                    k[1:]
                    if k[0] == "#"
                    else int(k): [
                        CategoryMember(
                            x["id"], x["name"], CategoryMemberType(x["type"])
                        )
                        for x in v
                    ]
                    for k, v in json.load(file).items()
                }

        path = os.path.join(TEMP_DIR, IMAGE_URLS_FILENAME)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as file:
                self.imagesCache = {int(k): v for k, v in json.load(file).items()}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, exc_tb):
        self.flushPendingOperations()
        self.saveCachesToDisk()

    def removeFromCache(self, page: typing.Union[int, str]):
        def del_(cache, page):
            if page in cache:
                del cache[page]

        pageid = title = None
        if type(page) is int:
            pageid = page
            title = self.idsToNames.get(page)
        elif type(page) is str:
            title = page
            pageid = self.namesToIDs.get(page)

        if title:
            if title in self.missingPagesCache:
                self.missingPagesCache.remove(title)
            del_(self.namesToIDs, title)
        if pageid:
            if str(pageid) in self.missingPagesCache:
                self.missingPagesCache.remove(str(pageid))
            del_(self.idsToNames, pageid)
            del_(self.pageContentsCache, pageid)
            del_(self.pageCategoriesCache, pageid)
            del_(self.imagesCache, pageid)
            del_(self.categoryMembersCache, pageid)

    def saveCachesToDisk(self):
        os.makedirs(TEMP_DIR, exist_ok=True)

        path = os.path.join(TEMP_DIR, PAGES_FILENAME)
        with open(path, "w", encoding="utf-8") as file:
            json.dump(
                [{"id": k, "name": v} for k, v in self.idsToNames.items()],
                file,
                indent=2,
            )

        path = os.path.join(TEMP_DIR, MISSING_PAGES_FILENAME)
        with open(path, "w", encoding="utf-8") as file:
            json.dump([v for v in self.missingPagesCache], file, indent=2)

        path = os.path.join(TEMP_DIR, CONTENTS_FILENAME)
        with open(path, "w", encoding="utf-8") as file:
            json.dump(
                {str(k): v for k, v in self.pageContentsCache.items()}, file, indent=2
            )

        path = os.path.join(TEMP_DIR, PAGE_CATS_FILENAME)
        with open(path, "w", encoding="utf-8") as file:
            json.dump(
                {str(k): v for k, v in self.pageCategoriesCache.items()}, file, indent=2
            )

        path = os.path.join(TEMP_DIR, CAT_MEMBERS_FILENAME)
        with open(path, "w", encoding="utf-8") as file:
            json.dump(
                {
                    f"#{k}"
                    if type(k) is str
                    else k: [
                        {"id": x.id, "name": x.name, "type": x.type.value} for x in v
                    ]
                    for k, v in self.categoryMembersCache.items()
                },
                file,
                indent=2,
            )

        path = os.path.join(TEMP_DIR, IMAGE_URLS_FILENAME)
        with open(path, "w", encoding="utf-8") as file:
            json.dump({str(k): v for k, v in self.imagesCache.items()}, file, indent=2)

    def operationsPending(self) -> bool:
        return bool(
            self.pendingGetPageContents
            or self.pendingGetPageCategories
            or self.pendingImages
            or self.pendingGetPageID
        )

    def flushPendingOperations(self):
        while self.operationsPending():
            self._executeGetContentsBatch()
            self._executeGetCategoriesBatch()
            self._executeGetImageURLBatch()
            self._executeGetPageIDBatch()

    def clearCache(self):
        self.categoryMembersCache.clear()
        self.pageCategoriesCache.clear()
        self.pageContentsCache.clear()
        self.imagesCache.clear()
        self.missingPagesCache.clear()

    namesToIDs: typing.Dict[str, int]
    idsToNames: typing.Dict[int, str]

    pageContentsCache: typing.Dict[int, str]
    pendingGetPageContents: typing.Dict[
        typing.Union[str, int], typing.List[typing.Callable[[str], None]]
    ]

    def getPageContents(self, page: typing.Union[str, int]):
        batcher = self

        class GetPageXMLDecorator:
            def __init__(self, callback: typing.Callable[[str], None]) -> None:
                if batcher.use_cache and str(page) in batcher.missingPagesCache:
                    return

                pageid = (
                    page if type(page) is int else batcher.namesToIDs.get(str(page))
                )
                if batcher.use_cache and pageid in batcher.pageContentsCache:
                    callback(batcher.pageContentsCache[pageid])
                else:
                    batcher.pendingGetPageContents.setdefault(pageid or page, [])
                    batcher.pendingGetPageContents[pageid or page].append(callback)
                    if len(batcher.pendingGetPageContents.keys()) >= BATCH_MAX:
                        batcher._executeGetContentsBatch()

            def __call__(self) -> None:
                raise Exception(
                    "Not supposed to call YugipediaBatcher-decorated function!"
                )

        return GetPageXMLDecorator

    def _executeGetContentsBatch(self):
        if not self.pendingGetPageContents:
            return
        pending = {k: v for k, v in self.pendingGetPageContents.items()}
        self.pendingGetPageContents.clear()
        pages = pending.keys()

        def do(pages: typing.Iterable[typing.Union[int, str]]):
            if not pages:
                return
            pageids = [str(p) for p in pages if type(p) is int]
            pagetitles = [str(p) for p in pages if type(p) is str]
            query = {
                "action": "query",
                "export": 1,
                "exportnowrap": 1,
                **({"pageids": "|".join(pageids)} if pageids else {}),
                **({"titles": "|".join(pagetitles)} if pagetitles else {}),
            }
            response_text = make_request(query).text
            pages_xml = xml.etree.ElementTree.fromstring(response_text)

            for page_xml in pages_xml.findall("mw:page", NAMESPACES):
                id = int(page_xml.find("mw:id", NAMESPACES).text)
                title = page_xml.find("mw:title", NAMESPACES).text

                self.namesToIDs[title] = id
                self.idsToNames[id] = title

                contents = (
                    page_xml.find("mw:revision", NAMESPACES)
                    .find("mw:text", NAMESPACES)
                    .text
                )
                self.pageContentsCache[id] = contents
                for callback in pending.get(id, []):
                    callback(contents)
                for callback in pending.get(title, []):
                    callback(contents)

        do([p for p in pages if type(p) is int])
        do([p for p in pages if type(p) is str])

        for p in pages:
            page = p if type(p) is int else self.namesToIDs.get(str(p))
            if page not in self.pageContentsCache:
                self.missingPagesCache.add(str(p))
                self.missingPagesCache.add(str(page))

    pageCategoriesCache: typing.Dict[int, typing.List[int]]
    pendingGetPageCategories: typing.Dict[
        typing.Union[str, int], typing.List[typing.Callable[[typing.List[int]], None]]
    ]

    def getPageCategories(self, page: typing.Union[str, int]):
        batcher = self

        class GetPageCategoriesDecorator:
            def __init__(
                self, callback: typing.Callable[[typing.List[int]], None]
            ) -> None:
                if batcher.use_cache and str(page) in batcher.missingPagesCache:
                    return

                pageid = (
                    page if type(page) is int else batcher.namesToIDs.get(str(page))
                )
                if batcher.use_cache and pageid in batcher.pageCategoriesCache:
                    callback(batcher.pageCategoriesCache[pageid])
                else:
                    batcher.pendingGetPageCategories.setdefault(pageid or page, [])
                    batcher.pendingGetPageCategories[pageid or page].append(callback)
                    if len(batcher.pendingGetPageCategories.keys()) >= BATCH_MAX:
                        batcher._executeGetCategoriesBatch()

            def __call__(self) -> None:
                raise Exception(
                    "Not supposed to call YugipediaBatcher-decorated function!"
                )

        return GetPageCategoriesDecorator

    def _executeGetCategoriesBatch(self):
        if not self.pendingGetPageCategories:
            return
        pending = {k: v for k, v in self.pendingGetPageCategories.items()}
        self.pendingGetPageCategories.clear()
        pages = pending.keys()

        def do(pages: typing.Iterable[typing.Union[int, str]]):
            if not pages:
                return
            pageids = [str(p) for p in pages if type(p) is int]
            pagetitles = [str(p) for p in pages if type(p) is str]
            query = {
                "action": "query",
                "prop": "categories",
                # without this the API hands back 10 categories per request,
                # which turns one batch of pages into dozens of round trips
                "cllimit": "max",
                **({"pageids": "|".join(pageids)} if pageids else {}),
                **({"titles": "|".join(pagetitles)} if pagetitles else {}),
            }

            cats_got: typing.Dict[int, typing.List[int]] = {}

            for result_page in paginate_query(query):
                for result in result_page["pages"]:
                    if result.get("missing") or result.get("invalid"):
                        self.missingPagesCache.add(
                            str(result.get("title") or result.get("pageid") or "")
                        )
                        continue

                    self.namesToIDs[result["title"]] = result["pageid"]
                    self.idsToNames[result["pageid"]] = result["title"]
                    cats_got.setdefault(result["pageid"], [])

                    if "categories" not in result:
                        continue

                    unknown_cats = [
                        x["title"]
                        for x in result["categories"]
                        if x["title"] not in self.namesToIDs
                    ]
                    if unknown_cats:
                        query2 = {
                            "action": "query",
                            "titles": "|".join(unknown_cats),
                        }
                        for result2_page in paginate_query(query2):
                            for result2 in result2_page["pages"]:
                                if "pageid" not in result2:
                                    continue
                                self.namesToIDs[result2["title"]] = result2["pageid"]
                                self.idsToNames[result2["pageid"]] = result2["title"]

                    cats_got[result["pageid"]].extend(
                        [
                            self.namesToIDs[x["title"]]
                            for x in result["categories"]
                            if x["title"] in self.namesToIDs
                        ]
                    )

            for pageid, cats in cats_got.items():
                self.pageCategoriesCache[pageid] = cats
                for callback in pending.get(pageid, []):
                    callback(cats)
                for callback in pending.get(self.idsToNames[pageid], []):
                    callback(cats)

        do([p for p in pages if type(p) is int])
        do([p for p in pages if type(p) is str])

    categoryMembersCache: typing.Dict[
        typing.Union[str, int], typing.List[CategoryMember]
    ]

    def _populateCatMembers(
        self, page: typing.Union[str, int]
    ) -> typing.Optional[typing.Union[int, str]]:
        pageid = None
        query = {
            "action": "query",
            "list": "categorymembers",
            **(
                {
                    "cmtitle": page,
                }
                if type(page) is str
                else {}
            ),
            **(
                {
                    "cmpageid": page,
                }
                if type(page) is int
                else {}
            ),
            **(
                {
                    "titles": page,
                }
                if type(page) is str
                else {}
            ),
            **(
                {
                    "pageids": page,
                }
                if type(page) is int
                else {}
            ),
            "cmlimit": "max",
            "cmprop": "ids|title|type",
        }

        members: typing.List[CategoryMember] = []
        for results in paginate_query(query):
            for result in results.get("pages") or []:
                if result.get("missing") or result.get("invalid"):
                    self.missingPagesCache.add(
                        str(result.get("title") or result.get("pageid") or "")
                    )
                    if result.get("invalid"):
                        continue
                pageid = result.get("pageid", page)
                self.categoryMembersCache[pageid] = members
                if "pageid" in result and "title" in result:
                    self.namesToIDs[result["title"]] = result["pageid"]
                    self.idsToNames[result["pageid"]] = result["title"]
            for result in results["categorymembers"]:
                if result.get("missing") or result.get("invalid"):
                    self.missingPagesCache.add(
                        str(result.get("title") or result.get("pageid") or "")
                    )
                    continue
                members.append(
                    CategoryMember(
                        result["pageid"],
                        result["title"],
                        CategoryMemberType(result["type"]),
                    )
                )

        return pageid

    def getCategoryMembers(self, page: typing.Union[str, int]):
        batcher = self

        class GetCatMemDecorator:
            def __init__(
                self, callback: typing.Callable[[typing.List[int]], None]
            ) -> None:
                pageid = (
                    page
                    if type(page) is int
                    else batcher.namesToIDs.get(str(page), page)
                )

                if not batcher.use_cache or pageid not in batcher.categoryMembersCache:
                    catid = batcher._populateCatMembers(page)
                    pageid = catid if catid is not None else pageid

                callback(
                    [
                        x.id
                        for x in batcher.categoryMembersCache.get(pageid, [])
                        if x.type == CategoryMemberType.PAGE
                    ]
                )

            def __call__(self) -> None:
                raise Exception(
                    "Not supposed to call YugipediaBatcher-decorated function!"
                )

        return GetCatMemDecorator

    def getSubcategories(self, page: typing.Union[str, int]):
        batcher = self

        class GetCatMemDecorator:
            def __init__(
                self, callback: typing.Callable[[typing.List[int]], None]
            ) -> None:
                pageid = (
                    page
                    if type(page) is int
                    else batcher.namesToIDs.get(str(page), page)
                )

                if not batcher.use_cache or pageid not in batcher.categoryMembersCache:
                    catid = batcher._populateCatMembers(page)
                    pageid = catid if catid is not None else pageid

                callback(
                    [
                        x.id
                        for x in batcher.categoryMembersCache.get(pageid, [])
                        if x.type == CategoryMemberType.SUBCAT
                    ]
                )

            def __call__(self) -> None:
                raise Exception(
                    "Not supposed to call YugipediaBatcher-decorated function!"
                )

        return GetCatMemDecorator

    def getCategoryMembersRecursive(self, page: typing.Union[str, int]):
        batcher = self

        class GetCatMemDecorator:
            def __init__(
                self, callback: typing.Callable[[typing.List[int]], None]
            ) -> None:
                result = []

                @batcher.getCategoryMembers(page)
                def getMembers(members: typing.List[int]):
                    result.extend(members)

                @batcher.getSubcategories(page)
                def getSubcats(members: typing.List[int]):
                    for member in members:

                        @batcher.getCategoryMembersRecursive(member)
                        def recur(members: typing.List[int]):
                            result.extend(members)

                callback(result)

            def __call__(self) -> None:
                raise Exception(
                    "Not supposed to call YugipediaBatcher-decorated function!"
                )

        return GetCatMemDecorator

    imagesCache: typing.Dict[int, str]
    pendingImages: typing.Dict[
        typing.Union[int, str], typing.List[typing.Callable[[str], None]]
    ]

    # Image lookups that never call their callback, counted by cause so that the images
    # the wiki refuses to serve don't mask the ones we failed to name. These three only
    # count lookups that reach the API, so on their own they shrink to nothing as the
    # page cache warms up.
    missingFilePages: int
    filePagesWithoutImage: int
    licenseRestrictedImages: int

    # Lookups the cache answered "missing" without asking the API. Counted separately so
    # the reported total stays comparable between a cold run and a warm one: without this
    # a CI run restoring `temp` reports near zero and reads as "no images are being lost",
    # when the loss is merely being remembered instead of rediscovered.
    cachedMissingImages: int

    def getImageURL(self, page: typing.Union[str, int]):
        batcher = self

        class GetImageDecorator:
            def __init__(self, callback: typing.Callable[[str], None]) -> None:
                if batcher.use_cache and str(page) in batcher.missingPagesCache:
                    batcher.cachedMissingImages += 1
                    return

                pageid = (
                    page if type(page) is int else batcher.namesToIDs.get(str(page))
                )
                if batcher.use_cache and pageid in batcher.imagesCache:
                    callback(batcher.imagesCache[pageid])
                else:
                    batcher.pendingImages.setdefault(pageid or page, [])
                    batcher.pendingImages[pageid or page].append(callback)
                    if len(batcher.pendingImages.keys()) >= BATCH_MAX:
                        batcher._executeGetImageURLBatch()

            def __call__(self) -> None:
                raise Exception(
                    "Not supposed to call YugipediaBatcher-decorated function!"
                )

        return GetImageDecorator

    def _executeGetImageURLBatch(self):
        if not self.pendingImages:
            return
        pending = {k: v for k, v in self.pendingImages.items()}
        self.pendingImages.clear()
        pages = pending.keys()

        def do(pages: typing.Iterable[typing.Union[int, str]]):
            if not pages:
                return
            pageids = [str(p) for p in pages if type(p) is int]
            pagetitles = [str(p) for p in pages if type(p) is str]
            query = {
                "action": "query",
                "prop": "imageinfo",
                **({"pageids": "|".join(pageids)} if pageids else {}),
                **({"titles": "|".join(pagetitles)} if pagetitles else {}),
                "iiprop": "url",
            }
            for result_page in paginate_query(query):
                for result in result_page["pages"]:
                    if result.get("missing") or result.get("invalid"):
                        self.missingPagesCache.add(
                            str(result.get("title") or result.get("pageid") or "")
                        )
                        self.missingFilePages += 1
                        continue

                    title = result["title"]
                    pageid = result["pageid"]

                    self.namesToIDs[title] = pageid
                    self.idsToNames[pageid] = title

                    if "imageinfo" not in result:
                        # this happens if an image metadata exists but no actual file with a URL; ignore it
                        # logging.warning(f"Page is not an image file: {title}")
                        self.missingPagesCache.add(title)
                        self.missingPagesCache.add(str(pageid))
                        self.filePagesWithoutImage += 1
                        continue

                    for image in result["imageinfo"]:
                        if image.get("filemissing"):
                            # We can't download licensed images.
                            # This is their (bad) way of telling us that.
                            self.missingPagesCache.add(title)
                            self.missingPagesCache.add(str(pageid))
                            # logging.warning(f"Image file cannot be accessed: {title}")
                            self.licenseRestrictedImages += 1
                            continue
                        if "url" not in image:
                            logging.warning(
                                f"Found strange response from server for image URL: {json.dumps(image)}"
                            )
                            continue
                        url = image["url"]
                        self.imagesCache[pageid] = url
                        for callback in pending.get(pageid, []):
                            callback(url)
                        for callback in pending.get(title, []):
                            callback(url)

        do([p for p in pages if type(p) is int])
        do([p for p in pages if type(p) is str])

    pendingGetPageID: typing.Dict[
        typing.Union[int, str], typing.List[typing.Callable[[int, str], None]]
    ]

    def getPageID(self, page: typing.Union[str, int]):
        batcher = self

        class GetIDDecorator:
            def __init__(self, callback: typing.Callable[[int, str], None]) -> None:
                if batcher.use_cache and str(page) in batcher.missingPagesCache:
                    return

                pageid = (
                    page if type(page) is int else batcher.namesToIDs.get(str(page))
                )
                # we make the dangerous assumption here that page IDs and internal titles never change
                # (that is, we ignore batcher.use_cache)
                if page in batcher.namesToIDs:
                    callback(batcher.namesToIDs[page], page)
                elif page in batcher.idsToNames:
                    callback(page, batcher.idsToNames[page])
                else:
                    batcher.pendingGetPageID.setdefault(pageid or page, [])
                    batcher.pendingGetPageID[pageid or page].append(callback)
                    if len(batcher.pendingGetPageID.keys()) >= BATCH_MAX:
                        batcher._executeGetPageIDBatch()

            def __call__(self) -> None:
                raise Exception(
                    "Not supposed to call YugipediaBatcher-decorated function!"
                )

        return GetIDDecorator

    def _executeGetPageIDBatch(self):
        if not self.pendingGetPageID:
            return
        pending = {k: v for k, v in self.pendingGetPageID.items()}
        self.pendingGetPageID.clear()
        pages = pending.keys()

        def do(pages: typing.Iterable[typing.Union[int, str]]):
            if not pages:
                return
            pageids = [str(p) for p in pages if type(p) is int]
            pagetitles = [str(p) for p in pages if type(p) is str]
            query = {
                "action": "query",
                **({"pageids": "|".join(pageids)} if pageids else {}),
                **({"titles": "|".join(pagetitles)} if pagetitles else {}),
            }
            redirects: typing.Dict[str, str] = {}
            for result_page in paginate_query(query):
                for redirect in result_page.get("redirects", []):
                    redirects[redirect["from"]] = redirect["to"]

                for result in result_page["pages"]:
                    if result.get("missing") or result.get("invalid"):
                        self.missingPagesCache.add(
                            str(result.get("title") or result.get("pageid") or "")
                        )
                        continue

                    pageid = result["pageid"]
                    title = result["title"]

                    self.namesToIDs[title] = pageid
                    self.idsToNames[pageid] = title

                    for callback in pending.get(pageid, []):
                        callback(pageid, title)
                    for callback in pending.get(title, []):
                        callback(pageid, title)
            for from_, to_ in redirects.items():
                if to_ in self.namesToIDs:
                    pageid = self.namesToIDs[to_]

                    self.namesToIDs[from_] = pageid

                    for callback in pending.get(from_, []):
                        callback(pageid, to_)
                else:
                    self.missingPagesCache.add(from_)

        do([p for p in pages if type(p) is int])
        do([p for p in pages if type(p) is str])
