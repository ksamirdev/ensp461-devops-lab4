import pytest

from service import web
from service.web import app, text_stats


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web, "DATABASE_URL", None)
    monkeypatch.setattr(web, "FAULT_RATE", 0.0)
    return app.test_client()


def test_healthz_reports_healthy(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json["healthy"] is True


def test_readyz_without_database_is_ready(client):
    assert client.get("/readyz").json == {"ready": True, "release": web.RELEASE}


def test_home_reports_release_and_color(client, monkeypatch):
    monkeypatch.setattr(web, "COLOR", "green")
    body = client.get("/").json
    assert body["color"] == "green"
    assert body["release"] == web.RELEASE


def test_text_stats_counts_unique_words_case_insensitively():
    assert text_stats("Build test build") == {"characters": 16, "words": 3, "unique_words": 2}


def test_stats_endpoint_returns_counts(client):
    response = client.post("/stats", json={"text": "ship it"})
    assert response.status_code == 200
    assert response.json == {"characters": 7, "words": 2, "unique_words": 2}


@pytest.mark.parametrize("body", [{}, {"text": 42}])
def test_stats_endpoint_rejects_invalid_text(client, body):
    assert client.post("/stats", json=body).status_code == 400


def test_analyses_needs_a_database(client):
    assert client.get("/analyses").status_code == 404


def test_fault_injection_fails_requests(client, monkeypatch):
    monkeypatch.setattr(web, "FAULT_RATE", 1.0)
    assert client.post("/stats", json={"text": "x"}).status_code == 500


def test_metrics_exposes_request_counter(client):
    client.get("/healthz")
    body = client.get("/metrics").get_data(as_text=True)
    assert 'textstats_http_requests_total{method="GET",route="/healthz",status="200"}' in body


def test_unknown_urls_share_one_metric_label(client):
    client.get("/no-such-page")
    body = client.get("/metrics").get_data(as_text=True)
    assert 'route="unmatched"' in body
    assert "no-such-page" not in body
