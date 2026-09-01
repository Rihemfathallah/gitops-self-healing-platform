"""
api/routes/index.py
-------------------
POST /api/index — manually trigger document re-indexation.
Runs indexation as a background task and returns immediately.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from api.auth import verify_api_key
from rag.indexer import Indexer
from metrics.prometheus import INDEXATION_RUNS, RAG_ERRORS, REQUEST_COUNT

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Index"])

# Prevents two indexation runs from happening simultaneously
_indexation_running = False


# ── Response models ───────────────────────────────────────────────────

class IndexResponse(BaseModel):
    message: str
    status: str


class IndexStatusResponse(BaseModel):
    running: bool
    message: str


# ── Routes ────────────────────────────────────────────────────────────

@router.post(
    "/index",
    response_model=IndexResponse,
    summary="Trigger document re-indexation",
)
async def trigger_index(background_tasks: BackgroundTasks, _key: str = Depends(verify_api_key)) -> IndexResponse:
    """
    Queue a full re-indexation of all documents in /data/documents.

    Returns immediately with status='started'.
    Check GET /api/index/status to monitor progress.

    Raises:
        HTTPException 409: If indexation is already running.
        HTTPException 500: If the background task cannot be queued.
    """
    # Reject if already running
    if _indexation_running:
        logger.warning("indexation requested but already running")
        REQUEST_COUNT.labels(method="POST", endpoint="/api/index", status="409").inc()
        raise HTTPException(
            status_code=409,
            detail="Indexation is already running. Wait for it to complete.",
        )

    logger.info("manual re-indexation requested")

    try:
        indexer = Indexer()
        background_tasks.add_task(_run_indexation, indexer)
    except Exception as exc:
        logger.exception("failed to queue indexation: %s", exc)
        RAG_ERRORS.labels(component="indexer").inc()
        REQUEST_COUNT.labels(method="POST", endpoint="/api/index", status="500").inc()
        raise HTTPException(
            status_code=500,
            detail="Could not start indexation",
        ) from exc

    REQUEST_COUNT.labels(method="POST", endpoint="/api/index", status="200").inc()
    return IndexResponse(
        message="Indexation started in the background. Check logs for progress.",
        status="started",
    )


@router.get(
    "/index/status",
    response_model=IndexStatusResponse,
    summary="Check if indexation is currently running",
)
async def index_status() -> IndexStatusResponse:
    """
    Returns whether a background indexation is currently in progress.
    Useful for the frontend to show a loading indicator.
    """
    return IndexStatusResponse(
        running=_indexation_running,
        message="Indexation in progress" if _indexation_running else "No indexation running",
    )


# ── Background helper ─────────────────────────────────────────────────

async def _run_indexation(indexer: Indexer) -> None:
    """
    Execute the indexer, update Prometheus metrics, and release the flag.
    """
    global _indexation_running
    _indexation_running = True

    try:
        logger.info("background indexation: starting")
        await indexer.run()
        logger.info("background indexation: complete")

        INDEXATION_RUNS.labels(status="success").inc()

    except Exception as exc:
        logger.exception("background indexation failed: %s", exc)
        INDEXATION_RUNS.labels(status="error").inc()
        RAG_ERRORS.labels(component="indexer").inc()

    finally:
        # Always release the flag even if indexation crashed
        _indexation_running = False
