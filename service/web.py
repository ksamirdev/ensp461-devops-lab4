"""Text statistics service for Lab 4: the Lab 3 app with Postgres persistence and deployment metadata."""
import logging
import os
import random
import time

import psycopg
from flask import Flask, g, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

RELEASE = os.environ.get("RELEASE", "dev")
COLOR = os.environ.get("COLOR", "")
DATABASE_URL = os.environ.get("DATABASE_URL")
# Fault injection for the canary lab: fraction of /stats requests that fail on purpose
FAULT_RATE = float(os.environ.get("FAULT_RATE", "0"))

app = Flask(__name__)

REQUESTS = Counter(
    "textstats_http_requests_total", "HTTP requests served", ["method", "route", "status"]
)
LATENCY = Histogram(
    "textstats_http_request_duration_seconds",
    "Request latency",
    ["route"],
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1),
)

log = logging.getLogger("textstats")
log.setLevel(logging.INFO)
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
log.addHandler(_handler)

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id bigserial PRIMARY KEY,
    characters integer NOT NULL,
    words integer NOT NULL,
    release text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
)
"""


def db():
    # ponytail: one connection per request; a pool (psycopg_pool) if connection setup shows up in latency.
    # It also means every request reconnects through the -rw Service, so a DB failover needs no app restart.
    return psycopg.connect(DATABASE_URL, connect_timeout=3)


_schema_ready = False


def ensure_schema(conn):
    global _schema_ready
    if not _schema_ready:
        conn.execute(SCHEMA)
        _schema_ready = True


def text_stats(text):
    words = text.split()
    return {
        "characters": len(text),
        "words": len(words),
        "unique_words": len({w.lower() for w in words}),
    }


@app.before_request
def start_timer():
    g.started = time.perf_counter()


@app.after_request
def observe(response):
    if request.path == "/metrics":
        return response
    # url_rule, not path, so unknown URLs cannot create unbounded label values
    route = request.url_rule.rule if request.url_rule else "unmatched"
    elapsed = time.perf_counter() - g.started
    REQUESTS.labels(request.method, route, str(response.status_code)).inc()
    LATENCY.labels(route).observe(elapsed)
    level = logging.WARNING if response.status_code >= 400 else logging.INFO
    log.log(
        level,
        "method=%s path=%s status=%s duration_ms=%.2f release=%s",
        request.method, route, response.status_code, elapsed * 1000, RELEASE,
    )
    return response


@app.get("/")
def home():
    return jsonify(service="text-stats", release=RELEASE, color=COLOR, pod=os.environ.get("HOSTNAME", ""))


@app.get("/healthz")
def healthz():
    """Liveness: the process answers. Never touches the database, so a DB outage does not restart pods."""
    return jsonify(healthy=True, release=RELEASE)


@app.get("/readyz")
def readyz():
    """Readiness: the pod can serve real traffic, including reaching its database when it has one."""
    if DATABASE_URL:
        try:
            with db() as conn:
                ensure_schema(conn)
        except psycopg.Error as exc:
            return jsonify(ready=False, error=type(exc).__name__), 503
    return jsonify(ready=True, release=RELEASE)


@app.get("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.post("/stats")
def stats():
    if FAULT_RATE and random.random() < FAULT_RATE:  # nosec B311 - fault injection, not security
        return jsonify(error="injected fault"), 500
    payload = request.get_json(silent=True) or {}
    text = payload.get("text")
    if not isinstance(text, str):
        return jsonify(error="JSON field 'text' must be a string"), 400
    result = text_stats(text)
    if DATABASE_URL:
        try:
            with db() as conn:
                ensure_schema(conn)
                row = conn.execute(
                    "INSERT INTO analyses (characters, words, release) VALUES (%s, %s, %s) RETURNING id",
                    (result["characters"], result["words"], RELEASE),
                ).fetchone()
            result["id"] = row[0]
        except psycopg.Error as exc:
            log.error("database write failed: %s", exc)
            return jsonify(error="database unavailable"), 503
    return jsonify(result)


@app.get("/analyses")
def analyses():
    if not DATABASE_URL:
        return jsonify(error="no database configured"), 404
    try:
        with db() as conn:
            ensure_schema(conn)
            count, last_id = conn.execute("SELECT count(*), coalesce(max(id), 0) FROM analyses").fetchone()
    except psycopg.Error:
        return jsonify(error="database unavailable"), 503
    return jsonify(count=count, last_id=last_id)

