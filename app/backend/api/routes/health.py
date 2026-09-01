"""
api/routes/health.py
--------------------
Liveness and readiness probe endpoints.

GET /health        → liveness  (is the container alive?)
GET /health/ready  → readiness (are ChromaDB and Ollama reachable?)
"""

import logging

import httpx
import chromadb
from fastapi import APIRouter
from pydantic import BaseModel

from config import settings
from metrics.prometheus import REQUEST_COUNT

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


# ── Response models ───────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Response for the liveness probe."""
    status: str
    service: str


class ReadinessResponse(BaseModel):
    """Response for the readiness probe — checks downstream services."""
    status: str
    chromadb: str
    ollama: str


# ── Liveness ──────────────────────────────────────────────────────────

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
    response_description="Confirms the container is alive",
)
async def health_check() -> HealthResponse:
    """
    Simple liveness probe with no external dependencies.
    Returns instantly even if ChromaDB or Ollama are down.
    """
    logger.debug("liveness probe requested")
    REQUEST_COUNT.labels(method="GET", endpoint="/health", status="200").inc()
    return HealthResponse(status="ok", service="rag-backend")


# ── Readiness ─────────────────────────────────────────────────────────

@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    response_description="Confirms downstream services are reachable",
)
async def readiness_check() -> ReadinessResponse:
    """
    Deep health check that pings ChromaDB and Ollama.

    Used by:
      - CI/CD gate (scripts/health-check.sh) before marking deploy as PASS
      - Docker Compose depends_on condition: service_healthy
      - Grafana alerting rules

    Returns:
        ReadinessResponse: status of each downstream service.
    """
    # ── Check ChromaDB ────────────────────────────────────────
    chroma_status = "unreachable"
    try:
        client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )
        client.heartbeat()
        chroma_status = "ok"
    except Exception as exc:
        logger.warning("readiness: chromadb unreachable — %s", exc)

    # ── Check Ollama ──────────────────────────────────────────
    ollama_status = "unreachable"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.ollama_url}/api/tags")
            if response.status_code == 200:
                ollama_status = "ok"
    except Exception as exc:
        logger.warning("readiness: ollama unreachable — %s", exc)

    # ── Overall status ────────────────────────────────────────
    overall = "ok" if chroma_status == "ok" and ollama_status == "ok" else "degraded"
    http_status = "200" if overall == "ok" else "503"

    REQUEST_COUNT.labels(method="GET", endpoint="/health/ready", status=http_status).inc()

    logger.info("readiness: overall=%s chroma=%s ollama=%s", overall, chroma_status, ollama_status)

    return ReadinessResponse(
        status=overall,
        chromadb=chroma_status,
        ollama=ollama_status,
    )
