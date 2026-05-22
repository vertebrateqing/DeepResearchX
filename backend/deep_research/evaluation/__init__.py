from __future__ import annotations
"""DeepResearchX evaluation module — RAG retrieval quality assessment.

Independent package; not imported by the main pipeline. Run via CLI or
explicit script calls.
"""

from deep_research.evaluation.metrics import MetricsCalculator
from deep_research.evaluation.models import (
    RAGBenchmarkReport,
    RAGQueryResult,
    RAGTestCase,
)
from deep_research.evaluation.rag_evaluator import RAGEvaluator

__all__ = [
    "MetricsCalculator",
    "RAGTestCase",
    "RAGQueryResult",
    "RAGBenchmarkReport",
    "RAGEvaluator",
]
