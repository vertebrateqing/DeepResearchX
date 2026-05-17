"""Tests for document upload API and RAG pipeline."""

from io import BytesIO
from pathlib import Path

import pytest

# Guard FastAPI TestClient — system pytest may not have python-multipart.
try:
    from fastapi.testclient import TestClient
    _HAS_TESTCLIENT = True
except Exception:  # noqa: BLE001
    _HAS_TESTCLIENT = False


@pytest.fixture
def client(tmp_path, monkeypatch):
    """FastAPI TestClient with tmp data dirs and a stubbed embedding service.

    Stubs out network calls (LLM embeddings) so tests are hermetic and don't
    require ``LLM_API_KEY`` to be set.
    """
    if not _HAS_TESTCLIENT:
        pytest.skip("fastapi TestClient / python-multipart not available")

    # Patch BEFORE importing main so the routers pick up the patched func.
    import api.documents as _doc_mod
    import deep_research.rag.embedding as _emb_mod
    import deep_research.rag.pipeline as _pipe_mod

    def _make_uploads_dir(sid):
        p = tmp_path / "uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    monkeypatch.setattr(
        _doc_mod,
        "_session_uploads_dir",
        _make_uploads_dir,
    )
    # Also redirect Chroma storage to a temp dir so tests don't pollute.
    monkeypatch.setattr(
        _pipe_mod,
        "_pipeline_cache",
        {},
    )

    # Stub the embedding service to avoid real API calls in tests.
    _FAKE_DIM = 8

    async def _fake_embed_texts(self, texts):
        return [[0.1] * _FAKE_DIM for _ in texts]

    async def _fake_embed_query(self, query):
        return [0.1] * _FAKE_DIM

    async def _fake_close(self):
        return None

    monkeypatch.setattr(_emb_mod.EmbeddingService, "embed_texts", _fake_embed_texts)
    monkeypatch.setattr(_emb_mod.EmbeddingService, "embed_query", _fake_embed_query)
    monkeypatch.setattr(_emb_mod.EmbeddingService, "close", _fake_close)

    try:
        from main import app
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"cannot import FastAPI app: {exc}")

    return TestClient(app)


class TestDocumentUploadAPI:
    def test_upload_requires_session_id(self, client):
        """Upload endpoint rejects missing session_id."""
        res = client.post("/api/documents/upload", data={})
        # FastAPI Form validation returns 422 for missing required fields
        assert res.status_code == 422
        assert "session_id" in str(res.json())

    def test_upload_and_list(self, client):
        """Happy path: upload a txt file, list it, delete it."""
        sid = "sess_test_001"

        # Upload
        file_data = BytesIO(b"Hello from test document upload.")
        res = client.post(
            "/api/documents/upload",
            data={"session_id": sid},
            files={"files": ("test.txt", file_data, "text/plain")},
        )
        assert res.status_code == 200, res.text
        payload = res.json()
        assert payload["session_id"] == sid
        assert len(payload["uploaded"]) == 1
        doc = payload["uploaded"][0]
        assert doc["filename"] == "test.txt"
        assert doc["extension"] == ".txt"
        assert doc["char_count"] > 0
        doc_id = doc["doc_id"]

        # List
        res = client.get("/api/documents", params={"session_id": sid})
        assert res.status_code == 200, res.text
        listed = res.json()["documents"]
        assert any(d["doc_id"] == doc_id for d in listed)

        # Delete
        res = client.delete(f"/api/documents/{doc_id}", params={"session_id": sid})
        assert res.status_code == 200, res.text
        assert res.json()["chunks_removed"] > 0

        # List again — should be empty
        res = client.get("/api/documents", params={"session_id": sid})
        assert res.status_code == 200, res.text
        assert len(res.json()["documents"]) == 0

    def test_upload_unsupported_extension(self, client):
        sid = "sess_test_002"
        file_data = BytesIO(b"fake zip")
        res = client.post(
            "/api/documents/upload",
            data={"session_id": sid},
            files={"files": ("data.zip", file_data, "application/zip")},
        )
        assert res.status_code == 200  # endpoint itself succeeds
        payload = res.json()
        assert len(payload["uploaded"]) == 0
        assert len(payload["failed"]) == 1
        assert "unsupported" in payload["failed"][0]["error"].lower()


class TestDocumentLoader:
    def test_load_txt(self, tmp_path):
        from deep_research.rag.document_loader import Document, load_document

        p = tmp_path / "test.txt"
        p.write_text("Hello world\n第二行", encoding="utf-8")

        doc: Document = load_document(p)
        assert "Hello world" in doc.content
        assert doc.metadata["extension"] == ".txt"
        assert doc.metadata["size_bytes"] == p.stat().st_size

    def test_load_pdf_path_not_found(self, tmp_path):
        from deep_research.rag.document_loader import load_document

        with pytest.raises(FileNotFoundError):
            load_document(tmp_path / "missing.pdf")

    def test_unsupported_extension(self, tmp_path):
        from deep_research.rag.document_loader import load_document

        p = tmp_path / "test.exe"
        p.write_text("bad", encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported file type"):
            load_document(p)


class TestRAGPipeline:
    def test_safe_collection_name(self):
        from deep_research.rag.pipeline import _safe_collection_name

        assert _safe_collection_name("session_123").startswith("session_123_")
        assert len(_safe_collection_name("a" * 100)) <= 63

    def test_collection_for_session(self):
        from deep_research.rag.pipeline import collection_for_session

        name = collection_for_session("sess_20250508_120000_abc123")
        assert "sess_20250508_120000_abc123" in name
