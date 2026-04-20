"""Hybrid retriever combining vector search and BM25."""

import logging
from typing import Any, Optional

from a_stock_analyzer.config.settings import get_settings
from a_stock_analyzer.rag.bm25_store import BM25Store
from a_stock_analyzer.rag.vector_store import ChromaVectorStore

logger = logging.getLogger(__name__)


class HybridRetriever:
    """Hybrid retriever using RRF fusion of vector and BM25 results."""

    def __init__(
        self,
        vector_store: Optional[ChromaVectorStore] = None,
        bm25_store: Optional[BM25Store] = None,
        k: int = 60,
    ) -> None:
        self.vector_store = vector_store or ChromaVectorStore()
        self.bm25_store = bm25_store or BM25Store()
        self.k = k  # RRF constant

    async def retrieve(
        self,
        query: str,
        query_embedding: list[float],
        top_k_vector: Optional[int] = None,
        top_k_bm25: Optional[int] = None,
        top_k_final: Optional[int] = None,
        filter_dict: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Retrieve documents using hybrid search.

        1. Query vector store and BM25 store in parallel
        2. Fuse results using Reciprocal Rank Fusion (RRF)
        3. Return top-k final results
        """
        settings = get_settings().rag.retrieval
        top_k_vector = top_k_vector or settings.top_k_vector
        top_k_bm25 = top_k_bm25 or settings.top_k_bm25
        top_k_final = top_k_final or settings.top_k_final

        # Get vector results
        vector_results = self.vector_store.search(
            query_embedding=query_embedding,
            top_k=top_k_vector,
            filter_dict=filter_dict,
        )

        # Get BM25 results
        bm25_results = self.bm25_store.search(query, top_k=top_k_bm25)

        # Fuse results using RRF
        fused_results = self._rrf_fusion(vector_results, bm25_results)

        return fused_results[:top_k_final]

    def _rrf_fusion(
        self,
        vector_results: list[dict[str, Any]],
        bm25_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Fuse results using Reciprocal Rank Fusion.

        RRF score = sum(1 / (k + rank)) for each result across all retrievers
        """
        scores: dict[str, float] = {}
        docs: dict[str, dict[str, Any]] = {}

        # Process vector results (convert distance to rank)
        for rank, result in enumerate(vector_results):
            doc_id = result["id"]
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (self.k + rank + 1)
            if doc_id not in docs:
                docs[doc_id] = {
                    "id": doc_id,
                    "content": result["content"],
                    "metadata": result.get("metadata", {}),
                    "vector_score": result.get("score", 0),
                }

        # Process BM25 results
        for rank, result in enumerate(bm25_results):
            doc_id = result["id"]
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (self.k + rank + 1)
            if doc_id not in docs:
                docs[doc_id] = {
                    "id": doc_id,
                    "content": result["content"],
                    "metadata": result.get("metadata", {}),
                    "bm25_score": result.get("score", 0),
                }
            else:
                docs[doc_id]["bm25_score"] = result.get("score", 0)

        # Sort by RRF score
        sorted_docs = sorted(
            [(doc_id, score) for doc_id, score in scores.items()],
            key=lambda x: x[1],
            reverse=True,
        )

        results = []
        for doc_id, rrf_score in sorted_docs:
            doc = docs[doc_id].copy()
            doc["rrf_score"] = rrf_score
            results.append(doc)

        return results

    def add_documents(
        self,
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: Optional[list[dict[str, Any]]] = None,
        ids: Optional[list[str]] = None,
    ) -> list[str]:
        """Add documents to both vector store and BM25 store."""
        # Add to vector store
        doc_ids = self.vector_store.add_documents(documents, embeddings, metadatas, ids)

        # Add to BM25 store
        self.bm25_store.add_documents(documents, metadatas, doc_ids)

        return doc_ids

    def count(self) -> dict[str, int]:
        """Get document counts from both stores."""
        return {
            "vector_store": self.vector_store.count(),
            "bm25_store": self.bm25_store.count(),
        }
