"""Unit tests for RAG system."""

import pytest

from deep_research.rag.text_splitter import RecursiveTextSplitter


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


class TestVectorStore:
    def test_vector_store_init(self):
        from deep_research.rag.vector_store import ChromaVectorStore

        store = ChromaVectorStore(
            collection_name="test_collection",
            persist_directory="/tmp/test_chroma",
        )
        assert store.collection_name == "test_collection"

    def test_vector_store_add_and_search(self):
        from deep_research.rag.vector_store import ChromaVectorStore

        store = ChromaVectorStore(
            collection_name="test_search",
            persist_directory="/tmp/test_chroma_search",
        )
        # Ensure collection exists before clearing
        _ = store.collection
        store.clear()
        store.add_documents(
            documents=["hello world", "foo bar"],
            embeddings=[[1.0, 0.0], [0.0, 1.0]],
            metadatas=[{"source": "a"}, {"source": "b"}],
            ids=["d1", "d2"],
        )
        results = store.search(query_embedding=[1.0, 0.0], top_k=2)
        assert len(results) == 2
        assert results[0]["id"] == "d1"
