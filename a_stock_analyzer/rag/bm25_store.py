"""BM25 index for keyword-based retrieval."""

import json
import logging
import pickle
from pathlib import Path
from typing import Any, Optional

import jieba
from rank_bm25 import BM25Okapi

from a_stock_analyzer.config.settings import get_settings

logger = logging.getLogger(__name__)


class BM25Store:
    """BM25 index for precise keyword retrieval, optimized for Chinese."""

    def __init__(
        self,
        index_path: Optional[str] = None,
        k1: Optional[float] = None,
        b: Optional[float] = None,
    ) -> None:
        settings = get_settings().rag.bm25
        self.index_path = Path(index_path or settings.index_path)
        self.k1 = k1 or settings.k1
        self.b = b or settings.b

        self._bm25: Optional[BM25Okapi] = None
        self._documents: list[str] = []
        self._metadatas: list[dict[str, Any]] = []
        self._ids: list[str] = []

        # Try to load existing index
        self._load()

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize Chinese text using jieba."""
        # Use jieba for Chinese, fallback to simple split
        tokens = list(jieba.cut_for_search(text))
        # Filter empty and very short tokens
        return [t.strip() for t in tokens if t.strip() and len(t.strip()) > 1]

    def add_documents(
        self,
        documents: list[str],
        metadatas: Optional[list[dict[str, Any]]] = None,
        ids: Optional[list[str]] = None,
    ) -> None:
        """Add documents to the BM25 index."""
        if metadatas is None:
            metadatas = [{} for _ in documents]
        if ids is None:
            from uuid import uuid4

            ids = [str(uuid4()) for _ in documents]

        self._documents.extend(documents)
        self._metadatas.extend(metadatas)
        self._ids.extend(ids)

        # Rebuild BM25 index
        tokenized_docs = [self._tokenize(doc) for doc in self._documents]
        self._bm25 = BM25Okapi(tokenized_docs, k1=self.k1, b=self.b)

        self._save()
        logger.info(f"Added {len(documents)} documents to BM25 index (total: {len(self._documents)})")

    def search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """Search for documents matching the query."""
        if self._bm25 is None or not self._documents:
            return []

        tokenized_query = self._tokenize(query)
        scores = self._bm25.get_scores(tokenized_query)

        # Get top-k results
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append({
                    "id": self._ids[idx],
                    "content": self._documents[idx],
                    "metadata": self._metadatas[idx],
                    "score": float(scores[idx]),
                })

        return results

    def delete(self, ids: list[str]) -> None:
        """Delete documents by IDs."""
        id_set = set(ids)
        keep_indices = [i for i, doc_id in enumerate(self._ids) if doc_id not in id_set]

        self._documents = [self._documents[i] for i in keep_indices]
        self._metadatas = [self._metadatas[i] for i in keep_indices]
        self._ids = [self._ids[i] for i in keep_indices]

        # Rebuild index
        if self._documents:
            tokenized_docs = [self._tokenize(doc) for doc in self._documents]
            self._bm25 = BM25Okapi(tokenized_docs, k1=self.k1, b=self.b)
        else:
            self._bm25 = None

        self._save()

    def _save(self) -> None:
        """Save index to disk."""
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "documents": self._documents,
            "metadatas": self._metadatas,
            "ids": self._ids,
            "k1": self.k1,
            "b": self.b,
        }
        with open(self.index_path, "wb") as f:
            pickle.dump(data, f)

    def _load(self) -> None:
        """Load index from disk."""
        if not self.index_path.exists():
            return

        try:
            with open(self.index_path, "rb") as f:
                data = pickle.load(f)

            self._documents = data.get("documents", [])
            self._metadatas = data.get("metadatas", [])
            self._ids = data.get("ids", [])
            self.k1 = data.get("k1", self.k1)
            self.b = data.get("b", self.b)

            if self._documents:
                tokenized_docs = [self._tokenize(doc) for doc in self._documents]
                self._bm25 = BM25Okapi(tokenized_docs, k1=self.k1, b=self.b)

            logger.info(f"Loaded BM25 index with {len(self._documents)} documents")
        except Exception as e:
            logger.warning(f"Failed to load BM25 index: {e}")

    def count(self) -> int:
        """Get total document count."""
        return len(self._documents)

    def clear(self) -> None:
        """Clear all documents."""
        self._documents = []
        self._metadatas = []
        self._ids = []
        self._bm25 = None
        if self.index_path.exists():
            self.index_path.unlink()
