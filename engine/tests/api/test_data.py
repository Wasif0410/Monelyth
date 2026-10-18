from __future__ import annotations

import csv
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from monelyth_engine import __version__
from tests.api.conftest import create_account

STATEMENT = (
    b"Date,Description,Amount\n"
    b"2026-09-01,PAYROLL ACME CORP,2000.00\n"
    b"2026-09-02,SQ *BLUE BOTTLE 0423 TORONTO ON,-5.25\n"
    b"2026-09-03,=HYPERLINK(1),-0.07\n"
)


@pytest.fixture
def seeded(api: TestClient) -> dict[str, Any]:
    account = create_account(api, name="Caf\u00e9 Checking")
    preview = api.post("/imports/preview", files={"file": ("s.csv", STATEMENT)}).json()
    response = api.post(
        "/imports",
        files={"file": ("s.csv", STATEMENT)},
        data={"account_id": str(account["id"]), "layout": json.dumps(preview["csv"]["layout"])},
    )
    assert response.status_code == 201, response.text
    create_account(api, name="Savings")
    return account


@pytest.fixture
def export_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "exports"
    folder.mkdir()
    return folder


def _export(api: TestClient, folder: Path) -> Path:
    response = api.post("/data/export", json={"folder": str(folder)})
    assert response.status_code == 201, response.text
    return Path(response.json()["path"])


def test_system_info(api: TestClient, seeded: dict[str, Any], tmp_path: Path) -> None:
    response = api.get("/system/info")

    assert response.status_code == 200, response.text
    info = response.json()
    database = tmp_path / "data" / "monelyth.db"
    wal = database.with_name("monelyth.db-wal")
    assert info == {
        "engine_version": __version__,
        "data_folder": str(tmp_path / "data"),
        "database_path": str(database),
        "database_size_bytes": info["database_size_bytes"],
        "account_count": 2,
        "transaction_count": 3,
    }
    on_disk = database.stat().st_size + (wal.stat().st_size if wal.exists() else 0)
    assert info["database_size_bytes"] == on_disk > 0


def test_system_info_for_a_new_database(api: TestClient) -> None:
    info = api.get("/system/info").json()

    assert (info["account_count"], info["transaction_count"]) == (0, 0)


def test_export_writes_the_database_csv_and_readme(
    api: TestClient, seeded: dict[str, Any], export_dir: Path
) -> None:
    response = api.post("/data/export", json={"folder": str(export_dir)})

    assert response.status_code == 201, response.text
    body = response.json()
    folder = Path(body["path"])
    assert body["transaction_count"] == 3
    assert folder.parent == export_dir
    assert re.fullmatch(r"Monelyth export \d{4}-\d{2}-\d{2} \d{6}", folder.name)
    assert sorted(p.name for p in folder.iterdir()) == [
        "README.txt",
        "monelyth.db",
        "transactions.csv",
    ]


def test_exported_database_holds_the_same_data(
    api: TestClient, seeded: dict[str, Any], export_dir: Path
) -> None:
    folder = _export(api, export_dir)

    with closing(sqlite3.connect(folder / "monelyth.db")) as copy:
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        accounts = copy.execute("SELECT name FROM accounts ORDER BY id").fetchall()
        transactions = copy.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        categories = copy.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    assert accounts == [("Caf\u00e9 Checking",), ("Savings",)]
    assert transactions == 3
    assert categories == len(api.get("/categories").json())


