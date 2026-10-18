import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def add(client, amount, category, day="2026-10-01", note=""):
    return client.post(
        "/api/expenses", json={"amount": amount, "category": category, "spent_on": day, "note": note}
    )


def test_create_and_list(client):
    r = add(client, "12.50", "Food")
    assert r.status_code == 201
    assert r.json()["category"] == "food"
    assert len(client.get("/api/expenses").json()) == 1


def test_summary_groups_and_totals(client):
    add(client, "10.00", "food")
    add(client, "5.25", "food")
    add(client, "40", "rent")
    s = client.get("/api/summary").json()
    assert s["total"] == "55.25"
    assert s["by_category"][0] == {"category": "rent", "total": "40.00", "count": 1}
    assert s["by_category"][1]["total"] == "15.25"


def test_date_filter(client):
    add(client, "10", "food", day="2026-09-30")
    add(client, "20", "food", day="2026-10-05")
    items = client.get("/api/expenses", params={"start": "2026-10-01"}).json()
    assert [i["amount"] for i in items] == ["20.00"]
    assert client.get("/api/summary", params={"end": "2026-09-30"}).json()["total"] == "10.00"


def test_validation(client):
    assert add(client, "0", "food").status_code == 422
    assert add(client, "-5", "food").status_code == 422
    assert add(client, "1.234", "food").status_code == 422
    assert add(client, "5", "").status_code == 422


def test_delete(client):
    eid = add(client, "9.99", "misc").json()["id"]
    assert client.delete(f"/api/expenses/{eid}").status_code == 204
    assert client.delete(f"/api/expenses/{eid}").status_code == 404
