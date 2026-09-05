"""
Tests for the SLI middleware and the chaos (bad release) middleware.
They build a tiny FastAPI app so they do not need ChromaDB, Ollama or torch.
"""

import importlib

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY


def _sample(name, labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _build_app(monkeypatch, **env):
    for key in ("CHAOS_ERROR_RATE", "CHAOS_LATENCY_MS", "CHAOS_CRASH_ON_START"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import chaos
    importlib.reload(chaos)
    from metrics.sli import SLIMetricsMiddleware

    app = FastAPI()

    @app.get("/api/items/{item_id}")
    async def item(item_id: int):
        if item_id == 0:
            raise HTTPException(status_code=500, detail="boom")
        return {"id": item_id}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.add_middleware(chaos.ChaosMiddleware)
    app.add_middleware(SLIMetricsMiddleware)
    return TestClient(app)


def test_route_template_is_used_not_raw_path(monkeypatch):
    client = _build_app(monkeypatch)
    labels = {"method": "GET", "route": "/api/items/{item_id}", "code": "200"}
    before = _sample("http_requests_total", labels)
    assert client.get("/api/items/1").status_code == 200
    assert client.get("/api/items/2").status_code == 200
    assert _sample("http_requests_total", labels) == before + 2


def test_server_errors_are_counted(monkeypatch):
    client = _build_app(monkeypatch)
    labels = {"method": "GET", "route": "/api/items/{item_id}", "code": "500"}
    before = _sample("http_requests_total", labels)
    assert client.get("/api/items/0").status_code == 500
    assert _sample("http_requests_total", labels) == before + 1


def test_probes_are_excluded(monkeypatch):
    client = _build_app(monkeypatch)
    labels = {"method": "GET", "route": "/health", "code": "200"}
    client.get("/health")
    assert _sample("http_requests_total", labels) == 0.0


def test_latency_histogram_observed(monkeypatch):
    client = _build_app(monkeypatch)
    labels = {"method": "GET", "route": "/api/items/{item_id}"}
    before = _sample("http_request_duration_seconds_count", labels)
    client.get("/api/items/3")
    assert _sample("http_request_duration_seconds_count", labels) == before + 1


def test_chaos_error_rate_one_fails_every_api_call_and_is_seen_by_sli(monkeypatch):
    client = _build_app(monkeypatch, CHAOS_ERROR_RATE="1.0")
    labels = {"method": "GET", "route": "unmatched", "code": "500"}
    before = _sample("http_requests_total", labels)
    for _ in range(5):
        assert client.get("/api/items/1").status_code == 500
    # Chaos answers before routing, so the route is "unmatched"; the SLO rules count it.
    assert _sample("http_requests_total", labels) == before + 5
    # Probes stay healthy: a bad release that passes health checks is the hard case.
    assert client.get("/health").status_code == 200


def test_chaos_latency(monkeypatch):
    client = _build_app(monkeypatch, CHAOS_LATENCY_MS="300")
    labels = {"method": "GET", "route": "/api/items/{item_id}", "le": "0.25"}
    fast_before = _sample("http_request_duration_seconds_bucket", labels)
    client.get("/api/items/1")
    assert _sample("http_request_duration_seconds_bucket", labels) == fast_before


def test_crash_on_start(monkeypatch):
    monkeypatch.setenv("CHAOS_CRASH_ON_START", "true")
    import chaos
    importlib.reload(chaos)
    with pytest.raises(SystemExit):
        chaos.crash_if_requested()


def test_preinitialized_series_start_at_zero():
    # rate() ignores the first value of a series: a series born at 1 hides its first
    # request. Pre-created at 0, the first request of a canary is visible (ADR 0002).
    from fastapi import FastAPI
    from metrics.sli import preinitialize

    app = FastAPI()

    @app.post("/api/preinit-probe")
    async def probe():
        return {}

    preinitialize(app)
    for code in ("200", "500", "503"):
        labels = {"method": "POST", "route": "/api/preinit-probe", "code": code}
        assert REGISTRY.get_sample_value("http_requests_total", labels) == 0.0
    labels = {"method": "POST", "route": "/api/preinit-probe"}
    assert REGISTRY.get_sample_value("http_request_duration_seconds_count", labels) == 0.0
    assert REGISTRY.get_sample_value(
        "http_requests_total", {"method": "POST", "route": "unmatched", "code": "500"}) is not None
