"""
metrics/sli.py
--------------
SLI instrumentation for the platform (EF-05).

One ASGI middleware records every API request in two series that the
SLO recording rules consume:

  http_requests_total{method, route, code}
  http_request_duration_seconds_bucket{method, route, le}

`route` is the route template (e.g. /api/query), never the raw path, so
cardinality stays bounded. Probes and /metrics are excluded: they are not
user traffic and would inflate availability.

It also exposes `neuralrag_build_info{version}` so dashboards can show which
release served which traffic.
"""

import os
import time

from prometheus_client import Counter, Gauge, Histogram
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Buckets must contain the latency SLO threshold (charts/neuralrag values:
# slo.latency.thresholdSeconds). Keep them in sync.
LATENCY_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0, 20.0, 30.0, 60.0)

EXCLUDED_PREFIXES = ("/metrics", "/health", "/docs", "/openapi.json")

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests handled by the API, by route template and status code.",
    ["method", "route", "code"],
)

HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds, by route template.",
    ["method", "route"],
    buckets=LATENCY_BUCKETS,
)

BUILD_INFO = Gauge(
    "neuralrag_build_info",
    "Always 1; labels identify the running release.",
    ["version"],
)
BUILD_INFO.labels(version=os.getenv("APP_VERSION", "dev")).set(1)


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path or "unmatched"


class SLIMetricsMiddleware:
    """Pure ASGI middleware (works with streaming responses and BackgroundTasks)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].startswith(EXCLUDED_PREFIXES):
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # An unhandled exception is counted as a 500, which is what the client sees.
            route = _route_template(scope)
            method = scope.get("method", "GET")
            HTTP_REQUESTS.labels(method=method, route=route, code=str(status["code"])).inc()
            HTTP_DURATION.labels(method=method, route=route).observe(time.perf_counter() - start)
