"""Smoke tests against a running deployment. Needs BASE_URL, e.g. http://localhost:8080."""
import os

import requests

BASE_URL = os.environ.get("BASE_URL")
if not BASE_URL:
    raise RuntimeError("smoke tests need BASE_URL")
EXPECTED_RELEASE = os.environ.get("EXPECTED_RELEASE")


def test_service_is_ready():
    response = requests.get(f"{BASE_URL}/readyz", timeout=5)
    assert response.status_code == 200, response.text


def test_deployed_release_is_the_one_we_built():
    body = requests.get(BASE_URL, timeout=5).json()
    assert body["service"] == "text-stats"
    if EXPECTED_RELEASE:
        assert body["release"] == EXPECTED_RELEASE


def test_write_reaches_the_database():
    before = requests.get(f"{BASE_URL}/analyses", timeout=5).json()["count"]
    response = requests.post(f"{BASE_URL}/stats", json={"text": "smoke test write"}, timeout=5)
    assert response.status_code == 200, response.text
    assert requests.get(f"{BASE_URL}/analyses", timeout=5).json()["count"] == before + 1
