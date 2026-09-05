"""
api/routes/query.py
-------------------
POST /api/query — main RAG question-answering endpoint.
Receives a question, runs the RAG pipeline, returns answer + source chunks.
"""

import asyncio
import logging
import threading
import time
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from api.auth import verify_api_key
from config import settings
from rag.engine import RAGEngine
from rag.errors import DependencyUnavailable
from metrics.prometheus import REQUEST_COUNT, REQUEST_LATENCY, RAG_QUERY_DURATION

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Query"])

_engine: RAGEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> RAGEngine:
    """Return or lazily initialise the RAG engine singleton (blocking, thread-safe)."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = RAGEngine()
    return _engine


async def _engine_for_request() -> RAGEngine:
    """Get the engine without blocking the event loop.

    The first call loads the embedding model and connects to ChromaDB (retries for
    up to ~100 s when ChromaDB is down). Done inline, it froze the event loop, so
    /health stopped answering and the kubelet restarted the pod.
    """
    try:
        return await asyncio.wait_for(asyncio.to_thread(get_engine), timeout=settings.engine_init_timeout_s)
    except asyncio.TimeoutError as exc:
        raise DependencyUnavailable("rag-engine", "initialisation still running") from exc
    except DependencyUnavailable:
        raise
    except Exception as exc:
        # Retriever() gives up when ChromaDB stays unreachable.
        raise DependencyUnavailable("chromadb", str(exc)) from exc


class QueryRequest(BaseModel):
    """Payload sent by the frontend for a RAG query."""
    question: str = Field(..., min_length=1, max_length=2000)
    department: str | None = Field(default=None, description="Department to scope the search")

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        # Rejected here (422) rather than in the engine: a blank question must not
        # trigger the engine's lazy start, nor count as a server error.
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


class SourceChunk(BaseModel):
    """A single document chunk returned as evidence for the answer."""
    content: str
    source: str
    score: float


class QueryResponse(BaseModel):
    """Full response returned to the frontend."""
    answer: str
    sources: List[SourceChunk]
    duration_ms: float


@router.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest, _key: str = Depends(verify_api_key)) -> QueryResponse:
    """
    Process a natural-language question through the full RAG pipeline.

    Steps:
      1. Embed the question
      2. Retrieve top-K chunks from ChromaDB
      3. Generate answer via Ollama
      4. Return answer + source chunks + timing
    """
    start = time.perf_counter()
    logger.info(
        "query received: length=%d preview=%s",
        len(request.question),
        request.question[:80],
    )

    try:
        engine = await _engine_for_request()

        # Time the RAG pipeline separately from total HTTP duration
        rag_start = time.perf_counter()
        result = await engine.query(request.question, department=request.department)
        RAG_QUERY_DURATION.observe(time.perf_counter() - rag_start)

        answer = result.answer
        sources = [
            SourceChunk(content=c.content, source=c.source, score=c.score)
            for c in result.chunks
        ]

        # Warn if no chunks were retrieved — documents may not be indexed
        if not sources:
            logger.warning("query returned no source chunks — documents may not be indexed yet")

    except DependencyUnavailable as exc:
        # A failed dependency must surface as a fast 5xx, counted by the availability SLI.
        logger.error("dependency unavailable: %s", exc)
        REQUEST_COUNT.labels(method="POST", endpoint="/api/query", status="503").inc()
        raise HTTPException(status_code=503, detail=f"Dependency unavailable: {exc.dependency}") from exc

    except Exception as exc:
        logger.exception("RAG engine error: %s", exc)
        REQUEST_COUNT.labels(method="POST", endpoint="/api/query", status="500").inc()
        raise HTTPException(status_code=500, detail="Internal RAG error") from exc

    duration_ms = (time.perf_counter() - start) * 1000
    REQUEST_COUNT.labels(method="POST", endpoint="/api/query", status="200").inc()
    REQUEST_LATENCY.labels(method="POST", endpoint="/api/query").observe(duration_ms / 1000)

    logger.info("query answered in %.1f ms", duration_ms)
    return QueryResponse(
        answer=answer,
        sources=sources,
        duration_ms=round(duration_ms, 2),
    )
