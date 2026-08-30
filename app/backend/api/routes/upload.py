"""
api/routes/upload.py
--------------------
POST /api/upload — Upload documents to the data/documents directory.
Accepts multiple files. Supported: PDF, DOCX, TXT, MD, CSV.
"""

import logging
from pathlib import Path
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from config import settings
from api.auth import verify_api_key
from rag.indexer import Indexer

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Upload"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


class UploadResponse(BaseModel):
    uploaded: List[str]
    message: str
    indexing: bool


@router.post(
    "/upload",
    response_model=UploadResponse,
    summary="Upload documents to the knowledge base",
)
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    _key: str = Depends(verify_api_key),
) -> UploadResponse:
    """
    Upload one or more documents to /data/documents.

    After uploading, trigger POST /api/index to re-index.
    """
    docs_dir = Path(settings.docs_path)
    docs_dir.mkdir(parents=True, exist_ok=True)

    uploaded: List[str] = []
    saved_paths: List[Path] = []

    for f in files:
        # Validate extension
        suffix = Path(f.filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            )

        # Sanitize filename — keep only the basename
        safe_name = Path(f.filename).name

        # Read and validate size
        content = await f.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File '{safe_name}' exceeds 50 MB limit.",
            )

        dest = docs_dir / safe_name
        dest.write_bytes(content)
        uploaded.append(safe_name)
        saved_paths.append(dest)
        logger.info("uploaded document: %s (%d bytes)", safe_name, len(content))

    # Incremental indexation — only index the newly uploaded files
    indexing = False
    try:
        background_tasks.add_task(_index_uploaded_files, saved_paths)
        indexing = True
        logger.info("incremental indexation queued for %d file(s)", len(saved_paths))
    except Exception as exc:
        logger.warning("could not auto-trigger indexation: %s", exc)

    return UploadResponse(
        uploaded=uploaded,
        message=(
            f"{len(uploaded)} file(s) uploaded successfully."
            + (" Indexing started." if indexing else " Re-index manually to make them searchable.")
        ),
        indexing=indexing,
    )


async def _index_uploaded_files(file_paths: List[Path]) -> None:
    """Index only the uploaded files in the background."""
    try:
        logger.info("incremental indexation: starting for %d file(s)", len(file_paths))
        indexer = Indexer()
        await indexer.index_files(file_paths)
        logger.info("incremental indexation: complete")
    except Exception as exc:
        logger.exception("incremental indexation failed: %s", exc)
