"""Tests for the operational endpoints added for Kubernetes and monitoring."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_ok(client):
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["database"] == "up"


def test_readyz_db_down(client):
    with patch("app.main.ping", side_effect=ConnectionError("db down")):
        r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["database"] == "down"


def test_liveness_ignores_db(client):
    # A database outage must not fail liveness, or Kubernetes would restart
    # every app pod for a problem a restart cannot fix.
    with patch("app.main.ping", side_effect=ConnectionError("db down")):
        assert client.get("/healthz").status_code == 200


def test_version(client):
    body = client.get("/version").json()
    assert set(body) >= {"version", "git_sha", "build_date"}


def test_version_header(client):
    assert "x-app-version" in client.get("/healthz").headers


def test_request_id_propagated(client):
    r = client.get("/api/expenses", headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"


def test_metrics_use_route_templates(client):
    eid = client.post(
        "/api/expenses", json={"amount": "12.50", "category": "food", "spent_on": "2026-10-01"}
    ).json()["id"]
    client.delete(f"/api/expenses/{eid}")
    client.get("/api/summary")
    text = client.get("/metrics").text
    assert 'route="/api/expenses/{expense_id}"' in text
    assert f'route="/api/expenses/{eid}"' not in text
    assert 'route="/api/summary"' in text
    assert 'expenses_operations_total{operation="create",outcome="success"}' in text
    assert "expenses_amount_recorded_total" in text
    assert "expenses_app_build_info" in text


def test_business_metric_has_no_user_labels(client):
    # Free-text categories must never become label values (unbounded cardinality).
    client.post("/api/expenses", json={"amount": "1", "category": "zzz-unique", "spent_on": "2026-10-01"})
    assert "zzz-unique" not in client.get("/metrics").text


def test_unmatched_route_label(client):
    client.get("/does-not-exist")
    assert 'route="unmatched"' in client.get("/metrics").text
