from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from monelyth_engine.config import Settings
from monelyth_engine.database import Database
from monelyth_engine.ingest.csv_statement import DATE_FORMATS
from monelyth_engine.services.importing import MAX_UPLOAD_BYTES
from tests.api.conftest import SAMPLE_DATA, create_account

CHECKING_CSV = (SAMPLE_DATA / "demo-checking.csv").read_bytes()
CARD_CSV = (SAMPLE_DATA / "demo-credit-card.csv").read_bytes()
CHECKING_OFX = (SAMPLE_DATA / "demo-checking.ofx").read_bytes()
CHECKING_ROWS = CHECKING_CSV.count(b"\n") - 1
CARD_ROWS = CARD_CSV.count(b"\n") - 1
# Every day is 12 or under, so the date order can't be detected and the user must choose it.
AMBIGUOUS_DATES_CSV = (
    b"Date,Description,Amount\n"
    b"03/04/2026,SQ *BLUE BOTTLE 0423 TORONTO ON,-4.50\n"
    b"05/06/2026,PAYROLL DEPOSIT ACME CORP,1200.00\n"
)


def _post_preview(
    api: TestClient,
    data: bytes,
    name: str = "statement.csv",
    layout: dict[str, Any] | None = None,
) -> Any:
    form = None if layout is None else {"layout": json.dumps(layout)}
    return api.post("/imports/preview", files={"file": (name, data)}, data=form)


