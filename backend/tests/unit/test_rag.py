"""Unit tests for RAG system."""

import pytest

from financial_agent.rag.text_splitter import RecursiveTextSplitter


class TestTextSplitter:
    def test_split_short_text(self):
        splitter = RecursiveTextSplitter(chunk_size=100, chunk_overlap=10)
        text = "这是一个测试文本。用于测试文本切分功能。"
        chunks = splitter.split_text(text)
        assert len(chunks) >= 1
        assert all(len(c) <= 100 for c in chunks)

    def test_split_long_text(self):
        splitter = RecursiveTextSplitter(chunk_size=50, chunk_overlap=5)
        text = "这是一段很长的测试文本。" * 20
        chunks = splitter.split_text(text)
        assert len(chunks) > 1
        # Check overlap
        if len(chunks) > 1:
            assert len(chunks[0]) > 0

    def test_split_chinese_paragraphs(self):
        splitter = RecursiveTextSplitter(chunk_size=30, chunk_overlap=5)
        text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
        chunks = splitter.split_text(text)
        assert len(chunks) >= 1


class TestDocumentLoader:
    def test_document_creation(self):
        from financial_agent.rag.document_loader import Document

        doc = Document(
            content="test content",
            metadata={"source": "test"},
            source="test.txt",
        )
        assert doc.content == "test content"
        assert doc.metadata["source"] == "test"

    def test_document_to_dict(self):
        from financial_agent.rag.document_loader import Document

        doc = Document(content="test", metadata={"key": "value"})
        d = doc.to_dict()
        assert d["content"] == "test"
        assert d["metadata"]["key"] == "value"


class TestRAGMerge:
    def test_merge_keeps_best_score(self):
        from financial_agent.rag.pipeline import _merge_retrieval_results

        results = [
            [{"id": "doc1", "score": 0.9, "content": "a"}, {"id": "doc2", "score": 0.5, "content": "b"}],
            [{"id": "doc1", "score": 0.7, "content": "a2"}, {"id": "doc3", "score": 0.8, "content": "c"}],
        ]
        merged = _merge_retrieval_results(results)
        assert len(merged) == 3
        doc1 = next(d for d in merged if d["id"] == "doc1")
        assert doc1["score"] == 0.9
        scores = [d["score"] for d in merged]
        assert scores == sorted(scores, reverse=True)

    def test_merge_empty(self):
        from financial_agent.rag.pipeline import _merge_retrieval_results

        assert _merge_retrieval_results([]) == []
        assert _merge_retrieval_results([[]]) == []

    def test_merge_missing_id_skipped(self):
        from financial_agent.rag.pipeline import _merge_retrieval_results

        results = [[{"score": 0.5, "content": "no id"}]]
        assert _merge_retrieval_results(results) == []
