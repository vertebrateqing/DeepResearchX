from __future__ import annotations
"""Evaluation report generator — aggregates results and writes human-readable output."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from deep_research.evaluation.models import RAGBenchmarkReport


class EvaluationReporter:
    """Write evaluation results to JSON and Markdown."""

    def __init__(self, report: RAGBenchmarkReport) -> None:
        self.report = report

    def to_dict(self) -> dict[str, Any]:
        return self.report.model_dump()

    def to_markdown(self) -> str:
        """Generate a human-readable Markdown report."""
        lines: list[str] = [
            "# RAG Evaluation Report",
            "",
            f"**Generated:** {datetime.utcnow().isoformat()}Z",
            f"**Total Queries:** {self.report.total_queries}",
            "",
            "## Overall Metrics",
            "",
        ]

        # Precision table
        lines.append("### Precision@k")
        lines.append("")
        for k, v in sorted(self.report.avg_precision_at_k.items()):
            lines.append(f"- P@{k}: {v:.4f}")
        lines.append("")

        # Recall table
        lines.append("### Recall@k")
        lines.append("")
        for k, v in sorted(self.report.avg_recall_at_k.items()):
            lines.append(f"- R@{k}: {v:.4f}")
        lines.append("")

        # Other metrics
        lines.extend([
            "### Other Metrics",
            f"- MRR: {self.report.avg_mrr:.4f}",
            f"- Avg Latency: {self.report.avg_latency_ms:.2f} ms",
            f"- Source Diversity: {self.report.avg_source_diversity:.4f}",
            "",
        ])

        # NDCG
        lines.append("### NDCG@k")
        lines.append("")
        for k, v in sorted(self.report.avg_ndcg_at_k.items()):
            lines.append(f"- NDCG@{k}: {v:.4f}")
        lines.append("")

        # Per-category
        if self.report.per_category:
            lines.append("## Per-Category Breakdown")
            lines.append("")
            for cat, stats in sorted(self.report.per_category.items()):
                lines.append(f"### {cat}")
                for key, val in stats.items():
                    lines.append(f"- {key}: {val}")
                lines.append("")

        # Per-query details with chunk texts
        if self.report.per_query_results:
            lines.append("## Per-Query Details")
            lines.append("")
            for detail in self.report.per_query_results:
                status = "FAIL" if detail.failure_reason else "OK"
                lines.append(f"### {detail.query_id} [{status}] — {detail.query}")
                lines.append("")

                # Expected answer
                if detail.expected_answer:
                    lines.append(f"**Expected Answer:** {detail.expected_answer}")
                    lines.append("")

                # Metrics
                lines.append("**Metrics:**")
                lines.append(f"- MRR: {detail.mrr:.4f} | Latency: {detail.latency_ms:.2f}ms | Retrieved: {detail.retrieved_count}")
                prec = ", ".join(f"P@{k}={v:.2f}" for k, v in sorted(detail.precision_at_k.items()))
                rec = ", ".join(f"R@{k}={v:.2f}" for k, v in sorted(detail.recall_at_k.items()))
                lines.append(f"- {prec}")
                lines.append(f"- {rec}")
                lines.append("")

                # Relevant docs
                if detail.relevant_docs:
                    lines.append("**Relevant Documents:**")
                    for doc in detail.relevant_docs:
                        source = doc.get("source", "")
                        filename = doc.get("filename", "")
                        if source or filename:
                            lines.append(f"- doc_id={doc['doc_id']} | source={source} | filename={filename}")
                        else:
                            lines.append(f"- doc_id={doc['doc_id']}")
                    lines.append("")

                # Relevant chunks
                if detail.relevant_chunks:
                    lines.append(f"**Relevant Chunks ({len(detail.relevant_chunks)}):**")
                    for chunk in detail.relevant_chunks:
                        lines.append(f"\n- `{chunk['id']}` (score={chunk['relevance_score']}, index={chunk['chunk_index']}, size={chunk['chunk_size']})")
                        preview = chunk.get("text_preview", "")
                        if preview:
                            # Escape pipe chars in markdown tables, keep newlines as spaces
                            safe = preview.replace("|", "\\|").replace("\n", " ")
                            lines.append(f"  \u003e {safe}")
                    lines.append("")

                # Retrieved chunks (top 5)
                if detail.retrieved_chunks:
                    lines.append(f"**Retrieved Chunks (top 5):**")
                    for i, chunk in enumerate(detail.retrieved_chunks, 1):
                        is_relevant = any(c["id"] == chunk["id"] for c in detail.relevant_chunks)
                        marker = " [RELEVANT]" if is_relevant else ""
                        lines.append(f"\n{i}. `{chunk['id']}`{marker}")
                        preview = chunk.get("text_preview", "")
                        if preview:
                            safe = preview.replace("|", "\\|").replace("\n", " ")
                            lines.append(f"   \u003e {safe}")
                    lines.append("")

                lines.append("---")
                lines.append("")

        # Failures summary
        if self.report.failures:
            lines.append("## Failures Summary (Zero Recall)")
            lines.append("")
            for f in self.report.failures:
                lines.append(f"- `{f['query_id']}`: {f['query']}")
            lines.append("")

        return "\n".join(lines)

    def save(self, output_dir: Path | str) -> tuple[Path, Path]:
        """Write both JSON and Markdown to the given directory.

        Returns (json_path, markdown_path).
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        json_path = output_dir / f"rag_eval_{timestamp}.json"
        md_path = output_dir / f"rag_eval_{timestamp}.md"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self.to_markdown())

        return json_path, md_path
