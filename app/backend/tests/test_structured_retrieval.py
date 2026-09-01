"""
tests/test_structured_retrieval.py
-----------------------------------
Tests for the structured UE/ECUE preprocessing and retrieval pipeline.

Covers:
  - UE/ECUE extraction regex patterns
  - Semantic chunk generation
  - match_ue_from_query utility
  - Indexer structured PDF integration
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path

from preprocessing.pdf_to_structured import (
    extract_ue_ecue_from_pdf,
    ue_to_semantic_chunk,
    build_structured_chunks,
    match_ue_from_query,
    _clean_name,
)


# ── match_ue_from_query ──────────────────────────────────────────────

class TestMatchUeFromQuery:
    """Tests for the UE code extraction utility."""

    def test_explicit_ue_code(self):
        assert match_ue_from_query("Quels sont les ECUE de l'UE 311 ?") == "311"

    def test_ue_code_no_space(self):
        assert match_ue_from_query("Que contient UE311 ?") == "311"

    def test_ue_code_lowercase(self):
        assert match_ue_from_query("contenu de ue 421") == "421"

    def test_three_digit_ue_4xx(self):
        assert match_ue_from_query("UE 411 Informatique") == "411"

    def test_three_digit_ue(self):
        assert match_ue_from_query("détails de l'UE 521") == "521"

    def test_unité_keyword(self):
        assert match_ue_from_query("l'unité 311 mathématiques") == "311"

    def test_module_keyword(self):
        assert match_ue_from_query("le module 312") == "312"

    def test_no_ue_code(self):
        assert match_ue_from_query("quels cours en semestre 1 ?") is None

    def test_empty_query(self):
        assert match_ue_from_query("") is None

    def test_ecue_code_not_matched(self):
        """4+ digit codes should NOT be matched as UE codes."""
        assert match_ue_from_query("détails ECUE 3111") is None

    def test_invalid_prefix_not_matched(self):
        """Codes not starting with 3/4/5 should not match."""
        assert match_ue_from_query("UE 211") is None
        assert match_ue_from_query("UE 42") is None


# ── _clean_name ───────────────────────────────────────────────────────

class TestCleanName:
    def test_strips_trailing_numbers(self):
        assert _clean_name("Mathématiques I 6") == "Mathématiques I"

    def test_strips_trailing_dashes(self):
        assert _clean_name("Physique —") == "Physique"

    def test_preserves_normal_name(self):
        assert _clean_name("Algèbre linéaire") == "Algèbre linéaire"


# ── ue_to_semantic_chunk ─────────────────────────────────────────────

class TestUeToSemanticChunk:
    def test_basic_chunk(self):
        ue = {
            "ue_code": "311",
            "ue_name": "Mathématiques I",
            "ecues": [
                {"code": "3111", "name": "Mathématiques de l'ingénieur"},
                {"code": "3112", "name": "Probabilité et Processus Stochastiques"},
            ],
        }
        text = ue_to_semantic_chunk(ue)
        assert "UE 311 Mathématiques I" in text
        assert "3111 Mathématiques de l'ingénieur" in text
        assert "3112 Probabilité et Processus Stochastiques" in text
        assert "éléments constitutifs" in text

    def test_no_ecues(self):
        ue = {"ue_code": "999", "ue_name": "Test", "ecues": []}
        text = ue_to_semantic_chunk(ue)
        assert "aucun ECUE" in text

    def test_single_ecue(self):
        ue = {
            "ue_code": "411",
            "ue_name": "Informatique",
            "ecues": [{"code": "4111", "name": "Algorithmes"}],
        }
        text = ue_to_semantic_chunk(ue)
        assert "- 4111 Algorithmes" in text


# ── extract_ue_ecue_from_pdf (mocked pdfplumber) ─────────────────────

class TestExtractUeEcue:
    """Tests with mocked pdfplumber to verify regex extraction logic."""

    @patch("preprocessing.pdf_to_structured.pdfplumber")
    def test_extracts_ue_and_ecues(self, mock_pdfplumber):
        """Simulates a PDF with UE 311 and two ECUEs."""
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [
                ["311", "Mathématiques I", "6", "2"],
                ["3111", "Mathématiques de l'ingénieur", "3", "1"],
                ["3112", "Probabilité et Processus Stochastiques", "3", "1"],
            ]
        ]
        mock_page.extract_text.return_value = ""

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber.open.return_value = mock_pdf

        result = extract_ue_ecue_from_pdf("test.pdf")

        assert len(result) >= 1
        ue311 = next((ue for ue in result if ue["ue_code"] == "311"), None)
        assert ue311 is not None
        assert len(ue311["ecues"]) == 2
        ecue_codes = {e["code"] for e in ue311["ecues"]}
        assert "3111" in ecue_codes
        assert "3112" in ecue_codes

    @patch("preprocessing.pdf_to_structured.pdfplumber")
    def test_empty_pdf(self, mock_pdfplumber):
        """PDF with no text should return empty list."""
        mock_pdf = MagicMock()
        mock_pdf.pages = []
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber.open.return_value = mock_pdf

        result = extract_ue_ecue_from_pdf("empty.pdf")
        assert result == []

    @patch("preprocessing.pdf_to_structured.pdfplumber")
    def test_orphan_ecue(self, mock_pdfplumber):
        """ECUE without parent UE should not crash."""
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [["3999", "Orphan Module", "3", "1"]]
        ]
        mock_page.extract_text.return_value = ""

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber.open.return_value = mock_pdf

        # Should not raise
        result = extract_ue_ecue_from_pdf("orphan.pdf")
        assert isinstance(result, list)


# ── build_structured_chunks ──────────────────────────────────────────

class TestBuildStructuredChunks:
    @patch("preprocessing.pdf_to_structured.pdfplumber")
    def test_returns_chunk_dicts(self, mock_pdfplumber):
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [
                ["312", "Physique I", "6", "2"],
                ["3121", "Électromagnétisme", "3", "1"],
            ]
        ]
        mock_page.extract_text.return_value = ""

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdfplumber.open.return_value = mock_pdf

        chunks = build_structured_chunks("program.pdf")
        assert len(chunks) >= 1
        chunk = chunks[0]
        assert "text" in chunk
        assert "source" in chunk
        assert "ue_code" in chunk
        assert chunk["source"] == "program.pdf"


# ── Integration: Indexer with structured PDFs ─────────────────────────

class TestIndexerStructuredIntegration:
    """Verify that _try_structured_pdf produces DocumentChunks with ue metadata."""

    def test_try_structured_pdf_returns_chunks(self):
        with patch("rag.indexer.chromadb.HttpClient"), \
             patch("rag.indexer.Embedder"), \
             patch("rag.indexer.build_structured_chunks") as mock_build:

            mock_build.return_value = [
                {
                    "text": "UE 311 Mathématiques I contient...",
                    "source": "program.pdf",
                    "ue_code": "311",
                    "ue_name": "Mathématiques I",
                },
            ]

            from rag.indexer import Indexer
            idx = Indexer()
            chunks = idx._try_structured_pdf(Path("program.pdf"), department="indus")

            assert len(chunks) == 1
            assert chunks[0].ue_code == "311"
            assert chunks[0].ue_name == "Mathématiques I"
            assert chunks[0].department == "indus"

    def test_try_structured_pdf_returns_empty_on_no_ues(self):
        with patch("rag.indexer.chromadb.HttpClient"), \
             patch("rag.indexer.Embedder"), \
             patch("rag.indexer.build_structured_chunks") as mock_build:

            mock_build.return_value = []

            from rag.indexer import Indexer
            idx = Indexer()
            chunks = idx._try_structured_pdf(Path("text.pdf"), department="admin")

            assert chunks == []