def test_exported_csv_lists_every_transaction(
    api: TestClient, seeded: dict[str, Any], export_dir: Path
) -> None:
    by_amount = {tx["amount_cents"]: tx for tx in api.get("/transactions").json()["items"]}
    salary = next(c for c in api.get("/categories").json() if c["name"] == "Salary")
    api.patch(f"/transactions/{by_amount[200_000]['id']}", json={"category_id": salary["id"]})

    folder = _export(api, export_dir)

    raw = (folder / "transactions.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with (folder / "transactions.csv").open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file))
    assert rows == [
        ["Date", "Account", "Description", "Merchant", "Category", "Amount", "Currency"],
        [
            "2026-09-01",
            "Caf\u00e9 Checking",
            "PAYROLL ACME CORP",
            "Payroll Acme Corp",
            "Salary",
            "2000.00",
            "CAD",
        ],
        [
            "2026-09-02",
            "Caf\u00e9 Checking",
            "SQ *BLUE BOTTLE 0423 TORONTO ON",
            "Blue Bottle",
            "",
            "-5.25",
            "CAD",
        ],
        ["2026-09-03", "Caf\u00e9 Checking", "'=HYPERLINK(1)", "Hyperlink 1", "", "-0.07", "CAD"],
    ]


def test_export_readme_describes_the_files(
    api: TestClient, seeded: dict[str, Any], export_dir: Path
) -> None:
    readme = (_export(api, export_dir) / "README.txt").read_text(encoding="utf-8")

    assert "monelyth.db" in readme
    assert "transactions.csv" in readme
    assert "All 3 transactions" in readme
    assert __version__ in readme


def test_export_of_an_empty_database(api: TestClient, export_dir: Path) -> None:
    folder = _export(api, export_dir)

    with (folder / "transactions.csv").open(encoding="utf-8-sig", newline="") as file:
        assert list(csv.reader(file)) == [
            ["Date", "Account", "Description", "Merchant", "Category", "Amount", "Currency"]
        ]


def test_exports_never_overwrite_each_other(
    api: TestClient, seeded: dict[str, Any], export_dir: Path
) -> None:
    first = _export(api, export_dir)
    second = _export(api, export_dir)

    assert first != second
    assert (first / "monelyth.db").exists()
    assert (second / "monelyth.db").exists()


@pytest.mark.parametrize("folder", ["exports", str(Path("relative") / "exports"), "C:exports"])
def test_export_rejects_a_relative_folder(api: TestClient, folder: str) -> None:
    response = api.post("/data/export", json={"folder": folder})

    assert response.status_code == 422
    assert response.json() == {"detail": "Choose the export folder by its full path."}


def test_export_rejects_a_missing_folder(api: TestClient, tmp_path: Path) -> None:
    missing = tmp_path / "nowhere"

    response = api.post("/data/export", json={"folder": str(missing)})

    assert response.status_code == 422
    assert response.json() == {"detail": f"The folder {missing} doesn't exist."}
    assert not missing.exists()


def test_export_rejects_a_file(api: TestClient, tmp_path: Path) -> None:
    file = tmp_path / "notes.txt"
    file.write_text("hello")

    response = api.post("/data/export", json={"folder": str(file)})

    assert response.status_code == 422
    assert response.json() == {"detail": f"{file} is a file, not a folder."}


@pytest.mark.parametrize("body", [{}, {"folder": ""}, {"folder": 3}, {"folder": "C:\\", "x": 1}])
def test_export_rejects_malformed_requests(api: TestClient, body: dict[str, Any]) -> None:
    assert api.post("/data/export", json=body).status_code == 422


def test_erase_deletes_everything_and_reseeds(api: TestClient, seeded: dict[str, Any]) -> None:
    categories = api.get("/categories").json()

    response = api.post("/data/erase", json={"confirm": "DELETE"})

    assert response.status_code == 200, response.text
    assert response.json() == {"deleted_accounts": 2, "deleted_transactions": 3}
    assert api.get("/accounts").json() == []
    assert api.get("/transactions").json() == {"items": [], "total": 0}
    assert api.get("/categories").json() == categories
    info = api.get("/system/info").json()
    assert (info["account_count"], info["transaction_count"]) == (0, 0)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"confirm": "delete"},
        {"confirm": "DELETE "},
        {"confirm": ""},
        {"confirm": True},
        {"confirm": "DELETE", "also": "this"},
    ],
)
def test_erase_needs_the_exact_confirmation(
    api: TestClient, seeded: dict[str, Any], body: dict[str, Any]
) -> None:
    response = api.post("/data/erase", json=body)

    assert response.status_code == 422
    assert len(api.get("/accounts").json()) == 2
    assert api.get("/transactions").json()["total"] == 3
