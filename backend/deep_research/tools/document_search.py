from __future__ import annotations
"""DocumentSearchTool — RAG retrieval over user-uploaded documents.

Bound to a specific collection (one per session) so a chapter worker only
sees chunks from the user's own uploads. The tool returns ranked text
chunks with citation metadata; the LLM then quotes them in the report.
"""

import logging
import time
from typing import Any, Optional

from deep_research.core.base import BaseTool
from deep_research.observability import get_langfuse
from deep_research.rag.pipeline import RAGPipeline, get_pipeline

logger = logging.getLogger(__name__)


class DocumentSearchTool(BaseTool):
    """Search inside the user's uploaded documents for this session."""

    name = "document_search"
    description = (
        "在用户上传的文档库（PDF / Word / 文本）中检索与查询最相关的段落。"
        "适用于：基于用户提供的资料进行分析、回答与上传文档相关的问题、"
        "在已有文档中查找具体细节或数据。优先使用此工具，再考虑联网搜索。"
    )
    parameters = {
        "query": {
            "type": "string",
            "description": "用自然语言描述要查找的内容，越具体越好。",
        },
        "top_k": {
            "type": "integer",
            "description": "返回的最相关片段数量",
            "default": 5,
        },
        "doc_ids": {
            "type": "array",
            "description": "可选：限定在某些文档内检索的 doc_id 列表",
            "items": {"type": "string"},
            "default": [],
        },
    }

    def __init__(
        self,
        collection_name: str,
        allowed_doc_ids: Optional[list[str]] = None,
        max_top_k: int = 10,
    ) -> None:
        self.collection_name = collection_name
        # When set, callers can only retrieve from these doc_ids regardless
        # of the doc_ids arg the LLM passes.
        self.allowed_doc_ids = list(allowed_doc_ids) if allowed_doc_ids else None
        self.max_top_k = max_top_k
        self._pipeline: Optional[RAGPipeline] = None
        self._trace_id: Optional[str] = None

    async def _get_pipeline(self) -> RAGPipeline:
        if self._pipeline is None:
            self._pipeline = await get_pipeline(self.collection_name)
        return self._pipeline

    async def execute(
        self,
        query: str,
        top_k: int = 5,
        doc_ids: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        if not query or not query.strip():
            return {"query": query, "chunks": [], "total": 0}

        # Apply caller scope first, then narrow with allowed_doc_ids if set.
        scope_ids: Optional[list[str]] = list(doc_ids) if doc_ids else None
        if self.allowed_doc_ids is not None:
            if scope_ids:
                scope_ids = [d for d in scope_ids if d in self.allowed_doc_ids]
            else:
                scope_ids = list(self.allowed_doc_ids)
            if not scope_ids:
                return {"query": query, "chunks": [], "total": 0}

        k = max(1, min(int(top_k or 5), self.max_top_k))

        lf = get_langfuse()
        span = (
            lf.span(
                trace_id=self._trace_id,
                name="document_search",
                input={"query": query, "top_k": k, "collection": self.collection_name},
            )
            if lf and self._trace_id
            else None
        )

        t0 = time.perf_counter()
        try:
            pipeline = await self._get_pipeline()
            hits = await pipeline.query(query, top_k=k, doc_ids=scope_ids)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[DocumentSearch] query failed: {e}")
            if span:
                span.end(output={"error": str(e)})
            return {"query": query, "chunks": [], "total": 0, "error": str(e)}

        chunks = []
        for hit in hits:
            md = hit.get("metadata") or {}
            chunks.append(
                {
                    "text": hit.get("content", ""),
                    "score": round(float(hit.get("score", 0.0)), 4),
                    "doc_id": md.get("doc_id"),
                    "filename": md.get("filename"),
                    "chunk_index": md.get("chunk_index"),
                    "title": md.get("filename") or md.get("doc_id") or "uploaded_document",
                    "url": "",
                }
            )

        latency = time.perf_counter() - t0
        logger.info(
            f"[DocumentSearch] query='{query[:60]}' hits={len(chunks)} "
            f"latency={latency:.2f}s collection={self.collection_name}"
        )
        if span:
            span.end(
                output={
                    "hits": len(chunks),
                    "top": [
                        {
                            "doc": c.get("filename"),
                            "score": c.get("score"),
                            "preview": c.get("text", "")[:200],
                        }
                        for c in chunks[:3]
                    ],
                },
                metadata={"latency_s": round(latency, 3)},
            )

        return {
            "query": query,
            "chunks": chunks,
            "total": len(chunks),
            "collection": self.collection_name,
        }
