"""Tests for text chunking strategies."""

import pytest

from deep_research.rag.chunking import (
    FixedLengthTextSplitter,
    RecursiveTextSplitter,
    SemanticTextSplitter,
    get_splitter,
)


class TestRecursiveTextSplitter:
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
        if len(chunks) > 1:
            assert len(chunks[0]) > 0

    def test_split_chinese_paragraphs(self):
        splitter = RecursiveTextSplitter(chunk_size=30, chunk_overlap=5)
        text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
        chunks = splitter.split_text(text)
        assert len(chunks) >= 1


class TestFixedLengthTextSplitter:
    def test_fixed_length_basic(self):
        splitter = FixedLengthTextSplitter(chunk_size=20, chunk_overlap=5)
        text = "abcdefghij" * 10  # 100 chars
        chunks = splitter.split_text(text)
        assert len(chunks) > 1
        # Each chunk should be <= chunk_size
        assert all(len(c) <= 20 for c in chunks)

    def test_fixed_length_overlap(self):
        splitter = FixedLengthTextSplitter(chunk_size=10, chunk_overlap=3)
        text = "0123456789abcdefghijklmnopqrstuvwxyz"
        chunks = splitter.split_text(text)
        assert len(chunks) >= 2
        # Verify overlap by checking consecutive chunks share prefix/suffix
        if len(chunks) >= 2:
            assert chunks[0][-3:] == chunks[1][:3]

    def test_empty_text(self):
        splitter = FixedLengthTextSplitter(chunk_size=10, chunk_overlap=2)
        assert splitter.split_text("") == []

    def test_single_chunk(self):
        splitter = FixedLengthTextSplitter(chunk_size=100, chunk_overlap=10)
        text = "short text"
        chunks = splitter.split_text(text)
        assert len(chunks) == 1
        assert chunks[0] == "short text"


class TestSemanticTextSplitter:
    def test_preserves_paragraphs(self):
        splitter = SemanticTextSplitter(chunk_size=200, chunk_overlap=20)
        text = "第一段内容在这里。\n\n第二段内容在这里。\n\n第三段内容在这里。"
        chunks = splitter.split_text(text)
        assert len(chunks) >= 1
        # Paragraphs should generally not be split if they fit
        for chunk in chunks:
            assert len(chunk) <= 200

    def test_splits_oversized_paragraph(self):
        splitter = SemanticTextSplitter(chunk_size=30, chunk_overlap=5)
        text = "这是一个非常长的段落，包含了大量的文字内容，需要被切分成多个小块。" * 5
        chunks = splitter.split_text(text)
        assert len(chunks) > 1
        assert all(len(c) <= 30 for c in chunks)

    def test_empty_text(self):
        splitter = SemanticTextSplitter(chunk_size=50, chunk_overlap=5)
        assert splitter.split_text("") == []
        assert splitter.split_text("   ") == []

    def test_sentence_boundaries(self):
        splitter = SemanticTextSplitter(chunk_size=100, chunk_overlap=10)
        text = "第一句。第二句。第三句。第四句。第五句。"
        chunks = splitter.split_text(text)
        assert len(chunks) >= 1
        # Chunks should not cut in the middle of sentences when possible
        for chunk in chunks:
            assert len(chunk) <= 100


class TestGetSplitter:
    def test_recursive_factory(self):
        splitter = get_splitter("recursive", chunk_size=50, chunk_overlap=5)
        assert isinstance(splitter, RecursiveTextSplitter)

    def test_fixed_factory(self):
        splitter = get_splitter("fixed", chunk_size=50, chunk_overlap=5)
        assert isinstance(splitter, FixedLengthTextSplitter)

    def test_semantic_factory(self):
        splitter = get_splitter("semantic", chunk_size=50, chunk_overlap=5)
        assert isinstance(splitter, SemanticTextSplitter)

    def test_unknown_strategy_raises(self):
        with pytest.raises(ValueError, match="Unknown chunking strategy"):
            get_splitter("unknown")

    def test_case_insensitive(self):
        splitter = get_splitter("FIXED", chunk_size=50, chunk_overlap=5)
        assert isinstance(splitter, FixedLengthTextSplitter)
