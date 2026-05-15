from __future__ import annotations
"""RAG pipeline: parse → chunk → embed → store, plus per-collection retrieval.

Used by ``/api/documents`` upload handlers and by ``DocumentSearchTool`` so a
chapter worker can pull relevant chunks from documents the user uploaded.

Each upload set lives in its own Chroma collection (``collection_name``) so a
session's documents don't cross-pollute another session.
"""

import asyncio
import hashlib
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

from typing import TYPE_CHECKING

from deep_research.config.settings import get_settings
from deep_research.rag.document_loader import Document, load_document
from deep_research.rag.chunking import get_splitter
from deep_research.rag.vector_store import ChromaVectorStore

if TYPE_CHECKING:
    from deep_research.rag.embedding import EmbeddingService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers — kept module-level so tests can target them directly
# ---------------------------------------------------------------------------


def _merge_retrieval_results(results: Iterable[Iterable[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Merge multiple ranked result lists, dedup by id, keep the best score.

    Used to combine vector and BM25 hits before reranking. Items
    missing an ``id`` field are dropped. Final list is sorted by ``score``
    descending.
    """
    by_id: dict[str, dict[str, Any]] = {}
    for batch in results or []:
        for hit in batch or []:
            doc_id = hit.get("id")
            if not doc_id:
                continue
            existing = by_id.get(doc_id)
            if existing is None or hit.get("score", 0) > existing.get("score", 0):
                by_id[doc_id] = dict(hit)

    return sorted(by_id.values(), key=lambda h: h.get("score", 0), reverse=True)


def _safe_collection_name(raw: str) -> str:
    """Sanitize a string into a Chroma-compatible collection name.

    Chroma requires names matching ``^[a-zA-Z0-9][a-zA-Z0-9._-]{1,61}[a-zA-Z0-9]$``.
    We slugify and add a short hash suffix to keep names unique-ish.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", raw).strip("_-.")
    if not cleaned:
        cleaned = "docs"
    cleaned = cleaned[:48].rstrip("_-.")
    if len(cleaned) < 3:
        cleaned = f"{cleaned}_col"
    suffix = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    name = f"{cleaned}_{suffix}"
    if not name[0].isalnum():
        name = f"c_{name}"
    return name[:63]


def collection_for_session(session_id: str) -> str:
    """Public helper: return the Chroma collection used for a session's uploads."""
    return _safe_collection_name(f"session_uploads_{session_id}")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class RAGPipeline:
    """Ingest documents into a Chroma collection and query them later."""

    def __init__(
        self,
        collection_name: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        chunking_strategy: str = "recursive",
        embedding_service: Optional["EmbeddingService"] = None,
        vector_store: Optional[ChromaVectorStore] = None,
    ) -> None:
        self.collection_name = collection_name
        self.chunking_strategy = chunking_strategy
        self.splitter = get_splitter(
            strategy=chunking_strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            embedding_service=embedding_service,
        )
        if embedding_service is None:
            from deep_research.rag.embedding import EmbeddingService
            embedding_service = EmbeddingService()
        self.embedding = embedding_service
        self.vector_store = vector_store or ChromaVectorStore(collection_name=collection_name)

    # -- Ingest ----------------------------------------------------------
    async def ingest_file(
        self,
        file_path: str | Path,
        doc_id: Optional[str] = None,
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Load → split → embed → store a single file."""
        path = Path(file_path)
        doc_id = doc_id or uuid.uuid4().hex
        meta = {"doc_id": doc_id}
        if extra_metadata:
            meta.update(extra_metadata)

        document: Document = await asyncio.to_thread(load_document, path, meta)
        return await self.ingest_document(document, doc_id=doc_id)

    async def ingest_document(
        self,
        document: Document,
        doc_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Split a pre-loaded Document and write its chunks to the store."""
        if not document.content.strip():
            logger.warning(
                f"[RAGPipeline] empty document, skipping: source={document.source}"
            )
            return {
                "doc_id": doc_id,
                "chunks": 0,
                "chunk_ids": [],
                "char_count": 0,
            }

        doc_id = doc_id or document.metadata.get("doc_id") or uuid.uuid4().hex
        document.metadata.setdefault("doc_id", doc_id)

        t0 = time.perf_counter()
        chunks: list[str] = self.splitter.split_text(document.content)
        if not chunks:
            chunks = [document.content]

        # Embed in chunks; EmbeddingService handles batching internally
        embeddings = await self.embedding.embed_texts(chunks)
        if len(embeddings) != len(chunks):
            raise RuntimeError(
                f"Embedding count mismatch: got {len(embeddings)} for {len(chunks)} chunks"
            )

        # Build chunk metadata (Chroma rejects None values, so skip empties)
        base_meta: dict[str, Any] = {
            k: v for k, v in document.metadata.items() if v is not None
        }
        base_meta["doc_id"] = doc_id

        chunk_ids = [f"{doc_id}__chunk__{i}" for i in range(len(chunks))]
        metadatas: list[dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
            md = dict(base_meta)
            md["chunk_index"] = i
            md["chunk_count"] = len(chunks)
            md["chunk_size"] = len(chunk)
            metadatas.append(md)

        await asyncio.to_thread(
            self.vector_store.add_documents,
            chunks,
            embeddings,
            metadatas,
            chunk_ids,
        )

        latency = time.perf_counter() - t0
        logger.info(
            f"[RAGPipeline] ingested doc_id={doc_id} chunks={len(chunks)} "
            f"chars={len(document.content)} latency={latency:.2f}s "
            f"collection={self.collection_name} strategy={self.chunking_strategy}"
        )
        return {
            "doc_id": doc_id,
            "chunks": len(chunks),
            "chunk_ids": chunk_ids,
            "char_count": len(document.content),
            "latency_s": round(latency, 3),
        }

    # -- Query -----------------------------------------------------------
    async def query(
        self,
        text: str,
        top_k: Optional[int] = None,
        doc_ids: Optional[list[str]] = None,
        hybrid: bool = True,
    ) -> list[dict[str, Any]]:
        """Return the most relevant chunks for ``text``.

        If ``doc_ids`` is provided, retrieval is restricted to chunks that
        belong to one of those parent documents.
        If ``hybrid`` is True (default), both vector similarity and BM25
        are used and the results are merged with reciprocal rank fusion.
        """
        if not text.strip():
            return []
        cfg = get_settings().rag.retrieval
        k = top_k or cfg.top_k_final or 5

        filter_dict: Optional[dict[str, Any]] = None
        if doc_ids:
            if len(doc_ids) == 1:
                filter_dict = {"doc_id": doc_ids[0]}
            else:
                filter_dict = {"doc_id": {"$in": list(doc_ids)}}

        # Vector retrieval
        embedding = await self.embedding.embed_query(text)
        vector_hits = await asyncio.to_thread(
            self.vector_store.search,
            embedding,
            cfg.top_k_vector or k * 2,
            filter_dict,
        )
        for hit in vector_hits:
            distance = hit.get("score", 0.0)
            hit["distance"] = distance
            hit["score"] = max(0.0, 1.0 - float(distance))

        if not hybrid:
            return _merge_retrieval_results([vector_hits])

        # BM25 retrieval
        try:
            from deep_research.rag.bm25_retriever import BM25Retriever

            bm25 = BM25Retriever(
                collection_name=self.collection_name,
                top_k=cfg.top_k_bm25 or k * 2,
                vector_store=self.vector_store,
            )
            bm25_hits = bm25.search(text, top_k=cfg.top_k_bm25 or k * 2, filter_dict=filter_dict)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[RAGPipeline] BM25 retrieval failed: {e}")
            bm25_hits = []

        # Reciprocal Rank Fusion (RRF) merging
        merged = _reciprocal_rank_fusion(vector_hits, bm25_hits, k=k)
        return merged

    # -- Manage ----------------------------------------------------------
    def list_documents(self) -> list[dict[str, Any]]:
        """Return one entry per ingested doc_id in this collection."""
        try:
            collection = self.vector_store.collection
            result = collection.get(include=["metadatas"])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[RAGPipeline] failed to list docs: {e}")
            return []

        docs: dict[str, dict[str, Any]] = {}
        for md in result.get("metadatas", []) or []:
            if not md:
                continue
            doc_id = md.get("doc_id")
            if not doc_id:
                continue
            if doc_id not in docs:
                docs[doc_id] = {
                    "doc_id": doc_id,
                    "filename": md.get("filename"),
                    "extension": md.get("extension"),
                    "char_count": md.get("char_count"),
                    "size_bytes": md.get("size_bytes"),
                    "uploaded_at": md.get("uploaded_at"),
                    "chunks": 0,
                }
            docs[doc_id]["chunks"] += 1
        return sorted(docs.values(), key=lambda d: d.get("uploaded_at") or "", reverse=True)

    async def delete_document(self, doc_id: str) -> int:
        """Delete every chunk belonging to ``doc_id``. Returns the chunk count removed."""
        try:
            collection = self.vector_store.collection
            existing = await asyncio.to_thread(
                collection.get,
                where={"doc_id": doc_id},
                include=[],
            )
            ids = list(existing.get("ids", []) or [])
            if not ids:
                return 0
            await asyncio.to_thread(self.vector_store.delete, ids)
            logger.info(
                f"[RAGPipeline] deleted doc_id={doc_id} "
                f"chunks={len(ids)} collection={self.collection_name}"
            )
            return len(ids)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[RAGPipeline] delete failed for {doc_id}: {e}")
            return 0

    def count(self) -> int:
        """Total chunk count in this collection."""
        try:
            return self.vector_store.count()
        except Exception:
            return 0

    async def close(self) -> None:
        await self.embedding.close()


# ---------------------------------------------------------------------------
# Retrieval merging helpers
# ---------------------------------------------------------------------------


def _reciprocal_rank_fusion(
    vector_hits: list[dict[str, Any]],
    bm25_hits: list[dict[str, Any]],
    k: int = 60,
    final_top_k: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Merge two ranked lists using Reciprocal Rank Fusion (RRF).

    RRF score = Σ 1 / (k + rank) for each list where the item appears.
    Higher score = better.
    """
    cfg = get_settings().rag.retrieval
    final_k = final_top_k or cfg.top_k_final or 10
    rrf_k = k

    scores: dict[str, float] = {}
    details: dict[str, dict[str, Any]] = {}

    def _register(hits: list[dict[str, Any]], source: str) -> None:
        for rank, hit in enumerate(hits, start=1):
            hid = hit.get("id")
            if not hid:
                continue
            scores[hid] = scores.get(hid, 0.0) + 1.0 / (rrf_k + rank)
            if hid not in details:
                details[hid] = dict(hit)
                details[hid]["sources"] = []
            details[hid]["sources"].append(source)
            # Keep best individual score for reference
            if source == "vector":
                details[hid]["vector_score"] = hit.get("score", 0.0)
            elif source == "bm25":
                details[hid]["bm25_score"] = hit.get("score", 0.0)

    _register(vector_hits, "vector")
    _register(bm25_hits, "bm25")

    # Sort by RRF score descending
    sorted_ids = sorted(scores.keys(), key=lambda i: scores[i], reverse=True)

    results = []
    for hid in sorted_ids[:final_k]:
        item = details[hid]
        item["rrf_score"] = round(scores[hid], 6)
        item["score"] = round(scores[hid], 6)
        results.append(item)
    return results


# ---------------------------------------------------------------------------
# Pipeline cache — avoid reloading vector stores per request
# ---------------------------------------------------------------------------


_pipeline_cache: dict[str, RAGPipeline] = {}
_pipeline_lock = asyncio.Lock()


async def get_pipeline(collection_name: str, **kwargs: Any) -> RAGPipeline:
    """Return a cached RAGPipeline for ``collection_name`` (creates on first call).

    Additional ``kwargs`` are forwarded to ``RAGPipeline.__init__``.  If
    kwargs differ from the cached instance, the cache is invalidated.
    """
    cache_key = collection_name
    cached = _pipeline_cache.get(cache_key)
    if cached and not kwargs:
        return cached

    # If kwargs provided (e.g. different chunking strategy or embedding model),
    # bypass cache to avoid mixing incompatible pipelines.
    if kwargs:
        return RAGPipeline(collection_name=collection_name, **kwargs)

    async with _pipeline_lock:
        if cache_key not in _pipeline_cache:
            _pipeline_cache[cache_key] = RAGPipeline(collection_name=collection_name)
        return _pipeline_cache[cache_key]


def reset_pipeline_cache() -> None:
    """Drop cached pipelines (useful for tests)."""
    _pipeline_cache.clear()