def _preview(
    api: TestClient,
    data: bytes,
    name: str = "statement.csv",
    layout: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = _post_preview(api, data, name, layout)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _commit(
    api: TestClient,
    account_id: int,
    data: bytes,
    layout: dict[str, Any] | None,
    name: str = "statement.csv",
) -> Any:
    form: dict[str, str] = {"account_id": str(account_id)}
    if layout is not None:
        form["layout"] = json.dumps(layout)
    return api.post("/imports", files={"file": (name, data)}, data=form)


def _import_csv(api: TestClient, account_id: int, data: bytes, name: str) -> dict[str, Any]:
    preview = _preview(api, data, name)
    assert preview["csv"]["questions"] == []
    response = _commit(api, account_id, data, preview["csv"]["layout"], name)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_csv_preview_detects_layout_and_cleans_merchants(api: TestClient) -> None:
    preview = _preview(api, CHECKING_CSV, "demo-checking.csv")

    assert preview["format"] == "csv"
    assert preview["file_name"] == "demo-checking.csv"
    assert preview["transaction_count"] == CHECKING_ROWS
    assert preview["previous_import"] is None
    assert preview["csv"]["layout_source"] == "detected"
    assert preview["csv"]["columns"] == ["Date", "Description", "Amount"]
    assert preview["csv"]["questions"] == []
    assert preview["csv"]["layout"]["amount"] == {"kind": "signed", "column": 2}
    first = preview["rows"][0]
    assert first == {
        "posted_date": "2025-10-01",
        "description": "PREAUTHORIZED DEBIT HARBOURVIEW PROPERTY MGMT",
        "merchant": first["merchant"],
        "amount_cents": -185000,
    }
    assert "PREAUTHORIZED" not in first["merchant"]
    assert len(preview["rows"]) == 10


def test_preview_lists_date_formats_with_labels(api: TestClient) -> None:
    formats = _preview(api, CHECKING_CSV)["csv"]["date_formats"]

    assert [f["code"] for f in formats] == list(DATE_FORMATS)
    assert {"code": "%d/%m/%Y", "label": "DD/MM/YYYY"} in formats
    assert {"code": "%b %d, %Y", "label": "Mon DD, YYYY"} in formats


def test_preview_asks_for_an_ambiguous_date_order(api: TestClient) -> None:
    preview = _preview(api, AMBIGUOUS_DATES_CSV)

    csv = preview["csv"]
    assert csv["layout"]["date_format"] is None
    assert [q["kind"] for q in csv["questions"]] == ["date_order_ambiguous"]
    assert csv["questions"][0]["options"] == ["%m/%d/%Y", "%d/%m/%Y"]
    assert preview["transaction_count"] is None


@pytest.mark.parametrize(
    ("date_format", "first_date"), [("%d/%m/%Y", "2026-04-03"), ("%m/%d/%Y", "2026-03-04")]
)
def test_preview_with_a_layout_reads_rows_with_it(
    api: TestClient, date_format: str, first_date: str
) -> None:
    layout = _preview(api, AMBIGUOUS_DATES_CSV)["csv"]["layout"]
    layout["date_format"] = date_format

    preview = _preview(api, AMBIGUOUS_DATES_CSV, layout=layout)

    assert preview["transaction_count"] == 2
    assert preview["rows"][0]["posted_date"] == first_date
    assert preview["csv"]["layout"] == layout
    assert preview["csv"]["layout_source"] == "chosen"
    assert preview["csv"]["questions"] == []
    assert preview["csv"]["columns"] == ["Date", "Description", "Amount"]


def test_preview_with_a_layout_applies_the_sign_convention(api: TestClient) -> None:
    detected = _preview(api, CHECKING_CSV)

    inverted = _preview(
        api, CHECKING_CSV, layout={**detected["csv"]["layout"], "invert_signs": True}
    )

    assert [row["amount_cents"] for row in inverted["rows"]] == [
        -row["amount_cents"] for row in detected["rows"]
    ]


def test_preview_with_a_layout_counts_the_whole_file(api: TestClient) -> None:
    layout = _preview(api, CHECKING_CSV)["csv"]["layout"]

    preview = _preview(api, CHECKING_CSV, layout=layout)

    assert preview["transaction_count"] == CHECKING_ROWS
    assert len(preview["rows"]) == 10


def test_preview_with_a_layout_that_does_not_fit_names_the_row(api: TestClient) -> None:
    layout = _preview(api, CHECKING_CSV)["csv"]["layout"]
    layout["date_format"] = "%d/%m/%Y"  # the file uses ISO dates

    response = _post_preview(api, CHECKING_CSV, layout=layout)

    assert response.status_code == 422
    assert response.json()["detail"] == (
        'Row 2: the date "2025-10-01" doesn\'t match the format DD/MM/YYYY.'
    )


@pytest.mark.parametrize("layout_text", ["not json", '{"version": 1}', "[]", '{"version": 2}'])
def test_preview_rejects_a_malformed_layout(api: TestClient, layout_text: str) -> None:
    response = api.post(
        "/imports/preview",
        files={"file": ("s.csv", CHECKING_CSV)},
        data={"layout": layout_text},
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_preview_refuses_a_layout_for_ofx(api: TestClient) -> None:
    layout = _preview(api, CHECKING_CSV)["csv"]["layout"]

    response = _post_preview(api, CHECKING_OFX, "demo-checking.ofx", layout)

    assert response.status_code == 422
    assert response.json()["detail"] == "A column layout only applies to CSV files."


def test_preview_with_a_layout_still_reports_a_previous_import(api: TestClient) -> None:
    account = create_account(api)
    result = _import_csv(api, account["id"], CHECKING_CSV, "demo-checking.csv")
    layout = _preview(api, CHECKING_CSV)["csv"]["layout"]

    preview = _preview(api, CHECKING_CSV, layout=layout)

    assert preview["previous_import"]["id"] == result["import_id"]


def test_preview_saves_nothing(api: TestClient) -> None:
    _preview(api, CHECKING_CSV)

    assert api.get("/transactions").json()["total"] == 0


def test_ofx_preview(api: TestClient) -> None:
    preview = _preview(api, CHECKING_OFX, "demo-checking.ofx")

    assert preview["format"] == "ofx"
    assert preview["currency"] == "CAD"
    assert preview["transaction_count"] == CHECKING_ROWS
    assert preview["csv"] is None


def test_unreadable_file_is_rejected_with_a_message(api: TestClient) -> None:
    response = api.post("/imports/preview", files={"file": ("x.csv", b"\x00\x01\x02 not a csv")})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_oversized_upload_is_rejected(api: TestClient) -> None:
    data = b"a" * (MAX_UPLOAD_BYTES + 1)

    response = api.post("/imports/preview", files={"file": ("huge.csv", data)})

    assert response.status_code == 413


def test_file_name_is_reduced_to_its_base_name(api: TestClient) -> None:
    preview = _preview(api, CHECKING_CSV, "C:\\Users\\me\\Downloads\\../evil/demo.csv")

    assert preview["file_name"] == "demo.csv"


def test_commit_csv_stores_transactions(api: TestClient) -> None:
    account = create_account(api)

    result = _import_csv(api, account["id"], CHECKING_CSV, "demo-checking.csv")

    assert result["added"] == CHECKING_ROWS
    assert result["skipped_duplicates"] == 0
    assert result["format"] == "csv"
    page = api.get("/transactions", params={"account_id": account["id"], "limit": 500}).json()
    assert page["total"] == CHECKING_ROWS
    assert all(tx["merchant"] for tx in page["items"])
    assert all(tx["category_id"] is None for tx in page["items"])


def test_confirmed_layout_is_remembered_for_the_bank(api: TestClient) -> None:
    account = create_account(api)
    _import_csv(api, account["id"], CHECKING_CSV, "september.csv")
    next_statement = CHECKING_CSV + b"2026-10-01,POS PURCHASE NEW CAFE,-4.50\n"

    preview = _preview(api, next_statement, "october.csv")

    assert preview["csv"]["layout_source"] == "saved"
    assert preview["csv"]["questions"] == []
    assert preview["transaction_count"] == CHECKING_ROWS + 1


def test_corrupt_saved_layout_falls_back_to_detection(
    api: TestClient, make_settings: Callable[..., Settings]
) -> None:
    account = create_account(api)
    _import_csv(api, account["id"], CHECKING_CSV, "september.csv")
    # The user owns the database file and could edit it; a bad profile must not break imports.
    with Database(make_settings().data_dir).connection() as conn:
        conn.execute("UPDATE csv_profiles SET mapping_json = '{\"version\": 99}'")

    preview = _preview(api, CHECKING_CSV + b"2026-10-01,POS PURCHASE NEW CAFE,-4.50\n")

    assert preview["csv"]["layout_source"] == "detected"


def test_phase_1_done_when_importing_twice_adds_nothing(api: TestClient) -> None:
    """PLAN.md Phase 1: importing the sample statements twice adds every row once."""
    checking = create_account(api, name="Demo Checking")
    card = create_account(api, name="Demo Visa")

    first = [
        _import_csv(api, checking["id"], CHECKING_CSV, "demo-checking.csv"),
        _import_csv(api, card["id"], CARD_CSV, "demo-credit-card.csv"),
    ]
    assert [r["added"] for r in first] == [CHECKING_ROWS, CARD_ROWS]

    # The very same files again: refused outright, with a message for the user.
    for account, data in ((checking, CHECKING_CSV), (card, CARD_CSV)):
        preview = _preview(api, data)
        assert preview["previous_import"] is not None
        response = _commit(api, account["id"], data, preview["csv"]["layout"])
        assert response.status_code == 409
        assert "already imported" in response.json()["detail"]

    # An overlapping statement (same rows re-exported plus one new one): only the new row lands.
    overlapping = CHECKING_CSV + b"2026-10-01,POS PURCHASE NEW CAFE,-4.50\n"
    second = _import_csv(api, checking["id"], overlapping, "demo-checking-oct.csv")
    assert second["added"] == 1
    assert second["skipped_duplicates"] == CHECKING_ROWS

    total = api.get("/transactions", params={"limit": 1}).json()["total"]
    assert total == CHECKING_ROWS + CARD_ROWS + 1


def test_identical_same_day_purchases_are_both_kept(api: TestClient) -> None:
    account = create_account(api)
    data = (
        b"Date,Description,Amount\n"
        b"2026-09-01,SQ *BLUE BOTTLE 0423 TORONTO ON,-5.00\n"
        b"2026-09-01,SQ *BLUE BOTTLE 0423 TORONTO ON,-5.00\n"
    )

    result = _import_csv(api, account["id"], data, "coffee.csv")

    assert result["added"] == 2


def test_commit_ofx(api: TestClient) -> None:
    account = create_account(api)

    response = _commit(api, account["id"], CHECKING_OFX, None, "demo-checking.ofx")

    assert response.status_code == 201, response.text
    assert response.json()["added"] == CHECKING_ROWS


def test_ofx_currency_must_match_the_account(api: TestClient) -> None:
    account = create_account(api, name="US Checking", currency="USD")

    response = _commit(api, account["id"], CHECKING_OFX, None, "demo-checking.ofx")

    assert response.status_code == 422
    assert "CAD" in response.json()["detail"]
    assert api.get("/transactions").json()["total"] == 0


def test_csv_commit_requires_a_layout(api: TestClient) -> None:
    account = create_account(api)

    response = _commit(api, account["id"], CHECKING_CSV, None)

    assert response.status_code == 422
    assert "columns" in response.json()["detail"]


def test_ofx_commit_refuses_a_layout(api: TestClient) -> None:
    account = create_account(api)
    layout = _preview(api, CHECKING_CSV)["csv"]["layout"]

    response = _commit(api, account["id"], CHECKING_OFX, layout)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("layout_text", "status"),
    [("not json", 422), ('{"version": 1}', 422), ("[]", 422)],
)
def test_malformed_layouts_are_rejected(api: TestClient, layout_text: str, status: int) -> None:
    account = create_account(api)

    response = api.post(
        "/imports",
        files={"file": ("s.csv", CHECKING_CSV)},
        data={"account_id": str(account["id"]), "layout": layout_text},
    )

    assert response.status_code == status
    assert api.get("/transactions").json()["total"] == 0


def test_layout_that_does_not_fit_the_file_is_rejected(api: TestClient) -> None:
    account = create_account(api)
    layout = _preview(api, CHECKING_CSV)["csv"]["layout"]
    layout["date_format"] = "%d/%m/%Y"  # the file uses ISO dates

    response = _commit(api, account["id"], CHECKING_CSV, layout)

    assert response.status_code == 422
    assert api.get("/transactions").json()["total"] == 0


def test_unknown_account_is_404(api: TestClient) -> None:
    layout = _preview(api, CHECKING_CSV)["csv"]["layout"]

    response = _commit(api, 999, CHECKING_CSV, layout)

    assert response.status_code == 404
