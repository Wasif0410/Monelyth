from __future__ import annotations

import time

import pytest

from monelyth_engine.normalize import normalize_merchant

# Raw bank description -> the merchant name the app shows. Grouped by the rule each row checks.
GOLDEN: list[tuple[str, str]] = [
    # The PLAN.md example.
    ("SQ *BLUE BOTTLE 0423 TORONTO ON", "Blue Bottle"),
    # Payment-processor prefixes, including nested ones.
    ("SQU*SQ *BLUE BOTTLE COFFEE", "Blue Bottle Coffee"),
    ("TST* THE KEG STEAKHOUSE 1234", "The Keg Steakhouse"),
    ("TST *SUSHI SHOP #00123 MONTREAL QC", "Sushi Shop"),
    ("PAYPAL *SPOTIFY", "Spotify"),
    ("PAYPAL *UBER EATS", "Uber Eats"),
    ("PP*EBAY.CA", "Ebay"),
    ("SP * GYMSHARK", "Gymshark"),
    ("SP ALLBIRDS", "Allbirds"),
    ("PY *CITY OF TORONTO TORONTO ON", "City of Toronto"),
    ("CKO*NETFLIX.COM", "Netflix"),
    ("IC* COSTCO BY INSTACART", "Costco by Instacart"),
    ("IN *ACME PLUMBING", "Acme Plumbing"),
    ("DD *DOORDASH MCDONALDS", "McDonald's"),
    ("DD DOORDASH TIMHORTONS", "Timhortons"),
    ("DOORDASH*BURGER KING", "Burger King"),
    ("DD *DOORDASH DASHPASS", "DoorDash"),
    ("DD DOORDASH", "DoorDash"),
    # Channel prefixes: how the card was used, not who was paid.
    ("POS 0423 SHOPPERS DRUG MART #1234 TORONTO ON", "Shoppers Drug Mart"),
    ("POS PURCHASE LOBLAWS 1029 TORONTO ON", "Loblaws"),
    ("VISA DEBIT PUR 0423 METRO 512 OTTAWA ON", "Metro"),
    ("VISA DEBIT RETAIL PURCHASE FRESHCO #3301", "Freshco"),
    ("DEBIT PURCHASE SOBEYS #812 HALIFAX NS", "Sobeys"),
    (
        "PURCHASE AUTHORIZED ON 09/14 STARBUCKS STORE 12345 SEATTLE WA S586257862432941 CARD 1234",
        "Starbucks",
    ),
    ("CHECKCARD 0914 THE HOME DEPOT 1234 DENVER CO", "The Home Depot"),
    ("RECURRING PAYMENT NETFLIX.COM", "Netflix"),
    ("PREAUTHORIZED DEBIT ROGERS WIRELESS", "Rogers Wireless"),
    ("CONTACTLESS INTERAC PURCHASE - 1234 TIM HORTONS #2231", "Tim Hortons"),
    ("INTERAC PURCHASE CANADIAN TIRE #0456", "Canadian Tire"),
    # Card numbers, store and terminal numbers, reference codes.
    ("XXXX1234 LOBLAWS", "Loblaws"),
    ("LOBLAWS ****1234", "Loblaws"),
    ("TIM HORTONS CARD ENDING 1234", "Tim Hortons"),
    ("TERMINAL 1234 FRESHCO", "Freshco"),
    ("REF 88123 ROGERS", "Rogers"),
    ("STARBUCKS COFFEE 12345", "Starbucks"),
    ("AMZN Mktp US*RT4Y67TR0", "Amazon"),
    ("AIRBNB * HMXYZ12345", "Airbnb"),
    ("SHELL C12345 TORONTO ON", "Shell"),
    ("COSTCO WHOLESALE W1234 TORONTO ON", "Costco"),
    # Phone numbers, dates, times and postal codes.
    ("GOOD LIFE FITNESS 866-579-7172", "Good Life Fitness"),
    ("NOODLE BOX 8665797172", "Noodle Box"),
    ("APPLE.COM/BILL 866-712-7753 ON", "Apple"),
    ("UBER *TRIP 2026-09-14", "Uber"),
    ("TIM HORTONS 12:34", "Tim Hortons"),
    ("FRESHCO 3301 TORONTO ON M5V 2T6", "Freshco"),
    ("FIVE GUYS 1234 NEW YORK NY 10001", "Five Guys"),
    # Trailing city, province or state, and country.
    ("TIM HORTONS #2231 OAKVILLE ON", "Tim Hortons"),
    ("TRADER JOE'S #123 SAN FRANCISCO CA", "Trader Joe's"),
    ("KFC #1234 NEW YORK NY", "KFC"),
    ("PIZZA PIZZA 1234 TORONTO, ON", "Pizza Pizza"),
    ("PIZZA NOVA 123 TORONTO ON USA", "Pizza Nova"),
    ("ESSO 12345 TORONTO ON CA", "Esso"),
    ("NETFLIX.COM LOS GATOS CA USA", "Netflix"),
    ("BLUE BOTTLE SMALLVILLE QC", "Blue Bottle Smallville"),
    ("TIM HORTONS ON", "Tim Hortons"),
    ("Spotify USA", "Spotify"),
    ("CITY OF OTTAWA ON", "City of Ottawa"),
    ("BANK OF MONTREAL QC", "Bank of Montreal"),
    # Websites.
    ("NETFLIX.COM", "Netflix"),
    ("HELP.UBER.COM", "Uber"),
    ("WWW.COSTCO.CA", "Costco"),
    ("UBER *TRIP HELP.UBER.COM", "Uber"),
    ("AMAZON.CA ON", "Amazon"),
    ("GOOGLE *YOUTUBE PREMIUM g.co/helppay#", "YouTube Premium"),
    # Aliases.
    ("AMZN MKTP CA*2K4X91 AMZN.COM/BILL WA", "Amazon"),
    ("Amazon.ca*P1A2B3C4", "Amazon"),
    ("AMAZON MKTPLACE PMTS AMZN.COM/BILL WA", "Amazon"),
    ("AMZN PRIME*1A2B3C4D", "Amazon Prime"),
    ("UBER* TRIP", "Uber"),
    ("UBER *EATS", "Uber Eats"),
    ("UBER CANADA/UBEREATS TORONTO ON", "Uber Eats"),
    ("UBER CANADA/UBERTRIP TORONTO ON", "Uber"),
    ("LYFT *RIDE", "Lyft"),
    ("MCDONALD'S #40123 TORONTO ON", "McDonald's"),
    ("MCDONALDS 12345 MISSISSAUGA ON", "McDonald's"),
    ("McDonald\u2019s", "McDonald's"),
    ("GOOGLE *YouTubePremium", "YouTube Premium"),
    ("COSTCO GAS W1234 TORONTO ON", "Costco Gas"),
    ("WAL-MART #1234 TORONTO ON", "Walmart"),
    ("WALMART SUPERCENTER #5678 PHOENIX AZ", "Walmart"),
    ("SHELL EASYPAY 1234", "Shell"),
    ("ESSO CIRCLE K 1234 TORONTO ON", "Esso"),
    ("PETRO-CANADA 12345 CALGARY AB", "Petro-Canada"),
    ("PETRO CANADA 98765", "Petro-Canada"),
    ("TRADER JOES #123", "Trader Joe's"),
    ("TOYS R US #1234 TORONTO ON CA", "Toys R Us"),
    ("CHICK-FIL-A #01234 ATLANTA GA", "Chick-fil-A"),
    ("DUNKIN DONUTS #345678", "Dunkin'"),
    ("LCBO/RAO #0123 TORONTO ON", "LCBO"),
    ("CVS/PHARMACY #01234", "CVS"),
    ("7 ELEVEN #1234", "7-Eleven"),
    ("DISNEY PLUS 1234", "Disney+"),
    # Display casing.
    ("O'REILLY AUTO PARTS 1234", "O'Reilly Auto Parts"),
    ("D'ANGELO BROS", "D'Angelo Bros"),
    ("JOE'S PIZZA", "Joe's Pizza"),
    ("IKEA NORTH YORK ON", "IKEA"),
    ("H&M 0123 TORONTO ON", "H&M"),
    ("A&W #1234 VANCOUVER BC", "A&W"),
    ("RBC ROYAL BANK", "RBC Royal Bank"),
    ("IN-N-OUT BURGER #123", "In-N-Out Burger"),
    ("Caf\u00e9 Ol\u00e9 #12", "Caf\u00e9 Ol\u00e9"),
    # Unicode spaces are collapsed after NFKC.
    ("TIM\u00a0HORTONS\u2003#2231", "Tim Hortons"),
    # Things cleaning must NOT remove.
    ("7-ELEVEN 34567 TORONTO ON", "7-Eleven"),
    ("4 PAWS GROOMING #12", "4 Paws Grooming"),
    ("FOREVER 21 #0123 TORONTO ON", "Forever 21"),
    ("PIER 1 IMPORTS #1234", "Pier 1 Imports"),
    ("THE BEER STORE #1234 TORONTO ON", "The Beer Store"),
    ("BED BATH & BEYOND #123", "Bed Bath & Beyond"),
    ("GAME ON", "Game On"),
    ("GAME ON SPORTS BAR", "Game On Sports Bar"),
    ("JOIN US", "Join Us"),
    ("BAR ME", "Bar Me"),
    ("DROP IN", "Drop In"),
    ("BLUE BOTTLE COFFEE CO", "Blue Bottle Coffee Co"),
    ("SPORT CHEK #123", "Sport Chek"),
    ("POSH NAILS", "Posh Nails"),
    ("GIFT CARD 25", "Gift Card 25"),
    ("CONTACTLESS", "Contactless"),
]


