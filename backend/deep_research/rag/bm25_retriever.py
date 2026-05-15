from __future__ import annotations
"""BM25 sparse retriever for hybrid RAG.

Uses ``rank-bm25`` (pure Python, no heavy deps) and ``jieba`` for
Chinese-aware tokenization.  The index is built lazily from the
Chroma collection metadata so we don't need a separate persistence
layer.
"""

import logging
from typing import Any, Optional

from deep_research.config.settings import get_settings

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    """Tokenize query / document text.  Uses jieba for Chinese, simple split for English."""
    try:
        import jieba

        return list(jieba.cut_for_search(text))
    except Exception:  # noqa: BLE001
        return text.lower().split()


class BM25Retriever:
    """BM25 sparse retriever backed by a Chroma collection.

    The index is rebuilt on every ``search()`` call from the collection's
    current documents.  For small per-session collections (tens to hundreds
    of chunks) this is fast enough and guarantees freshness after uploads
    or deletions.
    """

    def __init__(
        self,
        collection_name: str,
        top_k: int = 20,
        k1: Optional[float] = None,
        b: Optional[float] = None,
        vector_store: Optional["ChromaVectorStore"] = None,
    ) -> None:
        self.collection_name = collection_name
        cfg = get_settings().rag.bm25
        self.k1 = k1 if k1 is not None else cfg.k1
        self.b = b if b is not None else cfg.b
        self.top_k = top_k
        self._vector_store = vector_store

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        filter_dict: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Return BM25-ranked chunks for ``query``.

        Parameters
        ----------
        query :
            Raw query string.
        top_k :
            Number of results to return.
        filter_dict :
            Chroma ``where`` filter applied when fetching candidate docs.
        """
        try:
            from rank_bm25 import BM25Okapi
        except ImportError as exc:
            raise RuntimeError("BM25 requires 'rank-bm25'. Install it: pip install rank-bm25") from exc

        k = top_k or self.top_k

        # Fetch all documents + metadata from the collection
        docs, ids, metadatas = self._fetch_candidates(filter_dict)
        if not docs:
            return []

        # Tokenize corpus
        tokenized_corpus = [_tokenize(d) for d in docs]
        bm25 = BM25Okapi(tokenized_corpus, k1=self.k1, b=self.b)

        # Score query
        tokenized_query = _tokenize(query)
        scores = bm25.get_scores(tokenized_query)

        # Build ranked results (higher score = better)
        ranked = sorted(
            zip(ids, docs, metadatas, scores),
            key=lambda x: x[3],
            reverse=True,
        )[:k]

        # Normalize scores to [0, 1] for downstream merging with vector search
        max_score = max((s for _, _, _, s in ranked), default=1.0) or 1.0
        results = []
        for doc_id, doc, meta, score in ranked:
            results.append(
                {
                    "id": doc_id,
                    "content": doc,
                    "metadata": meta or {},
                    "score": float(score / max_score),  # normalized
                    "raw_score": float(score),
                }
            )
        return results

    def _fetch_candidates(
        self,
        filter_dict: Optional[dict[str, Any]] = None,
    ) -> tuple[list[str], list[str], list[dict[str, Any]]]:
        """Fetch documents, ids, and metadatas from the Chroma collection."""
        from deep_research.rag.vector_store import ChromaVectorStore

        store = self._vector_store or ChromaVectorStore(collection_name=self.collection_name)
        try:
            result = store.collection.get(
                where=filter_dict,
                include=["documents", "metadatas"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[BM25] failed to fetch candidates: {exc}")
            return [], [], []

        docs = list(result.get("documents") or [])
        ids = list(result.get("ids") or [])
        metas = list(result.get("metadatas") or [])
        return docs, ids, metas
