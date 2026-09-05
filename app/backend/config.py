"""
config.py
---------
Centralised application settings loaded from environment variables.
Uses pydantic-settings so every value can be overridden via a .env file
or real environment variables without changing code.

Usage:
    from config import settings
    print(settings.chroma_host)
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    All tuneable parameters for the RAG application.

    Pydantic reads these from environment variables (case-insensitive).
    Defaults are safe for local Docker Compose development.
    """

    # ── ChromaDB ──────────────────────────────────────────────────────────
    chroma_host: str = "chromadb"
    """Hostname of the ChromaDB container (Docker Compose service name)."""

    chroma_port: int = 8001
    """Port on which ChromaDB listens."""

    chroma_collection: str = "rag_documents"
    """Name of the ChromaDB collection that stores document embeddings."""

    # ── Ollama / LLM ──────────────────────────────────────────────────────
    ollama_url: str = "http://ollama:11434"
    """Base URL of the Ollama REST API."""

    ollama_model: str = "mistral"
    """Name of the model to pull and use for generation (e.g. mistral, llama3)."""

    chroma_timeout_s: float = 5.0
    """Socket timeout of every HTTP call to ChromaDB. The chromadb 0.5 client sets none:
    without it, a partitioned ChromaDB made each query hang until the pod was killed."""

    retrieval_timeout_s: float = 10.0
    """Wall-clock budget of the embed + retrieve step of a query. Past it, the API
    answers 503 instead of waiting (ADR 0003, retour d'expérience)."""

    engine_init_timeout_s: float = 60.0
    """Budget for the lazy creation of the RAG engine (model load + ChromaDB connection)
    on the first query of a pod. Past it, that query answers 503."""

    ollama_num_predict: int = 0
    """Maximum number of generated tokens (0 = model default). Bounding the answer
    length bounds the latency, which the latency SLO depends on."""

    # ── Documents & Embeddings ────────────────────────────────────────────
    docs_path: str = "/data/documents"
    """Path (inside the container) where source documents are stored."""

    embed_model: str = "all-MiniLM-L6-v2"
    """Sentence-transformers model name used to create embeddings."""

    top_k: int = 5
    """Number of most-similar chunks to retrieve from ChromaDB per query."""

    chunk_size: int = 500
    """Maximum number of characters per document chunk."""

    chunk_overlap: int = 50
    """Number of characters shared between consecutive chunks to preserve context."""

    auto_index_on_startup: bool = False
    """Whether to run document indexation automatically during app startup."""

    # ── API ───────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    """Host address uvicorn binds to."""

    api_port: int = 8000
    """Port uvicorn listens on."""

    log_level: str = "info"
    """Uvicorn / application log level (debug | info | warning | error)."""

    # ── Security ──────────────────────────────────────────────────────────
    api_key: str = "changeme-rag-secret-2026"
    """API key required in X-API-Key header for protected endpoints."""

    # ── Pydantic config ───────────────────────────────────────────────────
    model_config = SettingsConfigDict(
        env_file=".env",          # load from .env if present
        env_file_encoding="utf-8",
        case_sensitive=False,     # CHROMA_HOST == chroma_host
        extra="ignore",           # ignore env vars not declared here (e.g. GRAFANA_PASSWORD)
    )


# Singleton — import this object everywhere instead of instantiating Settings()
settings = Settings()
