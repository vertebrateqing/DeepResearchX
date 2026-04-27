"""Script to run agent evaluation."""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from financial_agent.evaluation.evaluator import AgentEvaluator
from financial_agent.evaluation.report import EvaluationReport

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_evaluation(benchmark_path: str, output_path: str) -> None:
    """Run evaluation on a benchmark."""
    evaluator = AgentEvaluator()

    logger.info(f"Running evaluation on {benchmark_path}")
    report = await evaluator.run_benchmark(benchmark_path, output_path)

    summary = report.get_summary()
    logger.info(f"Evaluation complete. Average score: {summary.get('avg_score', 0):.2f}")

    # Print summary
    print("\n" + "=" * 50)
    print("EVALUATION SUMMARY")
    print("=" * 50)
    print(f"Total cases: {summary.get('total_cases', 0)}")
    print(f"Average score: {summary.get('avg_score', 0):.2f}")
    print(f"Min score: {summary.get('min_score', 0):.2f}")
    print(f"Max score: {summary.get('max_score', 0):.2f}")
    print("\nCategory scores:")
    for cat, score in summary.get("category_scores", {}).items():
        print(f"  {cat}: {score:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run agent evaluation")
    parser.add_argument("--benchmark", required=True, help="Path to benchmark JSON file")
    parser.add_argument("--output", default="./evaluation_report", help="Output path for report")

    args = parser.parse_args()
    asyncio.run(run_evaluation(args.benchmark, args.output))


if __name__ == "__main__":
    main()
