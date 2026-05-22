from __future__ import annotations
"""Evaluation metrics for RAG and retrieval assessment.

Pure functions — no external dependencies, no LLM calls, no DB access.
"""

import math
from typing import Any


class MetricsCalculator:
    """Calculate retrieval and ranking metrics."""

    @staticmethod
    def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
        """Precision@k: fraction of top-k results that are relevant."""
        if k <= 0:
            return 0.0
        top_k = retrieved[:k]
        if not top_k:
            return 0.0
        return len(set(top_k) & relevant) / len(top_k)

    @staticmethod
    def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
        """Recall@k: fraction of relevant items found in top-k."""
        if not relevant:
            return 0.0
        top_k = retrieved[:k]
        return len(set(top_k) & relevant) / len(relevant)

    @staticmethod
    def f1_score(precision: float, recall: float) -> float:
        """F1 score: harmonic mean of precision and recall."""
        if precision + recall == 0:
            return 0.0
        return 2 * (precision * recall) / (precision + recall)

    @staticmethod
    def mrr(retrieved: list[str], relevant: set[str]) -> float:
        """Mean Reciprocal Rank: 1 / rank of first relevant item."""
        for rank, item in enumerate(retrieved, start=1):
            if item in relevant:
                return 1.0 / rank
        return 0.0

    @staticmethod
    def average_precision(retrieved: list[str], relevant: set[str]) -> float:
        """Average Precision (AP): mean of precision@k at each relevant rank."""
        if not relevant:
            return 0.0
        hits = 0
        sum_precisions = 0.0
        for rank, item in enumerate(retrieved, start=1):
            if item in relevant:
                hits += 1
                sum_precisions += hits / rank
        return sum_precisions / len(relevant)

    @staticmethod
    def ndcg_at_k(relevance_scores: list[float], k: int = 10) -> float:
        """NDCG@k: Normalized Discounted Cumulative Gain.

        Args:
            relevance_scores: Ordered list of relevance grades (>=0) for each
                retrieved item. Higher = more relevant.
            k: Cut-off rank.
        """
        if not relevance_scores:
            return 0.0
        scores = relevance_scores[:k]
        dcg = sum((2**s - 1) / math.log2(i + 2) for i, s in enumerate(scores))
        ideal_scores = sorted(scores, reverse=True)
        idcg = sum((2**s - 1) / math.log2(i + 2) for i, s in enumerate(ideal_scores))
        return dcg / idcg if idcg > 0 else 0.0

    @staticmethod
    def accuracy(predicted: list[Any], expected: list[Any]) -> float:
        """Element-wise accuracy between two ordered lists."""
        if not expected:
            return 0.0
        correct = sum(1 for p, e in zip(predicted, expected) if p == e)
        return correct / len(expected)
