from __future__ import annotations
"""Text splitting for long documents."""

import logging
import re
from typing import Optional

from deep_research.config.settings import get_settings

logger = logging.getLogger(__name__)


class RecursiveTextSplitter:
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
        """Split text into chunks."""
        return self._recursive_split(text, self.separators)

    def _recursive_split(self, text: str, separators: list[str]) -> list[str]:
        """Recursively split text."""
        final_chunks = []

        # Get the appropriate separator
        separator = separators[-1] if separators else ""
        new_separators = []

        for i, s in enumerate(separators):
            if s == "":
                separator = s
                break
            if re.search(s, text):
                separator = s
                new_separators = separators[i + 1 :]
                break

        # Split text
        splits = self._split_text_with_regex(text, separator)

        # Process splits
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
        """Split text using regex separator."""
        if not separator:
            return list(text)
        # Escape special regex characters
        escaped = re.escape(separator)
        splits = re.split(f"({escaped})", text)
        # Combine separator with preceding text
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
        """Merge splits into chunks of appropriate size."""
        docs = []
        current_doc = []
        current_length = 0

        for s in splits:
            s_len = self.length_function(s)
            if current_length + s_len > self.chunk_size and current_doc:
                # Save current doc
                docs.append(self._join_docs(current_doc, separator))
                # Keep overlap
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
        """Join documents with separator."""
        text = separator.join(docs)
        return text.strip()
