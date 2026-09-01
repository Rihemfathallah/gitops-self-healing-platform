"""
tests/test_upload.py
--------------------
Unit tests for POST /api/upload endpoint.

Tests cover:
  - Happy path with valid file + API key
  - Missing API key → 401
  - Wrong API key → 403
  - Unsupported file extension → 400
  - File exceeding size limit → 413
  - Multiple files upload
"""

import io
import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.upload import router


# ── Fixtures ──────────────────────────────────────────────────────────

API_KEY = "changeme-rag-secret-2026"


@pytest.fixture
def app():
    """Create a test FastAPI app with the upload router."""
    application = FastAPI()
    application.include_router(router, prefix="/api")
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


def _make_file(name: str = "test.txt", content: bytes = b"Hello world"):
    """Build a tuple suitable for the files parameter of TestClient."""
    return ("files", (name, io.BytesIO(content), "application/octet-stream"))


# ── Authentication ────────────────────────────────────────────────────

class TestUploadAuth:
    """Tests for API key enforcement on the upload endpoint."""

    @patch("api.routes.upload.Indexer")
    def test_missing_api_key_returns_401(self, _mock_idx, client):
        response = client.post("/api/upload", files=[_make_file()])
        assert response.status_code == 401

    @patch("api.routes.upload.Indexer")
    def test_wrong_api_key_returns_403(self, _mock_idx, client):
        response = client.post(
            "/api/upload",
            files=[_make_file()],
            headers={"X-API-Key": "wrong-key"},
        )
        assert response.status_code == 403


# ── Validation ────────────────────────────────────────────────────────

class TestUploadValidation:
    """Tests for file validation rules."""

    @patch("api.routes.upload.Indexer")
    def test_unsupported_extension_returns_400(self, _mock_idx, client, tmp_path):
        with patch("api.routes.upload.settings") as mock_settings:
            mock_settings.docs_path = str(tmp_path)
            mock_settings.api_key = API_KEY
            response = client.post(
                "/api/upload",
                files=[_make_file("photo.png")],
                headers={"X-API-Key": API_KEY},
            )
        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]

    @patch("api.routes.upload.Indexer")
    def test_oversized_file_returns_413(self, _mock_idx, client, tmp_path):
        big_content = b"x" * (50 * 1024 * 1024 + 1)  # just over 50 MB
        with patch("api.routes.upload.settings") as mock_settings:
            mock_settings.docs_path = str(tmp_path)
            mock_settings.api_key = API_KEY
            response = client.post(
                "/api/upload",
                files=[_make_file("big.txt", big_content)],
                headers={"X-API-Key": API_KEY},
            )
        assert response.status_code == 413


# ── Happy path ────────────────────────────────────────────────────────

class TestUploadHappyPath:
    """Tests for successful uploads."""

    @patch("api.routes.upload.Indexer")
    def test_single_txt_upload_returns_200(self, _mock_idx, client, tmp_path):
        with patch("api.routes.upload.settings") as mock_settings:
            mock_settings.docs_path = str(tmp_path)
            mock_settings.api_key = API_KEY
            response = client.post(
                "/api/upload",
                files=[_make_file("doc.txt", b"Some content")],
                headers={"X-API-Key": API_KEY},
            )

        assert response.status_code == 200
        data = response.json()
        assert "doc.txt" in data["uploaded"]
        assert data["indexing"] is True

    @patch("api.routes.upload.Indexer")
    def test_multiple_files_upload(self, _mock_idx, client, tmp_path):
        with patch("api.routes.upload.settings") as mock_settings:
            mock_settings.docs_path = str(tmp_path)
            mock_settings.api_key = API_KEY
            response = client.post(
                "/api/upload",
                files=[
                    _make_file("a.txt", b"AAA"),
                    _make_file("b.md", b"# BBB"),
                ],
                headers={"X-API-Key": API_KEY},
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data["uploaded"]) == 2
        assert "2 file(s) uploaded successfully" in data["message"]

    @patch("api.routes.upload.Indexer")
    def test_pdf_upload_accepted(self, _mock_idx, client, tmp_path):
        with patch("api.routes.upload.settings") as mock_settings:
            mock_settings.docs_path = str(tmp_path)
            mock_settings.api_key = API_KEY
            response = client.post(
                "/api/upload",
                files=[_make_file("report.pdf", b"%PDF-1.4 fake")],
                headers={"X-API-Key": API_KEY},
            )

        assert response.status_code == 200
        assert "report.pdf" in response.json()["uploaded"]


# ── Response structure ────────────────────────────────────────────────

class TestUploadResponse:
    """Tests for response schema."""

    @patch("api.routes.upload.Indexer")
    def test_response_has_required_fields(self, _mock_idx, client, tmp_path):
        with patch("api.routes.upload.settings") as mock_settings:
            mock_settings.docs_path = str(tmp_path)
            mock_settings.api_key = API_KEY
            response = client.post(
                "/api/upload",
                files=[_make_file("notes.md", b"# Notes")],
                headers={"X-API-Key": API_KEY},
            )

        data = response.json()
        assert "uploaded" in data
        assert "message" in data
        assert "indexing" in data
        assert isinstance(data["uploaded"], list)
        assert isinstance(data["message"], str)
        assert isinstance(data["indexing"], bool)
