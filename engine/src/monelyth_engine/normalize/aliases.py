"""Canonical names for merchants whose descriptions vary, plus display-casing exceptions.

This is data: add a line to teach the cleaner a merchant. Keys are written the way a description
looks partway through cleaning (lowercase, processor prefixes and store numbers already gone) and
are compared through ``merchant_key``, so ``"uber trip"`` also matches ``UBER *TRIP``. Keep the
keys sorted; a test enforces it. Values are shown exactly as written, and every value is also
recognised as a key for itself, so cleaning a canonical name gives it back unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "7eleven": "7-Eleven",
        "amazon": "Amazon",
        "amazon mktplace": "Amazon",
        "amazon mktplace pmts": "Amazon",
        "amazon.ca": "Amazon",
        "amazon.com": "Amazon",
        "amzn": "Amazon",
        "amzn mktp": "Amazon",
        "amzn prime": "Amazon Prime",
        "apple.com/bill": "Apple",
        "bestbuy": "Best Buy",
        "cdn tire": "Canadian Tire",
        "chick-fil-a": "Chick-fil-A",
        "costco": "Costco",
        "costco wholesale": "Costco",
        "cvs pharmacy": "CVS",
        "dashpass": "DoorDash",
        "dd doordash": "DoorDash",
        "disney plus": "Disney+",
        "disneyplus": "Disney+",
        "doordash": "DoorDash",
        "doordash dashpass": "DoorDash",
        "dunkin donuts": "Dunkin'",
        "esso": "Esso",
        "esso circle k": "Esso",
        "google google one": "Google One",
        "google youtube premium": "YouTube Premium",
        "google youtubepremium": "YouTube Premium",
        "home depot": "The Home Depot",
        "itunes.com/bill": "Apple",
        "lcbo/rao": "LCBO",
        "lyft": "Lyft",
        "lyft ride": "Lyft",
        "mcdonald's": "McDonald's",
        "petro-can": "Petro-Canada",
        "petro-canada": "Petro-Canada",
        "petrocan": "Petro-Canada",
        "rcss": "Real Canadian Superstore",
        "real cdn superstore": "Real Canadian Superstore",
        "shell": "Shell",
        "shell easypay": "Shell",
        "shell oil": "Shell",
        "skip the dishes": "SkipTheDishes",
        "spotify": "Spotify",
        "starbucks": "Starbucks",
        "starbucks coffee": "Starbucks",
        "starbucks store": "Starbucks",
        "tim hortons": "Tim Hortons",
        "toys r us": "Toys R Us",
        "trader joe's": "Trader Joe's",
        "uber": "Uber",
        "uber canada/ubereats": "Uber Eats",
        "uber canada/ubertrip": "Uber",
        "uber eats": "Uber Eats",
        "uber trip": "Uber",
        "ubereats": "Uber Eats",
        "ubertrip": "Uber",
        "wal-mart": "Walmart",
        "wal-mart supercenter": "Walmart",
        "walmart": "Walmart",
        "walmart supercenter": "Walmart",
        "whole foods market": "Whole Foods",
        "wholefds": "Whole Foods",
        "wholefds mkt": "Whole Foods",
        "youtubepremium": "YouTube Premium",
    }
)

UPPERCASE_WORDS: Final = frozenset(
    {
        *("a&w", "amc", "atm", "bmo", "bp", "cibc", "cvs", "dhl", "gnc", "h&m", "hbc", "hsbc"),
        *("ihop", "ikea", "kfc", "lcbo", "rbc", "saq", "td", "tjx", "ttc", "ups", "usps", "ymca"),
        # Tax agencies and taxes, which appear on refunds and payments.
        *("cra", "gst", "hst", "irs", "qst"),
    }
)
"""Words shown in capitals instead of title case: brands and abbreviations people write that way."""
