from __future__ import annotations
"""Evaluation metrics for agent assessment."""

import math
from typing import Any


class MetricsCalculator:
    """Calculate various evaluation metrics."""

    @staticmethod
    def accuracy(predicted: list[Any], expected: list[Any]) -> float:
        """Calculate accuracy."""
        if not expected:
            return 0.0
        correct = sum(1 for p, e in zip(predicted, expected) if p == e)
        return correct / len(expected)

    @staticmethod
    def f1_score(precision: float, recall: float) -> float:
        """Calculate F1 score."""
        if precision + recall == 0:
            return 0.0
        return 2 * (precision * recall) / (precision + recall)

    @staticmethod
    def relevance_score(retrieved: list[str], relevant: list[str]) -> dict[str, float]:
        """Calculate retrieval relevance metrics."""
        if not retrieved:
            return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

        retrieved_set = set(retrieved)
        relevant_set = set(relevant)

        true_positives = len(retrieved_set & relevant_set)

        precision = true_positives / len(retrieved_set) if retrieved_set else 0.0
        recall = true_positives / len(relevant_set) if relevant_set else 0.0
        f1 = MetricsCalculator.f1_score(precision, recall)

        return {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "true_positives": true_positives,
        }

    @staticmethod
    def ndcg(scores: list[float], k: int = 10) -> float:
        """Calculate NDCG@k."""
        if not scores:
            return 0.0

        scores = scores[:k]

        # DCG
        dcg = sum((2**s - 1) / math.log2(i + 2) for i, s in enumerate(scores))

        # IDCG (ideal DCG)
        ideal_scores = sorted(scores, reverse=True)
        idcg = sum((2**s - 1) / math.log2(i + 2) for i, s in enumerate(ideal_scores))

        return dcg / idcg if idcg > 0 else 0.0
