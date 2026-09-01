"""
rag/embedder.py
---------------
Thin wrapper around sentence-transformers for generating dense embeddings.

The Embedder converts a list of text strings into a list of float vectors.
It is used by both the Indexer (offline, for document chunks) and the
Retriever (online, for user queries).

Model: all-MiniLM-L6-v2 (default) — 384-dimensional, fast, runs on CPU.
Override via the EMBED_MODEL environment variable in .env.
"""

import logging
import time
from typing import List

from sentence_transformers import SentenceTransformer

from config import settings
from metrics.prometheus import RAG_ERRORS

logger = logging.getLogger(__name__)

# Number of texts encoded in one forward pass — prevents OOM on large batches
DEFAULT_BATCH_SIZE = 32


class Embedder:
    """
    Encapsulates the sentence-transformers embedding model.

    The model is loaded once at construction time and reused for every
    embed() call to avoid repeated disk I/O and GPU/CPU warm-up.

    Attributes:
        model_name (str):  HuggingFace model identifier.
        _model:            Loaded SentenceTransformer instance.
    """

    def __init__(self, model_name: str | None = None) -> None:
        """
        Initialise the embedder by loading the sentence-transformers model.

        Args:
            model_name: HuggingFace model identifier. Falls back to the
                        EMBED_MODEL setting (default: all-MiniLM-L6-v2).
        """
        self.model_name = model_name or settings.embed_model
        logger.info("embedder: loading model '%s'", self.model_name)
        # Load the model once — stays in memory for all subsequent calls
        self._model = SentenceTransformer(self.model_name)
        logger.info("embedder: model loaded (dim=%d)", self.dimension)

    def embed(self, texts: List[str], batch_size: int = DEFAULT_BATCH_SIZE) -> List[List[float]]:
        """
        Encode a batch of texts into dense float vectors.

        Args:
            texts:      Non-empty list of strings to embed.
            batch_size: Number of texts per forward pass (default 32).

        Returns:
            A list of embedding vectors — one per input text.

        Raises:
            ValueError:   If texts is empty.
            RuntimeError: If the model is not loaded or encoding fails.
        """
        if not texts:
            raise ValueError("texts must not be empty")
        if self._model is None:
            raise RuntimeError("embedding model is not loaded")

        logger.debug("embedder: embedding %d text(s) batch_size=%d", len(texts), batch_size)

        start = time.perf_counter()
        try:
            # batch_size controls memory usage during large indexation runs
            vectors = self._model.encode(
                texts,
                convert_to_numpy=True,
                batch_size=batch_size,
                show_progress_bar=False,
            ).tolist()
        except Exception as exc:
            logger.exception("embedder: encoding failed — %s", exc)
            RAG_ERRORS.labels(component="embedder").inc()
            raise RuntimeError("embedding failed") from exc

        logger.debug("embedder: encoded in %.3fs", time.perf_counter() - start)
        return vectors

    def embed_one(self, text: str) -> List[float]:
        """
        Convenience method — embed a single string and return its vector.

        Args:
            text: The string to embed.

        Returns:
            A single embedding vector (list of floats).
        """
        return self.embed([text])[0]

    @property
    def dimension(self) -> int:
        """
        Return the dimensionality of the embedding vectors.

        Returns:
            Integer dimension (384 for all-MiniLM-L6-v2).
        """
        return self._model.get_sentence_embedding_dimension()
