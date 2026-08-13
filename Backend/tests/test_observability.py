"""
Phase 1.8 — logging, request correlation, health, and error containment.
"""
import json
import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.observability import (
    ConsoleFormatter,
    JsonFormatter,
    RequestContextMiddleware,
    _clean_request_id,
    request_id_var,
)


def _app_with_middleware():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ping")
    def ping():
        from app.observability import current_request_id
        return {"request_id": current_request_id()}

    @app.get("/boom")
    def boom():
        raise HTTPException(418, "teapot")

    return app


# ── Request correlation ───────────────────────────────────────────────────────

def test_request_id_is_generated_and_returned():
    client = TestClient(_app_with_middleware())
    resp = client.get("/ping")

    assert resp.status_code == 200
    rid = resp.headers["x-request-id"]
    assert rid
    # The same id the handler saw is the one echoed back.
    assert resp.json()["request_id"] == rid


def test_inbound_request_id_is_propagated():
    """Lets a request be traced across services, not just within this one."""
    client = TestClient(_app_with_middleware())
    resp = client.get("/ping", headers={"x-request-id": "trace-abc123"})

    assert resp.headers["x-request-id"] == "trace-abc123"
    assert resp.json()["request_id"] == "trace-abc123"


@pytest.mark.parametrize(
    "hostile",
    [
        "bad id with spaces",
        'x" , "level":"CRITICAL',     # forged JSON field
        "line\nbreak",                # forged log line
        "x" * 200,                    # unbounded length
    ],
)
def test_malformed_request_id_is_replaced(hostile):
    """
    The header lands in log output, so an unvalidated value is a log-injection
    vector. Bad values are discarded and a fresh id generated.
    """
    client = TestClient(_app_with_middleware())
    resp = client.get("/ping", headers={"x-request-id": hostile})

    returned = resp.headers["x-request-id"]
    assert returned != hostile
    assert _clean_request_id(hostile.encode("utf-8", "ignore")) is None


def test_request_id_is_cleared_between_requests():
    client = TestClient(_app_with_middleware())
    client.get("/ping", headers={"x-request-id": "first-req"})
    assert request_id_var.get() is None, "context leaked past the request"


# ── Log formatting ────────────────────────────────────────────────────────────

def _record(**extra):
    rec = logging.LogRecord(
        name="tv.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="settled booking %s", args=("booking-1",), exc_info=None,
    )
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_json_formatter_emits_one_parseable_object():
    line = JsonFormatter().format(_record(http_status=200, duration_ms=12.5))
    parsed = json.loads(line)

    assert parsed["msg"] == "settled booking booking-1"
    assert parsed["level"] == "INFO"
    assert parsed["http_status"] == 200
    assert parsed["duration_ms"] == 12.5
    assert "\n" not in line, "a multi-line record breaks line-delimited ingestion"


def test_json_formatter_includes_request_id():
    token = request_id_var.set("req-xyz")
    try:
        parsed = json.loads(JsonFormatter().format(_record()))
        assert parsed["request_id"] == "req-xyz"
    finally:
        request_id_var.reset(token)


def test_json_formatter_serialises_exceptions():
    try:
        raise ValueError("kaboom")
    except ValueError:
        import sys
        rec = _record()
        rec.exc_info = sys.exc_info()
        parsed = json.loads(JsonFormatter().format(rec))

    assert "kaboom" in parsed["exception"]
    assert "\n" not in JsonFormatter().format(rec)


def test_console_formatter_is_readable():
    token = request_id_var.set("abc123")
    try:
        out = ConsoleFormatter().format(_record())
        assert "abc123" in out
        assert "settled booking booking-1" in out
    finally:
        request_id_var.reset(token)


# ── Health ────────────────────────────────────────────────────────────────────

def test_health_returns_503_when_database_is_down(monkeypatch):
    """A health check that reports 200 while broken is worse than none."""
    import app.routes.health as health_module

    class BrokenDB:
        def table(self, *_):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(health_module, "supabase", BrokenDB())

    app = FastAPI()
    app.include_router(health_module.router)
    resp = TestClient(app).get("/health")

    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"
    assert resp.json()["checks"]["database"]["status"] == "error"


def test_health_ok_when_database_responds(monkeypatch):
    import app.routes.health as health_module

    class OkDB:
        def table(self, *_):
            return self
        def select(self, *_):
            return self
        def limit(self, *_):
            return self
        def execute(self):
            return type("R", (), {"data": []})()

    monkeypatch.setattr(health_module, "supabase", OkDB())

    app = FastAPI()
    app.include_router(health_module.router)
    resp = TestClient(app).get("/health")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_liveness_never_touches_dependencies(monkeypatch):
    import app.routes.health as health_module

    class Exploding:
        def table(self, *_):
            raise AssertionError("liveness must not hit the database")

    monkeypatch.setattr(health_module, "supabase", Exploding())

    app = FastAPI()
    app.include_router(health_module.router)
    assert TestClient(app).get("/health/live").status_code == 200


def test_cron_secret_uses_constant_time_comparison():
    """A plain != leaks the secret one byte at a time via response timing."""
    import inspect

    import app.routes.health as health_module

    source = inspect.getsource(health_module.trigger_fulfillment_jobs)
    assert "compare_digest" in source


# ── Error containment ─────────────────────────────────────────────────────────

def test_500_response_carries_a_request_id():
    """
    Regression: the 500 handler runs inside Starlette's ServerErrorMiddleware,
    which is OUTSIDE user middleware — the request-id contextvar has already
    been reset by then, so the handler must read it off the scope instead.
    Observed live returning "request_id": null before the fix.
    """
    import main

    client = TestClient(main.app, raise_server_exceptions=False)

    @main.app.get("/_boom_for_test")
    def _boom():
        raise RuntimeError("intentional")

    resp = client.get("/_boom_for_test", headers={"x-request-id": "trace-500"})

    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == "An internal error occurred."
    assert body["request_id"] == "trace-500", "operator cannot correlate the report to logs"


def test_internal_errors_are_not_leaked_to_clients():
    """
    Exception text carries table names, SQL fragments and provider responses.
    The client gets a request id to quote; the detail stays in the logs.
    """
    import main

    client = TestClient(main.app, raise_server_exceptions=False)
    resp = client.get("/bookings/does-not-exist")

    # Whatever happens, no raw traceback or driver message reaches the client.
    body = resp.text.lower()
    for leak in ("traceback", "postgrest", "psycopg", "supabase.co", "select "):
        assert leak not in body, f"response leaked {leak!r}"
