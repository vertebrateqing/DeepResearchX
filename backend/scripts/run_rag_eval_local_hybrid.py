"""Run RAG benchmark evaluation using local embedding + hybrid retrieval.

Usage:
    cd /home/liqing/DeepResearchX/backend
    EMBEDDING_PROVIDER=local uv run python scripts/run_rag_eval_local_hybrid.py
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from deep_research.config.settings import get_settings
from deep_research.evaluation.rag_evaluator import RAGEvaluator
from deep_research.evaluation.reporter import EvaluationReporter
from deep_research.rag.document_loader import load_document
from deep_research.rag.embedding import EmbeddingService
from deep_research.rag.pipeline import RAGPipeline
from deep_research.rag.vector_store import ChromaVectorStore


QUERY_SEARCH_TERMS: dict[str, list[str]] = {
    "alibaba_001": ["996,347", "941,168", "總收入"],
    "alibaba_002": ["322,346", "客戶管理"],
    "alibaba_003": ["118,028", "雲智能集團", "世界第四大", "亞太地區最大"],
    "alibaba_004": ["132,300", "阿里國際數字商業集團"],
    "alibaba_005": ["AI基礎設施", "雲和AI", "AI驅動"],
    "alibaba_006": ["46億美元", "119億美元", "股份回購"],
    "alibaba_007": ["125,976", "淨利潤"],
    "alibaba_008": ["33%", "速賣通", "Trendyol", "Lazada"],
    "alibaba_009": ["競爭", "監管", "風險因素"],
    "alibaba_010": [],
}


def _find_relevant_chunks(all_chunks: list[dict], terms: list[str]) -> list[str]:
    if not terms:
        return []
    results = []
    for c in all_chunks:
        text = c.get("text", "")
        if any(t in text for t in terms):
            results.append(c["id"])
    return results


async def main() -> int:
    pdf_path = Path("/mnt/c/Users/liqing/Desktop/阿里巴巴集團控股有限公司2025財務年度報告.pdf")
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}")
        return 1

    collection_name = "alibaba_fy2025_benchmark"
    tmp_data = Path("/tmp/alibaba_benchmark_local_v2")
    tmp_data.mkdir(parents=True, exist_ok=True)
    chroma_dir = tmp_data / "chroma"

    benchmark_path = Path("deep_research/evaluation/datasets/alibaba_fy2025_benchmark.jsonl")

    settings = get_settings()
    print(f"Embedding provider: {settings.embedding.provider}")

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

    # Check if already ingested
    collection = pipeline.vector_store.collection
    count = collection.count()
    if count == 0:
        print(f"\nLoading PDF: {pdf_path.name}")
        doc = await asyncio.to_thread(load_document, pdf_path)
        print(f"Document loaded: {len(doc.content):,} chars")
        print("Ingesting into Chroma with local embedding...")
        result = await pipeline.ingest_document(doc)
        print(f"Ingested: {result['chunks']} chunks, doc_id={result['doc_id']}")
        doc_id = result["doc_id"]
    else:
        print(f"Using existing collection: {count} chunks")
        # Get doc_id from existing chunks
        all_meta = collection.get(include=["metadatas"])
        metas = all_meta.get("metadatas", [])
        doc_id = metas[0].get("doc_id") if metas else "unknown"
        print(f"Doc ID: {doc_id}")

    # Retrieve all chunks for relevance discovery
    all_data = collection.get(include=["documents", "metadatas"])
    all_chunks = []
    ids = all_data.get("ids", [])
    docs = all_data.get("documents", [])
    for i in range(len(ids)):
        all_chunks.append({"id": ids[i], "text": docs[i] if docs else "", "index": i})

    # Auto-discover relevant chunk IDs
    updated_cases = []
    with open(benchmark_path, "r", encoding="utf-8") as f:
        for line in f:
            case = json.loads(line)
            qid = case["query_id"]
            terms = QUERY_SEARCH_TERMS.get(qid, [])
            relevant_ids = _find_relevant_chunks(all_chunks, terms)
            case["relevant_doc_ids"] = [doc_id] if relevant_ids else []
            case["relevant_chunk_ids"] = relevant_ids
            case["relevance_scores"] = {cid: 2 for cid in relevant_ids}
            updated_cases.append(case)

    updated_path = tmp_data / "benchmark_updated.jsonl"
    with open(updated_path, "w", encoding="utf-8") as f:
        for case in updated_cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    evaluator = RAGEvaluator(pipeline=pipeline, benchmark_path=updated_path)

    for hybrid in [False, True]:
        mode = "hybrid" if hybrid else "vector-only"
        print(f"\n{'='*70}")
        print(f"Evaluating with {mode.upper()} retrieval")
        print(f"{'='*70}")

        report = await evaluator.run(top_k=10, ks=[1, 3, 5, 10], hybrid=hybrid)

        print(f"\n--- Results ({mode}) ---")
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
            for f_ in report.failures:
                print(f"  - {f_['query_id']}: {f_.get('reason', 'unknown')}")

        print(f"\nPer-category breakdown:")
        for cat, data in sorted(report.per_category.items()):
            print(f"  {cat}: count={data['count']}, "
                  f"mrr={data.get('avg_mrr', 0):.4f}, "
                  f"recall@1={data.get('avg_recall_at_k', {}).get(1, 0):.4f}")

        # Save human-readable report
        reporter = EvaluationReporter(report)
        out_dir = tmp_data / f"reports_{mode}"
        json_path, md_path = reporter.save(out_dir)
        print(f"\nReport saved:")
        print(f"  JSON: {json_path}")
        print(f"  MD:   {md_path}")

    await pipeline.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
