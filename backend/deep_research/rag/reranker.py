from __future__ import annotations
"""Document reranker for improving retrieval quality."""

import logging
from typing import Any, Optional

import numpy as np

from deep_research.rag.embedding import EmbeddingService

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """Simple cross-encoder reranker using embedding similarity."""

    def __init__(self, embedding_service: Optional[EmbeddingService] = None) -> None:
        self.embedding_service = embedding_service or EmbeddingService()

    async def rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Rerank documents by query relevance using embedding similarity."""
        if not documents:
            return []

        top_k = top_k or 5

        # Get query embedding
        query_embedding = await self.embedding_service.embed_query(query)

        # Get document embeddings
        doc_texts = [doc["content"] for doc in documents]
        doc_embeddings = await self.embedding_service.embed_texts(doc_texts)

        # Compute cosine similarity
        query_vec = np.array(query_embedding)
        query_vec = query_vec / (np.linalg.norm(query_vec) + 1e-10)

        scored_docs = []
        for doc, emb in zip(documents, doc_embeddings):
            doc_vec = np.array(emb)
            doc_vec = doc_vec / (np.linalg.norm(doc_vec) + 1e-10)
            similarity = float(np.dot(query_vec, doc_vec))

            scored_doc = doc.copy()
            scored_doc["rerank_score"] = similarity
            scored_docs.append(scored_doc)

        # Sort by rerank score
        scored_docs.sort(key=lambda x: x["rerank_score"], reverse=True)

        return scored_docs[:top_k]
