"""
tests/test_indexer.py
---------------------
Unit tests for the Indexer class (rag/indexer.py).

Tests cover:
  - File discovery with extension filtering
  - PDF and TXT loading
  - Text splitting into chunks
  - ChromaDB upsert pipeline
  - Edge cases: empty files, unsupported extensions, missing directory
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

from rag.indexer import Indexer, DocumentChunk, SUPPORTED_EXTENSIONS


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def docs_dir(tmp_path: Path) -> Path:
    """
    Create a temporary documents directory with sample files.

    Returns a temp dir with:
      - sample.txt  (valid)
      - notes.md    (valid)
      - image.png   (unsupported — must be ignored)
      - empty.txt   (empty — must be skipped)
    """
    docs = tmp_path / "documents"
    docs.mkdir()
    (docs / "sample.txt").write_text(
        "DevOps is the combination of development and operations practices. " * 20,
        encoding="utf-8",
    )
    (docs / "notes.md").write_text(
        "# RAG Notes\n\nRAG stands for Retrieval-Augmented Generation. " * 20,
        encoding="utf-8",
    )
    (docs / "image.png").write_bytes(b"\x89PNG\r\n")
    (docs / "empty.txt").write_text("", encoding="utf-8")
    return docs


@pytest.fixture
def indexer(docs_dir: Path) -> Indexer:
    """
    Return an Indexer with ChromaDB and Embedder mocked out.
    Points at the temp docs directory.
    """
    with patch("rag.indexer.chromadb.HttpClient") as mock_chroma, \
         patch("rag.indexer.Embedder") as mock_embedder_cls:

        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_chroma.return_value.get_or_create_collection.return_value = mock_collection

        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [[0.1] * 384]
        mock_embedder_cls.return_value = mock_embedder

        idx = Indexer()
        idx.docs_path = docs_dir
        yield idx


# ── _discover_files ───────────────────────────────────────────────────

class TestDiscoverFiles:
    """Tests for Indexer._discover_files()."""

    def test_returns_only_supported_extensions(self, indexer: Indexer):
        """Only PDF, TXT, and MD files must be returned."""
        files = indexer._discover_files()
        suffixes = {f.suffix for f in files}
        assert suffixes.issubset(SUPPORTED_EXTENSIONS)

    def test_ignores_unsupported_files(self, indexer: Indexer):
        """PNG and other unsupported files must not appear."""
        files = indexer._discover_files()
        names = [f.name for f in files]
        assert "image.png" not in names

    def test_returns_sorted_list(self, indexer: Indexer):
        """Files must be returned in alphabetical order."""
        files = indexer._discover_files()
        names = [f.name for f in files]
        assert names == sorted(names)

    def test_empty_directory_returns_empty_list(self, tmp_path: Path):
        """Empty directory must return an empty list."""
        with patch("rag.indexer.chromadb.HttpClient"), \
             patch("rag.indexer.Embedder"):
            idx = Indexer()
            idx.docs_path = tmp_path
            assert idx._discover_files() == []

    def test_returns_path_objects(self, indexer: Indexer):
        """All returned items must be Path objects."""
        files = indexer._discover_files()
        assert all(isinstance(f, Path) for f in files)


# ── _load_txt ─────────────────────────────────────────────────────────

class TestLoadTxt:
    """Tests for Indexer._load_txt()."""

    def test_reads_file_content(self, indexer: Indexer, docs_dir: Path):
        """Must return the full text content of the file."""
        content = indexer._load_txt(docs_dir / "sample.txt")
        assert "DevOps" in content

    def test_returns_string(self, indexer: Indexer, docs_dir: Path):
        """Return type must be str."""
        content = indexer._load_txt(docs_dir / "sample.txt")
        assert isinstance(content, str)

    def test_reads_markdown_file(self, indexer: Indexer, docs_dir: Path):
        """Must read .md files correctly."""
        content = indexer._load_txt(docs_dir / "notes.md")
        assert "RAG" in content

    def test_empty_file_returns_empty_string(self, indexer: Indexer, docs_dir: Path):
        """Empty file must return empty string."""
        content = indexer._load_txt(docs_dir / "empty.txt")
        assert content == ""


# ── _split_text ───────────────────────────────────────────────────────

class TestSplitText:
    """Tests for Indexer._split_text()."""

    def test_returns_list_of_document_chunks(self, indexer: Indexer):
        """Each item must be a DocumentChunk instance."""
        chunks = indexer._split_text("Hello world. " * 100, source="test.txt")
        assert all(isinstance(c, DocumentChunk) for c in chunks)

    def test_chunk_ids_are_unique(self, indexer: Indexer):
        """All chunk IDs within a document must be unique."""
        chunks = indexer._split_text("word " * 500, source="doc.txt")
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_chunk_id_format(self, indexer: Indexer):
        """Chunk IDs must follow the format source::chunk_N."""
        chunks = indexer._split_text("word " * 200, source="my_doc.txt")
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_id == f"my_doc.txt::chunk_{i}"

    def test_source_propagated_to_all_chunks(self, indexer: Indexer):
        """Every chunk's source attribute must match the passed source."""
        chunks = indexer._split_text("content " * 100, source="my_file.txt")
        assert all(c.source == "my_file.txt" for c in chunks)

    def test_empty_text_returns_empty_list(self, indexer: Indexer):
        """Empty text must return an empty list."""
        chunks = indexer._split_text("", source="empty.txt")
        assert chunks == []

    def test_chunk_text_is_not_empty(self, indexer: Indexer):
        """No chunk must have empty text content."""
        chunks = indexer._split_text("sentence. " * 100, source="test.txt")
        assert all(len(c.text) > 0 for c in chunks)


