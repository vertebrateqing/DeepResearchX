"""
Document upload + RAG management API.

Endpoints for uploading PDF / Word / text files, ingesting them into a
per-session vector collection, and listing / deleting them.

Routes (mounted under /api in main.py):

    POST   /api/documents/upload?session_id=...   (multipart files=...)
    GET    /api/documents?session_id=...
    DELETE /api/documents/{doc_id}?session_id=...
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from api.models import (
    DocumentDeleteResponse,
    DocumentInfo,
    DocumentListResponse,
    DocumentUploadResponse,
)
from deep_research.config.settings import get_settings
from deep_research.rag.document_loader import SUPPORTED_EXTENSIONS, is_supported_file
from deep_research.rag.pipeline import collection_for_session, get_pipeline

logger = logging.getLogger(__name__)

documents_router = APIRouter(prefix="/documents", tags=["documents"])

# ---------------------------------------------------------------------------
# Limits — kept conservative for now; tune via settings later if needed
# ---------------------------------------------------------------------------
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB per file
MAX_FILES_PER_REQUEST = 10


def _session_uploads_dir(session_id: str) -> Path:
    """Return ./deep_research/data/sessions/{session_id}/uploads, creating it."""
    base = Path("./deep_research/data/sessions") / session_id / "uploads"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _validate_session(session_id: Optional[str]) -> str:
    if not session_id or not session_id.strip():
        raise HTTPException(status_code=400, detail="session_id is required")
    sid = session_id.strip()
    if any(c in sid for c in "/\\.."):
        raise HTTPException(status_code=400, detail="invalid session_id")
    return sid


@documents_router.post("/upload", response_model=DocumentUploadResponse)
async def upload_documents(
    session_id: str = Form(..., description="对话会话 ID，决定文档归属与检索范围"),
    files: list[UploadFile] = File(..., description="上传的 PDF / Word / 文本文件"),
):
    """Receive one or more files, save to disk, ingest into Chroma."""
    sid = _validate_session(session_id)
    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"too many files ({len(files)} > {MAX_FILES_PER_REQUEST})",
        )

    upload_dir = _session_uploads_dir(sid)
    collection = collection_for_session(sid)
    pipeline = await get_pipeline(collection)

    uploaded: list[DocumentInfo] = []
    failed: list[dict] = []

    for upload in files:
        original_name = upload.filename or "unnamed"
        safe_name = Path(original_name).name  # strip any path
        if not is_supported_file(safe_name):
            failed.append(
                {
                    "filename": safe_name,
                    "error": (
                        f"unsupported file type; supported: "
                        f"{sorted(SUPPORTED_EXTENSIONS)}"
                    ),
                }
            )
            continue

        # Read all bytes (small files only — enforced by MAX_UPLOAD_BYTES)
        try:
            data = await upload.read()
        except Exception as e:  # noqa: BLE001
            failed.append({"filename": safe_name, "error": f"read failed: {e}"})
            continue
        finally:
            await upload.close()

        if len(data) == 0:
            failed.append({"filename": safe_name, "error": "empty file"})
            continue
        if len(data) > MAX_UPLOAD_BYTES:
            failed.append(
                {
                    "filename": safe_name,
                    "error": (
                        f"file too large ({len(data)} bytes > {MAX_UPLOAD_BYTES})"
                    ),
                }
            )
            continue

        doc_id = uuid.uuid4().hex
        # Keep original extension so loaders dispatch correctly.
        ext = Path(safe_name).suffix.lower()
        on_disk = upload_dir / f"{doc_id}{ext}"
        try:
            on_disk.write_bytes(data)
        except Exception as e:  # noqa: BLE001
            failed.append({"filename": safe_name, "error": f"save failed: {e}"})
            continue

        uploaded_at = datetime.utcnow().isoformat()
        try:
            result = await pipeline.ingest_file(
                file_path=on_disk,
                doc_id=doc_id,
                extra_metadata={
                    "filename": safe_name,
                    "stored_path": str(on_disk),
                    "session_id": sid,
                    "uploaded_at": uploaded_at,
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[Upload] ingest failed for {safe_name}")
            # Drop the on-disk file so we don't leave stale uploads behind
            try:
                on_disk.unlink(missing_ok=True)
            except Exception:
                pass
            failed.append({"filename": safe_name, "error": f"ingest failed: {e}"})
            continue

        uploaded.append(
            DocumentInfo(
                doc_id=doc_id,
                filename=safe_name,
                extension=ext,
                size_bytes=len(data),
                char_count=int(result.get("char_count", 0)),
                chunks=int(result.get("chunks", 0)),
                uploaded_at=uploaded_at,
            )
        )

    return DocumentUploadResponse(
        session_id=sid,
        collection=collection,
        uploaded=uploaded,
        failed=failed,
    )


@documents_router.get("", response_model=DocumentListResponse)
async def list_documents(
    session_id: str = Query(..., description="对话会话 ID"),
):
    sid = _validate_session(session_id)
    collection = collection_for_session(sid)
    pipeline = await get_pipeline(collection)
    docs_raw = pipeline.list_documents()

    docs = [
        DocumentInfo(
            doc_id=d.get("doc_id") or "",
            filename=d.get("filename") or "",
            extension=d.get("extension") or "",
            size_bytes=int(d.get("size_bytes") or 0),
            char_count=int(d.get("char_count") or 0),
            chunks=int(d.get("chunks") or 0),
            uploaded_at=d.get("uploaded_at") or "",
        )
        for d in docs_raw
        if d.get("doc_id")
    ]

    return DocumentListResponse(
        session_id=sid,
        collection=collection,
        documents=docs,
    )


@documents_router.delete("/{doc_id}", response_model=DocumentDeleteResponse)
async def delete_document(
    doc_id: str,
    session_id: str = Query(..., description="对话会话 ID"),
):
    sid = _validate_session(session_id)
    if not doc_id or not doc_id.isalnum():
        raise HTTPException(status_code=400, detail="invalid doc_id")

    collection = collection_for_session(sid)
    pipeline = await get_pipeline(collection)
    chunks_removed = await pipeline.delete_document(doc_id)

    # Best-effort: remove the on-disk file too
    upload_dir = _session_uploads_dir(sid)
    removed_file = False
    for f in upload_dir.glob(f"{doc_id}.*"):
        try:
            f.unlink(missing_ok=True)
            removed_file = True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[Upload] failed to remove file {f}: {e}")

    return DocumentDeleteResponse(
        session_id=sid,
        doc_id=doc_id,
        chunks_removed=chunks_removed,
        file_removed=removed_file,
    )
