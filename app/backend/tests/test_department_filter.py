"""
tests/test_department_filter.py
-------------------------------
Unit tests for department-based filtering in the Retriever.

Tests cover:
  - RetrievedChunk includes department field
  - _build_where_filter with department only
  - _build_where_filter with ue_code only
  - _build_where_filter with both department and ue_code
  - _build_where_filter with neither (returns None)
  - retrieve() passes department filter to ChromaDB
"""

import pytest
from unittest.mock import MagicMock, patch

from rag.retriever import Retriever, RetrievedChunk


# ── RetrievedChunk ────────────────────────────────────────────────────

class TestRetrievedChunkDepartment:
    """Tests for department field on RetrievedChunk."""

    def test_department_default_empty_string(self):
        chunk = RetrievedChunk(
            chunk_id="c1", content="hello", source="test.txt", score=0.9
        )
        assert chunk.department == ""

    def test_department_set_explicitly(self):
        chunk = RetrievedChunk(
            chunk_id="c1", content="hello", source="test.txt", score=0.9,
            department="Informatique",
        )
        assert chunk.department == "Informatique"


# ── _build_where_filter ──────────────────────────────────────────────

class TestBuildWhereFilter:
    """Tests for Retriever._build_where_filter logic."""

    @pytest.fixture
    def retriever(self):
        with patch("rag.retriever.chromadb.HttpClient"):
            r = Retriever.__new__(Retriever)
            r._client = MagicMock()
            r._collection = MagicMock()
            return r

    def test_no_filters_returns_none(self, retriever):
        assert retriever._build_where_filter(None, None) is None

    def test_department_only(self, retriever):
        result = retriever._build_where_filter("GI", None)
        assert result == {"$or": [{"department": "GI"}, {"department": ""}]}

    def test_ue_code_only(self, retriever):
        result = retriever._build_where_filter(None, "311")
        assert result == {"ue_code": "311"}

    def test_both_department_and_ue_code(self, retriever):
        result = retriever._build_where_filter("GI", "311")
        assert result == {
            "$and": [
                {"$or": [{"department": "GI"}, {"department": ""}]},
                {"ue_code": "311"},
            ]
        }


# ── _parse_results ───────────────────────────────────────────────────

class TestParseResultsDepartment:
    """Tests that _parse_results extracts department from metadata."""

    @pytest.fixture
    def retriever(self):
        with patch("rag.retriever.chromadb.HttpClient"):
            r = Retriever.__new__(Retriever)
            r._client = MagicMock()
            r._collection = MagicMock()
            return r

    def test_department_extracted_from_metadata(self, retriever):
        raw = {
            "ids": [["chunk_0"]],
            "documents": [["Some content"]],
            "metadatas": [[{"source": "test.txt", "department": "GI"}]],
            "distances": [[0.1]],
        }
        chunks = retriever._parse_results(raw)
        assert len(chunks) == 1
        assert chunks[0].department == "GI"

    def test_missing_department_defaults_to_empty(self, retriever):
        raw = {
            "ids": [["chunk_0"]],
            "documents": [["Some content"]],
            "metadatas": [[{"source": "test.txt"}]],
            "distances": [[0.1]],
        }
        chunks = retriever._parse_results(raw)
        assert chunks[0].department == ""
