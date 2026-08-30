"""
rag/indexer.py
--------------
Document loading, chunking, and vector storage pipeline.

Scans /data/documents, loads PDF, TXT, MD, and DOCX files, splits them into
overlapping chunks, generates embeddings, and upserts into ChromaDB.
Runs automatically at startup and can be triggered via POST /api/index.
"""

import logging
import time
from pathlib import Path
from typing import List

import chromadb
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings
from rag.embedder import Embedder
from metrics.prometheus import DOCUMENTS_INDEXED, INDEXATION_RUNS, RAG_ERRORS
from preprocessing.pdf_to_structured import build_structured_chunks

logger = logging.getLogger(__name__)

# All supported file extensions
SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}


class DocumentChunk:
    """A single chunk produced by splitting a source document."""

    def __init__(
        self,
        text: str,
        source: str,
        chunk_id: str,
        department: str = "",
        ue_code: str = "",
        ue_name: str = "",
    ) -> None:
        self.text = text
        self.source = source
        self.chunk_id = chunk_id
        self.department = department
        self.ue_code = ue_code
        self.ue_name = ue_name

    def __repr__(self) -> str:
        return (
            f"DocumentChunk(source={self.source!r}, dept={self.department!r}, "
            f"ue={self.ue_code or '-'}, len={len(self.text)})"
        )


