"""Unit tests for evaluation metrics calculator."""

import pytest

from deep_research.evaluation.metrics import MetricsCalculator


class TestPrecisionAtK:
    def test_perfect_precision(self):
        retrieved = ["a", "b", "c"]
        relevant = {"a", "b", "c"}
        assert MetricsCalculator.precision_at_k(retrieved, relevant, 3) == 1.0

    def test_zero_precision(self):
        retrieved = ["x", "y", "z"]
        relevant = {"a", "b"}
        assert MetricsCalculator.precision_at_k(retrieved, relevant, 3) == 0.0

    def test_partial_precision(self):
        retrieved = ["a", "x", "b", "y"]
        relevant = {"a", "b", "c"}
        assert MetricsCalculator.precision_at_k(retrieved, relevant, 2) == 0.5
        assert MetricsCalculator.precision_at_k(retrieved, relevant, 4) == 0.5

    def test_k_larger_than_list(self):
        retrieved = ["a"]
        relevant = {"a"}
        assert MetricsCalculator.precision_at_k(retrieved, relevant, 10) == 1.0


class TestRecallAtK:
    def test_perfect_recall(self):
        retrieved = ["a", "b", "c"]
        relevant = {"a", "b"}
        assert MetricsCalculator.recall_at_k(retrieved, relevant, 3) == 1.0

    def test_partial_recall(self):
        retrieved = ["a", "x", "y"]
        relevant = {"a", "b"}
        assert MetricsCalculator.recall_at_k(retrieved, relevant, 3) == 0.5

    def test_empty_relevant(self):
        assert MetricsCalculator.recall_at_k(["a", "b"], set(), 10) == 0.0


class TestF1Score:
    def test_harmonic_mean(self):
        assert MetricsCalculator.f1_score(1.0, 1.0) == 1.0
        assert MetricsCalculator.f1_score(0.0, 1.0) == 0.0
        assert MetricsCalculator.f1_score(0.5, 0.5) == 0.5

    def test_zero_denominator(self):
        assert MetricsCalculator.f1_score(0.0, 0.0) == 0.0


class TestMRR:
    def test_first_position(self):
        assert MetricsCalculator.mrr(["a", "b"], {"a"}) == 1.0

    def test_second_position(self):
        assert MetricsCalculator.mrr(["x", "a", "b"], {"a"}) == 0.5

    def test_no_relevant(self):
        assert MetricsCalculator.mrr(["x", "y"], {"a"}) == 0.0


class TestAveragePrecision:
    def test_perfect_ranking(self):
        # All relevant items at top
        retrieved = ["a", "b", "c", "d"]
        relevant = {"a", "b"}
        # precision@1=1.0, precision@2=1.0 -> AP=1.0
        assert MetricsCalculator.average_precision(retrieved, relevant) == 1.0

    def test_mixed_ranking(self):
        retrieved = ["a", "x", "b", "y"]
        relevant = {"a", "b"}
        # precision@1=1.0, precision@3=2/3 -> AP=(1.0 + 2/3)/2 = 5/6
        assert MetricsCalculator.average_precision(retrieved, relevant) == pytest.approx(5 / 6)

    def test_empty_relevant(self):
        assert MetricsCalculator.average_precision(["a", "b"], set()) == 0.0


class TestNDCG:
    def test_perfect_relevance(self):
        scores = [3, 3, 3]
        assert MetricsCalculator.ndcg_at_k(scores, 3) == 1.0

    def test_zero_relevance(self):
        assert MetricsCalculator.ndcg_at_k([0, 0, 0], 3) == 0.0

    def test_mixed_relevance(self):
        # Ideal: [3, 2, 1]
        # Actual: [3, 1, 2]
        actual = MetricsCalculator.ndcg_at_k([3, 1, 2], 3)
        ideal = MetricsCalculator.ndcg_at_k([3, 2, 1], 3)
        assert actual < ideal

    def test_k_cutoff(self):
        # Not in ideal order — k should matter
        scores = [1, 3, 2, 0]
        assert MetricsCalculator.ndcg_at_k(scores, 2) != MetricsCalculator.ndcg_at_k(scores, 4)
        assert MetricsCalculator.ndcg_at_k(scores, 4) > MetricsCalculator.ndcg_at_k(scores, 2)
