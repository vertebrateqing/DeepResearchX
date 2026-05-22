"""CLI runner for RAG evaluation on uploaded documents.

Usage:
    cd backend
    uv run python scripts/run_rag_eval.py \
        --collection session_uploads_xxx \
        --dataset deep_research/evaluation/datasets/rag_benchmark.jsonl \
        --output ./eval_results/
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from deep_research.evaluation.rag_evaluator import RAGEvaluator
from deep_research.evaluation.reporter import EvaluationReporter
from deep_research.rag.pipeline import RAGPipeline


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run RAG evaluation benchmark")
    parser.add_argument("--collection", required=True, help="Chroma collection name")
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to rag_benchmark.jsonl",
    )
    parser.add_argument(
        "--output",
        default="./eval_results",
        help="Directory to write JSON + Markdown reports",
    )
    parser.add_argument("--top-k", type=int, default=10, help="Retrieval top-k")
    parser.add_argument(
        "--ks",
        default="1,3,5,10",
        help="Comma-separated k values for metrics",
    )
    args = parser.parse_args()

    ks = [int(x.strip()) for x in args.ks.split(",") if x.strip()]

    pipeline = RAGPipeline(collection_name=args.collection)
    evaluator = RAGEvaluator(pipeline=pipeline, benchmark_path=args.dataset)

    print(f"Running RAG evaluation: {len(evaluator.cases)} queries, top_k={args.top_k}, ks={ks}")
    report = await evaluator.run(top_k=args.top_k, ks=ks)

    reporter = EvaluationReporter(report)
    json_path, md_path = reporter.save(args.output)

    print(f"\nReport saved:")
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")
    print(f"\nSummary:")
    print(f"  MRR:    {report.avg_mrr:.4f}")
    for k in sorted(report.avg_recall_at_k.keys()):
        print(f"  R@{k}:    {report.avg_recall_at_k[k]:.4f}")
    for k in sorted(report.avg_precision_at_k.keys()):
        print(f"  P@{k}:    {report.avg_precision_at_k[k]:.4f}")
    print(f"  Failures: {len(report.failures)}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
