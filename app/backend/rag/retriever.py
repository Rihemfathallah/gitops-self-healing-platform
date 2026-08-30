"""
rag/retriever.py
----------------
Vector similarity search against ChromaDB.

The Retriever takes a pre-computed query vector and returns the top-K
most semantically similar document chunks from the ChromaDB collection.
It is called on every user query (the online read path).
"""

import logging
import time
from dataclasses import dataclass
from typing import List

import chromadb
from chromadb.config import Settings as ChromaSettings

from config import settings
from metrics.prometheus import RAG_RETRIEVAL_DURATION, RAG_CHUNKS_RETRIEVED, RAG_ERRORS

logger = logging.getLogger(__name__)

# Primary similarity threshold for retrieved chunks
MIN_SCORE = 0.3

# Fallback threshold used only when no chunk passes MIN_SCORE
MIN_SCORE_FALLBACK = 0.2

CHROMA_TENANT = "default_tenant"
CHROMA_DATABASE = "default_database"

# Retry configuration for ChromaDB connection
CHROMA_CONNECT_RETRIES = 10
CHROMA_CONNECT_DELAY = 5  # seconds between retries


@dataclass
class RetrievedChunk:
    """A single search result returned from ChromaDB."""
    chunk_id: str
    content: str
    source: str
    score: float
    department: str = ""


