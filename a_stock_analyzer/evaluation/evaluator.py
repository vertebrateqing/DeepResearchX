"""Agent evaluation runner."""

import json
import logging
from pathlib import Path
from typing import Any

from a_stock_analyzer.core.orchestrator import OrchestratorAgent
from a_stock_analyzer.evaluation.llm_judge import LLMJudge
from a_stock_analyzer.evaluation.metrics import MetricsCalculator
from a_stock_analyzer.evaluation.report import EvaluationReport

logger = logging.getLogger(__name__)


class AgentEvaluator:
    """Evaluate agent performance on benchmark datasets."""

    def __init__(
        self,
        orchestrator: OrchestratorAgent | None = None,
        judge: LLMJudge | None = None,
    ) -> None:
        self.orchestrator = orchestrator or OrchestratorAgent()
        self.judge = judge or LLMJudge()
        self.metrics = MetricsCalculator()

    async def run_benchmark(
        self,
        benchmark_path: str | Path,
        output_path: str | Path | None = None,
    ) -> EvaluationReport:
        """Run evaluation on a benchmark dataset.

        Args:
            benchmark_path: Path to benchmark JSON file
            output_path: Path to save evaluation report

        Returns:
            EvaluationReport with results
        """
        benchmark_path = Path(benchmark_path)
        with open(benchmark_path, "r", encoding="utf-8") as f:
            benchmark = json.load(f)

        report = EvaluationReport(name=benchmark.get("name", "unnamed"))

        for item in benchmark.get("test_cases", []):
            result = await self._evaluate_case(item)
            report.add_result(result)

        if output_path:
            report.save(output_path)

        return report

    async def _evaluate_case(self, case: dict[str, Any]) -> dict[str, Any]:
        """Evaluate a single test case."""
        question = case["question"]
        expected = case.get("expected_answer", "")
        category = case.get("category", "general")

        logger.info(f"Evaluating case: {question[:80]}...")

        # Run agent
        try:
            response = await self.orchestrator.run(question)
            actual = response.content
            if isinstance(actual, dict):
                actual = actual.get("report", str(actual))
        except Exception as e:
            logger.error(f"Agent failed on case: {e}")
            actual = f"ERROR: {str(e)}"

        # Evaluate with LLM judge
        judge_result = await self.judge.evaluate_answer(
            question=question,
            answer=actual,
            reference=expected,
        )

        return {
            "question": question,
            "category": category,
            "expected": expected,
            "actual": actual,
            "judge_scores": judge_result.get("scores", {}),
            "overall_score": judge_result.get("overall_score", 0),
            "reasoning": judge_result.get("reasoning", ""),
        }

    async def evaluate_rag(
        self,
        test_cases: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Evaluate RAG retrieval quality.

        Args:
            test_cases: List of {"query": str, "relevant_docs": list[str]}

        Returns:
            Retrieval metrics
        """
        from a_stock_analyzer.rag.pipeline import RAGPipeline

        pipeline = RAGPipeline()
        all_precision = []
        all_recall = []
        all_f1 = []

        for case in test_cases:
            query = case["query"]
            relevant = case["relevant_docs"]

            result = await pipeline.query(query, top_k=10)
            retrieved = [r["id"] for r in result["results"]]

            metrics = self.metrics.relevance_score(retrieved, relevant)
            all_precision.append(metrics["precision"])
            all_recall.append(metrics["recall"])
            all_f1.append(metrics["f1"])

        return {
            "avg_precision": sum(all_precision) / len(all_precision) if all_precision else 0,
            "avg_recall": sum(all_recall) / len(all_recall) if all_recall else 0,
            "avg_f1": sum(all_f1) / len(all_f1) if all_f1 else 0,
            "num_queries": len(test_cases),
        }
