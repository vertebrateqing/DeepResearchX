"""Run RAG benchmark evaluation using local embedding model.

Usage:
    cd /home/liqing/DeepResearchX/backend
    EMBEDDING_PROVIDER=local uv run python scripts/run_rag_eval_local.py
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

# Ensure backend is on path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from deep_research.config.settings import get_settings
from deep_research.evaluation.models import RAGTestCase
from deep_research.evaluation.rag_evaluator import RAGEvaluator
from deep_research.rag.document_loader import load_document
from deep_research.rag.embedding import EmbeddingService
from deep_research.rag.pipeline import RAGPipeline
from deep_research.rag.vector_store import ChromaVectorStore


async def main() -> int:
    pdf_path = Path("/mnt/c/Users/liqing/Desktop/阿里巴巴集團控股有限公司2025財務年度報告.pdf")
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}")
        return 1

    collection_name = "alibaba_fy2025_benchmark"
    tmp_data = Path("/tmp/alibaba_benchmark_local")
    tmp_data.mkdir(parents=True, exist_ok=True)

    # Clean up old collection if exists
    chroma_dir = tmp_data / "chroma"
    if chroma_dir.exists():
        print(f"Removing old Chroma collection at {chroma_dir}")
        shutil.rmtree(chroma_dir)

    benchmark_path = Path("deep_research/evaluation/datasets/alibaba_fy2025_benchmark.jsonl")
    if not benchmark_path.exists():
        print(f"ERROR: Benchmark not found: {benchmark_path}")
        return 1

    settings = get_settings()
    print(f"Embedding provider: {settings.embedding.provider}")
    print(f"Embedding model: {settings.embedding.model}")
    print(f"Embedding local_model_path: {settings.embedding.local_model_path}")

    # 1. Load document
    print(f"\nLoading PDF: {pdf_path.name}")
    doc = await asyncio.to_thread(load_document, pdf_path)
    print(f"Document loaded: {len(doc.content):,} chars")

    # 2. Setup pipeline with local embedding
    print("Initializing local embedding model...")
    emb_service = EmbeddingService()

    vector_store = ChromaVectorStore(
        collection_name=collection_name,
        persist_directory=str(chroma_dir),
    )
    pipeline = RAGPipeline(
        collection_name=collection_name,
        vector_store=vector_store,
        embedding_service=emb_service,
    )

    # 3. Ingest document
    print("Ingesting into Chroma with local embedding...")
    result = await pipeline.ingest_document(doc)
    print(f"Ingested: {result['chunks']} chunks, doc_id={result['doc_id']}")

    # 4. Run evaluation
    print(f"\nRunning benchmark evaluation: {benchmark_path}")
    evaluator = RAGEvaluator(pipeline=pipeline, benchmark_path=benchmark_path)

    # Run with different top_k values
    for top_k in [5, 10]:
        print(f"\n{'='*60}")
        print(f"Evaluating with top_k={top_k}")
        print(f"{'='*60}")
        report = await evaluator.run(top_k=top_k, ks=[1, 3, 5, 10], hybrid=False)

        print(f"\n--- Results (top_k={top_k}) ---")
        print(f"Total queries: {report.total_queries}")
        print(f"Avg MRR: {report.avg_mrr:.4f}")
        for k, v in sorted(report.avg_precision_at_k.items()):
            print(f"  Precision@{k}: {v:.4f}")
        for k, v in sorted(report.avg_recall_at_k.items()):
            print(f"  Recall@{k}: {v:.4f}")
        for k, v in sorted(report.avg_ndcg_at_k.items()):
            print(f"  NDCG@{k}: {v:.4f}")
        print(f"Failures: {len(report.failures)}")
        if report.failures:
            for f in report.failures:
                print(f"  - {f['query_id']}: {f.get('reason', 'unknown')}")

        print(f"\nPer-category breakdown:")
        for cat, data in sorted(report.per_category.items()):
            print(f"  {cat}: count={data['count']}, "
                  f"mrr={data.get('avg_mrr', 0):.4f}, "
                  f"recall@1={data.get('avg_recall_at_k', {}).get(1, 0):.4f}")

    await pipeline.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
