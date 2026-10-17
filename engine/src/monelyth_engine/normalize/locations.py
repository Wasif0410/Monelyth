"""Place names that card networks append to a merchant name, such as ``TORONTO ON`` or ``CA``.

This is data: extend a set to teach the cleaner a new place. Every entry is written as
``merchant_key`` would produce it (lowercase, no accents, punctuation turned into spaces).
"""

from __future__ import annotations

from typing import Final

REGION_CODES: Final = frozenset(
    {
        # Canadian provinces and territories, plus PQ, the old code for Quebec.
        *("ab", "bc", "mb", "nb", "nl", "ns", "nt", "nu", "on", "pe", "pq", "qc", "sk", "yt"),
        # US states, Washington DC and Puerto Rico.
        *("al", "ak", "az", "ar", "ca", "co", "ct", "dc", "de", "fl", "ga", "hi", "ia", "id"),
        *("il", "in", "ks", "ky", "la", "ma", "md", "me", "mi", "mn", "mo", "ms", "mt", "nc"),
        *("nd", "ne", "nh", "nj", "nm", "nv", "ny", "oh", "ok", "or", "pa", "pr", "ri", "sc"),
        *("sd", "tn", "tx", "ut", "va", "vt", "wa", "wi", "wv", "wy"),
    }
)

COUNTRY_CODES: Final = frozenset({"ca", "can", "us", "usa"})

CODES_NEEDING_A_CITY: Final = frozenset(
    {"can", "co", "de", "hi", "id", "in", "la", "me", "oh", "ok", "or"}
)
"""Codes that are also everyday words, so a name can end in them: ``BLUE BOTTLE COFFEE CO``,
``DROP IN``, ``HOLD ME``. They are stripped only after a known city or a website."""

CODES_NEEDING_TWO_WORDS: Final = frozenset({"on", "us"})
"""``ON`` (Ontario) and ``US`` are too common to require a known city, but ``GAME ON`` and
``JOIN US`` are real names, so these are stripped without a city only when at least two words
come before them."""

CITY_CONNECTORS: Final = frozenset({"de", "du", "of"})
"""A city after one of these words is part of the name (``CITY OF TORONTO``, ``BANK OF
MONTREAL``), so only the code that follows it is stripped."""

CITIES: Final = frozenset(
    {
        # Ontario
        *("ajax", "aurora", "barrie", "belleville", "brampton", "brantford", "burlington"),
        *("cambridge", "collingwood", "east york", "etobicoke", "gloucester", "guelph"),
        *("hamilton", "kanata", "kingston", "kitchener", "london", "markham", "milton"),
        *("mississauga", "nepean", "newmarket", "niagara falls", "north bay", "north york"),
        *("oakville", "orillia", "oshawa", "ottawa", "peterborough", "pickering"),
        *("richmond hill", "saint catharines", "sarnia", "sault ste marie", "scarborough"),
        *("st catharines", "stouffville", "sudbury", "thornhill", "thunder bay", "toronto"),
        *("vaughan", "waterloo", "welland", "whitby", "windsor", "woodbridge"),
        # Quebec
        *("brossard", "dorval", "gatineau", "laval", "levis", "longueuil", "montreal"),
        *("pointe claire", "quebec", "quebec city", "saguenay", "saint laurent", "sherbrooke"),
        *("st laurent", "terrebonne", "trois rivieres"),
        # British Columbia
        *("abbotsford", "burnaby", "chilliwack", "coquitlam", "delta", "kamloops", "kelowna"),
        *("langley", "maple ridge", "nanaimo", "new westminster", "north vancouver"),
        *("port coquitlam", "richmond", "surrey", "vancouver", "victoria", "west vancouver"),
        *("whistler",),
        # Prairies, Atlantic Canada and the territories
        *("airdrie", "banff", "brandon", "calgary", "charlottetown", "dartmouth", "edmonton"),
        *("fort mcmurray", "fredericton", "halifax", "iqaluit", "lethbridge", "moncton"),
        *("red deer", "regina", "saint john", "saint johns", "saskatoon", "st albert"),
        *("st johns", "whitehorse", "winnipeg", "yellowknife"),
        # United States, including the head-office towns that subscriptions bill from
        *("albuquerque", "anchorage", "atlanta", "austin", "baltimore", "bellevue", "boston"),
        *("bronx", "brooklyn", "buffalo", "burbank", "charlotte", "chicago", "cincinnati"),
        *("cleveland", "columbus", "cupertino", "dallas", "denver", "detroit"),
        *("fort lauderdale", "honolulu", "houston", "indianapolis", "irvine", "jersey city"),
        *("kansas city", "las vegas", "long beach", "los angeles", "los gatos", "louisville"),
        *("manhattan", "memphis", "menlo park", "miami", "milwaukee", "minneapolis"),
        *("mountain view", "nashville", "new orleans", "new york", "newark", "oakland"),
        *("omaha", "orlando", "palo alto", "philadelphia", "phoenix", "pittsburgh"),
        *("portland", "queens", "raleigh", "redmond", "sacramento", "saint louis"),
        *("salt lake city", "san antonio", "san diego", "san francisco", "san jose"),
        *("santa monica", "scottsdale", "seattle", "st louis", "sunnyvale", "tampa"),
        *("tucson", "washington"),
    }
)
