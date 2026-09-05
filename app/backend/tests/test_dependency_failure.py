"""
Tests for dependency failures (incident "dependency-loss", ADR 0003).

Regression: when ChromaDB stopped answering, /api/query blocked the event loop
in a synchronous chromadb call without timeout. /health stopped answering, the
kubelet killed the pod, and the request was never counted: the availability
SLI saw nothing and no alert fired.

Expected now: the query fails fast with HTTP 503, the 503 is counted by the
SLI middleware, and the probes keep answering while ChromaDB hangs.

Light dependencies only (same as test_sli_chaos.py): chromadb, torch and
pdfplumber are stubbed when they are not installed.
"""

import asyncio
import importlib
import sys
import threading
import time
import types

import httpx
import pytest
from fastapi import FastAPI
from prometheus_client import REGISTRY


def _stub_heavy_modules() -> None:
    stubs = {
        "chromadb": {"HttpClient": object, "AdminClient": object},
        "chromadb.config": {"Settings": object},
        "sentence_transformers": {"SentenceTransformer": object},
        "pdfplumber": {},
    }
    for name, attrs in stubs.items():
        try:
            importlib.import_module(name)
        except ImportError:
            module = types.ModuleType(name)
            for key, value in attrs.items():
                setattr(module, key, value)
            sys.modules[name] = module


_stub_heavy_modules()

from config import settings  # noqa: E402
from api.routes import health, query  # noqa: E402
from metrics.sli import SLIMetricsMiddleware  # noqa: E402
from rag.engine import RAGEngine  # noqa: E402
from rag.errors import DependencyUnavailable  # noqa: E402

API_KEY = {"X-API-Key": settings.api_key}
QUESTION = {"question": "Qu'est-ce qu'un budget d'erreur ?"}
LABELS_503 = {"method": "POST", "route": "/api/query", "code": "503"}


class _Embedder:
    def embed_one(self, text):
        return [0.0, 1.0]


class _HangingRetriever:
    """Simulates the partition: the blocking chromadb call does not return."""

    def __init__(self):
        self.release = threading.Event()

    def retrieve(self, **kwargs):
        self.release.wait(timeout=10)
        return []


class _FailingRetriever:
    def retrieve(self, **kwargs):
        raise RuntimeError("ChromaDB query failed")


class _EmptyRetriever:
    def retrieve(self, **kwargs):
        return []


class _Generator:
    async def generate(self, question, chunks):
        return "ok"


class _FailingGenerator:
    async def generate(self, question, chunks):
        raise RuntimeError("Ollama returned error 404")


def _engine(retriever, generator=None) -> RAGEngine:
    engine = RAGEngine.__new__(RAGEngine)  # skip model loading and ChromaDB connection
    engine.embedder = _Embedder()
    engine.retriever = retriever
    engine.generator = generator or _Generator()
    return engine


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(health.router)
    app.include_router(query.router, prefix="/api")
    app.add_middleware(SLIMetricsMiddleware)
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=30)


def _count(labels) -> float:
    return REGISTRY.get_sample_value("http_requests_total", labels) or 0.0


@pytest.fixture
def use_engine(monkeypatch):
    def install(engine):
        monkeypatch.setattr(query, "get_engine", lambda: engine)
    return install


def test_hanging_chromadb_fails_fast_and_probes_stay_up(monkeypatch, use_engine):
    monkeypatch.setattr(settings, "retrieval_timeout_s", 0.5)
    retriever = _HangingRetriever()
    use_engine(_engine(retriever))
    before = _count(LABELS_503)

    async def scenario():
        async with _client(_app()) as client:
            async def timed(coro):
                start = time.perf_counter()
                response = await coro
                return response, time.perf_counter() - start

            async def probe_later():
                await asyncio.sleep(0.1)  # while the query waits on ChromaDB
                return await timed(client.get("/health"))

            (q, q_s), (h, h_s) = await asyncio.gather(
                timed(client.post("/api/query", json=QUESTION, headers=API_KEY)),
                probe_later(),
            )
        retriever.release.set()  # let the worker thread finish before the loop closes
        return q, q_s, h, h_s

    q, q_s, h, h_s = asyncio.run(scenario())

    assert q.status_code == 503
    assert q.json()["detail"] == "Dependency unavailable: chromadb"
    assert q_s < 3, "the query must fail within the retrieval budget, not hang"
    assert h.status_code == 200
    assert h_s < 0.3, "the event loop must stay free: liveness probes keep answering"
    assert _count(LABELS_503) == before + 1, "the failure must reach the availability SLI"


def test_chromadb_error_returns_503(use_engine):
    use_engine(_engine(_FailingRetriever()))
    before = _count(LABELS_503)

    async def scenario():
        async with _client(_app()) as client:
            return await client.post("/api/query", json=QUESTION, headers=API_KEY)

    response = asyncio.run(scenario())
    assert response.status_code == 503
    assert response.json()["detail"] == "Dependency unavailable: chromadb"
    assert _count(LABELS_503) == before + 1


def test_ollama_error_returns_503(use_engine):
    use_engine(_engine(_EmptyRetriever(), _FailingGenerator()))

    async def scenario():
        async with _client(_app()) as client:
            return await client.post("/api/query", json=QUESTION, headers=API_KEY)

    response = asyncio.run(scenario())
    assert response.status_code == 503
    assert response.json()["detail"] == "Dependency unavailable: ollama"


def test_engine_that_cannot_start_returns_503(monkeypatch):
    def broken():
        raise RuntimeError("could not connect to ChromaDB after 10 attempts")

    monkeypatch.setattr(query, "get_engine", broken)

    async def scenario():
        async with _client(_app()) as client:
            return await client.post("/api/query", json=QUESTION, headers=API_KEY)

    assert asyncio.run(scenario()).status_code == 503


def test_dependency_unavailable_is_a_runtime_error():
    # Callers that catch RuntimeError keep working.
    assert issubclass(DependencyUnavailable, RuntimeError)
