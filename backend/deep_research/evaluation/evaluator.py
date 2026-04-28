from __future__ import annotations
"""Agent evaluation runner."""

import json
import logging
from pathlib import Path
from typing import Any

from deep_research.core.orchestrator import OrchestratorAgent
from deep_research.evaluation.llm_judge import LLMJudge
from deep_research.evaluation.report import EvaluationReport

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

