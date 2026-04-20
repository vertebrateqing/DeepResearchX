"""Unit tests for RAG system."""

import pytest

from a_stock_analyzer.rag.text_splitter import RecursiveTextSplitter


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
        from a_stock_analyzer.rag.document_loader import Document

        doc = Document(
            content="test content",
            metadata={"source": "test"},
            source="test.txt",
        )
        assert doc.content == "test content"
        assert doc.metadata["source"] == "test"

    def test_document_to_dict(self):
        from a_stock_analyzer.rag.document_loader import Document

        doc = Document(content="test", metadata={"key": "value"})
        d = doc.to_dict()
        assert d["content"] == "test"
        assert d["metadata"]["key"] == "value"
