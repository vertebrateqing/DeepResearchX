"""Document reranker for improving retrieval quality."""

import logging
from typing import Any, Optional

import numpy as np

from a_stock_analyzer.rag.embedding import EmbeddingService

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


class WeightedReranker:
    """Weighted reranker combining multiple scores."""

    def __init__(
        self,
        rrf_weight: float = 0.4,
        vector_weight: float = 0.3,
        bm25_weight: float = 0.3,
    ) -> None:
        self.rrf_weight = rrf_weight
        self.vector_weight = vector_weight
        self.bm25_weight = bm25_weight

    def rerank(
        self,
        documents: list[dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Rerank using weighted combination of scores."""
        if not documents:
            return []

        top_k = top_k or len(documents)

        scored = []
        for doc in documents:
            rrf_score = doc.get("rrf_score", 0)
            vector_score = doc.get("vector_score", 0)
            bm25_score = doc.get("bm25_score", 0)

            # Normalize scores to 0-1 range
            # RRF is already normalized-ish
            # For vector (distance), smaller is better - convert to similarity
            # For BM25, already larger is better

            combined = (
                self.rrf_weight * rrf_score +
                self.vector_weight * (1.0 - min(vector_score, 1.0)) +  # distance to similarity
                self.bm25_weight * self._normalize_bm25(bm25_score)
            )

            doc_copy = doc.copy()
            doc_copy["combined_score"] = combined
            scored.append(doc_copy)

        scored.sort(key=lambda x: x["combined_score"], reverse=True)
        return scored[:top_k]

    def _normalize_bm25(self, score: float) -> float:
        """Normalize BM25 score to 0-1 range using sigmoid-like function."""
        import math
        return min(score / (score + 10), 1.0)
