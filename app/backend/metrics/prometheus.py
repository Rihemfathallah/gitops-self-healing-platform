"""
metrics/prometheus.py
---------------------
Prometheus metric definitions for the RAG backend.

All metrics are declared as module-level constants so they are
registered exactly once. Import them in route handlers and the
RAG engine to record observations.
"""

from prometheus_client import Counter, Histogram, Gauge


# ── HTTP Request metrics ──────────────────────────────────────────────

REQUEST_COUNT = Counter(
    name="rag_http_requests_total",
    documentation="Total number of HTTP requests received by the API.",
    labelnames=["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    name="rag_http_request_duration_seconds",
    documentation="End-to-end HTTP request latency in seconds.",
    labelnames=["method", "endpoint"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)


# ── RAG pipeline metrics ──────────────────────────────────────────────

RAG_QUERY_DURATION = Histogram(
    name="rag_query_duration_seconds",
    documentation="Time spent inside the full RAG pipeline.",
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 60.0),
)

RAG_RETRIEVAL_DURATION = Histogram(
    name="rag_retrieval_duration_seconds",
    documentation="Time spent querying ChromaDB for similar chunks.",
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.0),
)

RAG_GENERATION_DURATION = Histogram(
    name="rag_generation_duration_seconds",
    documentation="Time spent waiting for Ollama to produce a response.",
    buckets=(0.5, 1.0, 5.0, 10.0, 20.0, 60.0, 120.0),
)

RAG_CHUNKS_RETRIEVED = Histogram(
    name="rag_chunks_retrieved_total",
    documentation="Number of document chunks retrieved per query.",
    buckets=(1, 2, 3, 5, 10),
)


# ── Indexation metrics ────────────────────────────────────────────────

INDEXATION_RUNS = Counter(
    name="rag_indexation_runs_total",
    documentation="Number of indexation runs completed.",
    labelnames=["status"],
)

DOCUMENTS_INDEXED = Gauge(
    name="rag_documents_indexed",
    documentation="Current number of document chunks stored in ChromaDB.",
)


# ── Error metrics ─────────────────────────────────────────────────────

RAG_ERRORS = Counter(
    name="rag_errors_total",
    documentation="Total number of errors raised inside the RAG pipeline.",
    labelnames=["component"],
)