@pytest.mark.parametrize(("raw", "expected"), GOLDEN)
def test_golden(raw: str, expected: str) -> None:
    assert normalize_merchant(raw) == expected


@pytest.mark.parametrize("raw", [raw for raw, _ in GOLDEN])
def test_is_stable_on_its_own_output(raw: str) -> None:
    once = normalize_merchant(raw)

    assert normalize_merchant(once) == once


def test_variants_of_one_merchant_clean_to_one_name() -> None:
    variants = [
        "SQ *BLUE BOTTLE 0423 TORONTO ON",
        "SQ *BLUE BOTTLE 0611 TORONTO ON",
        "SQU*BLUE BOTTLE #00123",
        "BLUE BOTTLE",
        "Blue  Bottle",
    ]

    assert {normalize_merchant(variant) for variant in variants} == {"Blue Bottle"}


def test_uber_and_uber_eats_stay_distinct() -> None:
    assert normalize_merchant("UBER *TRIP") == "Uber"
    assert normalize_merchant("UBER *EATS") == "Uber Eats"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("POS 1234", "POS 1234"),
        ("#00123", "#00123"),
        ("  XXXX1234   09/14 ", "XXXX1234 09/14"),
        ("CARD ENDING 1234", "CARD ENDING 1234"),
    ],
)
def test_falls_back_to_the_original_when_nothing_is_left(raw: str, expected: str) -> None:
    assert normalize_merchant(raw) == expected


@pytest.mark.parametrize("raw", ["", " ", "\t\n", "\u00a0\u2003"])
def test_blank_description_is_rejected(raw: str) -> None:
    with pytest.raises(ValueError, match="blank"):
        normalize_merchant(raw)


def test_ten_thousand_calls_take_well_under_a_second() -> None:
    descriptions = [raw for raw, _ in GOLDEN]

    start = time.perf_counter()
    for index in range(10_000):
        normalize_merchant(descriptions[index % len(descriptions)])
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0, f"10,000 calls took {elapsed:.2f}s"
