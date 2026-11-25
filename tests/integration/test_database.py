"""Integration tests: the app against a real PostgreSQL server. Needs DATABASE_URL."""
import os
from concurrent.futures import ThreadPoolExecutor

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


def test_concurrent_first_writes_create_the_schema_once(client, monkeypatch):
    # Regression: 10 pods starting together raced on CREATE TABLE and 3 writes returned 503
    with web.db() as conn:
        conn.execute("DROP TABLE IF EXISTS analyses")
    monkeypatch.setattr(web, "_schema_ready", False)

    def first_write(_):
        monkeypatch.setattr(web, "_schema_ready", False)  # every "pod" believes it is first
        return web.app.test_client().post("/stats", json={"text": "cold start"}).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(first_write, range(10)))
    assert codes == [200] * 10
