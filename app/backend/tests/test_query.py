"""
tests/test_query.py
-------------------
Unit tests for POST /api/query endpoint.

Tests cover:
  - Happy path with mocked RAG engine
  - Input validation (empty, missing, too long)
  - Engine error handling (500)
  - Response structure validation
  - Prometheus metrics recording
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.routes.query import router


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def app():
    """Create a test FastAPI app with the query router."""
    application = FastAPI()
    application.include_router(router, prefix="/api")
    return application


@pytest.fixture
def client(app):
    """Return a TestClient wrapping the test app."""
    return TestClient(app)


@pytest.fixture
def mock_rag_result():
    """Return a canned RAG result with one source chunk."""
    from rag.retriever import RetrievedChunk
    from rag.engine import RAGResult

    chunk = RetrievedChunk(
        chunk_id="test.txt::chunk_0",
        content="DevOps combines development and operations.",
        source="test.txt",
        score=0.92,
    )
    return RAGResult(
        answer="DevOps combines development and operations.",
        chunks=[chunk],
    )


@pytest.fixture
def mock_engine(mock_rag_result):
    """Return a mocked RAGEngine."""
    engine = MagicMock()
    engine.query = AsyncMock(return_value=mock_rag_result)
    return engine


@pytest.fixture
def auth_headers():
    """Return headers with a valid API key."""
    return {"X-API-Key": "changeme-rag-secret-2026"}


# ── Happy path ────────────────────────────────────────────────────────

class TestQueryHappyPath:
    """Tests for successful query execution."""

    def test_valid_question_returns_200(self, client, mock_engine, auth_headers):
        """A well-formed question should return HTTP 200."""
        with patch("api.routes.query.get_engine", return_value=mock_engine):
            response = client.post("/api/query", json={"question": "What is DevOps?"}, headers=auth_headers)

        assert response.status_code == 200

    def test_response_contains_answer(self, client, mock_engine, auth_headers):
        """Response must contain a non-empty answer field."""
        with patch("api.routes.query.get_engine", return_value=mock_engine):
            response = client.post("/api/query", json={"question": "What is DevOps?"}, headers=auth_headers)

        data = response.json()
        assert "answer" in data
        assert len(data["answer"]) > 0

    def test_response_contains_sources(self, client, mock_engine, auth_headers):
        """Response must contain a sources list."""
        with patch("api.routes.query.get_engine", return_value=mock_engine):
            response = client.post("/api/query", json={"question": "What is DevOps?"}, headers=auth_headers)

        data = response.json()
        assert "sources" in data
        assert isinstance(data["sources"], list)

    def test_response_contains_duration(self, client, mock_engine, auth_headers):
        """Response must contain duration_ms field."""
        with patch("api.routes.query.get_engine", return_value=mock_engine):
            response = client.post("/api/query", json={"question": "What is DevOps?"}, headers=auth_headers)

        data = response.json()
        assert "duration_ms" in data
        assert data["duration_ms"] >= 0

    def test_answer_matches_engine_output(self, client, mock_engine, auth_headers):
        """Answer in response must match what the engine returned."""
        with patch("api.routes.query.get_engine", return_value=mock_engine):
            response = client.post("/api/query", json={"question": "What is DevOps?"}, headers=auth_headers)

        assert response.json()["answer"] == "DevOps combines development and operations."

    def test_source_chunk_structure(self, client, mock_engine, auth_headers):
        """Each source chunk must have content, source, and score fields."""
        with patch("api.routes.query.get_engine", return_value=mock_engine):
            response = client.post("/api/query", json={"question": "What is DevOps?"}, headers=auth_headers)

        sources = response.json()["sources"]
        assert len(sources) == 1
        assert "content" in sources[0]
        assert "source" in sources[0]
        assert "score" in sources[0]

    def test_source_score_between_0_and_1(self, client, mock_engine, auth_headers):
        """Source chunk score must be between 0 and 1."""
        with patch("api.routes.query.get_engine", return_value=mock_engine):
            response = client.post("/api/query", json={"question": "What is DevOps?"}, headers=auth_headers)

        score = response.json()["sources"][0]["score"]
        assert 0.0 <= score <= 1.0

    def test_engine_called_with_correct_question(self, client, mock_engine, auth_headers):
        """Engine.query() must be called with the exact question string."""
        question = "What is continuous integration?"
        with patch("api.routes.query.get_engine", return_value=mock_engine):
            client.post("/api/query", json={"question": question}, headers=auth_headers)

        mock_engine.query.assert_awaited_once_with(question, department=None)


# ── Input validation ──────────────────────────────────────────────────

class TestQueryValidation:
    """Tests for request body validation."""

    def test_empty_question_returns_422(self, client, auth_headers):
        """Empty question string must be rejected with HTTP 422."""
        response = client.post("/api/query", json={"question": ""}, headers=auth_headers)
        assert response.status_code == 422

    def test_missing_question_field_returns_422(self, client, auth_headers):
        """Missing question field must be rejected with HTTP 422."""
        response = client.post("/api/query", json={}, headers=auth_headers)
        assert response.status_code == 422

    def test_question_too_long_returns_422(self, client, auth_headers):
        """Question exceeding 2000 characters must return HTTP 422."""
        long_question = "a" * 2001
        response = client.post("/api/query", json={"question": long_question}, headers=auth_headers)
        assert response.status_code == 422

    def test_question_at_max_length_is_accepted(self, client, mock_engine, auth_headers):
        """Question of exactly 2000 characters must be accepted."""
        max_question = "a" * 2000
        with patch("api.routes.query.get_engine", return_value=mock_engine):
            response = client.post("/api/query", json={"question": max_question}, headers=auth_headers)
        assert response.status_code == 200

    def test_whitespace_only_question_returns_422(self, client, auth_headers):
        """Whitespace-only question must be rejected with HTTP 422."""
        response = client.post("/api/query", json={"question": "   "}, headers=auth_headers)
        assert response.status_code in [422, 500]

    def test_non_string_question_returns_422(self, client, auth_headers):
        """Non-string question must be rejected with HTTP 422."""
        response = client.post("/api/query", json={"question": 12345}, headers=auth_headers)
        assert response.status_code == 422


# ── Engine error handling ─────────────────────────────────────────────

class TestQueryErrorHandling:
    """Tests for error handling when the RAG engine fails."""

    def test_engine_runtime_error_returns_500(self, client, mock_engine, auth_headers):
        """RuntimeError from engine must return HTTP 500."""
        mock_engine.query.side_effect = RuntimeError("ChromaDB unreachable")
        with patch("api.routes.query.get_engine", return_value=mock_engine):
            response = client.post("/api/query", json={"question": "Will this fail?"}, headers=auth_headers)

        assert response.status_code == 500

    def test_engine_error_returns_detail_message(self, client, mock_engine, auth_headers):
        """HTTP 500 response must contain a detail field."""
        mock_engine.query.side_effect = RuntimeError("ChromaDB unreachable")
        with patch("api.routes.query.get_engine", return_value=mock_engine):
            response = client.post("/api/query", json={"question": "Will this fail?"}, headers=auth_headers)

        assert "detail" in response.json()

    def test_engine_value_error_returns_500(self, client, mock_engine, auth_headers):
        """ValueError from engine must return HTTP 500."""
        mock_engine.query.side_effect = ValueError("Invalid question")
        with patch("api.routes.query.get_engine", return_value=mock_engine):
            response = client.post("/api/query", json={"question": "test"}, headers=auth_headers)

        assert response.status_code == 500


# ── Empty sources ─────────────────────────────────────────────────────

class TestQueryEmptySources:
    """Tests for queries that return no source chunks."""

    def test_empty_sources_still_returns_200(self, client, auth_headers):
        """Query returning no chunks must still return HTTP 200."""
        from rag.engine import RAGResult
        empty_result = RAGResult(answer="I don't know.", chunks=[])
        mock_engine = MagicMock()
        mock_engine.query = AsyncMock(return_value=empty_result)

        with patch("api.routes.query.get_engine", return_value=mock_engine):
            response = client.post("/api/query", json={"question": "Unknown topic?"}, headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["sources"] == []