"""
rag/errors.py
-------------
Errors shared by the RAG pipeline and the API routes.

Kept free of heavy imports (chromadb, torch) so routes and tests can use them cheaply.
"""


class DependencyUnavailable(RuntimeError):
    """A downstream service (ChromaDB, Ollama) failed or did not answer in time.

    The API turns it into HTTP 503: the request fails fast and visibly, so the
    availability SLI counts it, instead of hanging until the client gives up.
    """

    def __init__(self, dependency: str, reason: str = "") -> None:
        self.dependency = dependency
        self.reason = reason
        super().__init__(f"{dependency} unavailable" + (f": {reason}" if reason else ""))
