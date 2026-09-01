"""
chaos.py
--------
Fault injection used to simulate a *bad release* (EF-10).

A faulty release is a normal Git change of the Helm values that sets one of
these variables. Nothing is active unless a variable is set, so a healthy
release behaves exactly like the original NeuralRAG.

  CHAOS_ERROR_RATE      float 0..1  share of /api/* requests answered with HTTP 500
  CHAOS_LATENCY_MS      int         extra latency added to every /api/* request
  CHAOS_CRASH_ON_START  bool        process exits at startup (crash-looping release)
"""

import asyncio
import logging
import os
import random
import sys

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)


def _float(name: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def crash_if_requested() -> None:
    """Called at import time of main.py: a crash-looping release never becomes ready."""
    if os.getenv("CHAOS_CRASH_ON_START", "false").lower() in {"1", "true", "yes"}:
        logger.error("chaos: CHAOS_CRASH_ON_START is set, exiting")
        sys.exit(3)


class ChaosMiddleware:
    """Injects errors and latency on /api/* routes only (probes stay green on purpose:
    a bad release that passes its health checks is the realistic, hard case)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.error_rate = min(max(_float("CHAOS_ERROR_RATE"), 0.0), 1.0)
        self.latency_s = max(_float("CHAOS_LATENCY_MS"), 0.0) / 1000
        if self.error_rate or self.latency_s:
            logger.warning("chaos: active error_rate=%.2f latency_ms=%.0f", self.error_rate, self.latency_s * 1000)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        if self.error_rate and random.random() < self.error_rate:
            response = JSONResponse({"detail": "injected fault (chaos)"}, status_code=500)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
