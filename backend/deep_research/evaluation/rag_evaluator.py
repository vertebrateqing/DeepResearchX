from __future__ import annotations
"""RAG retrieval evaluator — benchmark a RAGPipeline against annotated queries."""

import json
import time
from pathlib import Path
from typing import Any, Optional

from deep_research.evaluation.metrics import MetricsCalculator
from deep_research.evaluation.models import (
    QueryDetail,
    RAGBenchmarkReport,
    RAGQueryResult,
    RAGTestCase,
)
from deep_research.rag.pipeline import RAGPipeline


_DEFAULT_KS = [1, 3, 5, 10]


class RAGEvaluator:
    """Evaluate a RAGPipeline against a benchmark dataset of annotated queries."""

    def __init__(
        self,
        pipeline: RAGPipeline,
        benchmark_path: Path | str,
    ) -> None:
        self.pipeline = pipeline
        self.cases = self._load_benchmark(benchmark_path)
        self._chunk_texts: dict[str, str] = {}
        self._chunk_metas: dict[str, dict[str, Any]] = {}
        self._doc_info: dict[str, dict[str, Any]] = {}
        self._preloaded = False

    def _preload_chunks(self) -> None:
        """Pre-load all chunk texts and metadatas from the vector store."""
        if self._preloaded:
            return
        collection = self.pipeline.vector_store.collection
        all_data = collection.get(include=["documents", "metadatas"])
        ids = all_data.get("ids", [])
        docs = all_data.get("documents", [])
        metas = all_data.get("metadatas", [])
        for i in range(len(ids)):
            cid = ids[i]
            self._chunk_texts[cid] = docs[i] if docs else ""
            meta = metas[i] if metas else {}
            self._chunk_metas[cid] = meta
            doc_id = meta.get("doc_id", "")
            if doc_id and doc_id not in self._doc_info:
                self._doc_info[doc_id] = {
                    "doc_id": doc_id,
                    "source": meta.get("source", ""),
                    "filename": meta.get("filename", ""),
                }
        self._preloaded = True

    def _get_chunk_detail(self, chunk_id: str, relevance_score: float = 0.0) -> dict[str, Any]:
        """Build human-readable chunk detail."""
        text = self._chunk_texts.get(chunk_id, "")
        meta = self._chunk_metas.get(chunk_id, {})
        return {
            "id": chunk_id,
            "text": text,
            "text_preview": text[:500] if text else "",
            "relevance_score": relevance_score,
            "doc_id": meta.get("doc_id", ""),
            "chunk_index": meta.get("chunk_index", -1),
            "chunk_size": meta.get("chunk_size", 0),
        }

    def _get_doc_detail(self, doc_id: str) -> dict[str, Any]:
        """Build human-readable doc detail."""
        info = self._doc_info.get(doc_id, {})
        return {
            "doc_id": doc_id,
            "source": info.get("source", ""),
            "filename": info.get("filename", ""),
        }

    @staticmethod
    def _load_benchmark(path: Path | str) -> list[RAGTestCase]:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Benchmark file not found: {path}")

        cases: list[RAGTestCase] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                cases.append(RAGTestCase.model_validate_json(line))
        return cases

    async def evaluate_query(
        self,
        case: RAGTestCase,
        top_k: int = 10,
        ks: Optional[list[int]] = None,
        hybrid: bool = True,
    ) -> RAGQueryResult:
        """Run a single benchmark case and compute all metrics."""
        ks = ks or _DEFAULT_KS
        relevant_ids = set(case.relevant_chunk_ids)

        # Run retrieval and time it
        t0 = time.perf_counter()
        hits = await self.pipeline.query(case.query, top_k=top_k, hybrid=hybrid)
        latency_ms = (time.perf_counter() - t0) * 1000

        retrieved_ids = [str(hit.get("id", "")) for hit in hits]
        retrieved_doc_ids = {str(hit.get("metadata", {}).get("doc_id", "")) for hit in hits}
        retrieved_doc_ids.discard("")

        # Build relevance scores for NDCG (0 for non-relevant)
        relevance_scores: list[float] = []
        for hit in hits:
            chunk_id = str(hit.get("id", ""))
            if chunk_id in case.relevance_scores:
                relevance_scores.append(float(case.relevance_scores[chunk_id]))
            elif chunk_id in relevant_ids:
                relevance_scores.append(1.0)
            else:
                relevance_scores.append(0.0)

        # Compute per-k metrics
        precisions: dict[int, float] = {}
        recalls: dict[int, float] = {}
        ndcgs: dict[int, float] = {}
        calc = MetricsCalculator()

        for k in ks:
            precisions[k] = calc.precision_at_k(retrieved_ids, relevant_ids, k)
            recalls[k] = calc.recall_at_k(retrieved_ids, relevant_ids, k)
            ndcgs[k] = calc.ndcg_at_k(relevance_scores, k)

        source_diversity = (
            len(retrieved_doc_ids) / len(hits) if hits else 0.0
        )

        return RAGQueryResult(
            query_id=case.query_id,
            query=case.query,
            precision_at_k=precisions,
            recall_at_k=recalls,
            mrr=calc.mrr(retrieved_ids, relevant_ids),
            ndcg_at_k=ndcgs,
            latency_ms=round(latency_ms, 2),
            source_diversity=round(source_diversity, 4),
            retrieved_count=len(hits),
            retrieved_ids=retrieved_ids,
        )

    async def run(
        self,
        top_k: int = 10,
        ks: Optional[list[int]] = None,
        hybrid: bool = True,
    ) -> RAGBenchmarkReport:
        """Run all benchmark cases and produce an aggregated report."""
        ks = ks or _DEFAULT_KS
        results: list[RAGQueryResult] = []
        failures: list[dict[str, Any]] = []
        per_category: dict[str, list[RAGQueryResult]] = {}
        query_details: list[QueryDetail] = []

        # Pre-load chunk texts for human-readable reporting
        self._preload_chunks()

        for case in self.cases:
            result = await self.evaluate_query(case, top_k=top_k, ks=ks, hybrid=hybrid)
            results.append(result)

            zero_recall = all(result.recall_at_k.get(k, 0) == 0 for k in ks)
            if zero_recall:
                failures.append({
                    "query_id": case.query_id,
                    "query": case.query,
                    "reason": "zero_recall",
                })

            per_category.setdefault(case.category, []).append(result)

            # Build human-readable relevant chunk details
            relevant_chunks: list[dict[str, Any]] = []
            for cid in case.relevant_chunk_ids:
                score = case.relevance_scores.get(cid, 1)
                relevant_chunks.append(self._get_chunk_detail(cid, score))

            # Build human-readable retrieved chunk details (top-5 for readability)
            retrieved_chunks: list[dict[str, Any]] = []
            for cid in result.retrieved_ids[:5]:
                retrieved_chunks.append(self._get_chunk_detail(cid))

            # Build doc info
            relevant_docs = [self._get_doc_detail(did) for did in case.relevant_doc_ids if did]

            query_details.append(QueryDetail(
                query_id=case.query_id,
                query=case.query,
                category=case.category,
                expected_answer=case.expected_answer,
                precision_at_k=result.precision_at_k,
                recall_at_k=result.recall_at_k,
                mrr=result.mrr,
                ndcg_at_k=result.ndcg_at_k,
                latency_ms=result.latency_ms,
                retrieved_count=result.retrieved_count,
                failure_reason="zero_recall" if zero_recall else "",
                relevant_chunks=relevant_chunks,
                retrieved_chunks=retrieved_chunks,
                relevant_docs=relevant_docs,
            ))

        # Aggregate averages
        def _avg(values: list[float]) -> float:
            return sum(values) / len(values) if values else 0.0

        avg_precision = {k: _avg([r.precision_at_k.get(k, 0) for r in results]) for k in ks}
        avg_recall = {k: _avg([r.recall_at_k.get(k, 0) for r in results]) for k in ks}
        avg_ndcg = {k: _avg([r.ndcg_at_k.get(k, 0) for r in results]) for k in ks}

        category_stats: dict[str, dict[str, Any]] = {}
        for cat, cat_results in per_category.items():
            category_stats[cat] = {
                "count": len(cat_results),
                "avg_precision_at_5": _avg([r.precision_at_k.get(5, 0) for r in cat_results]),
                "avg_recall_at_5": _avg([r.recall_at_k.get(5, 0) for r in cat_results]),
                "avg_mrr": _avg([r.mrr for r in cat_results]),
            }

        return RAGBenchmarkReport(
            total_queries=len(results),
            avg_precision_at_k={k: round(v, 4) for k, v in avg_precision.items()},
            avg_recall_at_k={k: round(v, 4) for k, v in avg_recall.items()},
            avg_mrr=round(_avg([r.mrr for r in results]), 4),
            avg_ndcg_at_k={k: round(v, 4) for k, v in avg_ndcg.items()},
            avg_latency_ms=round(_avg([r.latency_ms for r in results]), 2),
            avg_source_diversity=round(_avg([r.source_diversity for r in results]), 4),
            per_category=category_stats,
            failures=failures,
            metadata={"top_k": top_k, "ks": ks},
            per_query_results=query_details,
        )
