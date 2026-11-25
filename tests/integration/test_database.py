"""Integration tests: the app against a real PostgreSQL server. Needs DATABASE_URL."""
import os

import pytest

from service import web

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    # Fail, never skip: a pipeline gate that silently skips is not a gate
    raise RuntimeError("integration tests need DATABASE_URL pointing at a PostgreSQL server")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web, "DATABASE_URL", DATABASE_URL)
    monkeypatch.setattr(web, "FAULT_RATE", 0.0)
    return web.app.test_client()


def test_readyz_reaches_database(client):
    assert client.get("/readyz").status_code == 200


def test_stats_are_persisted(client):
    before = client.get("/analyses").json["count"]
    saved = client.post("/stats", json={"text": "persist me please"}).json
    after = client.get("/analyses").json
    assert after["count"] == before + 1
    assert after["last_id"] == saved["id"]


def test_rows_record_the_release(client):
    row_id = client.post("/stats", json={"text": "which release"}).json["id"]
    with web.db() as conn:
        release = conn.execute("SELECT release FROM analyses WHERE id = %s", (row_id,)).fetchone()[0]
    assert release == web.RELEASE


def test_unreachable_database_is_reported_not_crashed(client, monkeypatch):
    monkeypatch.setattr(web, "DATABASE_URL", "postgresql://nobody:x@127.0.0.1:1/none")
    assert client.get("/readyz").status_code == 503
    assert client.post("/stats", json={"text": "lost"}).status_code == 503
