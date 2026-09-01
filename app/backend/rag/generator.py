"""
rag/generator.py
----------------
LLM response generation via the Ollama REST API.

The Generator takes the user's question and the retrieved document chunks,
builds a prompt, sends it to Ollama (Mistral 7B), and returns the generated
answer as a plain string.

No fine-tuning — inference only.
"""

import logging
import time
from typing import List

import httpx

from config import settings
from rag.retriever import RetrievedChunk
from metrics.prometheus import RAG_GENERATION_DURATION, RAG_ERRORS

logger = logging.getLogger(__name__)

OLLAMA_GENERATE_PATH = "/api/generate"

SYSTEM_PROMPT = (
    "You are a helpful assistant. "
    "Answer the user's question using ONLY the context provided below. "
    "If the answer is not in the context, say so honestly. "
    "Do not make up information."
)


class Generator:
    """
    Calls the Ollama REST API to generate a grounded answer.

    Attributes:
        ollama_url (str):  Base URL of the Ollama service.
        model      (str):  Model name to use for generation.
        _client:           Reusable async HTTP client.
    """

    def __init__(self) -> None:
        """Initialise the HTTP client pointing at the Ollama service."""
        self.ollama_url = settings.ollama_url
        self.model = settings.ollama_model
        # Reuse a single async client for connection pooling
        self._client = httpx.AsyncClient(
            base_url=self.ollama_url,
            timeout=120.0,  # LLM generation can be slow on CPU
        )
        logger.info("generator: ready (model=%s, url=%s)", self.model, self.ollama_url)

    async def generate(self, question: str, chunks: List[RetrievedChunk]) -> str:
        """
        Generate a grounded answer from a question and retrieved chunks.

        Args:
            question: The user's natural-language question.
            chunks:   Retrieved document chunks used as context.

        Returns:
            str: The LLM's generated answer.

        Raises:
            RuntimeError: If Ollama times out or returns an error.
        """
        prompt = self._build_prompt(question, chunks)
        logger.debug(
            "generator: sending prompt to Ollama (chars=%d chunks=%d)",
            len(prompt),
            len(chunks),
        )

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if settings.ollama_num_predict > 0:
            payload["options"] = {"num_predict": settings.ollama_num_predict}

        start = time.perf_counter()
        try:
            response = await self._client.post(OLLAMA_GENERATE_PATH, json=payload)
            response.raise_for_status()
            answer = response.json()["response"]

        except httpx.TimeoutException as exc:
            RAG_ERRORS.labels(component="generator").inc()
            logger.error("generator: Ollama request timed out after %.1fs", time.perf_counter() - start)
            raise RuntimeError("Ollama request timed out") from exc

        except httpx.HTTPStatusError as exc:
            RAG_ERRORS.labels(component="generator").inc()
            logger.error("generator: Ollama returned HTTP %s", exc.response.status_code)
            raise RuntimeError(f"Ollama returned error {exc.response.status_code}") from exc

        except Exception as exc:
            RAG_ERRORS.labels(component="generator").inc()
            logger.exception("generator: unexpected error — %s", exc)
            raise RuntimeError("generation failed unexpectedly") from exc

        duration = time.perf_counter() - start
        RAG_GENERATION_DURATION.observe(duration)
        logger.info("generator: response received in %.2fs", duration)

        return answer

    def _build_prompt(self, question: str, chunks: List[RetrievedChunk]) -> str:
        """
        Assemble the final prompt sent to the LLM.

        Injects retrieved chunks as numbered context blocks before the question.

        Args:
            question: The user's question.
            chunks:   Retrieved chunks to inject as context.

        Returns:
            str: Fully assembled prompt string.
        """
        context_blocks = []
        for i, chunk in enumerate(chunks, start=1):
            # Number each source block for easier tracing in logs
            block = f"[{i}] Source: {chunk.source}\n{chunk.content}"
            context_blocks.append(block)

        context_text = (
            "\n---\n".join(context_blocks)
            if context_blocks
            else "No context available."
        )

        return (
            f"{SYSTEM_PROMPT}\n\n"
            f"[CONTEXT]\n{context_text}\n\n"
            f"[QUESTION]\n{question}\n\n"
            f"[ANSWER]\n"
        )

    async def close(self) -> None:
        """Close the underlying HTTP client — call during app shutdown."""
        await self._client.aclose()
        logger.info("generator: HTTP client closed")

    async def ping(self) -> bool:
        """
        Check that the Ollama service is reachable.

        Returns:
            bool: True if Ollama responds with 200, False otherwise.
        """
        try:
            r = await self._client.get("/api/tags")
            return r.status_code == 200
        except Exception as exc:
            logger.warning("generator: ping failed — %s", exc)
            return False
