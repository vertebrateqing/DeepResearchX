from __future__ import annotations
"""Pydantic models for evaluation data structures."""

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class RAGTestCase(BaseModel):
    """A single RAG evaluation test case."""

    query_id: str
    query: str
    collection_name: Optional[str] = None
    relevant_doc_ids: list[str] = Field(default_factory=list)
    relevant_chunk_ids: list[str] = Field(default_factory=list)
    relevance_scores: dict[str, int] = Field(default_factory=dict)
    category: str = "general"
    expected_answer: str = ""


class RAGQueryResult(BaseModel):
    """Result of evaluating a single query."""

    query_id: str
    query: str
    precision_at_k: dict[int, float] = Field(default_factory=dict)
    recall_at_k: dict[int, float] = Field(default_factory=dict)
    mrr: float = 0.0
    ndcg_at_k: dict[int, float] = Field(default_factory=dict)
    latency_ms: float = 0.0
    source_diversity: float = 0.0
    retrieved_count: int = 0
    retrieved_ids: list[str] = Field(default_factory=list)


class QueryDetail(BaseModel):
    """Human-readable detail for a single benchmark query."""

    query_id: str
    query: str
    category: str = "general"
    expected_answer: str = ""
    precision_at_k: dict[int, float] = Field(default_factory=dict)
    recall_at_k: dict[int, float] = Field(default_factory=dict)
    mrr: float = 0.0
    ndcg_at_k: dict[int, float] = Field(default_factory=dict)
    latency_ms: float = 0.0
    retrieved_count: int = 0
    failure_reason: str = ""
    # Chunk text content for human review
    relevant_chunks: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_chunks: list[dict[str, Any]] = Field(default_factory=list)
    # Document info
    relevant_docs: list[dict[str, Any]] = Field(default_factory=list)


class RAGBenchmarkReport(BaseModel):
    """Aggregated report across all benchmark queries."""

    total_queries: int = 0
    avg_precision_at_k: dict[int, float] = Field(default_factory=dict)
    avg_recall_at_k: dict[int, float] = Field(default_factory=dict)
    avg_mrr: float = 0.0
    avg_ndcg_at_k: dict[int, float] = Field(default_factory=dict)
    avg_latency_ms: float = 0.0
    avg_source_diversity: float = 0.0
    per_category: dict[str, dict[str, Any]] = Field(default_factory=dict)
    failures: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    per_query_results: list[QueryDetail] = Field(default_factory=list)
