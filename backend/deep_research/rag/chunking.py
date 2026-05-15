from __future__ import annotations
"""Text chunking strategies for RAG.

Strategies
----------
recursive   : Recursively split by separators (paragraph → sentence → word → char).
              Best general-purpose strategy; preserves natural boundaries.
fixed       : Fixed-length character split with overlap.
              Fastest, most predictable; may cut mid-sentence.
semantic    : Paragraph / sentence boundary preservation with optional
              embedding-based topic-shift detection.
              Best for preserving meaning; slower if embeddings enabled.
"""

import logging
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from deep_research.config.settings import get_settings

if TYPE_CHECKING:
    from deep_research.rag.embedding import EmbeddingService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_SENTENCE_DELIMITERS = re.compile(r"([。！？\.\?!]+)")


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences (Chinese + English aware)."""
    parts = _SENTENCE_DELIMITERS.split(text)
    sentences: list[str] = []
    i = 0
    while i < len(parts):
        s = parts[i]
        # attach the delimiter to the preceding sentence
        if i + 1 < len(parts):
            s += parts[i + 1]
            i += 2
        else:
            i += 1
        s = s.strip()
        if s:
            sentences.append(s)
    return sentences


def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs by double newlines."""
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _merge_small_chunks(chunks: list[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    """Merge adjacent chunks that are smaller than chunk_size."""
    if not chunks:
        return []
    merged: list[str] = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = merged[-1]
        curr = chunks[i]
        if len(prev) + len(curr) <= chunk_size:
            merged[-1] = prev + "\n" + curr
        else:
            merged.append(curr)
    # Apply overlap by ensuring no chunk exceeds chunk_size
    result: list[str] = []
    for chunk in merged:
        if len(chunk) <= chunk_size:
            result.append(chunk)
            continue
        # If still too large, split by sentences
        sentences = _split_sentences(chunk)
        current = ""
        for s in sentences:
            if len(current) + len(s) + 1 > chunk_size and current:
                result.append(current.strip())
                # overlap: keep last sentences up to chunk_overlap
                overlap_text = ""
                for prev_s in reversed(current.split("\n")):
                    if len(overlap_text) + len(prev_s) + 1 > chunk_overlap:
                        break
                    overlap_text = prev_s + "\n" + overlap_text if overlap_text else prev_s
                current = overlap_text + "\n" + s if overlap_text else s
            else:
                current = current + "\n" + s if current else s
        if current.strip():
            if len(current) <= chunk_size:
                result.append(current.strip())
            else:
                # Ultimate fallback: force-split with fixed-length
                fallback = FixedLengthTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
                result.extend(fallback.split_text(current))
    return result


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class BaseTextSplitter(ABC):
    """Abstract base for text splitters."""

    @abstractmethod
    def split_text(self, text: str) -> list[str]:
        """Split ``text`` into chunks and return them."""


# ---------------------------------------------------------------------------
# 1. Recursive text splitter (existing behaviour)
# ---------------------------------------------------------------------------


class RecursiveTextSplitter(BaseTextSplitter):
    """Recursively split text by separators, optimized for Chinese."""

    def __init__(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        separators: Optional[list[str]] = None,
        length_function: callable = len,
    ) -> None:
        settings = get_settings().rag.text_splitter
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        self.separators = separators or settings.separators
        self.length_function = length_function

    def split_text(self, text: str) -> list[str]:
        return self._recursive_split(text, self.separators)

    def _recursive_split(self, text: str, separators: list[str]) -> list[str]:
        final_chunks = []
        separator = separators[-1] if separators else ""
        new_separators: list[str] = []

        for i, s in enumerate(separators):
            if s == "":
                separator = s
                break
            if re.search(s, text):
                separator = s
                new_separators = separators[i + 1 :]
                break

        splits = self._split_text_with_regex(text, separator)
        good_splits = []
        for s in splits:
            if self.length_function(s) < self.chunk_size:
                good_splits.append(s)
            else:
                if good_splits:
                    final_chunks.extend(self._merge_splits(good_splits, separator))
                    good_splits = []
                if not new_separators:
                    final_chunks.append(s)
                else:
                    final_chunks.extend(self._recursive_split(s, new_separators))

        if good_splits:
            final_chunks.extend(self._merge_splits(good_splits, separator))

        return final_chunks

    def _split_text_with_regex(self, text: str, separator: str) -> list[str]:
        if not separator:
            return list(text)
        escaped = re.escape(separator)
        splits = re.split(f"({escaped})", text)
        result = []
        current = ""
        for i, s in enumerate(splits):
            if i % 2 == 0:
                current = s
            else:
                current += s
                result.append(current)
                current = ""
        if current:
            result.append(current)
        return [s for s in result if s]

    def _merge_splits(self, splits: list[str], separator: str) -> list[str]:
        docs = []
        current_doc = []
        current_length = 0

        for s in splits:
            s_len = self.length_function(s)
            if current_length + s_len > self.chunk_size and current_doc:
                docs.append(self._join_docs(current_doc, separator))
                while current_length > self.chunk_overlap and current_doc:
                    current_doc.pop(0)
                    current_length = sum(self.length_function(x) for x in current_doc)
                current_doc = []
                current_length = 0

            current_doc.append(s)
            current_length += s_len

        if current_doc:
            docs.append(self._join_docs(current_doc, separator))

        return [d for d in docs if d]

    def _join_docs(self, docs: list[str], separator: str) -> str:
        text = separator.join(docs)
        return text.strip()


# ---------------------------------------------------------------------------
# 2. Fixed-length text splitter
# ---------------------------------------------------------------------------


class FixedLengthTextSplitter(BaseTextSplitter):
    """Fixed-length character splitter with overlap.

    Fastest strategy; guarantees every chunk is exactly ``chunk_size``
    (except the last). May cut mid-sentence — use for structured / tabular
    text where natural boundaries don't matter.
    """

    def __init__(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> None:
        settings = get_settings().rag.text_splitter
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap

    def split_text(self, text: str) -> list[str]:
        if not text:
            return []
        chunks = []
        start = 0
        step = self.chunk_size - self.chunk_overlap
        while start < len(text):
            end = start + self.chunk_size
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start += step
            # Avoid infinite loop on tiny step
            if step <= 0:
                start = end
        return chunks


# ---------------------------------------------------------------------------
# 3. Semantic text splitter
# ---------------------------------------------------------------------------


class SemanticTextSplitter(BaseTextSplitter):
    """Semantic boundary-preserving splitter.

    Algorithm:
    1. Split by paragraphs (preserves highest-level semantic boundary).
    2. For paragraphs larger than ``chunk_size``, split by sentences.
    3. Merge very small adjacent chunks to reduce fragmentation.
    4. Optional: if ``embedding_service`` is provided, detect topic shifts
       between adjacent chunks and split where similarity drops below
       ``threshold``.

    Parameters
    ----------
    chunk_size : int
        Target chunk size in characters.
    chunk_overlap : int
        Overlap in characters when sentence-level fallback is needed.
    threshold : float
        Cosine-similarity threshold for topic-shift detection.
        Only active when ``embedding_service`` is given.
    embedding_service : EmbeddingService | None
        If provided, embeddings are used to refine boundaries.
    """

    def __init__(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        threshold: float = 0.65,
        embedding_service: Optional["EmbeddingService"] = None,
    ) -> None:
        settings = get_settings().rag.text_splitter
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        self.threshold = threshold
        self.embedding_service = embedding_service

    def split_text(self, text: str) -> list[str]:
        if not text.strip():
            return []

        paragraphs = _split_paragraphs(text)
        if not paragraphs:
            paragraphs = [text.strip()]

        # Stage 1: paragraph-based chunks (split oversized paragraphs by sentences)
        stage1: list[str] = []
        for para in paragraphs:
            if len(para) <= self.chunk_size:
                stage1.append(para)
            else:
                sentences = _split_sentences(para)
                current = ""
                for s in sentences:
                    if len(current) + len(s) + 1 > self.chunk_size and current:
                        stage1.append(current.strip())
                        current = s
                    else:
                        current = current + " " + s if current else s
                if current.strip():
                    stage1.append(current.strip())

        # Stage 2: merge tiny chunks with neighbours
        stage2 = _merge_small_chunks(stage1, self.chunk_size, self.chunk_overlap)

        # Stage 3: optional embedding-based topic-shift refinement
        if self.embedding_service and len(stage2) > 1:
            return self._refine_by_embeddings(stage2)

        return stage2

    def _refine_by_embeddings(self, chunks: list[str]) -> list[str]:
        """Merge adjacent chunks whose embedding similarity > threshold."""
        import asyncio

        try:
            # Run the async embedding comparison synchronously (ingest runs
            # inside asyncio.to_thread anyway, so this won't block the event
            # loop).
            return asyncio.get_event_loop().run_until_complete(
                self._async_refine(chunks)
            )
        except RuntimeError:
            # No running event loop — safe to create one
            return asyncio.run(self._async_refine(chunks))

    async def _async_refine(self, chunks: list[str]) -> list[str]:
        import numpy as np

        embeddings = await self.embedding_service.embed_texts(chunks)
        vectors = [np.array(e) for e in embeddings]
        for v in vectors:
            v /= np.linalg.norm(v) + 1e-10

        merged: list[str] = [chunks[0]]
        for i in range(1, len(chunks)):
            sim = float(np.dot(vectors[i - 1], vectors[i]))
            prev_len = len(merged[-1])
            curr_len = len(chunks[i])
            if sim > self.threshold and prev_len + curr_len <= self.chunk_size:
                merged[-1] = merged[-1] + "\n" + chunks[i]
            else:
                merged.append(chunks[i])
        return merged


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_splitter(
    strategy: str = "recursive",
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    embedding_service: Optional["EmbeddingService"] = None,
) -> BaseTextSplitter:
    """Return a text splitter by strategy name.

    Supported strategies: ``recursive``, ``fixed``, ``semantic``.
    """
    strategy = strategy.lower().strip()
    if strategy == "recursive":
        return RecursiveTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    if strategy == "fixed":
        return FixedLengthTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    if strategy == "semantic":
        return SemanticTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            embedding_service=embedding_service,
        )
    raise ValueError(f"Unknown chunking strategy {strategy!r}; choose from: recursive, fixed, semantic")
