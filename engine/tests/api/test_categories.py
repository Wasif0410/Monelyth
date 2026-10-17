from __future__ import annotations

from fastapi.testclient import TestClient


def test_default_categories_are_listed(api: TestClient) -> None:
    categories = api.get("/categories").json()
    kinds = {c["name"]: c["kind"] for c in categories}

    assert kinds["Salary"] == "income"
    assert kinds["Transfers"] == "transfer"
    assert kinds["Groceries"] == "expense"
    assert len(categories) == 20
