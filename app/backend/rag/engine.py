"""
rag/engine.py
-------------
Top-level RAG orchestrator.

Wires together Embedder → Retriever → Generator.
This is the only RAG class that route handlers talk to directly.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import List

from rag.retriever import Retriever, RetrievedChunk
from rag.generator import Generator
from rag.embedder import Embedder
from rag.errors import DependencyUnavailable
from config import settings
from metrics.prometheus import RAG_QUERY_DURATION, RAG_ERRORS
from preprocessing.pdf_to_structured import match_ue_from_query

logger = logging.getLogger(__name__)


@dataclass
class RAGResult:
    """Full output of a RAG query returned to the route handler."""
    answer: str
    chunks: List[RetrievedChunk] = field(default_factory=list)


class RAGEngine:
    """
    Orchestrates the Embed → Retrieve → Generate pipeline.

    Attributes:
        embedder  (Embedder):  Converts text to dense vectors.
        retriever (Retriever): Fetches top-K chunks from ChromaDB.
        generator (Generator): Calls Ollama to produce the final answer.
    """

    def __init__(self) -> None:
        """Initialise all sub-components. Called once at app startup."""
        logger.info("initialising RAGEngine")
        self.embedder = Embedder()
        self.retriever = Retriever()
        self.generator = Generator()
        logger.info("RAGEngine ready")

    async def query(self, question: str, department: str | None = None) -> RAGResult:
        """
        Run the full RAG pipeline for a user question.

        Steps:
          1. Embed the question into a dense vector
          2. Retrieve the top-K most similar document chunks
          3. Generate a grounded answer via Ollama

        Args:
            question:   Natural-language question from the user.
            department: Optional department to scope the search.

        Returns:
            RAGResult: Generated answer and the source chunks used.

        Raises:
            ValueError:            If question is empty or too long.
            DependencyUnavailable: If ChromaDB or Ollama fails or is too slow.
            RuntimeError:          If the embedding step fails.
        """
        if not question.strip():
            raise ValueError("question must not be empty")
        if len(question) > 2000:
            raise ValueError("question exceeds maximum length of 2000 characters")

        start = time.perf_counter()

        # ── Steps 1-2: Embed + Retrieve ───────────────────────────────
        # Both calls are blocking (torch, chromadb over requests). They run in a
        # worker thread with a wall-clock budget: a ChromaDB that stops answering
        # must neither freeze the event loop (probes time out, kubelet kills the
        # pod, the request is never counted) nor hold the client indefinitely.
        try:
            chunks = await asyncio.wait_for(
                asyncio.to_thread(self._embed_and_retrieve, question, department),
                timeout=settings.retrieval_timeout_s,
            )
        except asyncio.TimeoutError as exc:
            RAG_ERRORS.labels(component="retriever").inc()
            raise DependencyUnavailable(
                "chromadb", f"no answer within {settings.retrieval_timeout_s:.0f} s"
            ) from exc

        # ── Step 3: Generate ──────────────────────────────────────────
        logger.info("engine.query: generating answer")
        try:
            answer = await self.generator.generate(question=question, chunks=chunks)
        except Exception as exc:
            RAG_ERRORS.labels(component="generator").inc()
            raise DependencyUnavailable("ollama", str(exc)) from exc

        # Record total RAG pipeline duration
        RAG_QUERY_DURATION.observe(time.perf_counter() - start)

        logger.info(
            "engine.query: complete — chunks=%d duration=%.2fs",
            len(chunks),
            time.perf_counter() - start,
        )

        return RAGResult(answer=answer, chunks=chunks)

    def _embed_and_retrieve(self, question: str, department: str | None) -> List[RetrievedChunk]:
        """Blocking part of the pipeline; runs in a worker thread (see query())."""
        logger.info("engine.query: embedding question")
        try:
            query_vector = self.embedder.embed_one(question)
        except Exception as exc:
            RAG_ERRORS.labels(component="embedder").inc()
            raise RuntimeError("embedding step failed") from exc

        ue_code = match_ue_from_query(question)
        if ue_code:
            logger.info("engine.query: detected UE code %s in query", ue_code)

        logger.info("engine.query: retrieving chunks (dept=%s, ue=%s)", department or "all", ue_code or "none")
        try:
            return self.retriever.retrieve(
                query_vector=query_vector,
                department=department,
                ue_code=ue_code,
            )
        except Exception as exc:
            RAG_ERRORS.labels(component="retriever").inc()
            raise DependencyUnavailable("chromadb", str(exc)) from exc

    async def is_ready(self) -> bool:
        """
        Check whether all downstream services are reachable.

        Returns:
            bool: True only if both ChromaDB and Ollama respond.
        """
        try:
            return self.retriever.ping() and await self.generator.ping()
        except Exception as exc:
            logger.warning("engine.is_ready: check failed — %s", exc)
            return False