class Retriever:
    """
    Queries ChromaDB for the most similar chunks to a given query vector.

    Attributes:
        _client:      ChromaDB HTTP client.
        _collection:  ChromaDB collection handle.
    """

    def __init__(self) -> None:
        logger.info(
            "retriever: connecting to ChromaDB at %s:%s",
            settings.chroma_host,
            settings.chroma_port,
        )

        # ── Wait for ChromaDB to be ready (retry loop) ────────────────
        self._client = self._connect_with_retry()

        # ── Ensure tenant + database exist (ChromaDB 0.5+ requires this)
        self._ensure_tenant_and_database()

        # ── Reconnect with tenant + database context ──────────────────
        self._client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=int(settings.chroma_port),
            tenant=CHROMA_TENANT,
            database=CHROMA_DATABASE,
        )

        # ── Get or create the collection with cosine distance ─────────
        self._collection = self._client.get_or_create_collection(
            name=settings.chroma_collection,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("retriever: connected — collection '%s' ready", settings.chroma_collection)

    def _connect_with_retry(self) -> chromadb.HttpClient:
        """
        Try to connect to ChromaDB, retrying on failure.
        This handles the race condition where ChromaDB starts after the backend.
        """
        for attempt in range(1, CHROMA_CONNECT_RETRIES + 1):
            try:
                client = chromadb.HttpClient(
                    host=settings.chroma_host,
                    port=int(settings.chroma_port),
                )
                client.heartbeat()  # Verify the server is actually reachable
                logger.info("retriever: ChromaDB is reachable (attempt %d)", attempt)
                return client
            except Exception as exc:
                logger.warning(
                    "retriever: ChromaDB not ready yet (attempt %d/%d) — %s",
                    attempt,
                    CHROMA_CONNECT_RETRIES,
                    exc,
                )
                if attempt < CHROMA_CONNECT_RETRIES:
                    time.sleep(CHROMA_CONNECT_DELAY)

        raise RuntimeError(
            f"retriever: could not connect to ChromaDB at "
            f"{settings.chroma_host}:{settings.chroma_port} "
            f"after {CHROMA_CONNECT_RETRIES} attempts"
        )

    def _ensure_tenant_and_database(self) -> None:
        """Create tenant and database if they don't exist (ChromaDB 0.5+)."""
        try:
            admin = chromadb.AdminClient(
                settings=ChromaSettings(
                    chroma_api_impl="chromadb.api.fastapi.FastAPI",
                    chroma_server_host=settings.chroma_host,
                    chroma_server_http_port=int(settings.chroma_port),
                )
            )
            existing_tenants = [t.name for t in admin.list_tenants()]
            if CHROMA_TENANT not in existing_tenants:
                logger.info("retriever: creating tenant '%s'", CHROMA_TENANT)
                admin.create_tenant(CHROMA_TENANT)

            existing_dbs = [d.name for d in admin.list_databases(tenant=CHROMA_TENANT)]
            if CHROMA_DATABASE not in existing_dbs:
                logger.info("retriever: creating database '%s'", CHROMA_DATABASE)
                admin.create_database(CHROMA_DATABASE, tenant=CHROMA_TENANT)

        except Exception as exc:
            logger.warning(
                "retriever: admin setup skipped (may already exist or older Chroma version) — %s", exc
            )

    def retrieve(
        self,
        query_vector: List[float],
        top_k: int | None = None,
        department: str | None = None,
        ue_code: str | None = None,
    ) -> List[RetrievedChunk]:
        """
        Search the vector store for the top-K most similar chunks.

        Args:
            query_vector: Dense embedding of the user's question.
            top_k:        Number of results to return.
            department:   Optional department to filter results.
            ue_code:      Optional UE code to prioritize matching chunks.

        Returns:
            List[RetrievedChunk]: Ranked list filtered by MIN_SCORE.

        Raises:
            RuntimeError: If the ChromaDB query fails.
        """
        if self._collection is None:
            raise RuntimeError("ChromaDB collection is not initialised")

        k = top_k or settings.top_k
        logger.debug(
            "retriever: querying top-%d chunks (dept=%s, ue=%s)",
            k, department or "all", ue_code or "none",
        )

        # Build where filter: combine department + ue_code if both present
        where_filter = self._build_where_filter(department, ue_code)

        # If a UE code is specified, try a targeted query first
        if ue_code:
            chunks = self._query_chroma(query_vector, k, where_filter)
            if chunks:
                logger.info(
                    "retriever: UE %s filter matched %d chunk(s)", ue_code, len(chunks)
                )
                # Also fetch broader results and merge (UE chunks get priority)
                broader_filter = {"department": department} if department else None
                broad_chunks = self._query_chroma(query_vector, k, broader_filter)
                return self._merge_and_rank(chunks, broad_chunks, ue_code)

        chunks = self._query_chroma(query_vector, k, where_filter)

        # Filter out low-relevance chunks (primary threshold)
        primary_chunks = [c for c in chunks if c.score >= MIN_SCORE]

        if primary_chunks:
            chunks = primary_chunks
        else:
            # Fallback threshold improves recall for broader/less-specific queries.
            fallback_chunks = [c for c in chunks if c.score >= MIN_SCORE_FALLBACK]
            if fallback_chunks:
                logger.info(
                    "retriever: no chunks above %.2f, using fallback threshold %.2f (%d chunk(s))",
                    MIN_SCORE,
                    MIN_SCORE_FALLBACK,
                    len(fallback_chunks),
                )
                chunks = fallback_chunks
            else:
                # Final safety net: return the best available chunk to avoid empty context.
                if chunks:
                    top_chunk = max(chunks, key=lambda c: c.score)
                    logger.info(
                        "retriever: no chunks above thresholds %.2f/%.2f, returning top-1 fallback (score=%.4f)",
                        MIN_SCORE,
                        MIN_SCORE_FALLBACK,
                        top_chunk.score,
                    )
                    chunks = [top_chunk]
                else:
                    chunks = []
                    logger.warning(
                        "retriever: no chunks returned by ChromaDB — collection may be empty",
                    )

        RAG_CHUNKS_RETRIEVED.observe(len(chunks))
        logger.debug("retriever: returning %d chunk(s)", len(chunks))

        return chunks

    def _build_where_filter(self, department: str | None, ue_code: str | None) -> dict | None:
        """Build a ChromaDB where filter from optional department and ue_code.

        When a department is specified, also includes documents with no department
        (empty string) so that user-uploaded files in the root folder are always searchable.
        """
        conditions = []
        if department:
            conditions.append({"$or": [{"department": department}, {"department": ""}]})
        if ue_code:
            conditions.append({"ue_code": ue_code})

        if len(conditions) > 1:
            return {"$and": conditions}
        elif conditions:
            return conditions[0]
        return None

    def _query_chroma(
        self, query_vector: List[float], k: int, where_filter: dict | None
    ) -> List[RetrievedChunk]:
        """Execute a single ChromaDB query and return parsed results."""
        start = time.perf_counter()
        try:
            results = self._collection.query(
                query_embeddings=[query_vector],
                n_results=k,
                include=["documents", "metadatas", "distances"],
                where=where_filter,
            )
        except Exception as exc:
            RAG_ERRORS.labels(component="retriever").inc()
            logger.error("retriever: ChromaDB query failed — %s", exc)
            raise RuntimeError("ChromaDB query failed") from exc

        RAG_RETRIEVAL_DURATION.observe(time.perf_counter() - start)
        return self._parse_results(results)

    def _merge_and_rank(
        self,
        ue_chunks: List[RetrievedChunk],
        broad_chunks: List[RetrievedChunk],
        ue_code: str,
    ) -> List[RetrievedChunk]:
        """Merge UE-specific and broad results, prioritizing UE matches."""
        seen_ids = {c.chunk_id for c in ue_chunks}
        merged = list(ue_chunks)

        for chunk in broad_chunks:
            if chunk.chunk_id not in seen_ids:
                merged.append(chunk)
                seen_ids.add(chunk.chunk_id)

        # Sort: UE-matching chunks first (by score), then the rest (by score)
        merged.sort(
            key=lambda c: (0 if f"ue_{ue_code}" in c.chunk_id else 1, -c.score)
        )
        return merged[:settings.top_k]

    def _parse_results(self, raw: dict) -> List[RetrievedChunk]:
        """
        Convert raw ChromaDB response into RetrievedChunk objects.

        Converts cosine distance to similarity score: score = 1 - distance.
        """
        chunks: List[RetrievedChunk] = []
        ids = raw["ids"][0]
        documents = raw["documents"][0]
        metadatas = raw["metadatas"][0]
        distances = raw["distances"][0]

        for cid, doc, meta, dist in zip(ids, documents, metadatas, distances):
            chunks.append(RetrievedChunk(
                chunk_id=cid,
                content=doc,
                source=meta.get("source", "unknown"),
                score=round(1 - dist, 4),
                department=meta.get("department", ""),
            ))
        return chunks

    def ping(self) -> bool:
        """Check that the ChromaDB server is reachable."""
        try:
            self._client.heartbeat()
            return True
        except Exception as exc:
            logger.warning("retriever: ping failed — %s", exc)
            return False
