from __future__ import annotations
"""Evaluation report generation."""

import json
from pathlib import Path
from typing import Any


class EvaluationReport:
    """Aggregates and formats evaluation results."""

    def __init__(self, name: str = "evaluation") -> None:
        self.name = name
        self.results: list[dict[str, Any]] = []

    def add_result(self, result: dict[str, Any]) -> None:
        """Add a single evaluation result."""
        self.results.append(result)

    def get_summary(self) -> dict[str, Any]:
        """Get summary statistics."""
        if not self.results:
            return {}

        scores = [r.get("overall_score", 0) for r in self.results]
        categories: dict[str, list[float]] = {}

        for r in self.results:
            cat = r.get("category", "general")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(r.get("overall_score", 0))

        return {
            "name": self.name,
            "total_cases": len(self.results),
            "avg_score": sum(scores) / len(scores) if scores else 0,
            "min_score": min(scores) if scores else 0,
            "max_score": max(scores) if scores else 0,
            "category_scores": {
                cat: sum(scores) / len(scores)
                for cat, scores in categories.items()
            },
        }

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "name": self.name,
            "summary": self.get_summary(),
            "results": self.results,
        }

    def to_markdown(self) -> str:
        """Convert report to markdown."""
        summary = self.get_summary()

        lines = [
            f"# 评测报告: {self.name}",
            "",
            "## 汇总",
            "",
            f"- **总案例数**: {summary.get('total_cases', 0)}",
            f"- **平均得分**: {summary.get('avg_score', 0):.2f}",
            f"- **最低得分**: {summary.get('min_score', 0):.2f}",
            f"- **最高得分**: {summary.get('max_score', 0):.2f}",
            "",
            "### 分类得分",
            "",
        ]

        for cat, score in summary.get("category_scores", {}).items():
            lines.append(f"- **{cat}**: {score:.2f}")

        lines.extend(["", "## 详细结果", ""])

        for i, result in enumerate(self.results):
            lines.extend([
                f"### 案例 {i+1}",
                f"**问题**: {result.get('question', 'N/A')[:100]}...",
                f"**分类**: {result.get('category', 'N/A')}",
                f"**得分**: {result.get('overall_score', 'N/A')}",
                f"**评价**: {result.get('reasoning', 'N/A')[:200]}",
                "",
            ])

        return "\n".join(lines)

    def save(self, path: str | Path) -> None:
        """Save report to file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Save JSON
        json_path = path.with_suffix(".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

        # Save Markdown
        md_path = path.with_suffix(".md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self.to_markdown())
