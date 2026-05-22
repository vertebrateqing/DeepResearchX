from __future__ import annotations
"""Index health metrics for uploaded-document collections.

Operates on a live RAGPipeline to inspect the state of the Chroma collection.
"""

import hashlib
import logging
from typing import Any, Optional

from deep_research.rag.pipeline import RAGPipeline

logger = logging.getLogger(__name__)

_REQUIRED_METADATA_FIELDS = {"doc_id", "chunk_index", "filename"}


def duplicate_chunk_rate(pipeline: RAGPipeline) -> float:
    """Fraction of chunks whose text content is an exact duplicate.

    Uses MD5 hashing on stripped text for speed.
    """
    try:
        collection = pipeline.vector_store.collection
        result = collection.get(include=["documents"])
    except Exception as e:
        logger.warning(f"[IndexHealth] failed to read collection: {e}")
        return 0.0

    docs = result.get("documents") or []
    if not docs:
        return 0.0

    seen: set[str] = set()
    dups = 0
    for text in docs:
        if text is None:
            continue
        h = hashlib.md5(text.strip().encode("utf-8")).hexdigest()
        if h in seen:
            dups += 1
        else:
            seen.add(h)

    return dups / len(docs) if docs else 0.0


def metadata_completeness(pipeline: RAGPipeline) -> dict[str, float]:
    """Per-field completeness rate for required metadata keys.

    Returns {field_name: fraction_of_chunks_with_non_empty_value}.
    """
    try:
        collection = pipeline.vector_store.collection
        result = collection.get(include=["metadatas"])
    except Exception as e:
        logger.warning(f"[IndexHealth] failed to read collection: {e}")
        return {f: 0.0 for f in _REQUIRED_METADATA_FIELDS}

    metadatas = result.get("metadatas") or []
    if not metadatas:
        return {f: 0.0 for f in _REQUIRED_METADATA_FIELDS}

    counts: dict[str, int] = {f: 0 for f in _REQUIRED_METADATA_FIELDS}
    for md in metadatas:
        if not md:
            continue
        for field in _REQUIRED_METADATA_FIELDS:
            val = md.get(field)
            if val is not None and str(val).strip():
                counts[field] += 1

    total = len(metadatas)
    return {f: counts[f] / total for f in _REQUIRED_METADATA_FIELDS}


def index_stats(pipeline: RAGPipeline) -> dict[str, Any]:
    """High-level statistics about the collection."""
    try:
        total = pipeline.count()
        docs = pipeline.list_documents()
    except Exception as e:
        logger.warning(f"[IndexHealth] failed to read collection: {e}")
        return {"total_chunks": 0, "total_docs": 0, "avg_chunk_length": 0}

    if total == 0:
        return {"total_chunks": 0, "total_docs": 0, "avg_chunk_length": 0}

    try:
        collection = pipeline.vector_store.collection
        result = collection.get(include=["documents"])
        texts = result.get("documents") or []
        lengths = [len(t) for t in texts if t]
        avg_len = sum(lengths) / len(lengths) if lengths else 0
    except Exception:
        avg_len = 0

    return {
        "total_chunks": total,
        "total_docs": len(docs),
        "avg_chunk_length": round(avg_len, 1),
    }
