"""Tests for BM25 retriever and hybrid retrieval."""

import pytest

from deep_research.rag.vector_store import ChromaVectorStore
from deep_research.rag.bm25_retriever import BM25Retriever, _tokenize


class TestTokenize:
    def test_tokenize_returns_list(self):
        tokens = _tokenize("hello world")
        assert isinstance(tokens, list)
        assert len(tokens) > 0

    def test_tokenize_chinese(self):
        tokens = _tokenize("中文分词测试")
        assert isinstance(tokens, list)
        # jieba should produce multiple tokens
        assert len(tokens) >= 1


class TestBM25Retriever:
    def test_init(self):
        retriever = BM25Retriever(collection_name="test_bm25")
        assert retriever.collection_name == "test_bm25"

    def test_search_empty_collection(self, tmp_path):
        """Searching an empty collection returns empty results."""
        store = ChromaVectorStore(
            collection_name="test_bm25_empty",
            persist_directory=str(tmp_path / "chroma"),
        )
        # ensure collection exists
        _ = store.collection
        store.clear()
        retriever = BM25Retriever(collection_name="test_bm25_empty")
        results = retriever.search("test query")
        assert results == []

    def test_search_with_documents(self, tmp_path):
        """BM25 retrieves documents matching query terms."""
        store = ChromaVectorStore(
            collection_name="test_bm25_docs",
            persist_directory=str(tmp_path / "chroma"),
        )
        _ = store.collection
        store.clear()
        store.add_documents(
            documents=[
                "人工智能是未来的关键技术",
                "深度学习是机器学习的一个分支",
                "天气很好，适合户外活动",
            ],
            embeddings=[[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]],
            metadatas=[{"doc_id": "d1"}, {"doc_id": "d2"}, {"doc_id": "d3"}],
            ids=["c1", "c2", "c3"],
        )
        retriever = BM25Retriever(
            collection_name="test_bm25_docs",
            vector_store=store,
        )
        results = retriever.search("人工智能", top_k=3)
        assert len(results) >= 1
        # Top result should mention 人工智能
        assert "人工智能" in results[0]["content"] or "人工智能" in str(results[0].get("metadata", {}))

    def test_filter_by_doc_id(self, tmp_path):
        store = ChromaVectorStore(
            collection_name="test_bm25_filter",
            persist_directory=str(tmp_path / "chroma"),
        )
        _ = store.collection
        store.clear()
        store.add_documents(
            documents=["人工智能", "机器学习"],
            embeddings=[[1.0, 0.0], [0.0, 1.0]],
            metadatas=[{"doc_id": "d1"}, {"doc_id": "d2"}],
            ids=["c1", "c2"],
        )
        retriever = BM25Retriever(
            collection_name="test_bm25_filter",
            vector_store=store,
        )
        results = retriever.search("人工智能", filter_dict={"doc_id": "d1"})
        assert len(results) == 1
        assert results[0]["metadata"]["doc_id"] == "d1"


class TestHybridRetrieval:
    def test_rrf_merge(self, tmp_path):
        """Reciprocal Rank Fusion merges vector and BM25 results."""
        from deep_research.rag.pipeline import _reciprocal_rank_fusion

        vector_hits = [
            {"id": "a", "content": "人工智能", "score": 0.9},
            {"id": "b", "content": "机器学习", "score": 0.8},
        ]
        bm25_hits = [
            {"id": "b", "content": "机器学习", "score": 1.0},
            {"id": "c", "content": "深度学习", "score": 0.7},
        ]
        merged = _reciprocal_rank_fusion(vector_hits, bm25_hits, k=60, final_top_k=10)
        ids = [m["id"] for m in merged]
        # b appears in both lists, so it should rank highest
        assert ids[0] == "b"
        # a and c should also be present
        assert "a" in ids
        assert "c" in ids
