"""
api/routes/query.py
-------------------
POST /api/query — main RAG question-answering endpoint.
Receives a question, runs the RAG pipeline, returns answer + source chunks.
"""

import logging
import time
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import verify_api_key
from rag.engine import RAGEngine
from metrics.prometheus import REQUEST_COUNT, REQUEST_LATENCY, RAG_QUERY_DURATION

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Query"])

_engine: RAGEngine | None = None


def get_engine() -> RAGEngine:
    """Return or lazily initialise the RAG engine singleton."""
    global _engine
    if _engine is None:
        _engine = RAGEngine()
    return _engine


class QueryRequest(BaseModel):
    """Payload sent by the frontend for a RAG query."""
    question: str = Field(..., min_length=1, max_length=2000)
    department: str | None = Field(default=None, description="Department to scope the search")


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
        engine = get_engine()

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
