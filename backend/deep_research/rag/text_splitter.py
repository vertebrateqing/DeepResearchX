from __future__ import annotations
"""Backward-compatible re-export of RecursiveTextSplitter.

New code should import from ``deep_research.rag.chunking`` instead.
"""

from deep_research.rag.chunking import RecursiveTextSplitter

__all__ = ["RecursiveTextSplitter"]