class Indexer:
    """
    Orchestrates the full document ingestion pipeline.

    Supported formats: PDF, TXT, MD, DOCX

    Attributes:
        docs_path    (Path):     Directory containing source documents.
        embedder     (Embedder): Produces embedding vectors from text.
        chunk_size   (int):      Max characters per chunk.
        chunk_overlap(int):      Overlap between consecutive chunks.
    """

    def __init__(self) -> None:
        self.docs_path = Path(settings.docs_path)
        self.embedder = Embedder()
        self.chunk_size = settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap

        # Connect to ChromaDB and obtain or create the target collection
        self._chroma_client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )
        self._collection = self._chroma_client.get_or_create_collection(
            settings.chroma_collection
        )

    async def index_files(self, file_paths: List[Path]) -> None:
        """Index only the specified files (incremental indexing)."""
        start = time.perf_counter()
        valid = [f for f in file_paths if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS]
        if not valid:
            logger.warning("indexer: no valid files to index")
            return

        logger.info("indexer: incremental — indexing %d file(s)", len(valid))
        all_chunks: List[DocumentChunk] = []
        for file_path in valid:
            try:
                chunks = self._process_file(file_path)
                all_chunks.extend(chunks)
                logger.info("indexer: %s → %d chunks", file_path.name, len(chunks))
            except Exception as exc:
                RAG_ERRORS.labels(component="indexer").inc()
                logger.warning("indexer: skipping %s — %s", file_path.name, exc)

        if all_chunks:
            await self._upsert_to_chroma(all_chunks)
            DOCUMENTS_INDEXED.set(self.get_chunk_count())

        logger.info(
            "indexer: incremental done — %d chunks in %.2fs",
            len(all_chunks),
            time.perf_counter() - start,
        )

    async def run(self) -> None:
        """
        Execute the full ingestion pipeline end-to-end.

        Raises:
            FileNotFoundError: If docs_path does not exist.
        """
        if not self.docs_path.exists():
            raise FileNotFoundError(f"docs_path not found: {self.docs_path}")

        start = time.perf_counter()
        files = self._discover_files()
        logger.info("indexer: found %d file(s) to index", len(files))

        if not files:
            logger.warning("indexer: no supported files found in %s", self.docs_path)
            logger.warning("indexer: supported formats: %s", SUPPORTED_EXTENSIONS)
            return

        all_chunks: List[DocumentChunk] = []
        for file_path in files:
            try:
                chunks = self._process_file(file_path)
                all_chunks.extend(chunks)
                logger.info("indexer: %s → %d chunks", file_path.name, len(chunks))
            except Exception as exc:
                RAG_ERRORS.labels(component="indexer").inc()
                logger.warning("indexer: skipping %s — %s", file_path.name, exc)

        if all_chunks:
            await self._upsert_to_chroma(all_chunks)
            DOCUMENTS_INDEXED.set(self.get_chunk_count())
            INDEXATION_RUNS.labels(status="success").inc()
        else:
            logger.warning("indexer: no chunks produced — nothing indexed")
            INDEXATION_RUNS.labels(status="success").inc()

        logger.info(
            "indexer: done — %d chunks indexed in %.2fs",
            len(all_chunks),
            time.perf_counter() - start,
        )

    def get_chunk_count(self) -> int:
        """Return the number of chunks currently stored in ChromaDB."""
        return self._collection.count()

    # ── Private helpers ───────────────────────────────────────────────

    def _discover_files(self) -> List[Path]:
        """Return all supported files in docs_path and its subdirectories, sorted by name."""
        return sorted(
            f for f in self.docs_path.rglob("*")
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        )

    def _detect_department(self, file_path: Path) -> str:
        """Detect corresponding department from the file's parent folder."""
        relative = file_path.relative_to(self.docs_path)
        if len(relative.parts) > 1:
            return relative.parts[0]
        return ""

    def _process_file(self, file_path: Path) -> List[DocumentChunk]:
        """Load and chunk a single file based on its extension."""
        suffix = file_path.suffix.lower()
        department = self._detect_department(file_path)

        # ── Structured extraction for PDFs (UE/ECUE) ─────────────
        if suffix == ".pdf":
            structured = self._try_structured_pdf(file_path, department)
            if structured:
                logger.info(
                    "indexer: %s → %d structured UE chunks",
                    file_path.name, len(structured),
                )
                # Also generate regular chunks so non-UE content is indexed
                text = self._load_pdf(file_path)
                if text.strip():
                    regular = self._split_text(text, source=file_path.name, department=department)
                    return structured + regular
                return structured

        if suffix == ".pdf":
            text = self._load_pdf(file_path)
        elif suffix in {".txt", ".md"}:
            text = self._load_txt(file_path)
        elif suffix == ".docx":
            text = self._load_docx(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_path.suffix}")

        # Guard against empty documents
        if not text.strip():
            logger.warning("indexer: %s produced no text — skipping", file_path.name)
            return []

        return self._split_text(text, source=file_path.name, department=department)

    def _try_structured_pdf(self, file_path: Path, department: str) -> List[DocumentChunk]:
        """Attempt structured UE/ECUE extraction from a PDF. Returns [] if none found."""
        try:
            structured_data = build_structured_chunks(file_path)
        except Exception as exc:
            logger.warning(
                "indexer: structured extraction failed for %s — %s", file_path.name, exc
            )
            return []

        if not structured_data:
            return []

        chunks = []
        for i, item in enumerate(structured_data):
            chunk_id = (
                f"{department}/{file_path.name}::ue_{item['ue_code']}" if department
                else f"{file_path.name}::ue_{item['ue_code']}"
            )
            chunks.append(DocumentChunk(
                text=item["text"],
                source=file_path.name,
                chunk_id=chunk_id,
                department=department,
                ue_code=item["ue_code"],
                ue_name=item["ue_name"],
            ))

        logger.info(
            "indexer: structured extraction found %d UE(s) in %s: %s",
            len(chunks),
            file_path.name,
            ", ".join(f"UE {c.ue_code}" for c in chunks),
        )
        return chunks

    def _load_pdf(self, file_path: Path) -> str:
        """Extract and join text from all pages of a PDF."""
        loader = PyPDFLoader(str(file_path))
        pages = loader.load()
        return "\n".join(p.page_content for p in pages)

    def _load_txt(self, file_path: Path) -> str:
        """Read a plain-text or Markdown file as UTF-8."""
        return file_path.read_text(encoding="utf-8")

    def _load_docx(self, file_path: Path) -> str:
        """
        Extract text from a Word document (.docx).

        Reads all paragraphs and joins them with newlines.
        Skips empty paragraphs automatically.

        Args:
            file_path: Path to the .docx file.

        Returns:
            str: Full text content of the document.
        """
        from docx import Document
        doc = Document(str(file_path))

        # Extract text from paragraphs
        paragraphs = [
            paragraph.text
            for paragraph in doc.paragraphs
            if paragraph.text.strip()
        ]

        # Also extract text from tables
        table_texts = []
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        table_texts.append(cell.text.strip())

        all_text = paragraphs + table_texts
        return "\n".join(all_text)

    def _split_text(self, text: str, source: str, department: str = "") -> List[DocumentChunk]:
        """Split raw text into overlapping DocumentChunk objects."""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        pieces = splitter.split_text(text)
        prefix = f"{department}/{source}" if department else source
        return [
            DocumentChunk(
                text=t,
                source=source,
                chunk_id=f"{prefix}::chunk_{i}",
                department=department,
            )
            for i, t in enumerate(pieces)
        ]

    async def _upsert_to_chroma(self, chunks: List[DocumentChunk]) -> None:
        """Embed all chunks and upsert them into ChromaDB."""
        texts = [c.text for c in chunks]
        ids = [c.chunk_id for c in chunks]
        metadatas = []
        for c in chunks:
            meta = {"source": c.source, "department": c.department}
            if c.ue_code:
                meta["ue_code"] = c.ue_code
                meta["ue_name"] = c.ue_name
            metadatas.append(meta)

        logger.info(
            "indexer: embedding %d chunks (collection had %d before)",
            len(chunks),
            self.get_chunk_count(),
        )

        start = time.perf_counter()
        vectors = self.embedder.embed(texts)
        logger.info("indexer: embedding done in %.2fs", time.perf_counter() - start)

        start = time.perf_counter()
        self._collection.upsert(
            ids=ids,
            embeddings=vectors,
            documents=texts,
            metadatas=metadatas,
        )
        logger.info("indexer: upsert done in %.2fs", time.perf_counter() - start)
