"""Structured findings from research workers.

Findings are the standardized output format from all workers in the
deepresearch pipeline. They separate:
  - summary: brief text for the Planner to evaluate (100-200 chars)
  - details: full structured data for the Synthesizer to consume
  - sources: provenance and confidence tracking
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Source:
    """Provenance of a piece of information."""

    type: str  # "web" | "akshare" | "report" | "calculation" | "llm"
    url: str = ""
    title: str = ""
    accessed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "url": self.url,
            "title": self.title,
            "accessed_at": self.accessed_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Source:
        return cls(
            type=data.get("type", "unknown"),
            url=data.get("url", ""),
            title=data.get("title", ""),
            accessed_at=datetime.fromisoformat(data["accessed_at"]) if data.get("accessed_at") else datetime.now(),
        )


@dataclass
class Finding:
    """A structured research finding produced by a Worker.

    Fields:
        task_id: ID of the task that produced this finding.
        role: Role of the worker (e.g. "tavily_search", "data_fetch").
        summary: Short text for Planner evaluation (~100-200 chars).
        details: Full structured data for Synthesizer consumption.
        sources: List of data sources with provenance.
        confidence: 0-1 score representing reliability.
        timestamp: When this finding was created.
    """

    task_id: str
    role: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    sources: list[Source] = field(default_factory=list)
    confidence: float = 0.8
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "role": self.role,
            "summary": self.summary,
            "details": self.details,
            "sources": [s.to_dict() for s in self.sources],
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        return cls(
            task_id=data["task_id"],
            role=data.get("role", "unknown"),
            summary=data.get("summary", ""),
            details=data.get("details", {}),
            sources=[Source.from_dict(s) for s in data.get("sources", [])],
            confidence=data.get("confidence", 0.8),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now(),
        )

    def to_planner_context(self) -> str:
        """Brief representation for Planner context (token-efficient)."""
        src_types = ", ".join({s.type for s in self.sources}) if self.sources else "unknown"
        return (
            f"[{self.role}] {self.summary} "
            f"(confidence: {self.confidence:.0%}, sources: {src_types})"
        )

    @classmethod
    def from_agent_result(
        cls,
        task_id: str,
        role: str,
        result: dict[str, Any],
    ) -> Finding:
        """Build a Finding from a GenericWorker execution result.

        Expects result to contain keys:
          - "summary": str
          - "details": dict (optional)
          - "sources": list[dict] (optional)
          - "confidence": float (optional)
        """
        summary = result.get("summary", "")
        if not summary:
            # Fallback: use answer field or truncate content
            content = result.get("answer", "") or result.get("content", "") or str(result)
            summary = content[:200] + "..." if len(content) > 200 else content

        raw_sources = result.get("sources", [])
        sources: list[Source] = []
        for rs in raw_sources:
            if isinstance(rs, dict):
                sources.append(Source.from_dict(rs))
            elif isinstance(rs, Source):
                sources.append(rs)

        return cls(
            task_id=task_id,
            role=role,
            summary=summary,
            details=result.get("details", {}),
            sources=sources,
            confidence=result.get("confidence", 0.8),
        )