# ── _process_file ─────────────────────────────────────────────────────

class TestProcessFile:
    """Tests for Indexer._process_file()."""

    def test_processes_txt_file(self, indexer: Indexer, docs_dir: Path):
        """Must process .txt files and return chunks."""
        chunks = indexer._process_file(docs_dir / "sample.txt")
        assert isinstance(chunks, list)

    def test_processes_md_file(self, indexer: Indexer, docs_dir: Path):
        """Must process .md files and return chunks."""
        chunks = indexer._process_file(docs_dir / "notes.md")
        assert isinstance(chunks, list)

    def test_empty_file_returns_empty_list(self, indexer: Indexer, docs_dir: Path):
        """Empty file must return empty list."""
        chunks = indexer._process_file(docs_dir / "empty.txt")
        assert chunks == []

    def test_unsupported_extension_raises_value_error(self, indexer: Indexer, docs_dir: Path):
        """Unsupported file extension must raise ValueError."""
        with pytest.raises(ValueError):
            indexer._process_file(docs_dir / "image.png")


# ── Full pipeline run() ───────────────────────────────────────────────

class TestIndexerRun:
    """Integration-style tests for Indexer.run()."""

    @pytest.mark.asyncio
    async def test_run_completes_without_error(self, indexer: Indexer):
        """run() must complete without raising for a valid docs dir."""
        indexer.embedder.embed.return_value = [[0.1] * 384] * 10
        await indexer.run()

    @pytest.mark.asyncio
    async def test_run_raises_if_docs_path_missing(self, tmp_path: Path):
        """run() must raise FileNotFoundError if docs_path does not exist."""
        with patch("rag.indexer.chromadb.HttpClient"), \
             patch("rag.indexer.Embedder"):
            idx = Indexer()
            idx.docs_path = tmp_path / "nonexistent"
            with pytest.raises(FileNotFoundError):
                await idx.run()

    @pytest.mark.asyncio
    async def test_run_skips_corrupt_files_gracefully(
        self, indexer: Indexer, docs_dir: Path
    ):
        """
        run() must log a warning and continue if one file fails.
        It must not raise an exception.
        """
        (docs_dir / "corrupt.pdf").write_bytes(b"NOT A VALID PDF")
        indexer.embedder.embed.return_value = [[0.1] * 384] * 10
        await indexer.run()

    @pytest.mark.asyncio
    async def test_run_calls_upsert_when_chunks_exist(self, indexer: Indexer):
        """run() must call ChromaDB upsert when documents produce chunks."""
        indexer.embedder.embed.return_value = [[0.1] * 384] * 50
        await indexer.run()
        assert indexer._collection.upsert.called

    @pytest.mark.asyncio
    async def test_run_does_not_upsert_when_no_chunks(self, tmp_path: Path):
        """run() must NOT call upsert when no chunks are produced."""
        empty_dir = tmp_path / "empty_docs"
        empty_dir.mkdir()

        with patch("rag.indexer.chromadb.HttpClient") as mock_chroma, \
             patch("rag.indexer.Embedder"):
            mock_collection = MagicMock()
            mock_chroma.return_value.get_or_create_collection.return_value = mock_collection

            idx = Indexer()
            idx.docs_path = empty_dir
            await idx.run()

            mock_collection.upsert.assert_not_called()


# ── DocumentChunk ─────────────────────────────────────────────────────

class TestDocumentChunk:
    """Tests for DocumentChunk dataclass."""

    def test_repr_contains_source(self):
        """__repr__ must include the source filename."""
        chunk = DocumentChunk(text="hello", source="doc.txt", chunk_id="doc.txt::chunk_0")
        assert "doc.txt" in repr(chunk)

    def test_repr_contains_length(self):
        """__repr__ must include text length."""
        chunk = DocumentChunk(text="hello world", source="doc.txt", chunk_id="doc.txt::chunk_0")
        assert "11" in repr(chunk)

    def test_attributes_stored_correctly(self):
        """All attributes must be stored as passed."""
        chunk = DocumentChunk(text="content", source="file.txt", chunk_id="file.txt::chunk_0")
        assert chunk.text == "content"
        assert chunk.source == "file.txt"
        assert chunk.chunk_id == "file.txt::chunk_0"