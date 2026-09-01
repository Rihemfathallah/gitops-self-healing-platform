"""
main.py
-------
FastAPI application entry point.
Creates the app, registers routers, mounts metrics,
triggers document indexation on startup, runs uvicorn for local dev.
"""

import asyncio
import logging
import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from config import settings
from api.routes import health, index, query, upload
from chaos import ChaosMiddleware, crash_if_requested
from metrics.sli import SLIMetricsMiddleware
from rag.indexer import Indexer

# JSON structured logging — parseable by Promtail → Loki
logging.basicConfig(
    level=settings.log_level.upper(),
    format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}',
)
logger = logging.getLogger(__name__)

# A release configured to crash-loop must fail before serving anything.
crash_if_requested()


async def _run_startup_indexation() -> None:
    """Run automatic indexation in the background without blocking app startup."""
    logger.info("startup: beginning automatic document indexation")
    try:
        indexer = Indexer()
        await indexer.run()
        logger.info("startup: indexation complete")
    except Exception as exc:
        # Don't crash — ChromaDB may not be ready yet on first boot
        # Documents can be re-indexed via POST /api/index
        logger.warning("startup: indexation failed — %s — continuing anyway", exc)


def _run_startup_indexation_sync() -> None:
    """Run async indexation in a dedicated thread so startup stays responsive."""
    asyncio.run(_run_startup_indexation())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan handler.

    Startup:  index documents, warn but don't crash if ChromaDB unavailable
    Shutdown: close open HTTP clients
    """
    # ── Startup ───────────────────────────────────────────────
    app.state.startup_index_task = None
    if settings.auto_index_on_startup:
        app.state.startup_index_task = asyncio.create_task(
            asyncio.to_thread(_run_startup_indexation_sync)
        )
        logger.info("startup: indexation scheduled in background")
    else:
        logger.info("startup: automatic indexation disabled")

    yield  # app runs here

    # ── Shutdown ──────────────────────────────────────────────
    logger.info("shutdown: releasing resources")
    index_task = getattr(app.state, "startup_index_task", None)
    if index_task is not None and not index_task.done():
        index_task.cancel()
        logger.info("shutdown: startup indexation task cancellation requested")

    try:
        # Close the Generator's httpx.AsyncClient if engine was initialised
        from api.routes.query import _engine
        if _engine is not None:
            await _engine.generator.close()
            logger.info("shutdown: generator HTTP client closed")
    except Exception as exc:
        logger.warning("shutdown: error releasing resources — %s", exc)


def create_app() -> FastAPI:
    """
    Construct and configure the FastAPI application.

    Returns:
        FastAPI: Fully configured app instance.
    """
    app = FastAPI(
        title="RAG API",
        description="Retrieval-Augmented Generation API backed by ChromaDB and Ollama.",
        version="1.0.0",
        docs_url="/docs",
        lifespan=lifespan,
    )

    # CORS — allow all origins for local development
    # TODO: restrict allow_origins in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Fault injection first, SLI metrics last: the last middleware added is the
    # outermost one, so injected 500s and delays are seen by the SLI exactly as
    # a client would see them.
    app.add_middleware(ChaosMiddleware)
    app.add_middleware(SLIMetricsMiddleware)

    # Register API routers
    app.include_router(health.router)
    app.include_router(query.router, prefix="/api")
    app.include_router(index.router, prefix="/api")
    app.include_router(upload.router, prefix="/api")

    # Mount Prometheus metrics — scraped by Prometheus every 15s
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    return app


app = create_app()


if __name__ == "__main__":
    # Local dev only — Docker uses gunicorn or uvicorn directly
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        log_level=settings.log_level,
    )
